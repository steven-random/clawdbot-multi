#!/usr/bin/env bash
# ============================================================
#  ClawdBot — Ubuntu Setup & Deploy Script
#  Run as a user with sudo privileges
# ============================================================
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✔]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✘]${NC} $*"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     ClawdBot Multi-Agent Installer       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Install Docker ────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    warn "Docker not found. Installing..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    info "Docker installed. You may need to re-login for group changes."
else
    info "Docker already installed: $(docker --version)"
fi

# ── 2. Install Docker Compose ────────────────────────────────
if ! docker compose version &>/dev/null; then
    warn "Docker Compose plugin not found. Installing..."
    sudo apt-get update -qq
    sudo apt-get install -y docker-compose-plugin
else
    info "Docker Compose installed: $(docker compose version)"
fi

# ── 3. Check .env exists ─────────────────────────────────────
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        warn ".env created from .env.example"
        warn ">>> EDIT .env NOW and fill in your API keys before continuing <<<"
        echo ""
        echo "Required keys:"
        echo "  ANTHROPIC_API_KEY   — get from console.anthropic.com"
        echo "  SLACK_BOT_TOKEN     — from api.slack.com/apps"
        echo "  SLACK_APP_TOKEN     — from api.slack.com/apps (Socket Mode)"
        echo "  SLACK_SIGNING_SECRET— from api.slack.com/apps"
        echo ""
        read -p "Press ENTER when you've filled in .env..." _
    else
        error ".env.example not found. Are you in the clawdbot directory?"
    fi
else
    info ".env file found"
fi

# ── 4. Validate required .env keys ──────────────────────────
source .env
[ -z "$ANTHROPIC_API_KEY" ]    && error "ANTHROPIC_API_KEY is not set in .env"
[ -z "$SLACK_BOT_TOKEN" ]      && error "SLACK_BOT_TOKEN is not set in .env"
[ -z "$SLACK_APP_TOKEN" ]      && error "SLACK_APP_TOKEN is not set in .env"
[ -z "$SLACK_SIGNING_SECRET" ] && error "SLACK_SIGNING_SECRET is not set in .env"
info "All required environment variables are set"

# ── 5. Create Slack channels reminder ───────────────────────
echo ""
warn "Make sure these Slack channels exist and @ClawdBot is invited:"
echo "  #${SLACK_CHANNEL_CODE:-agent-code}"
echo "  #${SLACK_CHANNEL_DATA:-agent-data}"
echo "  #${SLACK_CHANNEL_SEARCH:-agent-search}"
echo "  #${SLACK_CHANNEL_DOCS:-agent-docs}"
echo ""
read -p "Press ENTER when channels are ready..." _

# ── 6. Build & start all containers ─────────────────────────
info "Building Docker images (this may take a few minutes)..."
docker compose build

info "Starting all services..."
docker compose up -d

# ── 7. Health check ──────────────────────────────────────────
echo ""
info "Waiting for services to start..."
sleep 5

services=("clawdbot_redis" "clawdbot_postgres" "clawdbot_slack_gateway"
          "clawdbot_agent_code" "clawdbot_agent_data"
          "clawdbot_agent_search" "clawdbot_agent_docs")

all_ok=true
for svc in "${services[@]}"; do
    status=$(docker inspect --format='{{.State.Status}}' "$svc" 2>/dev/null || echo "missing")
    if [ "$status" = "running" ]; then
        info "$svc → running"
    else
        warn "$svc → $status"
        all_ok=false
    fi
done

echo ""
if $all_ok; then
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   ClawdBot is up and running! 🚀         ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo "  Send a message in #agent-code   → Code Agent"
    echo "  Send a message in #agent-data   → Data Agent"
    echo "  Send a message in #agent-search → Search Agent"
    echo "  Send a message in #agent-docs   → Docs Agent"
    echo ""
    echo "  Logs:  docker compose logs -f"
    echo "  Stop:  docker compose down"
else
    warn "Some containers may not be healthy. Check logs:"
    echo "  docker compose logs slack_gateway"
    echo "  docker compose logs agent_code"
fi
