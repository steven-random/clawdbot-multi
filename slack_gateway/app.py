import os, json, uuid, asyncio, logging

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
log = logging.getLogger("slack_gateway")

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
import redis.asyncio as aioredis

app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])
REDIS_URL = os.environ["REDIS_URL"]
CHANNEL_TO_AGENT: dict[str, str] = {}
AGENT_CHANNEL_NAMES = {
    "email": os.environ.get("SLACK_CHANNEL_EMAIL", "email-agent"),
    "stock": os.environ.get("SLACK_CHANNEL_STOCK", "stock-analyst-agent"),
}
PENDING: dict[str, dict] = {}


async def resolve_channels():
    from slack_sdk.web.async_client import AsyncWebClient
    client = AsyncWebClient(token=os.environ["SLACK_BOT_TOKEN"])
    cursor = None
    channel_name_to_id = {}
    while True:
        resp = await client.conversations_list(types="public_channel,private_channel", limit=200, cursor=cursor)
        for ch in resp["channels"]:
            channel_name_to_id[ch["name"]] = ch["id"]
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    for agent_id, ch_name in AGENT_CHANNEL_NAMES.items():
        ch_id = channel_name_to_id.get(ch_name)
        if ch_id:
            CHANNEL_TO_AGENT[ch_id] = agent_id
            log.info(f"✅ Mapped #{ch_name} ({ch_id}) → agent:{agent_id}")
        else:
            log.warning(f"⚠️ Channel #{ch_name} not found")


# 捕获所有事件用于调试
@app.event({"type": "message"})
async def handle_message(event, say):
    log.info(f"📨 MESSAGE EVENT: {json.dumps(event)}")
    if event.get("bot_id") or event.get("subtype"):
        log.info("Ignoring bot/subtype message")
        return
    channel_id = event["channel"]
    agent_id = CHANNEL_TO_AGENT.get(channel_id)
    log.info(f"Channel: {channel_id}, Agent: {agent_id}, Known channels: {CHANNEL_TO_AGENT}")
    if not agent_id:
        return
    text = event.get("text", "").strip()
    if not text:
        return
    task_id = str(uuid.uuid4())
    thread_ts = event.get("thread_ts") or event["ts"]
    PENDING[task_id] = {"channel": channel_id, "thread_ts": thread_ts}
    await say(text=f"⏳ *{agent_id.capitalize()} Agent* is thinking…")
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    await redis.publish(f"tasks:{agent_id}", json.dumps({
        "task_id": task_id, "agent_id": agent_id, "text": text,
        "slack_channel": channel_id, "slack_thread_ts": thread_ts,
        "user": event.get("user"),
    }))
    await redis.aclose()
    log.info(f"Dispatched task {task_id} → agent:{agent_id}")


async def result_listener():
    from slack_sdk.web.async_client import AsyncWebClient
    client = AsyncWebClient(token=os.environ["SLACK_BOT_TOKEN"])
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    async with redis.pubsub() as ps:
        await ps.psubscribe("results:*")
        log.info("Result listener started")
        async for message in ps.listen():
            if message["type"] != "pmessage":
                continue
            try:
                data = json.loads(message["data"])
                status = data.get("status")
                if status == "thinking":
                    continue
                task_id = data.get("task_id")
                pending = PENDING.pop(task_id, {})
                channel = data.get("slack_channel") or pending.get("channel")
                thread_ts = data.get("slack_thread_ts") or pending.get("thread_ts")
                if status == "done":
                    result = data.get("result", "")
                    chunks = [result[i:i+2900] for i in range(0, len(result), 2900)]
                    for i, chunk in enumerate(chunks):
                        header = f"✅ *{data.get('agent_name', 'Agent')}*\n" if i == 0 else ""
                        await client.chat_postMessage(channel=channel, text=header + chunk, mrkdwn=True)
                elif status == "error":
                    await client.chat_postMessage(channel=channel, text=f"❌ *Error:* {data.get('error')}")
            except Exception as e:
                log.exception(f"Result listener error: {e}")


async def main():
    await resolve_channels()
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    asyncio.create_task(result_listener())
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
