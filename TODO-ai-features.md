# AI Feature Ideas — 待讨论

基于当前 demo 的架构（AgentCore + MCP + 双 Agent 对比），以下是可以加进去的 AI 相关功能，按类别分组。优先级和取舍咱们一起定。

---

## 🔍 AIOps 可观测性 & 自动诊断

### 1. Agent 调用链可视化 (Trace Viewer)
- 在 Chatbot UI 里展示 agent 的 tool call 链路（哪些 tool 被调了、顺序、耗时、返回值）
- 对比 LangGraph vs Strands 的决策路径差异
- 数据来源：agent 返回 intermediate steps / tool call history

### 2. 异常自动归因 Agent
- 新增一个 "诊断 Agent"，输入是 CloudWatch Logs / X-Ray traces
- 自动分析 Lambda 错误、超时、异常模式，给出根因推断
- 可以做成 MCP tool：`analyze_error_logs(function_name, time_range)`

### 3. Agent 行为 Diff
- 记录每次 agent 调用的完整 tool call 序列
- 当同一个 prompt 在两个 agent 上产生不同结果时，自动高亮差异
- 可以做成一个 "regression detection" 功能

### 4. 自动生成 Runbook
- Agent 在排查问题后，自动生成一份 Runbook（步骤 + 命令 + 预期结果）
- 存到 DynamoDB 或 S3，下次类似问题可以直接引用

---

## 🤖 Agent 能力增强

### 5. Multi-turn 对话 + 记忆
- 当前是 stateless（每次请求独立）
- 加 session memory（DynamoDB 存对话历史），让 agent 能引用上下文
- 例如："刚才说的那只猫，它的设备呢？"

### 6. Agent 自主巡检 (Proactive Agent)
- 定时触发（EventBridge Scheduler → Lambda → invoke agent）
- Agent 主动检查所有猫的健康指标，发现异常自动生成 alert
- 展示 "AI 主动发现问题" 的能力

### 7. RAG — 知识库增强
- 加一个 Bedrock Knowledge Base（S3 存猫咪护理文档、设备手册）
- Agent 在回答时可以引用知识库内容
- 例如："布偶猫一天应该吃多少？" → 从知识库检索

### 8. 多模态输入
- 支持用户上传猫咪照片，agent 通过 Claude Vision 分析
- 例如："这只猫看起来健康吗？" + 图片 → 分析体态、毛色
- 或者分析设备照片判断设备状态

### 9. Tool Use 动态发现
- 当前 agent 启动时加载固定 9 个 tool
- 支持运行时动态注册新 tool（比如用户自定义的 webhook）
- 展示 MCP 的动态扩展能力

---

## 📊 数据 & 分析

### 10. 异常检测模型
- 对 DeviceTelemetry 和 HealthMetrics 做时序异常检测
- 可以用 Bedrock 的 embedding + 简单统计，或者接 SageMaker
- Agent 调用 `detect_anomaly(cat_id, metric_type)` tool

### 11. 喂食建议 (Recommendation)
- 基于历史喂食数据 + 猫的品种/体重，AI 生成个性化喂食建议
- 新 tool：`get_feeding_recommendation(cat_id)`

### 12. 自然语言查询 DynamoDB (Text-to-Query)
- 用户说 "过去一周哪只猫吃得最少"
- Agent 自动构造 DynamoDB query，聚合数据，返回结果
- 展示 AI 的数据分析能力

---

## 🛠️ 开发者体验 & Demo 效果

### 13. Bug 注入 Agent
- 一个专门的 agent/tool，接收自然语言描述的 bug
- 自动修改 Lambda handler 代码并部署到 test 环境
- 例如："让 feeding handler 在周末返回 500"

### 14. A/B 测试框架
- 在 Chatbot UI 上支持切换不同 model（Haiku / Sonnet / 自定义）
- 对比不同模型在相同 prompt 下的表现（准确性、延迟、成本）
- 加一个简单的评分机制（thumbs up/down）

### 15. Agent 评估 Dashboard
- 集成 Omni Studios 的评估结果（你已经有 `.omni/` 配置）
- 在 UI 上展示 agent 的准确率、工具使用效率、响应时间趋势

### 16. Streaming 响应
- 当前是等 agent 完整响应后才显示
- 改成 streaming（SSE），逐 token 显示
- 用户体验更好，也能展示 AgentCore 的 streaming 能力

### 17. Cost Tracking
- 记录每次 agent 调用的 token 用量（input/output tokens）
- 在 UI 上显示每次对话的成本估算
- 对比两个 agent 的成本效率

---

## 🔐 安全 & 治理

### 18. Guardrails
- 接入 Bedrock Guardrails，限制 agent 的输出范围
- 例如：不允许 agent 删除数据、不允许讨论非猫相关话题
- 展示 AI 安全治理能力

### 19. Agent 审计日志
- 记录所有 agent 的 tool call 到独立的审计表
- 谁问了什么、agent 做了什么操作、结果是什么
- 可以用于合规审计和事后分析

---

## 🏗️ 架构演进

### 20. Multi-Agent 协作
- 引入 "协调者 Agent"，根据用户意图路由到不同专业 agent
- 例如：健康问题 → 健康 Agent，设备问题 → 设备 Agent
- 展示 multi-agent orchestration 模式

### 21. Human-in-the-Loop
- 某些高风险操作（如发送设备命令）需要人工确认
- Agent 暂停执行，通过 WebSocket 通知 UI，等待用户确认
- 展示 AI + 人工协作的模式

### 22. Agent 热更新
- 不重新部署容器的情况下更新 agent 的 system prompt 或 tool 配置
- 通过 DynamoDB 或 Parameter Store 存储配置，agent 定期拉取
- 展示运维友好的 agent 管理方式

---

## 投票区

在这里标记你感兴趣的（✅ 要做 / ⏳ 以后再说 / ❌ 不需要）：

| # | Feature | 优先级 | 备注 |
|---|---------|--------|------|
| 1 | 调用链可视化 | | |
| 2 | 异常归因 Agent | | |
| 3 | Agent 行为 Diff | | |
| 4 | 自动生成 Runbook | | |
| 5 | Multi-turn 对话 | | |
| 6 | 自主巡检 | | |
| 7 | RAG 知识库 | | |
| 8 | 多模态输入 | | |
| 9 | Tool 动态发现 | | |
| 10 | 异常检测 | | |
| 11 | 喂食建议 | | |
| 12 | Text-to-Query | | |
| 13 | Bug 注入 Agent | | |
| 14 | A/B 测试 | | |
| 15 | 评估 Dashboard | | |
| 16 | Streaming 响应 | | |
| 17 | Cost Tracking | | |
| 18 | Guardrails | | |
| 19 | 审计日志 | | |
| 20 | Multi-Agent | | |
| 21 | Human-in-the-Loop | | |
| 22 | Agent 热更新 | | |
