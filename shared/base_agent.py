"""
shared/base_agent.py
────────────────────
Base class that every ClawdBot agent inherits from.
Handles: Redis pub/sub, Claude API calls, response posting back via Redis.
"""

import os
import sys
import json
import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime

# Ensure /shared is in path so the capabilities package is importable
if "/shared" not in sys.path:
    sys.path.insert(0, "/shared")

import redis.asyncio as aioredis
import anthropic
from capabilities.registry import load as load_capabilities

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)


class BaseAgent(ABC):
    """
    Lifecycle:
      1. Subscribes to Redis channel  f"tasks:{agent_id}"
      2. On each message, calls  handle_task(task)  (override in subclass)
      3. Posts result back to   f"results:{task_id}"

    Memory:
      Each agent has isolated long-term memory stored in Redis under the key
      f"agent_memory:{agent_id}". No local files or extra volume mounts needed.

    Capabilities:
      Set AGENT_CAPABILITIES=minneru,database (comma-separated) in docker-compose.yml.
      All available capabilities are registered in shared/capabilities/registry.py.
      Capabilities are auto-loaded at startup; no agent code changes required.
    """

    def __init__(self):
        self.agent_id: str = os.environ["AGENT_ID"]
        self.agent_name: str = os.environ["AGENT_NAME"]
        self.slack_channel: str = os.environ["SLACK_CHANNEL_NAME"]
        self.redis_url: str = os.environ["REDIS_URL"]
        self.model: str = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        self.max_tokens: int = int(os.environ.get("MAX_TOKENS", "4096"))

        self.claude = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.log = logging.getLogger(self.agent_name)

        # In-memory cache; loaded from Redis at the start of run()
        self.memory: dict = {"entries": [], "updated_at": None}
        self._redis: aioredis.Redis | None = None

        # Capabilities loaded from AGENT_CAPABILITIES env var in run()
        self._capabilities: list = []

    # ── Memory management ──────────────────────────────────

    @property
    def _memory_key(self) -> str:
        return f"agent_memory:{self.agent_id}"

    async def _load_memory(self):
        """Load memory from Redis into self.memory."""
        data = await self._redis.get(self._memory_key)
        if data:
            try:
                self.memory = json.loads(data)
                self.log.info(f"Loaded memory ({len(self.memory.get('entries', []))} entries)")
            except (json.JSONDecodeError, Exception) as e:
                self.log.warning(f"Failed to parse memory: {e}")

    async def _save_memory(self):
        """Persist self.memory to Redis."""
        self.memory["updated_at"] = datetime.utcnow().isoformat()
        await self._redis.set(
            self._memory_key,
            json.dumps(self.memory, ensure_ascii=False),
        )

    async def remember(self, content: str, category: str = "general"):
        """Add a memory entry and persist."""
        self.memory["entries"].append({
            "content": content,
            "category": category,
            "created_at": datetime.utcnow().isoformat(),
        })
        # Keep last 200 entries to prevent unbounded growth
        self.memory["entries"] = self.memory["entries"][-200:]
        await self._save_memory()
        self.log.info(f"Saved memory [{category}]: {content[:60]}…")

    async def forget(self, keyword: str) -> int:
        """Remove memory entries containing keyword. Returns count removed."""
        before = len(self.memory["entries"])
        self.memory["entries"] = [
            e for e in self.memory["entries"]
            if keyword.lower() not in e["content"].lower()
        ]
        removed = before - len(self.memory["entries"])
        if removed:
            await self._save_memory()
        return removed

    def get_memory_context(self) -> str:
        """Format memory entries for injection into system prompt."""
        entries = self.memory.get("entries", [])
        if not entries:
            return ""
        lines = []
        for e in entries:
            cat = e.get("category", "general")
            lines.append(f"- [{cat}] {e['content']}")
        return (
            "\n\n## Your Memory (learned from past interactions)\n"
            + "\n".join(lines)
        )

    # ── Override these in subclass ───────────────────────────

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for this agent."""

    async def get_tools(self) -> list[dict]:
        """
        Return Anthropic-format tool definitions for this agent.
        By default returns the definitions from loaded capabilities.
        Supports both single-tool (DEFINITION) and multi-tool (DEFINITIONS) capabilities.
        Override in subclass to add agent-specific tools on top.
        """
        tools = []
        for cap in self._capabilities:
            if hasattr(cap, "DEFINITIONS"):
                tools.extend(cap.DEFINITIONS)
            else:
                tools.append(cap.DEFINITION)
        return tools

    async def pre_process(self, task: dict) -> dict:
        """Optional hook: enrich/validate task before sending to Claude."""
        return task

    async def post_process(self, result: str, task: dict) -> str:
        """Optional hook: transform Claude's output before returning."""
        return result

    # ── Core flow ────────────────────────────────────────────

    async def call_claude(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        """
        Calls Claude with optional tool-use loop.
        Keeps going until Claude stops calling tools.
        """
        # Inject memory context into system prompt
        system = self.system_prompt + self.get_memory_context()

        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools

        full_text = []

        while True:
            response = await self.claude.messages.create(**kwargs)

            # Collect text blocks
            for block in response.content:
                if block.type == "text":
                    full_text.append(block.text)

            # Stop if no tool use
            if response.stop_reason != "tool_use":
                break

            # Handle tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_result = await self.handle_tool_call(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(tool_result),
                    })

            # Add assistant turn + tool results and continue
            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]
            kwargs["messages"] = messages

        return "\n".join(full_text)

    async def handle_tool_call(self, name: str, input_: dict) -> str:
        """
        Dispatch a tool call. Resolution order:
          1. Loaded capabilities (from AGENT_CAPABILITIES)
          2. Built-in memory tools (save_memory, recall_memory, forget_memory)
          3. Subclass overrides (call super() to reach this fallback)
        """
        # 1. Try capabilities (supports single DEFINITION and multi DEFINITIONS)
        for cap in self._capabilities:
            defs = cap.DEFINITIONS if hasattr(cap, "DEFINITIONS") else [cap.DEFINITION]
            if any(d["name"] == name for d in defs):
                return await cap.run({"_tool": name, **input_})

        # 2. Built-in memory tools
        if name == "save_memory":
            await self.remember(input_["content"], input_.get("category", "general"))
            return "Memory saved."
        if name == "recall_memory":
            keyword = input_.get("keyword", "")
            entries = self.memory.get("entries", [])
            if keyword:
                entries = [e for e in entries if keyword.lower() in e["content"].lower()]
            if not entries:
                return "No matching memories found."
            return "\n".join(f"[{e.get('category','general')}] {e['content']}" for e in entries[-20:])
        if name == "forget_memory":
            removed = await self.forget(input_["keyword"])
            return f"Removed {removed} memory entries."
        return f"Tool '{name}' not implemented."

    def _memory_tool_defs(self) -> list[dict]:
        """Built-in tool definitions for memory management."""
        return [
            {
                "name": "save_memory",
                "description": "Save important information to your long-term memory. Use this to remember user preferences, key facts, or anything worth recalling in future conversations.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "What to remember"},
                        "category": {
                            "type": "string",
                            "description": "Category tag, e.g. 'user_preference', 'fact', 'instruction'",
                            "default": "general",
                        },
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "recall_memory",
                "description": "Search your long-term memory for relevant past information.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "Keyword to search for (empty string returns recent memories)"},
                    },
                    "required": [],
                },
            },
            {
                "name": "forget_memory",
                "description": "Remove memory entries containing a keyword.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "Keyword to match entries to remove"},
                    },
                    "required": ["keyword"],
                },
            },
        ]

    async def process_task(self, task: dict) -> str:
        """Main entry point for a task."""
        task = await self.pre_process(task)
        messages = [{"role": "user", "content": task["text"]}]

        # Re-hydrate conversation history if provided
        if history := task.get("history"):
            messages = history + messages

        tools = await self.get_tools()
        # Merge agent-specific tools with built-in memory tools
        all_tools = self._memory_tool_defs() + (tools or [])
        result = await self.call_claude(messages, all_tools or None)
        result = await self.post_process(result, task)
        return result

    # ── Redis pub/sub loop ───────────────────────────────────

    async def run(self):
        self.log.info(f"Starting — listening on tasks:{self.agent_id}")
        self._redis = aioredis.from_url(self.redis_url, decode_responses=True)

        # Load this agent's memory from Redis
        await self._load_memory()

        # Load capabilities declared in AGENT_CAPABILITIES env var
        caps_env = os.environ.get("AGENT_CAPABILITIES", "")
        self._capabilities = load_capabilities(caps_env.split(",") if caps_env else [])
        for cap in self._capabilities:
            await cap.setup()
        if self._capabilities:
            names = ", ".join(cap.NAME for cap in self._capabilities)
            self.log.info(f"Active capabilities: {names}")

        async with self._redis.pubsub() as ps:
            await ps.subscribe(f"tasks:{self.agent_id}")

            async for message in ps.listen():
                if message["type"] != "message":
                    continue

                try:
                    task = json.loads(message["data"])
                    task_id = task["task_id"]
                    self.log.info(f"Received task {task_id}: {task['text'][:60]}…")

                    # Post "thinking" ack
                    await self._redis.publish(
                        f"results:{task_id}",
                        json.dumps({"status": "thinking", "agent": self.agent_id}),
                    )

                    result = await self.process_task(task)

                    await self._redis.publish(
                        f"results:{task_id}",
                        json.dumps({
                            "status": "done",
                            "agent": self.agent_id,
                            "agent_name": self.agent_name,
                            "result": result,
                            "task_id": task_id,
                            "slack_channel": task.get("slack_channel"),
                            "slack_thread_ts": task.get("slack_thread_ts"),
                            "timestamp": datetime.utcnow().isoformat(),
                        }),
                    )

                except Exception as e:
                    self.log.exception(f"Error processing task: {e}")
                    await self._redis.publish(
                        f"results:{task_id}",
                        json.dumps({
                            "status": "error",
                            "agent": self.agent_id,
                            "error": str(e),
                            "task_id": task.get("task_id", "unknown"),
                        }),
                    )
