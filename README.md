# ClawdBot 多Agent系统

基于 OpenAI Codex CLI + Slack 的本地多Agent AI系统。每个Agent独立运行在Docker容器里，通过专属Slack频道控制。

## 系统架构

    Slack频道
        |
    Slack Gateway（接收消息，路由到对应Agent）
        |
      Redis（消息队列）
      /         \
  Email Agent   Stock Agent
        |
    Codex CLI（GPT-5-Codex）

## 当前Agent列表

| Agent | Slack频道 | 职责 |
|---|---|---|
| Email Agent | #email-agent | Gmail邮箱管理 |
| Stock Agent | #stock-analyst-agent | 美股分析 |

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
      depends_on:
        - redis
      networks:
        - clawdbot_net
      volumes:
        - ~/.codex:/root/.codex:ro
        - ./agents/myagent:/app
        - ./shared:/shared

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

### 第四步：在Slack删除或存档对应频道

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

    cd ~/clawdbot
    docker-compose down
    docker-compose up -d

### 情况四：Codex登录过期

如果Agent回复"authentication failed"或无响应：

    codex login

重新登录后重启Agent：

    docker-compose restart agent_email agent_stock

### 情况五：Redis数据丢失

Redis重启后消息队列会清空，但不影响功能，Agent会重新监听。

如果Redis无法启动：

    docker-compose logs redis
    docker volume rm clawdbot_redis_data
    docker-compose up -d redis

### 情况六：完全重新部署

    cd ~/clawdbot
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
