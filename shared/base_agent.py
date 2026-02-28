"""
shared/base_agent.py
────────────────────
Base class that every ClawdBot agent inherits from.
Handles: Redis pub/sub, Claude API calls, response posting back via Redis.
"""

import os
import json
import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime

import redis.asyncio as aioredis
import anthropic

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

    # ── Override these in subclass ───────────────────────────

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for this agent."""

    @abstractmethod
    async def get_tools(self) -> list[dict]:
        """Return Anthropic-format tool definitions for this agent."""

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
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
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
        """Override in subclass to handle tool calls."""
        return f"Tool '{name}' not implemented."

    async def process_task(self, task: dict) -> str:
        """Main entry point for a task."""
        task = await self.pre_process(task)
        messages = [{"role": "user", "content": task["text"]}]

        # Re-hydrate conversation history if provided
        if history := task.get("history"):
            messages = history + messages

        tools = await self.get_tools()
        result = await self.call_claude(messages, tools or None)
        result = await self.post_process(result, task)
        return result

    # ── Redis pub/sub loop ───────────────────────────────────

    async def run(self):
        self.log.info(f"Starting — listening on tasks:{self.agent_id}")
        redis = aioredis.from_url(self.redis_url, decode_responses=True)

        async with redis.pubsub() as ps:
            await ps.subscribe(f"tasks:{self.agent_id}")

            async for message in ps.listen():
                if message["type"] != "message":
                    continue

                try:
                    task = json.loads(message["data"])
                    task_id = task["task_id"]
                    self.log.info(f"Received task {task_id}: {task['text'][:60]}…")

                    # Post "thinking" ack
                    await redis.publish(
                        f"results:{task_id}",
                        json.dumps({"status": "thinking", "agent": self.agent_id}),
                    )

                    result = await self.process_task(task)

                    await redis.publish(
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
                    await redis.publish(
                        f"results:{task_id}",
                        json.dumps({
                            "status": "error",
                            "agent": self.agent_id,
                            "error": str(e),
                            "task_id": task.get("task_id", "unknown"),
                        }),
                    )
