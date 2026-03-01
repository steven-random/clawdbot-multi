# ClawdBot 多Agent系统

基于 OpenAI Codex CLI + Slack 的本地多Agent AI系统。每个Agent独立运行在Docker容器里，通过专属Slack频道控制。

## 系统架构

```
Slack频道 #email-agent          Slack频道 #stock-analyst-agent
         \                                /
          └──────── Slack Gateway ────────┘
                         │
                       Redis
                    （消息路由 + 独立记忆存储）
                    /           \
             Email Agent      Stock Agent
             （Docker容器）    （Docker容器）
                  │                 │
            Codex CLI           Codex CLI
          （gpt-5-codex）      （gpt-5-codex）
```

## Agent如何做到互相隔离

这是系统设计的核心。Agent之间完全独立，互不影响，通过以下四层机制实现：

### 1. 消息路由隔离 — Redis频道

Slack Gateway 根据消息来自哪个 Slack 频道，将任务发布到对应的 Redis 频道：

```
#email-agent  消息  →  Redis 发布到  tasks:email
#stock-analyst-agent 消息  →  Redis 发布到  tasks:stock
```

每个 Agent 只订阅自己的频道（`tasks:{agent_id}`），绝对不会收到发给其他 Agent 的消息。

### 2. 记忆隔离 — Redis Key 命名空间

每个 Agent 的长期记忆存储在独立的 Redis Key 下：

```
agent_memory:email   →  只有 Email Agent 读写
agent_memory:stock   →  只有 Stock Agent 读写
```

Agent 只操作自己的 Key，不存在任何跨Agent读取记忆的机制。

### 3. 能力隔离 — 环境变量控制

每个 Agent 容器通过 `AGENT_CAPABILITIES` 环境变量声明自己能用哪些工具。
只有被声明的能力才会被加载，其他能力的代码甚至不会被 import：

```yaml
agent_email:
  environment:
    AGENT_CAPABILITIES: email,minneru   # Email Agent 可以操作邮箱、转换PDF

agent_stock:
  environment:
    AGENT_CAPABILITIES: minneru         # Stock Agent 只能转换PDF，不能碰邮箱
```

### 4. 进程隔离 — 独立Docker容器

每个 Agent 运行在完全独立的 Docker 容器里，独立的文件系统、网络命名空间、进程空间。一个 Agent 崩溃不会影响其他 Agent。

---

## 当前Agent列表

| Agent | Slack频道 | 职责 | 能力 |
|---|---|---|---|
| Email Agent | #email-agent | Yahoo邮箱管理（收发读删） | `email`, `minneru` |
| Stock Agent | #stock-analyst-agent | 美股分析 | `minneru` |

## 当前可用能力（Capability Registry）

工具、API、数据库等外部能力统一定义在 `shared/capabilities/`，按需分配给各 Agent。

| 能力名 | 功能 | 所需环境变量 |
|---|---|---|
| `email` | Yahoo邮箱 IMAP/SMTP（读取、搜索、发送、管理） | `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD`, `IMAP_HOST`, `IMAP_PORT`, `SMTP_HOST`, `SMTP_PORT` |
| `minneru` | PDF → Markdown（RunPod Serverless） | `RUNPOD_API_KEY`, `MINNERU_ENDPOINT_ID` |
| `database` | 远程数据库只读查询 | `DATABASE_URL` |

---

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

必填：
- `SLACK_BOT_TOKEN`、`SLACK_APP_TOKEN`、`SLACK_SIGNING_SECRET`

邮箱能力（如需）：
- `EMAIL_ADDRESS`、`EMAIL_APP_PASSWORD`（Yahoo应用专用密码）

### 4. 在Slack创建频道并邀请Bot

    /invite @ClawdBot

### 5. 启动

    docker-compose up -d --build

### 6. 验证

    docker-compose ps        # 所有服务状态应为 Up
    docker-compose logs -f agent_email

---

## 日常维护

查看容器状态：

    docker-compose ps

查看日志：

    docker-compose logs -f agent_email
    docker-compose logs -f agent_stock

重启单个Agent：

    docker-compose restart agent_email

代码更新后重新部署：

    git pull
    docker-compose down
    docker-compose up -d --build

---

## 添加新Agent

### 第一步：创建Agent目录

    cp -r agents/email agents/myagent

### 第二步：修改 agents/myagent/agent.py

在 `SYSTEM_PROMPTS` 里加入新Agent的角色描述：

```python
SYSTEM_PROMPTS = {
    "email": "...",
    "stock": "...",
    "myagent": "你对新Agent的描述",
}
```

### 第三步：在 docker-compose.yml 添加新服务

```yaml
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
    AGENT_CAPABILITIES: minneru   # 留空则无外部能力
  depends_on:
    - redis
  networks:
    - clawdbot_net
  volumes:
    - ~/.codex:/root/.codex:ro
    - ./agents/myagent:/app
    - ./shared:/shared
```

> 无需创建任何本地目录。记忆自动存入 Redis（`agent_memory:myagent`），能力通过环境变量按需分配。

### 第四步：在Slack创建频道

创建 `#my-agent-channel`，然后执行：

    /invite @ClawdBot

### 第五步：启动新Agent

    docker-compose up -d --build agent_myagent

---

## 添加新能力

1. 在 `shared/capabilities/` 新建文件，继承 `Capability` 基类（参考 `minneru.py`）
2. 在 `shared/capabilities/registry.py` 的 `REGISTRY` 里加一行（字符串形式，懒加载）
3. 在需要的 Agent 的 `AGENT_CAPABILITIES` 里加上这个名字
4. 重启对应 Agent 容器

---

## 删除Agent

    docker-compose stop agent_email
    docker-compose rm -f agent_email
    rm -rf agents/email
    # 在 docker-compose.yml 中删除对应 service 块

可选：清除该Agent的记忆：

    docker exec clawdbot_redis redis-cli del agent_memory:email

---

## Agent记忆管理

查看某个Agent的记忆：

    docker exec clawdbot_redis redis-cli get agent_memory:email

查看所有Agent的记忆key：

    docker exec clawdbot_redis redis-cli keys "agent_memory:*"

清除某个Agent的记忆：

    docker exec clawdbot_redis redis-cli del agent_memory:email

---

## 服务器宕机恢复

### 服务器重启后自动恢复

所有容器已设置 `restart: unless-stopped`，服务器重启后Docker会自动重启容器。

### 容器崩溃

    docker-compose ps                          # 查看哪个容器有问题
    docker-compose logs --tail=50 agent_email  # 查看错误日志
    docker-compose restart agent_email         # 重启

### 全部重启

    cd ~/clawdbot-multi
    docker-compose down
    docker-compose up -d

### Codex登录过期

如果Agent无响应或返回认证错误：

    codex login
    docker-compose restart agent_email agent_stock

### Redis数据问题

Redis已开启AOF持久化（`--appendonly yes`），重启后记忆数据不会丢失。

    docker-compose logs redis
    docker-compose up -d redis

> 警告：`docker volume rm clawdbot_redis_data` 会永久删除所有Agent的记忆，请谨慎操作。

---

## 环境变量说明

| 变量 | 说明 |
|---|---|
| `SLACK_BOT_TOKEN` | Slack Bot Token（xoxb-开头） |
| `SLACK_APP_TOKEN` | Slack App Token（xapp-开头） |
| `SLACK_SIGNING_SECRET` | Slack签名密钥 |
| `REDIS_URL` | Redis连接地址（容器内默认 redis://redis:6379） |
| `EMAIL_ADDRESS` | Yahoo邮箱地址 |
| `EMAIL_APP_PASSWORD` | Yahoo应用专用密码 |
| `IMAP_HOST` / `IMAP_PORT` | Yahoo IMAP服务器（imap.mail.yahoo.com / 993） |
| `SMTP_HOST` / `SMTP_PORT` | Yahoo SMTP服务器（smtp.mail.yahoo.com / 587） |
| `RUNPOD_API_KEY` | RunPod API密钥（minneru能力） |
| `MINNERU_ENDPOINT_ID` | RunPod Serverless端点ID（minneru能力） |
| `DATABASE_URL` | 远程数据库连接字符串（database能力） |
