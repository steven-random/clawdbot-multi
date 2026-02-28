# 🤖 ClawdBot — Multi-Agent System (Slack-Controlled)

A production-ready, locally-hosted multi-agent AI system powered by Claude, controlled entirely through Slack. Each agent runs in its own Docker container and responds only in its dedicated Slack channel.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Slack Workspace                          │
│  #agent-code  #agent-data  #agent-search  #agent-docs          │
└───────────────────────┬─────────────────────────────────────────┘
                        │ Socket Mode (WebSocket)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Slack Gateway (Bolt)                          │
│   • Receives all messages                                       │
│   • Maps channel → agent                                        │
│   • Pushes tasks to Redis                                       │
│   • Posts results back to Slack                                 │
└───────────────────────┬─────────────────────────────────────────┘
                        │ Redis Pub/Sub
          ┌─────────────┼──────────────┬──────────────┐
          ▼             ▼              ▼              ▼
   ┌────────────┐ ┌───────────┐ ┌──────────────┐ ┌──────────────┐
   │ Code Agent │ │ Data Agent│ │ Search Agent │ │  Docs Agent  │
   │            │ │           │ │              │ │              │
   │ run_python │ │  run_sql  │ │  web_search  │ │  read_file   │
   │  run_bash  │ │list_tables│ │  fetch_page  │ │  write_file  │
   │ write_file │ │desc_table │ │              │ │  list_files  │
   └────────────┘ └─────┬─────┘ └──────────────┘ └──────────────┘
                        │
                 ┌──────▼──────┐
                 │  PostgreSQL  │
                 └─────────────┘
```

---

## Quick Start

### 1. Clone / copy this project to your Ubuntu server

```bash
# Copy the clawdbot folder to your server
scp -r clawdbot/ user@your-server:~/clawdbot
cd ~/clawdbot
```

### 2. Create your Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → From Scratch
2. Name it `ClawdBot`, pick your workspace
3. **Socket Mode** → Enable Socket Mode → Generate App Token (scope: `connections:write`) → Save as `SLACK_APP_TOKEN`
4. **OAuth & Permissions** → Bot Token Scopes:
   - `channels:read`
   - `chat:write`
   - `groups:read`
   - `im:read`
   - `mpim:read`
5. **Event Subscriptions** → Enable → Subscribe to bot events:
   - `message.channels`
   - `message.groups`
6. Install app to workspace → copy **Bot User OAuth Token** → `SLACK_BOT_TOKEN`
7. **Basic Information** → **Signing Secret** → `SLACK_SIGNING_SECRET`

### 3. Create Slack Channels & Invite the Bot

Create these channels in Slack (exact names matter):
- `#agent-code`
- `#agent-data`
- `#agent-search`
- `#agent-docs`

In each channel, type: `/invite @ClawdBot`

### 4. Configure environment

```bash
cp .env.example .env
nano .env   # Fill in your keys
```

### 5. Deploy

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

That's it! Send a message in any agent channel and ClawdBot will respond.

---

## Usage Examples

### #agent-code
```
Write a Python function that parses a CSV file and returns a list of dicts
```
```
Debug this code: [paste code]
```
```
Run this script and show me the output: print(sum(range(100)))
```

### #agent-data
```
List all tables in the database
```
```
Show me the top 5 rows from sample_metrics
```
```
Write a SQL query to find average values grouped by metric_name
```

### #agent-search
```
Search for the latest news about AI agents
```
```
Summarize this page: https://example.com/article
```

### #agent-docs
```
Create a README for a FastAPI project
```
```
List all files in my workspace
```
```
Summarize this text: [paste long text]
```

---

## Management Commands

```bash
# View all logs
docker compose logs -f

# View a specific agent's logs
docker compose logs -f agent_code

# Restart a single agent (no downtime for others)
docker compose restart agent_search

# Stop everything
docker compose down

# Rebuild after code changes
docker compose up -d --build agent_code

# Update all agents
docker compose up -d --build
```

---

## Project Structure

```
clawdbot/
├── docker-compose.yml          # All services defined here
├── .env.example                # Copy to .env and fill in
├── shared/
│   └── base_agent.py           # Base class all agents inherit
├── slack_gateway/
│   ├── app.py                  # Slack Bolt app (Socket Mode)
│   ├── Dockerfile
│   └── requirements.txt
├── agents/
│   ├── code/                   # Code / Dev Agent
│   │   ├── agent.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── data/                   # Data / DB Agent
│   ├── search/                 # Web Search Agent
│   └── docs/                   # File / Docs Agent
├── nginx/
│   └── nginx.conf
└── scripts/
    ├── setup.sh                # One-command installer
    └── init_db.sql             # PostgreSQL schema
```

---

## Adding a New Agent

1. Create `agents/myagent/` directory
2. Create `agent.py` extending `BaseAgent`:

```python
from base_agent import BaseAgent

class MyAgent(BaseAgent):

    @property
    def system_prompt(self) -> str:
        return "You are the MyAgent..."

    async def get_tools(self) -> list[dict]:
        return []  # Add tools here

if __name__ == "__main__":
    import asyncio
    asyncio.run(MyAgent().run())
```

3. Add to `docker-compose.yml`:

```yaml
agent_myagent:
  build: ./agents/myagent
  environment:
    AGENT_ID: myagent
    AGENT_NAME: "My Agent"
    SLACK_CHANNEL_NAME: agent-myagent
```

4. Create the `#agent-myagent` Slack channel and invite `@ClawdBot`
5. `docker compose up -d --build agent_myagent`

---

## Security Notes

- The Code Agent runs scripts inside Docker (sandboxed)
- The Data Agent blocks destructive SQL (DROP, TRUNCATE, DELETE)
- The Docs Agent restricts file access to `/workspace` only
- All containers share an internal network — nothing is exposed except port 80 (nginx)
- Keep your `.env` file private — never commit it to git
