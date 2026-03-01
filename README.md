# ClawdBot 多Agent系统

基于 OpenAI Codex CLI + Slack 的本地多Agent AI系统。每个Agent独立运行在Docker容器里，通过专属Slack频道控制。

## 系统架构

    Slack频道
        |
    Slack Gateway（接收消息，路由到对应Agent）
        |
      Redis（消息队列 + 各Agent独立记忆存储）
      /         \
  Email Agent   Stock Agent
        |
    Codex CLI（GPT-5-Codex）

## 当前Agent列表

| Agent | Slack频道 | 职责 |
|---|---|---|
| Email Agent | #email-agent | Gmail邮箱管理 |
| Stock Agent | #stock-analyst-agent | 美股分析 |

## Agent记忆系统

每个Agent拥有独立的长期记忆，存储在Redis中：

    agent_memory:email   → Email Agent 的记忆
    agent_memory:stock   → Stock Agent 的记忆

Agent会在对话中自动存取记忆（通过 `save_memory` / `recall_memory` / `forget_memory` 工具）。记忆会注入到每次对话的系统提示中，实现跨会话的上下文保持。

查看某个Agent的记忆：

    docker exec clawdbot_redis redis-cli get agent_memory:email

查看所有Agent的记忆key：

    docker exec clawdbot_redis redis-cli keys "agent_memory:*"

清除某个Agent的记忆：

    docker exec clawdbot_redis redis-cli del agent_memory:email

## 能力系统（Capability Registry）

工具、API、数据库等外部能力统一定义在 `shared/capabilities/` 目录里，每个 Agent 通过 `AGENT_CAPABILITIES` 环境变量声明自己能用哪些。

### 当前可用能力

| 能力名 | 功能 | 所需环境变量 |
|---|---|---|
| `minneru` | PDF → Markdown（RunPod Serverless） | `RUNPOD_API_KEY`, `MINNERU_ENDPOINT_ID` |
| `database` | 远程数据库只读查询（需自行接入驱动） | `DATABASE_URL` |

### 为 Agent 分配能力

只需在 `docker-compose.yml` 对应 service 的 `environment` 块里配置：

    agent_email:
      environment:
        AGENT_CAPABILITIES: minneru,database   # 逗号分隔，留空则无外部能力

Agent 重启后自动加载，无需修改任何 Python 代码。

### 添加新能力

1. 在 `shared/capabilities/` 新建文件（参考 `minneru.py`），继承 `Capability` 基类
2. 在 `shared/capabilities/registry.py` 的 `REGISTRY` 里加一行
3. 在需要的 Agent 的 `AGENT_CAPABILITIES` 里加上这个名字
4. 重启对应 Agent 容器

## 环境要求

- Ubuntu 20.04+
- Docker 20+
- docker-compose 1.29+
- Node.js 18+（用于Codex CLI）
- ChatGPT Plus/Pro账号（用于Codex CLI登录）

## 部署步骤

### 1. 克隆代码

    git clone https://github.com/steven-random/clawdbot-multi.git
    cd clawdbot-multi

### 2. 安装 Codex CLI 并登录

    npm install -g @openai/codex
    codex login

### 3. 配置环境变量

    cp .env.example .env
    nano .env

需要填写：
- SLACK_BOT_TOKEN
- SLACK_APP_TOKEN
- SLACK_SIGNING_SECRET

### 4. 在Slack创建频道并邀请Bot

在每个Agent频道里执行：

    /invite @ClawdBot

### 5. 启动

    docker-compose up -d --build

### 6. 验证运行

    docker-compose ps

所有服务状态应该是 Up。

## 日常维护命令

查看所有容器状态：

    docker-compose ps

查看某个Agent日志：

    docker-compose logs -f agent_email
    docker-compose logs -f agent_stock

重启所有服务：

    docker-compose restart

重启某个Agent：

    docker-compose restart agent_email

代码更新后重新部署：

    git pull
    docker-compose down
    docker-compose up -d --build

## 添加新Agent

### 第一步：创建Agent目录

    cp -r agents/email agents/myagent

### 第二步：修改 agents/myagent/agent.py

把 SYSTEM_PROMPTS 里加入新Agent的角色描述：

    SYSTEM_PROMPTS = {
        "email": "You are an AI email assistant...",
        "stock": "You are a US stock market analyst...",
        "myagent": "你对新Agent的描述",
    }

### 第三步：在 docker-compose.yml 添加新服务

在 services 末尾加入：

    agent_myagent:
      build:
        context: ./agents/myagent
        dockerfile: Dockerfile
      container_name: clawdbot_agent_myagent
      restart: unless-stopped
      env_file: .env
      environment:
        AGENT_ID: myagent
        AGENT_NAME: "My Agent"
        SLACK_CHANNEL_NAME: my-agent-channel
        REDIS_URL: redis://redis:6379
        CODEX_MODEL: gpt-5-codex
        AGENT_CAPABILITIES: minneru   # 留空则无外部能力
      depends_on:
        - redis
      networks:
        - clawdbot_net
      volumes:
        - ~/.codex:/root/.codex:ro
        - ./agents/myagent:/app
        - ./shared:/shared

> 注意：无需为新Agent创建任何本地目录或额外挂载volume。记忆自动存入Redis，能力通过 `AGENT_CAPABILITIES` 按需分配。

### 第四步：在 .env 添加频道名

    SLACK_CHANNEL_MYAGENT=my-agent-channel

### 第五步：在Slack创建频道

创建 #my-agent-channel，然后执行：

    /invite @ClawdBot

### 第六步：启动新Agent

    docker-compose up -d --build agent_myagent

## 删除Agent

### 第一步：停止并删除容器

    docker-compose stop agent_email
    docker-compose rm -f agent_email

### 第二步：删除代码目录

    rm -rf agents/email

### 第三步：从 docker-compose.yml 删除对应的 service 块

用编辑器打开并删除对应段落：

    nano docker-compose.yml

### 第四步（可选）：清除该Agent的记忆

    docker exec clawdbot_redis redis-cli del agent_memory:email

### 第五步：在Slack删除或存档对应频道

## 服务器宕机恢复

### 情况一：服务器重启后自动恢复

所有容器已设置 restart: unless-stopped，服务器重启后Docker会自动重启容器。

验证：

    docker-compose ps

### 情况二：容器崩溃

查看哪个容器有问题：

    docker-compose ps

查看错误日志：

    docker-compose logs --tail=50 agent_email

重启出问题的容器：

    docker-compose restart agent_email

### 情况三：全部重启

    cd ~/clawdbot-multi
    docker-compose down
    docker-compose up -d

### 情况四：Codex登录过期

如果Agent回复"authentication failed"或无响应：

    codex login

重新登录后重启Agent：

    docker-compose restart agent_email agent_stock

### 情况五：Redis数据问题

Redis已开启AOF持久化（`--appendonly yes`），重启后记忆数据不会丢失。

如果Redis无法启动：

    docker-compose logs redis
    docker-compose up -d redis

> 警告：执行 `docker volume rm clawdbot_redis_data` 会永久删除所有Agent的记忆，请谨慎操作。

### 情况六：完全重新部署

    cd ~/clawdbot-multi
    docker-compose down
    docker rmi clawdbot_slack_gateway clawdbot_agent_email clawdbot_agent_stock
    docker-compose up -d --build

## 环境变量说明

| 变量 | 说明 |
|---|---|
| SLACK_BOT_TOKEN | Slack Bot Token（xoxb-开头） |
| SLACK_APP_TOKEN | Slack App Token（xapp-开头） |
| SLACK_SIGNING_SECRET | Slack签名密钥 |
| SLACK_CHANNEL_EMAIL | Email Agent的Slack频道名 |
| SLACK_CHANNEL_STOCK | Stock Agent的Slack频道名 |
| CODEX_MODEL | 使用的Codex模型（默认gpt-5-codex） |
| REDIS_URL | Redis连接地址 |
