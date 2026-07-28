# PRD — Phase 1：SDK 接入与配置层

| 项 | 内容 |
|---|---|
| 版本 | v1.0 |
| 阶段 | Phase 1 / 4 |
| 状态 | ✅ 已实施并验收通过 |
| 依赖 | agent-memory-system 后端可部署（docker-compose）；sdk-python 可本地安装 |
| 后续 | Phase 2（写入）、Phase 3（召回）均依赖本阶段交付物 |

---

## 1. 背景与问题

xiaopaw-v2 当前的三层记忆（Bootstrap Prompt / Session Context / pgvector
索引）存在结构性局限：

- **P1 无可插拔抽象**：记忆后端硬编码 pgvector + psycopg2（`memory/indexer.py`
  直接拼 SQL），无法切换/并联其他记忆后端；
- **P2 无统一配置入口**：记忆相关配置只有 `memory.db_dsn` 一项，无法表达
  远程记忆服务的地址、鉴权、召回参数；
- **P3 无渐进开关**：缺少控制新记忆路径的 feature flag，无法灰度。

agent-memory-system 提供了成熟的记忆基础能力（片段/变量/图谱/召回）和
Python SDK（`agent-memory-sdk`），本阶段负责把 SDK "接进来但不启用"——
交付依赖、配置、开关和封装层四件基础设施，为 Phase 2/3 的写入与召回
提供地基。

## 2. 目标与非目标

### 目标

- G1：xiaopaw-v2 可选安装 `agent-memory-sdk`（不装不影响任何现有功能）
- G2：config.yaml 可完整表达远程记忆连接与召回参数，支持环境变量注入
- G3：提供 `enable_remote_memory` feature flag，默认关闭
- G4：提供 `RemoteMemoryStore` 封装层（进程级单例），屏蔽 SDK 细节，
  统一失败降级语义
- G5：应用启动/关闭时正确初始化/释放记忆客户端

### 非目标

- 不实现任何实际的记忆写入（Phase 2）或召回注入（Phase 3）
- 不改动 pgvector 索引路径的任何行为
- 不实现 per-routing_key 多 workspace 租户隔离（Phase 4 演进项）
- 不发布 SDK 到 PyPI（本地路径安装即可）

## 3. 用户故事

| 编号 | 角色 | 故事 | 验收口径 |
|---|---|---|---|
| US-1 | 平台运维 | 我可以通过环境变量 `AGENT_MEMORY_URL` / `AGENT_MEMORY_API_KEY` 配置记忆服务，不用改代码 | 设置环境变量 + flag 后启动日志出现 `remote memory enabled` |
| US-2 | 平台运维 | 我不配置远程记忆时，系统行为与升级前完全一致 | flag 默认 false，回归测试全绿 |
| US-3 | 开发者 | 我调用 `remote_memory_store` 的任何方法都不需要 try/except，失败自动降级 | 封装层内部吞异常并记日志 |
| US-4 | 开发者 | SDK 未安装时系统能正常启动，只是远程记忆不可用 | ImportError 降级为禁用 + 一次性告警 |

## 4. 功能需求

### FR-1 可选依赖声明（P0）

- `pyproject.toml` 新增 optional-dependencies 组 `remote-memory`，内容为
  `agent-memory-sdk>=0.1.0`；
- 注释说明本地开发安装方式：`pip install -e ../pm/agent-memory-system/sdk-python`；
- SDK 仅引入 httpx + pydantic，不得引入 SQLAlchemy/ChromaDB 等 embedded
  模式重依赖（明确不安装 `agent-memory-sdk[embedded]`）。

### FR-2 配置模型扩展（P0）

`xiaopaw/config/validator.py::MemoryConfig` 新增字段（Pydantic 校验）：

| 字段 | 类型 | 默认 | 约束 | 说明 |
|---|---|---|---|---|
| `remote_base_url` | str | `""` | — | 记忆服务地址，**必须含 `/api/v1` 前缀**（SDK 传输层不自动拼接） |
| `remote_api_key` | str | `""` | — | Bearer API Key（`amk_xxx`） |
| `remote_timeout` | float | `10.0` | 1.0 ≤ x ≤ 120.0 | 单请求超时（秒） |
| `recall_top_k` | int | `5` | 1 ≤ x ≤ 20 | 召回片段数 |
| `recall_max_chars` | int | `4000` | 200 ≤ x ≤ 20000 | 召回注入最大字符数 |

- `config.yaml` / `config.yaml.example` 同步补充 memory 段，采用
  `${AGENT_MEMORY_URL:-}` / `${AGENT_MEMORY_API_KEY:-}` shell 风格环境变量
  展开（复用现有 `_expand_env` 机制，未设置解析为空串 = 功能禁用）。

### FR-3 Feature Flag（P0）

- `xiaopaw/config/flags.py::FeatureFlags` 新增 `enable_remote_memory: bool = False`；
- config.yaml / config.yaml.example 的 feature_flags 段补示例（值为 false）；
- flag 语义：**总开关**。false 时 Phase 2/3 的所有读写路径短路，
  `RemoteMemoryStore.init_from_config` 直接返回（保持禁用）。

### FR-4 RemoteMemoryStore 封装层（P0）

新文件 `xiaopaw/memory/remote_memory.py`，对标 `llm/model_router.py`
的进程级单例模式：

- 模块级单例 `remote_memory_store = RemoteMemoryStore()`；
- `init_from_config(memory_cfg, flags)`：
  - flag 关闭 → 记 info 日志，保持禁用；
  - `remote_base_url` 或 `remote_api_key` 为空 → 记 warning，保持禁用；
  - base_url 缺 `/api/` 前缀 → 记 warning 提示可能 404（不阻止启用）；
  - 全部就绪 → `is_enabled = True`；
- `_get_client()` 懒初始化 `AsyncMemoryClient`（复用 httpx 连接池）；
  `agent_memory` 包 ImportError 时降级禁用 + 告警一次，**不抛异常**；
- 对外暴露异步接口 `recall()` / `save_turn()` / `save_turn_background()`
  （行为需求见 Phase 2/3 PRD，本阶段交付接口骨架与降级语义）；
- `close()` 释放 httpx 连接。

### FR-5 生命周期挂接（P0）

- `xiaopaw/main.py` 启动流程：`load_config` 后调用
  `remote_memory_store.init_from_config(cfg.memory, cfg.feature_flags)`；
- 优雅关闭流程：`runner.shutdown()` 后调用 `remote_memory_store.close()`。

### FR-6 环境验证工具（P1）

- `verify-env.py` 的"其他配置项"清单加入 `AGENT_MEMORY_URL` /
  `AGENT_MEMORY_API_KEY`（未设置时提示"远程长期记忆将不可用"，不算失败）；
- `--check-api` 模式下若 `AGENT_MEMORY_URL` 已设置，探测记忆服务
  `/health` 端点（401/404 视为服务在线）。

## 5. 非功能需求

| 编号 | 需求 | 指标 |
|---|---|---|
| NFR-1 | 零回归 | flag 关闭时全量单测通过率 100%，无行为差异 |
| NFR-2 | 可选依赖 | 未安装 SDK 时 `import xiaopaw` 与启动流程零报错 |
| NFR-3 | 配置校验 | 非法值（如 remote_timeout=0.1）启动即报 Pydantic ValidationError |
| NFR-4 | 安全 | API Key 只经环境变量注入，不落盘 config.yaml 明文、不打印到日志 |
| NFR-5 | 代码风格 | ruff 零新增告警；注释/命名与所在文件一致 |

## 6. 验收标准

- [x] AC-1：`pip install -e ../pm/agent-memory-system/sdk-python` 后可
  `from agent_memory.async_client import AsyncMemoryClient`
- [x] AC-2：`load_config(config.yaml)` 携带新字段成功，环境变量正确展开
- [x] AC-3：flag=false / base_url 空 / api_key 空 三种情形下
  `store.is_enabled == False`
- [x] AC-4：完整配置 + flag=true → `store.is_enabled == True`，启动日志
  `remote memory enabled: <url>`
- [x] AC-5：SDK 未安装时首次调用降级禁用，进程不崩溃
- [x] AC-6：单测 `tests/unit/test_remote_memory.py::TestInitFromConfig`
  4 项全绿；全量单测 800 passed 无回归

## 7. 测试计划

- 单测（无网络）：init 分支覆盖（flag 关/缺 url/缺 key/完整）、SDK
  缺失 monkeypatch `builtins.__import__` 模拟 ImportError 降级；
- 手工：`FEISHU_APP_SECRET=x AGENT_MEMORY_URL=... python -c "load_config(...)"`
  验证环境变量展开；`verify-env.py --check-api` 探测输出。

## 8. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| base_url 漏配 `/api/v1` 导致全部 404 | 中 | init 时前缀启发式告警（FR-4）+ 文档/配置注释三处强调 |
| SDK 与 xiaopaw 依赖冲突 | 低 | SDK 仅 httpx+pydantic，均为 xiaopaw 已有依赖族 |
| API Key 泄漏 | 中 | 仅环境变量注入；日志只打 base_url 不打 key |

## 9. 实施记录（验收快照）

- 交付文件：`pyproject.toml`、`xiaopaw/config/validator.py`、
  `xiaopaw/config/flags.py`、`config.yaml`、`config.yaml.example`、
  `xiaopaw/memory/remote_memory.py`（新建）、`xiaopaw/main.py`、`verify-env.py`
- 验证结果：单测 19/19 通过（含本阶段 4 项）；全量回归 800 passed / 4 skipped
