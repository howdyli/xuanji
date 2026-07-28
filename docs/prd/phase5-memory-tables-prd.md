# PRD — Phase 5：结构化记忆表（Tables）对接

| 项 | 内容 |
|---|---|
| 版本 | v1.1（已实施） |
| 阶段 | Phase 5（Phase 1–4 收尾后的扩展项） |
| 状态 | ✅ 已实施（2026-07-28） |
| 依赖 | Phase 4 已上线（偏好工具模式、remote_memory 降级框架复用） |
| 后续 | Graph 图谱记忆（另行评估，不在本期） |

---

## 1. 背景与问题

Phase 1–4 打通了 Fragments（对话摘要片段）与 Variables（键值偏好）两类
记忆能力，但记忆系统的 **Tables（结构化记忆表）** 能力仍闲置：

- 用户在对话中表达的**结构化信息**（待办、开销等）目前只能落为
  非结构化片段，无法过滤、排序、精确更新（如"把周报待办标记完成"）；
- 记忆系统前端的 Tables 页面对 xiaopaw 用户永远为空，能力浪费；
- 记忆系统已提供完整 API（建表 / 增删改查 / 批量 / 自然语言查询
  `POST /memory/tables/{name}/query`），xiaopaw 侧零调用点。

## 2. 目标与非目标

### 目标

- G1：模型判断用户表达了结构化信息时，主动写入记忆表
  （工具路线，复用 Phase 4 `save_user_preference` 的成熟模式）
- G2：模型可按需查询记忆表回答用户（"我有哪些待办？"）
- G3：表结构受白名单管控，防止模型滥用建表导致 schema 泛滥
- G4：全链路降级：记忆服务不可用时工具返回提示，对话不受影响

### 非目标

- 不做被动 NLU 抽取（后端 extraction 路线另行评估）
- 不做表数据的召回注入（避免上下文膨胀；查询由工具按需触发）
- 不接入 `/tables/parse`（自然语言解析建表）与 `execute_sql`（自由
  SQL 面向人不面向模型，权限风险高）
- 不做跨表 join / 聚合分析

## 3. 用户故事

| 编号 | 角色 | 故事 | 验收口径 |
|---|---|---|---|
| US-1 | 终端用户 | 我说"帮我记一下：周五要交周报"，之后能在记忆系统前端的 Tables 页看到这条待办 | `todo` 表出现对应记录 |
| US-2 | 终端用户 | 我问"我有哪些待办？"，助手列出记忆表里的待办 | 回复内容与表记录一致 |
| US-3 | 终端用户 | 我说"周报那条待办完成了"，记录状态被更新而非新增 | 原记录 `status` 字段变更 |
| US-4 | 平台运维 | 模型不会乱建表 | 服务端只存在白名单内的表 |

## 4. 功能需求

### FR-1 SDK Tables 能力补齐（P0）

`sdk-python` `AsyncMemoryClient` 新增（对应后端既有端点）：

- `create_table(table_name, fields)` → `POST /memory/tables`
- `add_record(table_name, record)` → `POST /memory/tables/{name}/records`
- `query_records(table_name, filters=None, limit=100)` →
  `GET /memory/tables/{name}/records`
- `update_records(table_name, filters, updates)` →
  `PUT /memory/tables/{name}/records`
- `list_tables()` → `GET /memory/tables/`

异常处理与现有方法一致：失败返回 None/False/[]，不向上抛。

### FR-2 表白名单与懒建表（P0）

- 新增配置 `memory.structured_tables`：表名 → 字段 schema 映射，
  默认内置两张表：
  - `todo`：`title TEXT / due_date TEXT / status TEXT`（status 默认
    `pending`）
  - `expense`：`item TEXT / amount REAL / date TEXT`
- `RemoteMemoryStore` 新增 `ensure_table_sync(table_name) -> bool`：
  首次写入前建表（服务端已存在则跳过，幂等）；白名单外表名直接
  返回 False；
- 建表结果进程内缓存（`_ensured_tables: set`），同表只探测一次。

### FR-3 写入工具 SaveStructuredRecordTool（P0）

- 新文件 `xiaopaw/tools/save_record_tool.py`，模式对齐
  `SaveUserPreferenceTool`：
  - 参数：`table_name`（白名单校验）、`record`（JSON 对象，字段名
    必须 ⊆ 该表 schema，多余字段拒绝并提示合法字段列表）；
  - `_run` 跑在 executor 线程 → 走同步 httpx 路径（复用
    `set_preference_sync` 的实现约束，禁止跨线程用 AsyncClient）；
  - 工具描述含正反例：✅"帮我记一下周五交周报"→todo；✅"今天打车
    花了 45 元"→expense；❌闲聊/偏好（偏好走 save_user_preference）；
- 挂载条件：`enable_remote_memory` 且新 flag
  `enable_structured_tables`（默认 **false**，灰度开启）。

### FR-4 查询/更新工具 QueryStructuredRecordsTool（P1）

- 参数：`table_name` + 可选 `filters`（等值过滤 dict）；
- 返回紧凑文本（每行一条记录，上限 20 条，超限提示"仅显示前 20 条"）；
  空表/无命中返回明确提示而非空串；
- 更新场景（US-3）首版由"query 查到 record → 模型再调 save 工具带
  `record_id` 走 update 分支"实现；`record` 中含 `record_id` 字段时
  `SaveStructuredRecordTool` 转为更新既有记录。

### FR-5 可观测性（P2）

- `_stats` 计数器扩展两项：`table_write_total / table_write_failed`，
  并入现有 `stats()` 返回与每 100 次汇总日志（FR-6 框架复用）。

## 5. 非功能需求

| 编号 | 需求 | 指标 |
|---|---|---|
| NFR-1 | 降级安全 | 服务不可用时工具返回中文提示，不抛异常、不阻塞对话 |
| NFR-2 | 回退能力 | `enable_structured_tables=false` 即整体下线，行为与 Phase 4 一致 |
| NFR-3 | 权限最小化 | 复用现有 API Key（memory:read + memory:write），无需 delete/sql 权限 |
| NFR-4 | 延迟可控 | 工具调用发生在模型推理环节内（用户显式请求记录，属任务本身），单次 HTTP 超时 ≤ 10s |

## 6. 验收标准

- [x] AC-1：对话说"帮我记一下：周五要交周报" → 模型调
  `save_structured_record` → 服务端 `todo` 表出现记录；前端 Tables
  页可见
- [x] AC-2：`todo` 表不存在时首写自动建表；重复写入不重复建表
  （幂等）；同会话第二次写入不再发建表请求（缓存生效）
- [x] AC-3：白名单外表名（如 `diary`）被工具拒绝，返回提示含合法
  表名列表；服务端无新表产生
- [x] AC-4：问"我有哪些待办？" → 查询工具返回记录 → 回复内容与
  表数据一致
- [x] AC-5：带 `record_id` 的写入转为更新：US-3 场景原记录 status
  变更、记录总数不变
- [x] AC-6：停掉记忆服务 → 工具返回降级提示，对话正常；恢复后
  功能自愈
- [x] AC-7：`enable_structured_tables=false`（默认）时工具不挂载，
  全量回归通过
- [x] AC-8：新增单测覆盖：白名单/字段校验、建表幂等与缓存、更新
  分支、降级路径、计数器

## 7. 测试计划

- 单测：工具参数校验矩阵（非法表名/多余字段/record_id 更新分支）、
  `ensure_table_sync` 幂等与缓存、SDK 新方法（mock httpx）、降级；
- 集成（服务在线）：建表 → 写入 → 查询 → 更新闭环；前端 Tables
  页人工核对；
- 回归：flag on/off 两态全量单测；
- 手工：AC-1/AC-4/AC-5 真实对话场景走查。

## 8. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 模型把闲聊/偏好写进表 | 中 | 工具描述正反例 + 白名单 + 字段校验三重约束；与偏好工具描述互相引流 |
| 模型频繁误触发查询工具 | 低 | 描述限定"用户明确询问记录类信息时"；返回上限 20 条控制上下文 |
| schema 演进（加字段）导致新旧记录不一致 | 中 | 首版 schema 固定在配置中；变更走配置发布 + 后端表结构手工迁移 |
| update 误伤（record_id 张冠李戴） | 中 | 更新前必须先 query 确认 record_id（工具描述强制此顺序） |

## 9. 发布与回退

- 发布顺序：FR-1（SDK）→ FR-2（白名单/建表）→ FR-3（写工具）→
  FR-4（查/更新工具）→ FR-5（观测）；
- `enable_structured_tables` 默认 false 发布，灰度验证 AC-1~AC-6 后
  再默认开启；
- 回退：置 false 即下线全部新行为；已写入的表数据保留在记忆系统侧，
  不做清理（无副作用）。

---

## 10. 实施记录（2026-07-28）

### 交付文件

| FR | 文件 | 内容 |
|---|---|---|
| FR-1 | `pm/agent-memory-system/sdk-python/src/agent_memory/async_client.py` | 新增 `create_table / list_tables / add_record / query_records / update_record` 五方法，失败返 None/False/[] 不抛 |
| FR-2 | `xiaopaw/config/validator.py` | `MemoryConfig.structured_tables` 白名单（内置 todo/expense） |
| FR-2 | `xiaopaw/config/flags.py` | `enable_structured_tables`（默认 false） |
| FR-2/4/5 | `xiaopaw/memory/remote_memory.py` | `ensure_table_sync`（懒建表+进程内缓存）、`add_record_sync / update_record_sync / query_records_sync`、`table_write_total/failed` 计数器 |
| FR-3/4 | `xiaopaw/tools/structured_record_tools.py` | `SaveStructuredRecordTool`（record_id 转更新）+ `QueryStructuredRecordsTool`，白名单+字段子集双校验 |
| FR-3 | `xiaopaw/agents/main_crew.py` | 双 flag 门控挂载两工具 |
| 配套 | `xiaopaw/agents/direct_answer.py` | 直答旁路关键词补"记一下/记个/记录/待办/开销/花了/记账"（否则结构化请求被旁路拦截、工具不可见） |
| 配套 | `config.yaml.example` | structured_tables 示例 + 新 flag 注释 |
| AC-8 | `tests/unit/test_structured_tables.py` | 29 个用例（store 5+7、工具 8+4、配置 3、coerce 3，含 mock httpx） |

### 与草案的差异

1. FR-1 `update_records(filters, updates)` 改为 `update_record(record_id,
   updates)`：后端 `PUT /records` 只支持按 `record_id`（query 参数）
   单条更新，不支持 filters 批量；
2. FR-1 `query_records` 改走 `POST /{name}/query`：`GET /records` 不
   支持 filters，过滤查询只有 POST 端点；
3. FR-3 文件名 `save_record_tool.py` → `structured_record_tools.py`
   （两工具共享校验逻辑，合一文件）。

### AC 验证快照

- AC-1/4/5：TestAPI 真实对话三轮（记录→查询→标记完成），工具调用
  日志 `before_tool_call: save_structured_record` 存证，服务端记录
  id=4 状态 pending→done、总数不变；
- AC-2：集成验证 ensure#1 建表、ensure#2 命中缓存（httpx 仅 1 次
  调用）；服务端已存在时返回成功/含 exist 文本均视为成功；
- AC-3：`diary` 被拒→提示含"expense、todo"；`list_tables` 仅 todo；
- AC-6：坏端口 store 各方法返降级值不抛（Connection refused 仅
  warning）；同步请求无长连接，服务恢复即自愈；
- AC-7：flag 默认 false，全量回归 1020 passed / 4 skipped；
- AC-8：`tests/unit/test_structured_tables.py` 29 passed。

### 运营注意项

- 后端 `create_memory_table` 对已存在的表会**覆盖 schema 元数据**
  （物理表 IF NOT EXISTS 不动）：工具侧永远传完整白名单 schema，
  禁止手工用窄 schema 调 create_table，否则字段会"消失"；
- 本机 `config.yaml` 已将 `enable_structured_tables` 置 true 配合人工
  测试；仓库默认值（flags.py / config.yaml.example）保持 false。
