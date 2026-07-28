# PRD — Phase 3：记忆召回注入（闭环）

| 项 | 内容 |
|---|---|
| 版本 | v1.0 |
| 阶段 | Phase 3 / 4 |
| 状态 | ✅ 已实施并验收通过 |
| 依赖 | Phase 1（封装层）、Phase 2（写入数据源） |
| 后续 | Phase 4 在闭环之上做能力增强与旧路径收敛 |

---

## 1. 背景与问题

Phase 2 完成后记忆"写得进"，但智能体推理时仍然只依赖 Bootstrap Prompt
（memory.md 等静态文件）与当前 Session Context，**历史长期记忆完全不参与
推理**——这正是现状"只写不读"断链的另一半。

技术约束：

- CrewAI 的 `before_llm_hook`（`main_crew.py` 中现有钩子）是**同步**函数，
  在其中执行异步 HTTP 召回需要嵌套事件循环，风险高；
- `build_agent_fn` 返回的 `agent_fn` 本身运行在异步环境
  （事件循环线程池之外的 async 上下文），是安全的召回执行点；
- backstory 注入必须限长，防止召回内容挤占上下文窗口。

## 2. 目标与非目标

### 目标

- G1：flag 开启时，每轮推理前用**用户当前消息**语义召回相关长期记忆
- G2：召回结果以结构化标签段注入 orchestrator agent 的 backstory
  （bootstrap prompt 之后），供推理参考
- G3：空召回零污染——无相关记忆时 prompt 与现状完全一致
- G4：召回失败/超时静默降级为空串，推理照常进行
- G5：注入内容受 `recall_max_chars` 限长

### 非目标

- 不在 CrewAI 同步 hook 内做任何网络 IO
- 不做多轮对话级的召回缓存/去重（首版每轮独立召回）
- 不做召回结果的重排（rerank）与置信过滤（依赖记忆系统后端排序）
- 不向 sub-agent（非 orchestrator）注入记忆

## 3. 用户故事

| 编号 | 角色 | 故事 | 验收口径 |
|---|---|---|---|
| US-1 | 终端用户 | 我上周告诉过助手的偏好/事实，本周新会话里它还记得 | 跨 session 提问可命中历史 fragment 内容 |
| US-2 | 终端用户 | 记忆服务慢/挂了，我的提问最多损失"想起往事"，回复速度和质量不受灾难性影响 | recall 超时 → 空注入，回复正常 |
| US-3 | 提示工程师 | 注入的记忆有明确边界标记与"可能过时"提示，模型不会把召回当指令执行 | `<long_term_memory>` 标签 + 免责导语 |
| US-4 | 平台运维 | 我能从日志看到每轮召回命中长度 | `remote memory recalled N chars` 日志 |

## 4. 功能需求

### FR-1 RemoteMemoryStore.recall（P0）

- 签名：`async recall(query, routing_key="", top_k=None) -> str`；
- 实现：调 SDK `recall_context(query=query, max_fragments=top_k or
  recall_top_k)`（`POST /memory/recall`），取响应中的 `context_text`；
- 结果超过 `recall_max_chars` 时截断并追加 `...(截断)` 标记；
- `asyncio.wait_for(remote_timeout)` 兜底超时；
- 任何异常（HTTP 错误/超时/解析失败）→ 记 warning 返回 `""`；
- store 未启用 → 直接返回 `""`（零网络开销）。

### FR-2 召回执行点（P0）

`agents/main_crew.py::build_agent_fn` 内的 `agent_fn`（async）中，
沙箱获取之后、`MemoryAwareCrew` 构造之前：

```python
recalled_memory = ""
if (flags is not None and getattr(flags, "enable_remote_memory", False)
        and remote_memory_store.is_enabled):
    recalled_memory = await remote_memory_store.recall(
        query=user_message, routing_key=routing_key)
```

约束：召回查询词 = 用户原始消息（不做改写）；召回在回复路径上同步
await，延迟预算见 NFR-1。

### FR-3 backstory 注入（P0）

- `MemoryAwareCrew.__init__` 新增参数 `recalled_memory: str = ""`；
- `orchestrator()` 构建 backstory 时，在 bootstrap prompt 拼接**之后**追加：

```text
<long_term_memory>
以下为长期记忆召回内容，供参考，可能过时：
{recalled_memory}
</long_term_memory>
```

- `recalled_memory` 为空串时**不追加任何内容**（含标签本身），保证
  空召回零污染；
- 标签命名与现有 prompt 中 XML 风格段落一致；导语明示"供参考，可能
  过时"，降低模型将记忆误当最新事实/指令的风险。

### FR-4 参数可调（P1）

- `recall_top_k`（1–20，默认 5）与 `recall_max_chars`（200–20000，默认
  4000）经 config.yaml 调节，无需改代码；
- 二者语义在 `config.yaml.example` 与 docs/16 指南中说明。

## 5. 非功能需求

| 编号 | 需求 | 指标 |
|---|---|---|
| NFR-1 | 延迟预算 | 召回在回复路径上，最大附加延迟 = remote_timeout（默认 10s，建议生产调至 2–3s）；正常命中 < 500ms（记忆服务本地部署） |
| NFR-2 | 上下文安全 | 注入 ≤ recall_max_chars，不挤爆模型上下文窗口 |
| NFR-3 | 故障隔离 | 召回路径任何异常 → 空注入，0 用户可见错误 |
| NFR-4 | 提示安全 | 记忆内容包裹在专用标签内且带免责导语（防提示注入放大） |

## 6. 验收标准

- [x] AC-1：召回成功 → backstory 含 `<long_term_memory>` 段且位于
  bootstrap prompt 之后
- [x] AC-2：召回为空/失败/禁用 → backstory 与 flag 关闭时逐字节一致
- [x] AC-3：召回结果 > recall_max_chars 时被截断（单测覆盖）
- [x] AC-4：recall 遇 HTTP 4xx/5xx、超时均返回 `""` 不抛（单测覆盖）
- [x] AC-5：flag 关闭时 agent_fn 不触碰 remote_memory_store（零网络请求）
- [x] AC-6（集成）：真实后端 写入"我喜欢喝美式咖啡" →
  新 session 提问咖啡偏好 → 召回文本含"美式"
  （已验收：本地拉起记忆服务，会话 A save_turn → 会话 B recall 命中）

## 7. 测试计划

- 单测（AsyncMock）：`TestRecall` 6 项——成功取 context_text、空结果、
  超长截断、HTTP 错误降级、超时降级、禁用短路；
- backstory 注入逻辑经 MemoryAwareCrew 构造断言（含空串不注入分支）；
- 集成：写入→轮询召回闭环（后端 embedding 异步索引存在秒级延迟，
  测试内轮询最多 30s）；
- 手工验收脚本（docs/16 指南）：两轮对话验证"上轮告知、下轮想起"。

## 8. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 召回把回复延迟拖到 remote_timeout 上限 | 中 | wait_for 硬超时 + 生产建议下调 timeout；后续可演进为"上一轮预取"模式 |
| 召回内容与当前问题无关造成噪声 | 中 | 后端相关度排序 + top_k 限量 + "可能过时"导语；必要时下调 top_k |
| 记忆内容含恶意指令（间接提示注入） | 中 | 标签隔离 + 导语声明"仅供参考"；写入侧仅存本平台自身对话（source=xiaopaw） |
| 每轮召回增加记忆服务 QPS | 低 | QPS = 对话轮次数，量级低；服务端自带鉴权限流 |

## 9. 实施记录（验收快照）

- 交付文件：`xiaopaw/memory/remote_memory.py`（recall，含 `...(截断)` 标记）、
  `xiaopaw/agents/main_crew.py`（agent_fn 预取 + MemoryAwareCrew 注入）、
  `tests/unit/test_main_crew_recall_injection.py`（AC-1/AC-2 注入单测）
- 验证结果：单测 19/19 + 注入 2/2；全量回归 802 passed / 4 skipped；
  AC-6 真实后端闭环命中（会话 A 写入咖啡偏好 → 会话 B 召回含"美式"）
- 前置修复：AC-6/AC-7 验收中发现并修复了记忆系统后端召回链路
  workspace_id 丢失 bug（auto_recall.py / auto_recall_service.py /
  recall_engine.py 三处透传），否则 API Key 写入的片段永远召不回
