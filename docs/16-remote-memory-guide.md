# 远程长期记忆对接指南（agent-memory-system）

xiaopaw-v2 通过 `agent-memory-sdk` 对接 [agent-memory-system](../../pm/agent-memory-system/)
的记忆基础能力，为智能体提供跨会话的长期记忆闭环（写入 + 召回）。

## 架构

```
┌─────────────────────────── xiaopaw-v2 ───────────────────────────┐
│  agent_fn (main_crew.py)                                         │
│    ① 推理前: RemoteMemoryStore.recall(user_message)              │
│       → 召回上下文注入 orchestrator backstory <long_term_memory> │
│    ② 回复后: RemoteMemoryStore.save_turn_background(...)         │
│       → fire-and-forget 写记忆片段（与 pgvector 索引双写并行）    │
│                                                                   │
│  xiaopaw/memory/remote_memory.py（进程级单例，SDK 封装层）        │
└───────────────────────────────┬──────────────────────────────────┘
                                │ HTTP (AsyncMemoryClient, httpx)
                                ▼
              agent-memory-system 后端 (FastAPI :8000/api/v1)
              POST /memory/fragments   POST /memory/recall
```

失败语义：召回失败/超时返回空串不注入；写入失败仅记日志。记忆服务
故障**永不阻断**对话主流程。

## 启用步骤

### 1. 部署记忆服务

```bash
cd ../pm/agent-memory-system
docker-compose up -d          # backend :8000 + redis（开发环境 SQLite + FakeRedis）
```

在记忆系统管理界面（Settings → API Keys）创建 API Key（`amk_xxx`）。

### 2. 安装 SDK

```bash
# 本地开发（同一工作区）
pip install -e ../pm/agent-memory-system/sdk-python
# 或（SDK 发布后）
pip install "xiaopaw-v2[remote-memory]"
```

### 3. 配置环境变量

```bash
# .env
AGENT_MEMORY_URL=http://localhost:8000/api/v1   # 必须包含 /api/v1 前缀
AGENT_MEMORY_API_KEY=amk_xxxxxxxx
```

### 4. 打开 Feature Flag

```yaml
# config.yaml
feature_flags:
  enable_remote_memory: true
```

### 5. 验证

```bash
python verify-env.py --check-api    # 含记忆服务连通性探测
```

启动后日志出现 `remote memory enabled: http://...` 即生效。

## 配置项（config.yaml → memory 段）

| 配置 | 默认 | 说明 |
|---|---|---|
| `remote_base_url` | `${AGENT_MEMORY_URL:-}` | 记忆服务地址，必须含 `/api/v1` |
| `remote_api_key` | `${AGENT_MEMORY_API_KEY:-}` | Bearer API Key |
| `remote_timeout` | `10.0` | 单次请求超时（秒） |
| `recall_top_k` | `5` | 召回片段数量 |
| `recall_max_chars` | `4000` | 召回注入的最大字符数 |

## 身份映射与回退

- 初期采用**单 workspace** 策略：`routing_key`/`session_id` 写入
  fragment `metadata`，用于用户维度区分；后续可演进为 per-routing_key
  workspace（映射逻辑集中在 `remote_memory.py`）。
- 回退：`enable_remote_memory: false`（默认）即完全回到现状路径；
  双写期间 pgvector 索引持续积累，随时可切回，无数据迁移风险。
