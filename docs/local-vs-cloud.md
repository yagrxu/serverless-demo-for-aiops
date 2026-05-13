# Local vs Cloud — 技术对比详解

本文档详细对比本地开发环境和 AWS 云端部署在每一层的技术实现差异，帮助开发者理解两套环境的等价关系和各自的边界。

---

## 总览

| 层级 | 本地 | 云端 |
|------|------|------|
| UI 托管 | Next.js dev server (host) | CloudFront + S3 + Fargate (ALB) |
| Agent 运行时 | uvicorn 进程 (host) | Bedrock AgentCore Runtime (Docker) |
| MCP 网关 | mcp-server/server.py (host) | AgentCore Gateway (托管服务) |
| API 计算 | FastAPI shim (Docker) | API Gateway + Lambda |
| 数据库 | DynamoDB Local (Docker) | DynamoDB (托管) |
| 认证 | 无 | SigV4 签名 |
| 网络 | localhost 直连 | VPC + ALB + CloudFront |

---

## 1. UI 层

### 本地

```
Chatbot UI (Next.js)        → http://localhost:3000
Device Simulator (Vite)     → http://localhost:5174  (未集成到 up.sh)
Admin Console (Vite)        → http://localhost:5175  (未集成到 up.sh)
```

- Chatbot 通过 `LOCAL_MODE=true` 环境变量切换为直接 HTTP 调用本地 agent
- 环境变量 `LANGGRAPH_URL=http://localhost:8081`、`STRANDS_URL=http://localhost:8082` 指定 agent 地址
- 热更新：Vite HMR / Next.js Fast Refresh，改代码即时生效

### 云端

```
CloudFront Distribution (HTTPS)
  ├── /                     → ALB → Fargate (Next.js chatbot, 容器化)
  ├── /device-simulator/*   → S3 (静态文件)
  └── /admin-console/*      → S3 (静态文件)
```

- Chatbot 运行在 **ECS Fargate** 上（ARM64, 512 CPU / 1024 MB），不是静态文件
- Fargate Task Role 拥有 `bedrock-agentcore:InvokeAgentRuntime` 权限，通过 SigV4 签名调用 AgentCore Runtime
- ALB 安全组仅允许 CloudFront 前缀列表 (`pl-3b927c52`) 的入站流量
- Device Simulator 和 Admin Console 是纯静态 SPA，构建后上传到 S3

### 关键差异

| 维度 | 本地 | 云端 |
|------|------|------|
| Chatbot 运行方式 | Node.js 进程 (dev mode) | Fargate 容器 (production build) |
| Chatbot 调用 Agent | 直接 HTTP POST 到 localhost | SigV4 签名调用 AgentCore Runtime API |
| 静态 UI 服务 | Vite dev server | S3 + CloudFront OAC |
| HTTPS | 无 (HTTP) | CloudFront 强制 HTTPS |
| 缓存 | 无 | CloudFront 缓存静态资源，Chatbot 路由 TTL=0 |

---

## 2. Agent 层

### 本地

```
agents/langgraph/server.py  → uvicorn :8081 (host 进程)
agents/strands/server.py    → uvicorn :8082 (host 进程)
```

- 直接继承 shell 的 AWS credentials（`AWS_PROFILE` 或环境变量）
- 通过 `MCP_SERVER_URL=http://localhost:8083/mcp` 连接本地 MCP Server
- 使用 **plain Streamable HTTP** 传输（无签名）
- 支持 `--reload` 热重载，改代码自动重启
- 日志直接输出到终端或 `local/.logs/agent-*.log`

### 云端

```
Bedrock AgentCore Runtime (AWS::BedrockAgentCore::Runtime)
  ├── cat_demo_langgraph  → ECR image (linux/amd64)
  └── cat_demo_strands    → ECR image (linux/amd64)
```

- 运行在 AgentCore 托管基础设施上，开发者不管理底层计算资源
- Docker 镜像从 ECR 拉取，tag 为 commit SHA
- 通过 `MCP_SERVER_URL` 环境变量连接 AgentCore Gateway
- 使用 **SigV4 签名的 Streamable HTTP** 传输（`streamable_http_sigv4.py`）
- 执行角色拥有 `bedrock:InvokeModel`、`bedrock-agentcore:InvokeGateway` 权限
- 日志自动写入 CloudWatch Logs

### Agent 代码中的环境感知

Agent 代码（`server.py`）通过检测 `MCP_SERVER_URL` 中是否包含 `gateway.bedrock-agentcore` 来自动切换认证模式：

```python
# agents/strands/server.py
def _create_mcp_client() -> MCPClient:
    if "gateway.bedrock-agentcore" in MCP_SERVER_URL:
        # 云端：SigV4 签名
        return MCPClient(lambda: streamablehttp_client_with_sigv4(...))
    else:
        # 本地：无签名
        return MCPClient(lambda: streamablehttp_client(MCP_SERVER_URL))
```

```python
# agents/langgraph/server.py
def _build_mcp_connection_config() -> dict:
    config = {"url": MCP_SERVER_URL, "transport": "streamable_http"}
    if "gateway.bedrock-agentcore" in MCP_SERVER_URL:
        # 云端：附加 SigV4Auth
        config["auth"] = SigV4HTTPXAuth(...)
    return config
```

### 关键差异

| 维度 | 本地 | 云端 |
|------|------|------|
| 运行环境 | 主机 Python 进程 | AgentCore 托管容器 |
| 镜像架构 | 不需要镜像 | linux/amd64 Docker image |
| MCP 认证 | 无 (plain HTTP) | SigV4 签名 |
| AWS 凭证来源 | shell 环境变量 / ~/.aws | AgentCore 执行角色 (IAM Role) |
| 调用入口 | `POST http://localhost:808x/invocations` | AgentCore `InvokeAgentRuntime` API |
| 热重载 | 支持 (`--reload`) | 需要重新构建镜像并部署 |
| 日志 | 终端 / 本地文件 | CloudWatch Logs |

---

## 3. MCP 网关层

### 本地

```
mcp-server/server.py (FastMCP)  → http://localhost:8083
```

- 使用 `FastMCP` 框架，暴露 9 个 MCP tool
- 接收 agent 的 MCP tool call → 转换为 HTTP 请求 → 发送到 API shim (`:8000`)
- 传输协议：Streamable HTTP (SSE)
- 无认证，无授权
- 健康检查：`GET /health`

**工具映射逻辑**：

```python
@mcp.tool()
async def get_cat_profile(cat_id: str) -> str:
    return await _api_get(f"/cats/{cat_id}")  # → http://localhost:8000/cats/{id}
```

### 云端

```
AgentCore Gateway (AWS::BedrockAgentCore::Gateway)
  ├── CatProfileTarget  → Lambda (cat-profile)
  ├── FeedingTarget     → Lambda (feeding)
  ├── HealthTarget      → Lambda (health)
  └── DeviceTarget      → Lambda (device)
```

- AWS 托管服务，无需运维
- 协议：MCP (Streamable HTTP)
- 认证：SigV4（agent 调用 gateway 时签名）
- 工具定义：在 CDK 中以 `ToolSchema.InlinePayload` 声明（不是从代码动态加载）
- 调用方式：**直接 Lambda Invoke**（不经过 API Gateway），通过 Gateway IAM Role 授权

### 关键差异

| 维度 | 本地 | 云端 |
|------|------|------|
| 实现 | Python 进程 (FastMCP) | AWS 托管服务 |
| 工具定义 | 代码中 `@mcp.tool()` 装饰器 | CDK ToolSchema (声明式) |
| 下游调用 | HTTP → API shim → DDB Local | 直接 Lambda Invoke → DDB |
| 认证 | 无 | SigV4 (agent→gateway) + IAM Role (gateway→lambda) |
| 延迟 | ~1ms (localhost) | ~10-50ms (网络 + Lambda 冷启动) |
| 工具数量 | 9 个 (代码定义) | 10 个 (CDK 定义，含 lookup_cat_by_name) |

**重要**：本地 MCP Server 通过 HTTP 调用 API shim，而云端 Gateway 直接 invoke Lambda（绕过 API Gateway）。这意味着云端 agent 的 tool call 不会出现在 API Gateway 的访问日志中，只会出现在 Lambda 的 CloudWatch Logs 里。

---

## 4. API / 计算层

### 本地

```
local/api/app.py (FastAPI, Docker)  → http://localhost:8000
```

- FastAPI 应用，将 HTTP 请求转换为 API Gateway event 格式
- 导入并直接调用 `cdk/lambda/*/handler.py` 中的 `lambda_handler` 函数
- Lambda 代码通过 Docker volume bind-mount 挂载（`./cdk/lambda:/app/lambda:ro`）
- 支持 `--reload`，修改 handler 代码后自动重载
- 同时服务 UI 直接调用和 MCP Server 的 tool call

```python
# local/api/app.py — 将 HTTP 请求转为 Lambda event
async def _invoke(handler, resource, method, request, path_params=None):
    event = {
        "resource": resource,
        "httpMethod": method,
        "pathParameters": path_params,
        "queryStringParameters": dict(request.query_params),
        "body": body_bytes.decode() if body_bytes else None,
    }
    result = handler(event, None)  # 直接调用 lambda_handler
    return Response(content=result["body"], status_code=result["statusCode"])
```

### 云端

```
API Gateway (REST) → Lambda (Python 3.12)
  ├── /cats/*           → cat-profile handler
  ├── /devices/*        → device handler
  ├── /feedings/*       → feeding handler
  └── /health/*         → health handler
```

- API Gateway REST API，带 X-Ray tracing
- 4 个独立 Lambda 函数，各自只有访问对应 DynamoDB 表的 IAM 权限
- 256 MB / 10s timeout / Active X-Ray tracing / 1 周日志保留
- 两条调用路径：
  1. UI/外部 → API Gateway → Lambda（有 API Gateway 日志）
  2. Agent → AgentCore Gateway → Lambda Invoke（无 API Gateway 日志）

### 关键差异

| 维度 | 本地 | 云端 |
|------|------|------|
| 运行方式 | 单个 FastAPI 进程 (Docker) | 4 个独立 Lambda 函数 |
| 代码 | 同一份 handler.py | 同一份 handler.py |
| 请求格式 | FastAPI 模拟 API Gateway event | 真实 API Gateway event |
| IAM 隔离 | 无（共享进程） | 每个 Lambda 独立 Role |
| 冷启动 | 无 | 有（首次调用 ~500ms） |
| 并发 | 单进程多线程 | Lambda 自动扩缩 |
| X-Ray | 无 | 开启 |
| 热重载 | 支持（bind-mount + reload） | 需要 `cdk deploy` |

---

## 5. 数据层

### 本地

```
DynamoDB Local (Docker)  → http://localhost:8001
```

- `amazon/dynamodb-local:latest` 镜像，`-sharedDb -inMemory` 模式
- 数据存在内存中，容器重启后丢失
- 表名为简单名称：`CatProfiles`、`Devices` 等
- Lambda handler 通过 `DDB_ENDPOINT=http://ddb:8000` 环境变量连接（Docker 内部网络）
- 无容量限制、无节流、无 IAM 鉴权

### 云端

```
DynamoDB (托管)  → 默认 endpoint
```

- 7 张表，全部 PAY_PER_REQUEST（按需计费）
- 表名带 CDK 生成的后缀（如 `aiops-cat-demo-data-CatProfilesAF84B1BF-O7DO4LZM6Q8G`）
- Lambda 通过默认 DynamoDB endpoint 访问（`DDB_ENDPOINT` 未设置时走默认）
- 有 IAM 权限控制、CloudWatch 指标、自动备份

### Handler 中的环境感知

```python
# cdk/lambda/*/handler.py 中的通用模式
endpoint = os.environ.get("DDB_ENDPOINT")  # 本地有值，云端为 None
table = boto3.resource("dynamodb", endpoint_url=endpoint).Table(TABLE_NAME)
```

### 关键差异

| 维度 | 本地 | 云端 |
|------|------|------|
| 实现 | DynamoDB Local (Java, Docker) | DynamoDB (托管) |
| 持久化 | 内存（重启丢失） | 持久化存储 |
| 表名 | 简单名称 | CDK 生成的唯一名称 |
| 容量模式 | 无限制 | PAY_PER_REQUEST |
| IAM | 无 | 每个 Lambda 独立权限 |
| GSI | 支持 | 支持 |
| 延迟 | <1ms | 1-10ms |
| 数据初始化 | `init-ddb.sh` + `seed.sh` | `test/seed-cloud.sh` |

---

## 6. 网络与认证

### 本地

```
所有组件通过 localhost 直连，无认证：

UI → Agent:       HTTP POST localhost:808x
Agent → MCP:      Streamable HTTP localhost:8083
MCP → API:        HTTP localhost:8000
API → DDB:        HTTP localhost:8001 (Docker 内部 ddb:8000)
```

- 无 TLS、无签名、无 IAM
- Docker 内部网络：`api` 容器通过 `http://ddb:8000` 访问 DynamoDB Local
- 主机通过端口映射访问：`:8000` (API)、`:8001` (DDB)

### 云端

```
认证链路：

Browser → CloudFront (HTTPS, 无用户认证)
CloudFront → ALB (HTTP, CloudFront prefix list 限制)
Fargate → AgentCore Runtime (SigV4, bedrock-agentcore:InvokeAgentRuntime)
AgentCore Runtime → AgentCore Gateway (SigV4, bedrock-agentcore:InvokeGateway)
AgentCore Gateway → Lambda (IAM Role, lambda:InvokeFunction)
Lambda → DynamoDB (IAM Role, dynamodb:GetItem/PutItem/Query/Scan)
```

- 每一跳都有 IAM 权限控制
- Agent 调用 Gateway 时使用 SigV4 签名（`streamable_http_sigv4.py`）
- Chatbot Fargate 调用 AgentCore 时使用 Task Role 的临时凭证签名
- 无 Cognito / 无用户级认证（demo 设计决策）

---

## 7. 可观测性

| 信号 | 本地 | 云端 |
|------|------|------|
| Agent 日志 | `local/.logs/agent-*.log` 或终端 | CloudWatch Logs |
| MCP Server 日志 | `local/.logs/mcp-server.log` | N/A (托管服务) |
| API 日志 | `docker compose logs api` | CloudWatch + API Gateway 访问日志 |
| 链路追踪 | 无 | X-Ray (Lambda + API Gateway) |
| 指标 | 无 | CloudWatch (Lambda/DDB/API GW) |
| Agent 调用追踪 | 终端输出 | AgentCore 运行时日志 |

---

## 8. 启动与部署

### 本地启动

```bash
# 全量启动
./local/scripts/up.sh

# 只启动基础设施，手动跑 agent
./local/scripts/up.sh --no-agents
./local/scripts/start-agent.sh strands   # 单独启动一个 agent

# 停止
./local/scripts/down.sh
```

启动顺序：Docker (DDB + API) → init tables → seed data → MCP Server → Agents → UIs

### 云端部署

```bash
cd cdk && npm ci
TAG=$(git rev-parse HEAD)

# Phase 1: 基础设施 (注意：不要传 -c skipAgents=true，
# 否则 ECR 跨栈 exports 会被识别为未使用而尝试删除)
npx cdk deploy aiops-cat-demo-ecr aiops-cat-demo-observability \
  aiops-cat-demo-data aiops-cat-demo-api aiops-cat-demo-gateway \
  -c imageTag=$TAG

# Phase 2: 构建并推送镜像 (linux/arm64，因为 Fargate 和 AgentCore 都是 ARM64)
docker buildx build --platform linux/arm64 --push agents/langgraph
docker buildx build --platform linux/arm64 --push agents/strands
docker buildx build --platform linux/arm64 --push ui/chatbot

# Phase 3: 部署消费镜像的栈
npx cdk deploy aiops-cat-demo-agents aiops-cat-demo-fargate \
  aiops-cat-demo-ui -c imageTag=$TAG
```

---

## 9. 同一份代码如何适配两套环境

| 代码文件 | 环境感知机制 |
|----------|-------------|
| `cdk/lambda/*/handler.py` | `DDB_ENDPOINT` 环境变量：有值→DDB Local，无值→真实 DDB |
| `agents/*/server.py` | `MCP_SERVER_URL` 中是否含 `gateway.bedrock-agentcore`：是→SigV4，否→plain HTTP |
| `agents/*/server.py` | `MODEL_ID` 环境变量：可切换模型 |
| `ui/chatbot` | `LOCAL_MODE` 环境变量：true→直接 HTTP 调 agent，false→SigV4 调 AgentCore |

设计原则：**同一份 handler/agent 代码在两套环境中运行，通过环境变量切换行为，不需要条件编译或分支代码。**

---

## 10. 端口速查

| 端口 | 本地服务 | 云端等价物 |
|------|----------|-----------|
| 3000 | Chatbot UI (Next.js dev) | Fargate → ALB → CloudFront `/` |
| 5174 | Device Simulator (Vite) | S3 → CloudFront `/device-simulator/` |
| 5175 | Admin Console (Vite) | S3 → CloudFront `/admin-console/` |
| 8081 | LangGraph agent (uvicorn) | AgentCore Runtime `cat_demo_langgraph` |
| 8082 | Strands agent (uvicorn) | AgentCore Runtime `cat_demo_strands` |
| 8083 | MCP Server (FastMCP) | AgentCore Gateway |
| 8000 | API shim (FastAPI, Docker) | API Gateway + Lambda |
| 8001 | DynamoDB Local (Docker) | DynamoDB (托管) |
