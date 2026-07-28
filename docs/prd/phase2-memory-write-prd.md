# PRD — Phase 2：记忆写入（双写过渡）

| 项 | 内容 |
|---|---|
| 版本 | v1.0 |
| 阶段 | Phase 2 / 4 |
| 状态 | ✅ 已实施并验收通过 |
| 依赖 | Phase 1（RemoteMemoryStore、配置、flag） |
| 后续 | Phase 3 依赖本阶段写入的记忆片段作为召回数据源 |

---

## 1. 背景与问题

xiaopaw-v2 每轮对话结束后，`agents/main_crew.py::run_and_index()` 通过
`memory/indexer.py::async_index_turn` 将对话摘要写入 pgvector `memories`
表。该路径存在的问题：

- **P1 数据孤岛**：索引数据只进不出（无召回消费方），沉淀在私有 PG 表中，
  无法被 agent-memory-system 的召回/生命周期/图谱能力复用；
- **P2 后端锁定**：写入逻辑与 psycopg2/pgvector 强耦合；
- **P3 存量隐患**：`_index_coroutine` 在 `run_and_index` 中被创建后未被
  调度执行（存量疑似 bug，见 §9 备注），pgvector 索引可能实际未生效。

本阶段在**不动 pgvector 路径**的前提下，把每轮对话并行写入
agent-memory-system（记忆片段 fragment），形成双轨数据积累，为 Phase 3
召回提供数据源，为 Phase 4 收敛 pgvector 提供切换底气。

## 2. 目标与非目标

### 目标

- G1：flag 开启时，每轮对话（用户消息 + 助手回复）异步写入记忆服务，
  成为可被语义召回的 fragment
- G2：写入完全 fire-and-forget：不增加用户可感知的回复延迟，失败不影响
  回复发送与会话持久化
- G3：写入携带足够的溯源元数据（session_id / routing_key / turn_ts /
  source），支撑后续按用户维度过滤与多租户演进
- G4：SDK 异步客户端具备与同步客户端对齐的片段写入能力

### 非目标

- 不修改/删除 pgvector 写入路径（含存量 `_index_coroutine` 未调度问题，
  单独立项处理）
- 不做记忆去重、重要性自动评分、记忆压缩（记忆系统后端职责）
- 不写入变量（Variables）/图谱（Graph）类记忆（Phase 4）

## 3. 用户故事

| 编号 | 角色 | 故事 | 验收口径 |
|---|---|---|---|
| US-1 | 终端用户 | 我与智能体的对话内容被沉淀为长期记忆，后续会话可被想起 | 记忆系统后台可查到对话 fragment |
| US-2 | 终端用户 | 记忆服务宕机时我的对话完全不受影响 | 写入失败仅日志告警，回复正常 |
| US-3 | 平台运维 | 我能通过日志确认每轮写入成功/失败 | `remote memory saved turn for session X` / warning 日志 |
| US-4 | 数据管理员 | 我能在记忆系统中按用户（routing_key）区分记忆归属 | fragment metadata 含 routing_key |

## 4. 功能需求

### FR-1 SDK 异步片段写入能力（P0）

`pm/agent-memory-system/sdk-python/src/agent_memory/async_client.py`
的 `AsyncMemoryClient` 补充方法（与同步版 `MemoryClient.remember_fragment`
对齐，并扩展 metadata）：

```python
async def remember_fragment(
    content: str,
    fragment_type: str = "fact",
    importance_score: float = 0.5,
    ttl: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]
# → POST /memory/fragments
```

后端 `CreateFragmentRequest` 已支持 metadata 字段，无需后端改动。

### FR-2 RemoteMemoryStore.save_turn（P0）

- 签名：`async save_turn(session_id, routing_key, user_message,
  assistant_reply, summary="")`；
- **内容策略**：优先使用 `summary`（若非空）；否则拼
  `用户：{user_message[:500]}\n助手：{assistant_reply[:1000]}`；
  最终内容按 `memory.max_save_length`（默认 2000）截断；
- **片段属性**：`fragment_type="info"`、`importance_score=0.5`、不设 TTL
  （生命周期策略在 Phase 4 引入）；
- **metadata**：`{session_id, routing_key, turn_ts(毫秒), source:"xiaopaw"}`；
- **失败语义**：超时（`remote_timeout`，asyncio.wait_for 兜底）与任何异常
  只记 warning 日志，不向上抛。

### FR-3 后台调度 save_turn_background（P0）

- 用 `asyncio.create_task` 在事件循环上调度 `save_turn`，调用方立即返回；
- 任务引用保存在 `_pending_tasks` 集合中防止 GC 提前回收，完成后经
  done-callback 自动清理；
- 无运行中事件循环（同步测试环境）时静默跳过（debug 日志），不崩溃；
- store 未启用时零开销短路。

### FR-4 主流程接入点（P0）

`agents/main_crew.py::run_and_index()`：在计算出 `reply` 之后、返回之前：

```python
if getattr(self._flags, "enable_remote_memory", False):
    remote_memory_store.save_turn_background(
        session_id=..., routing_key=..., user_message=..., assistant_reply=reply,
    )
```

约束：

- 位于现有 `async_index_turn`（pgvector）代码块**之后并列**，两条写路径
  互不感知、各自吞异常；
- flag 通过 `getattr` 读取，兼容旧 `FeatureFlags` 实例（无该字段时视为 false）。

### FR-5 摘要复用策略（P1）

- 当前实现直接使用原文拼接（indexer 的 LLM 摘要在其协程内部生成，
  无法在不调度它的情况下复用）；
- 若后续 pgvector 路径修复/收敛（Phase 4），应在 `remote_memory.py` 内
  调 `model_router.get_llm(task_type="memory_indexing")` 生成一句话摘要后
  写入，避免存储原文冗余。本项为 Phase 4 待办，不阻塞本阶段验收。

## 5. 非功能需求

| 编号 | 需求 | 指标 |
|---|---|---|
| NFR-1 | 零延迟增加 | save_turn 不在回复路径上 await；回复 P99 延迟无可测变化 |
| NFR-2 | 故障隔离 | 记忆服务 5xx/超时/断网 → 仅 warning 日志，0 用户可见错误 |
| NFR-3 | 资源安全 | 后台任务不泄漏（done-callback 清理）；单请求超时 ≤ remote_timeout |
| NFR-4 | 数据上限 | 单片段内容 ≤ max_save_length 字符，防止大回复撑爆记忆库 |

## 6. 验收标准

- [x] AC-1：`AsyncMemoryClient.remember_fragment` 存在且签名含 metadata；
  SDK 自有测试套件无回归（70 passed）
- [x] AC-2：flag 开启 + store 启用时，一轮对话触发一次
  `POST /memory/fragments`，metadata 四字段齐全
- [x] AC-3：summary 非空时内容为 summary；超长内容截断至 max_save_length
- [x] AC-4：写入抛异常/超时不向上传播（单测覆盖）
- [x] AC-5：flag 关闭时零调用（`_pending_tasks` 为空）
- [x] AC-6：后台任务完成后引用集合自动清空
- [x] AC-7（集成）：真实后端 remember→片段可查
  （已验收：本地拉起记忆服务，`test_remote_memory_integration.py` 2 passed；
  验收中发现并修复后端召回链路 workspace_id 丢失 bug，见 Phase 3 PRD §9）

## 7. 测试计划

- 单测（AsyncMock，无网络）：`TestSaveTurn` 5 项 + `TestSaveTurnBackground`
  2 项，覆盖 metadata、截断、summary 优先、异常吞噬、禁用短路、后台调度；
- 集成：`test_save_then_recall_roundtrip`（依赖 AGENT_MEMORY_URL/KEY，
  未配置自动 skip）；
- 回归：flag 关闭跑全量单测（800 passed）。

## 8. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 高频对话导致记忆库低质量片段膨胀 | 中 | max_save_length 限长；Phase 4 引入 TTL + importance_score 生命周期 |
| 双写期间两侧数据语义不一致（pgvector 存摘要，远程存原文拼接） | 低 | 过渡期可接受；Phase 4 统一为摘要写入（FR-5） |
| 进程退出时在途写入任务丢失 | 低 | fire-and-forget 语义下可接受（丢单轮记忆不影响正确性）；close() 在 shutdown 尾部执行 |

## 9. 实施记录（验收快照）

- 交付文件：`agent_memory/async_client.py`（SDK 补丁）、
  `xiaopaw/memory/remote_memory.py`（save_turn/save_turn_background）、
  `xiaopaw/agents/main_crew.py`（run_and_index 双写接入）
- 验证结果：单测 19/19；SDK 测试 70 passed（1 失败为存量 langchain
  可选依赖缺失，与本阶段无关）
- **存量问题备注**：`run_and_index` 中 pgvector 的 `_index_coroutine`
  创建后未被 await/调度，疑似存量 bug（本阶段未改动，建议单独立项确认）。
  远程写入使用 `asyncio.create_task` 正确调度，不受影响。
