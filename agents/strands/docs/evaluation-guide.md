# Cat Care Agent — Evaluation & 数据集指南

**日期**: 2026-05-03
**Agent**: Strands Cat Care Assistant
**模型**: us.anthropic.claude-sonnet-4-6

---

## 1. 背景

Cat Care Agent 是一个基于 Strands SDK 的单 agent + MCP tools 架构，通过 9 个工具（list_cats, get_cat_profile, get_feedings, record_feeding, get_health_metrics, get_health_alerts, list_devices, get_device, send_device_command）为用户提供猫咪护理服务。

本文档记录了 evaluation 体系的设计、数据集生成流程和标注规范。

---

## 2. 评估维度

基于业务需求，定义了 3 个核心评估维度：

### 2.1 Response Time（响应时间）

| 属性 | 值 |
|------|-----|
| Kind ID | `custom-1777791977372` |
| 类型 | scored-categorical |
| 标准 | 端到端响应时间（从请求到完整回复） |
| 阈值 | 15 秒 |

| 标签 | 分数 | 含义 |
|------|------|------|
| ≤15s | 1.0 | 通过 — 响应时间在可接受范围内 |
| >15s | 0.0 | 不通过 — 响应过慢，需优化 |

**判定方法**: 直接读取 trace 的 `latencyMs` 字段，与 15000ms 比较。

### 2.2 Intent Understanding（意图理解）

| 属性 | 值 |
|------|-----|
| Kind ID | `custom-1777791977374` |
| 类型 | scored-categorical |
| 标准 | Agent 是否正确理解用户的真实意图 |

| 标签 | 分数 | 含义 |
|------|------|------|
| correct | 1.0 | 完全理解意图，执行了正确的操作 |
| partial | 0.5 | 部分理解，但遗漏了关键步骤或多余确认 |
| misunderstood | 0.0 | 完全误解用户意图 |

**判定方法**: 人工审查 trace 的 input/output，对比用户意图与 agent 实际行为。

### 2.3 Cat ID Lookup（猫咪 ID 查找）

| 属性 | 值 |
|------|-----|
| Kind ID | `custom-1777791977376` |
| 类型 | scored-categorical |
| 标准 | Agent 是否在操作前先正确识别/查找目标猫咪的 ID |

| 标签 | 分数 | 含义 |
|------|------|------|
| correct | 1.0 | 正确找到并使用了猫咪 ID |
| wrong | 0.5 | 找到了 ID 但用错了（如查了别的猫） |
| missing | 0.0 | 没有查找 ID 就直接操作，或完全没找到 |

**判定方法**: 检查 trace 中的 TOOL span，确认是否调用了 `list_cats` 或 `get_cat_profile`，以及传入的 `cat_id` 参数是否正确。

---

## 3. 测试数据集

### 3.1 数据集信息

| 属性 | 值 |
|------|-----|
| 名称 | Cat Care Agent 基准测试集 v1 |
| ID | `0641a233-5d65-4ceb-a39c-39de208c5586` |
| 样本数 | 4 |
| 创建日期 | 2026-05-03 |

### 3.2 猫咪基础数据

系统中注册了两只猫：

| 名称 | 昵称 | cat_id | 品种 | 性别 | 生日 |
|------|------|--------|------|------|------|
| 火锅 | 锅锅 | hotpot | 英国短毛猫（矮脚） | 雄 | 2023-04-27 |
| 烧烤 | 烤烤 | bbq | 英国短毛猫 | 雌 | 2023-06-14 |

### 3.3 测试用例详情

#### 用例 1: 简单打招呼

| 属性 | 值 |
|------|-----|
| Trace ID | `bc23532ef81b5fb2b991a37ec4d3d8ae` |
| 输入 | `[Context: cat_id='mittens'] 你好` |
| 场景 | 用户打招呼，不涉及具体操作 |
| 延迟 | 4.8s |
| 工具调用 | 无 |

**标注结果**:
- Response Time: ≤15s ✅ (score: 1.0)
- Intent Understanding: correct ✅ (score: 1.0)
- Cat ID Lookup: N/A（打招呼不需要查猫 ID）

---

#### 用例 2: 带 context 的健康查询

| 属性 | 值 |
|------|-----|
| Trace ID | `881f00c5fba822af53c0e9f9b3618ca7` |
| 输入 | `[Context: cat_id='mittens'] 查看健康数据` |
| 场景 | context 中已提供 cat_id，直接查询健康数据 |
| 延迟 | 5.9s |
| 工具调用 | `get_health_metrics(mittens)` + `get_health_alerts(mittens)` |

**标注结果**:
- Response Time: ≤15s ✅ (score: 1.0)
- Intent Understanding: correct ✅ (score: 1.0)
- Cat ID Lookup: correct ✅ (score: 1.0) — 正确使用了 context 中的 mittens

---

#### 用例 3: 昵称查找（首次，带错误 context）

| 属性 | 值 |
|------|-----|
| Trace ID | `264a516dce2b0979f79a8f3b2e707b2c` |
| 输入 | `[Context: cat_id='mittens'] 帮我查一下 锅锅的状态` |
| 场景 | 用户用昵称"锅锅"查询，但 context 给的是 mittens |
| 延迟 | 127s ⚠️ |
| 工具调用 | `list_cats()` → 找到 hotpot/bbq |

**标注结果**:
- Response Time: >15s ❌ (score: 0.0) — 主要是 Bedrock 冷启动导致 TTFT 122s
- Intent Understanding: partial ⚠️ (score: 0.5) — 找到了锅锅=火锅，但没有直接查状态，而是反问确认
- Cat ID Lookup: correct ✅ (score: 1.0) — 正确调用了 list_cats 找到了猫

**问题分析**: Agent 在 list_cats 返回结果后，虽然已经看到"火锅"的昵称就是"锅锅"，但仍然反问用户确认，没有直接执行查询。这是意图理解的一个弱点。

---

#### 用例 4: 昵称查找（第二次，无 context）

| 属性 | 值 |
|------|-----|
| Trace ID | `7b6afe002357ae8d48628fa6b913b700` |
| 输入 | `帮我查一下 锅锅的状态` |
| 场景 | 同样的问题，但这次没有 cat_id context，且有上一轮对话历史 |
| 延迟 | 136s ⚠️ |
| 工具调用 | `get_health_metrics(hotpot)` + `get_health_alerts(hotpot)` + `get_feedings(hotpot)` |

**标注结果**:
- Response Time: >15s ❌ (score: 0.0) — 同样是 Bedrock 冷启动问题
- Intent Understanding: correct ✅ (score: 1.0) — 这次直接查了火锅的全部状态
- Cat ID Lookup: correct ✅ (score: 1.0) — 正确使用了 hotpot

**对比用例 3**: 有了上一轮的对话历史，Agent 这次不再反问，直接执行了查询。说明多轮对话的上下文帮助了意图理解。

---

## 4. 数据集扩展建议

当前 4 条 trace 覆盖的场景有限，建议补充以下测试用例：

### 4.1 火锅（hotpot）相关

| # | 输入 | 测试目标 |
|---|------|---------|
| 5 | "锅锅今天吃了多少？" | 昵称 → cat_id 映射 + get_feedings |
| 6 | "火锅的喂食器还有多少粮？" | 名称查找 + list_devices/get_device |
| 7 | "帮锅锅记录一下，刚喂了 30g 湿粮" | 昵称 + record_feeding 写操作 |
| 8 | "锅锅体重是不是太重了？" | 需要 get_health_metrics + 判断 |

### 4.2 烧烤（bbq）相关

| # | 输入 | 测试目标 |
|---|------|---------|
| 9 | "烤烤最近怎么样？" | 昵称查找 bbq |
| 10 | "查一下烧烤的健康警报" | 名称查找 + get_health_alerts |
| 11 | "烤烤的饮水机正常吗？" | 昵称 + list_devices + get_device |

### 4.3 多猫 / 边界场景

| # | 输入 | 测试目标 |
|---|------|---------|
| 12 | "两只猫今天都吃了什么？" | 多猫查询，需要两次 get_feedings |
| 13 | "帮我查一下猫的情况" | 模糊查询，没指定哪只猫 |
| 14 | "喂食器坏了怎么办" | 不需要 cat_id 的通用问题 |
| 15 | "Mittens 的健康数据" | 查询不存在的猫（context 中的 mittens 不在系统里） |

### 4.4 设备操作

| # | 输入 | 测试目标 |
|---|------|---------|
| 16 | "帮锅锅的饮水机加水" | send_device_command |
| 17 | "列出所有智能设备" | list_devices |

---

## 5. 标注流程

### 5.1 标注步骤

1. **产生 trace**: 向 agent 发送测试请求
2. **在 Trace Explorer 中查看**: 确认 trace 状态为 success
3. **分析 trace 详情**: 查看 span 层级、工具调用、输入输出
4. **标注三个维度**:
   - Response Time: 根据 latencyMs 自动判定
   - Intent Understanding: 人工对比输入意图与输出行为
   - Cat ID Lookup: 检查 TOOL span 中的 cat_id 参数
5. **加入数据集**: 将标注好的 trace 加入测试数据集

### 5.2 标注规范

**Response Time 判定**:
- 读取 AGENT span 的 duration（毫秒）
- ≤ 15000ms → "≤15s"
- > 15000ms → ">15s"
- 注意：Bedrock 冷启动可能导致首次请求延迟很高（>120s），这是基础设施问题而非 agent 问题

**Intent Understanding 判定**:
- correct: agent 的回复完全匹配用户意图，执行了正确的操作
- partial: agent 理解了部分意图，但有遗漏（如多余确认、漏掉子任务）
- misunderstood: agent 完全误解了用户想要什么

**Cat ID Lookup 判定**:
- correct: 在需要 cat_id 的操作中，正确找到并使用了目标猫的 ID
- wrong: 找到了 ID 但用错了（如用户问火锅，查了烧烤）
- missing: 需要 cat_id 但没有查找，或者查找失败
- N/A: 该请求不需要 cat_id（如打招呼、通用问题）

---

## 6. 已知问题

### 6.1 Bedrock 冷启动延迟

用例 3 和 4 的延迟分别为 127s 和 136s，主要原因是 Bedrock 模型冷启动（TTFT > 120s）。实际的 LLM 推理 + 工具调用时间约 4-11s。

**建议**: 在评估 Response Time 时，区分"冷启动"和"热请求"两种场景。

### 6.2 昵称匹配的多余确认

用例 3 中，Agent 在 list_cats 返回结果后，虽然数据中明确显示"火锅"的 nickname 是"锅锅"，但仍然反问用户确认。这可能是因为 system prompt 中没有明确指示"昵称匹配时直接使用"。

**建议**: 在 system prompt 中添加："当用户使用猫咪的昵称时，如果能从 list_cats 结果中明确匹配到，直接使用对应的 cat_id，无需反问确认。"

---

## 7. 后续计划

1. **扩展数据集**: 按第 4 节的建议补充 10+ 条测试用例
2. **自动化评估**: Response Time 可以通过 evaluator 自动判定
3. **优化 system prompt**: 解决昵称匹配的多余确认问题
4. **Bedrock 预热**: 考虑 provisioned throughput 或定时预热请求
5. **回归测试**: 每次修改 prompt 或工具后，用数据集重新评估
