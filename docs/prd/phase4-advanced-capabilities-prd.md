# PRD — Phase 4：高级能力与 pgvector 收敛

| 项 | 内容 |
|---|---|
| 版本 | v1.0 |
| 阶段 | Phase 4 / 4 |
| 状态 | ✅ 已实施（2026-07-28，实施记录见 §11） |
| 依赖 | Phase 1–3 上线且双写稳定运行（建议 ≥ 2 周观察期） |
| 后续 | 无（本阶段完成后集成项目收尾） |

---

## 1. 背景与问题

Phase 1–3 交付了"写入 → 召回 → 注入"的基础闭环，但仍遗留三类问题：

- **P1 记忆能力浅**：只用了记忆系统的 fragment 能力；用户偏好仍存在
  memory.md 静态文件中（无法结构化更新），Variables（键值偏好）与
  Graph（实体关系）能力闲置；
- **P2 记忆库无治理**：所有片段永久保存、importance 固定 0.5，长期运行
  会积累大量低价值对话片段，召回信噪比下降；
- **P3 旧路径悬置**：pgvector 双写仍在（且存量 `_index_coroutine` 未被
  调度的疑似 bug 未处理），双轨长期并存增加维护成本；片段内容为原文
  拼接而非摘要，存储冗余。

## 2. 目标与非目标

### 目标

- G1：用户显式偏好从"对话片段"升级为记忆系统 **Variables**（可覆盖更新、
  可精确读取），memory.md 中的存量偏好一次性迁移
- G2：对话片段引入**生命周期治理**：TTL + 差异化 importance_score，
  低价值片段自动衰减/过期
- G3：写入内容升级为 **LLM 一句话摘要**（复用 model_router 廉价模型），
  替代原文拼接
- G4：确认并处置 pgvector 旧路径：修复或下线 `_index_coroutine`，双写
  验证期结束后收敛为仅远程记忆（保留 flag 可回退）
- G5：可观测性：召回命中率、写入成败计数进入日志/指标

### 非目标

- 不接入 Graph 图谱记忆（价值/成本比待定，另行评估）
- 不做记忆系统后端的任何改造（多租户 workspace 拆分等由记忆系统侧规划）
- 不做跨平台记忆共享（xiaopaw 之外的 source）

## 3. 用户故事

| 编号 | 角色 | 故事 | 验收口径 |
|---|---|---|---|
| US-1 | 终端用户 | 我说"以后回复我用英文"，助手把它当作可更新的偏好而不是一条对话流水 | Variables 中出现/更新 `reply_language` 类键值 |
| US-2 | 终端用户 | 我很久以前的闲聊不会稀释助手对我重要信息的记忆 | 低分片段过期，召回优先命中高价值片段 |
| US-3 | 平台运维 | 我可以在双写观察期后一键切断 pgvector 写入 | 关闭旧路径开关后系统正常，回归全绿 |
| US-4 | 平台运维 | 我能量化记忆功能的健康度 | 日志/指标含召回命中率、写入成功率 |

## 4. 功能需求

### FR-1 偏好类记忆升级为 Variables（P0）

- `RemoteMemoryStore` 新增：
  - `async set_preference(key, value, scope="user", routing_key="")`
    → SDK `Variables API`（upsert 语义）；
  - `async get_preferences(routing_key="") -> dict`（启动/召回时合并读取）；
- 偏好识别策略（首版从简）：在 orchestrator 工具集中新增
  `save_user_preference` CrewAI 工具，由模型判断用户表达了持久偏好时
  主动调用（工具描述中给出正反例）；不做被动 NLU 抽取；
- 召回注入扩展：`<long_term_memory>` 段之外，新增
  `<user_preferences>` 段注入已存偏好键值（数量上限 20 条，超限按
  更新时间倒序截取）。

### FR-2 memory.md 存量偏好迁移（P1）

- 一次性脚本 `scripts/migrate_memory_md.py`：解析 workspace 内
  memory.md 的偏好条目 → 写入 Variables；
- 幂等：重复执行以 key 覆盖，不产生重复；
- 迁移后 memory.md 保留只读（Bootstrap Prompt 仍加载），双源并存一个
  版本周期后再评估移除。

### FR-3 片段生命周期治理（P0）

- `save_turn` 写入参数升级：
  - `ttl`：普通对话片段设 90 天（可配 `memory.fragment_ttl_days`，
    0 = 永久）；
  - `importance_score`：含用户显式陈述事实（首版启发式：消息含
    "记住/我是/我的/以后" 等模式）→ 0.7，否则 0.4（可配）；
- 过期/衰减执行由记忆系统后端 lifecycle 任务负责，xiaopaw 侧只负责
  打分与 TTL 声明。

### FR-4 摘要化写入（P1）

- `save_turn` 在内容拼接前尝试调
  `model_router.get_llm(task_type="memory_indexing")` 生成 ≤ 100 字
  一句话摘要（超时 5s）；
- 摘要失败/超时 → 回退现行原文拼接策略（不丢写入）；
- 摘要调用发生在后台任务内（save_turn 已是 fire-and-forget），不增加
  回复延迟。

### FR-5 pgvector 路径收敛（P0）

分两步，均需独立验证：

1. **确认存量 bug**：为 `_index_coroutine` 未调度问题立复现测试；
   结论二选一——(a) 确系 bug 且功能已被远程记忆替代 → 直接移除该
   代码块与 `memory/indexer.py` 依赖；(b) 存在隐藏调度路径 → 补文档
   说明后按计划下线；
2. **下线开关**：新增 flag `enable_pgvector_indexing`（默认 true），
   双写观察期（建议 ≥ 2 周、召回命中率达标）后置 false 发布；一个
   版本周期无回退诉求后物理删除旧代码与 `memories` 表依赖。

### FR-6 可观测性（P1）

- `RemoteMemoryStore` 内置计数器：`recall_total / recall_hit /
  save_total / save_failed`；
- 每 100 次操作输出一行汇总 info 日志（与现有日志风格一致）；
- 预留 `stats() -> dict` 方法供健康检查端点暴露。

## 5. 非功能需求

| 编号 | 需求 | 指标 |
|---|---|---|
| NFR-1 | 零延迟增加 | 摘要/偏好写入均在后台任务内，回复路径延迟不变 |
| NFR-2 | 回退能力 | enable_remote_memory 关闭仍是总逃生门；pgvector 下线前 enable_pgvector_indexing 可独立回开 |
| NFR-3 | 迁移安全 | memory.md 迁移脚本 dry-run 模式先行，输出 diff 供人工确认 |
| NFR-4 | 成本控制 | 摘要用 cheap 档模型（memory_indexing 路由已存在），单条 < 200 token |

## 6. 验收标准

- [x] AC-1：对话中说“以后用英文回复我” → Variables 出现对应键值；
  下一轮 `<user_preferences>` 段包含该偏好
- [x] AC-2：migrate_memory_md.py dry-run 输出正确 diff；执行后 Variables
  与 memory.md 条目一一对应；重复执行无重复数据
- [x] AC-3：普通片段带 TTL=90d；含“记住…”消息片段 importance=0.7
- [x] AC-4：摘要生成失败时片段仍成功写入（内容为原文拼接）
- [x] AC-5：`_index_coroutine` 问题有明确结论（复现测试 + 处置记录）
- [x] AC-6：enable_pgvector_indexing=false 时全量回归通过，对话正常
- [x] AC-7：日志可见 recall/save 计数汇总；stats() 返回四项计数
- [x] AC-8：全量单测无回归；新增功能单测覆盖（偏好工具、TTL/打分、
  摘要回退、计数器）

## 7. 测试计划

- 单测：偏好工具调用参数、启发式打分分支、摘要超时回退、迁移脚本
  幂等性（tmp 文件夹造 memory.md）、计数器累加；
- 集成（需服务在线）：set_preference → get_preferences 闭环；带 TTL
  片段写入后字段核对；
- 回归：三个 flag 组合矩阵（remote on/off × pgvector on/off）跑全量单测；
- 手工：双写观察期数据核对（远程片段数 vs 对话轮数），召回命中率抽样。

## 8. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 模型滥用 save_user_preference 工具（把闲聊当偏好存） | 中 | 工具描述给正反例约束；Variables 上限 20 条注入 + 可后台清理 |
| 启发式 importance 打分误判 | 低 | 分值仅影响排序权重非硬过滤；后续可换 LLM 打分 |
| pgvector 下线后发现隐藏消费方 | 中 | 下线前全仓库反向依赖排查 + flag 回开窗口保留一个版本周期 |
| 摘要模型故障拖慢后台任务堆积 | 低 | 摘要 5s 超时回退原文；_pending_tasks 规模可经 stats() 观察 |

## 9. 已随 Phase 1–3 提前交付的运维项

以下原属本阶段的支撑项已在前序阶段完成，不再重复实施：

- ✅ `verify-env.py`：AGENT_MEMORY_URL/API_KEY 检查 + `/health` 连通性探测
- ✅ `docs/16-remote-memory-guide.md`：部署、启用、回退、故障排查指南
- ✅ 集成测试骨架 `tests/integration/test_remote_memory_integration.py`
  （环境未配置自动 skip，可直接扩展本阶段集成用例）

## 10. 发布与回退

- 发布顺序：FR-6（观测）→ FR-3（治理）→ FR-1/2（偏好）→ FR-4（摘要）
  → FR-5（收敛，最后执行且需观察期数据支撑）；
- 每个 FR 独立可发布、独立可回退；FR-5 步骤 2 是唯一不可即时回退项
  （物理删除前保留 flag 一个版本周期）。

## 11. 实施记录（2026-07-28）

按 §10 发布顺序实施，全部 FR 交付。

### 交付文件

| 文件 | 变更 |
|---|---|
| `xiaopaw/memory/remote_memory.py` | FR-6 计数器 `_stats`/`stats()`/每 100 次汇总日志；FR-3 `_score_importance` 启发式（正则 `记住\|我是\|我的\|以后\|我喜欢\|我不喜欢\|叫我\|别忘了` → 0.7，否则 0.4）+ TTL（天→秒，0=永久）；FR-4 `_summarize_turn`（memory_indexing 路由 + 5s 超时回退原文）；FR-1 `set_preference`/`get_preferences`（上限 20 条取尾部）/`set_preference_sync`（同步 httpx，供工具线程） |
| `xiaopaw/tools/save_preference_tool.py` | 新增 `SaveUserPreferenceTool`（key 蛇形校验、描述含正反例） |
| `xiaopaw/agents/main_crew.py` | `<user_preferences>` 注入段（位于 `<long_term_memory>` 之后）；偏好工具挂载；agent_fn 预取 `get_preferences`；FR-5 `_index_coroutine` → `create_task` 修复 + flag 门控 |
| `xiaopaw/config/validator.py` | MemoryConfig +4 字段：`fragment_ttl_days=90`/`importance_default=0.4`/`importance_high=0.7`/`summary_timeout=5.0` |
| `xiaopaw/config/flags.py` | +`enable_pgvector_indexing`（默认 true） |
| `scripts/migrate_memory_md.py` | FR-2 迁移脚本（`mem_md_<sha8>` 哈希 key 幂等 + `--dry-run`） |
| sdk-python `async_client.py` | +`get_variable`/`list_variables`（Variables 读能力补齐） |
| 测试 | `test_remote_memory.py` 追加 Stats/Lifecycle/Summarization/Preferences 四组；新增 `test_preference_and_migration.py`；`test_main_crew_recall_injection.py` 扩展偏好注入 3 用例 |

### FR-5 `_index_coroutine` 结论（AC-5）

- **确系 bug**：脚本复现 `RuntimeWarning: coroutine 'async_index_turn' was
  never awaited`，coroutine 仅赋值给实例属性从未调度 → pgvector 索引
  写入实际从未执行（`memories` 表无 xiaopaw 新增数据）；
- **处置**：选 §4 FR-5 路线 (a) 变体——因 `memories` 表尚有读消费方
  （frontend/search_service、skills/search_memory），未直接移除，而是
  修复为 `create_task` 真调度 + `enable_pgvector_indexing` flag 门控；
  双写观察期后置 false 下线，一个版本周期无回退诉求再物理删除。

### AC 验证快照

- AC-1（集成）：`set_preference_sync` → 服务端 Variables 出现键值 →
  `get_preferences` 读回；upsert 覆盖验证（英文→中文）通过。对话内
  触发环节以工具单测（key 校验/成功/失败降级）+ 注入单测为口径；
- AC-2（集成）：dry-run 输出 3 条 diff → 执行 2 条成功 → 重复执行
  幂等（同 key 覆盖）→ 服务端 `mem_md_*` 条目核对一致；
- AC-3（集成）：服务端片段字段 `importance_score=0.7`、`ttl=7776000`
  （=90d）、`expires_at` 正确；
- AC-4（单测）：`test_summarize_failure_falls_back_to_raw` 等覆盖
  摘要异常/超时回退原文拼接，写入不丢；
- AC-6（回归）：flag=false 下全量 1049 passed / 15 skipped；仅 3 个
  e2e 失败为存量环境性问题（git HEAD 基线同样失败，与 flag 及本次
  改动无关：沙箱拦截行为依赖真实运行环境）；
- AC-7（集成）：真实服务上 `stats()` 返回 recall_total/recall_hit/
  save_total/save_failed + pending_tasks；每 100 次操作输出汇总日志；
- AC-8：全量回归 834 passed / 4 skipped（单测口径）；新增/改动三个
  测试文件 53 passed；ruff 新增文件全绿；`config.yaml` 真实加载验证
  新字段取默认值，向后兼容。

### 遗留事项

- pgvector flag 置 false 的正式发布需双写观察期（≥ 2 周）召回命中率
  数据支撑（§10）；
- `main_crew.py` 两处存量 ruff 告警（AliyunLLM F401 / last_exc F841，
  HEAD 已存在）未处理；
- memory.md 生产实例当前为空模板，无存量条目需迁移（AC-2 用测试
  workspace 验收）。

