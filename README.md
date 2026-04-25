# XiaoPaw v3 — 飞书本地工作助手（系统加固版）

> **版本**：v3.0（2026-04-25）| 极客时间《企业级多智能体设计实战》课程配套代码。
> 从第 17 课骨架出发，经历四代演进：能力(L17) → 记忆(L22) → 协作(L29) → **加固(L30-33)**。

---

## 课程学习导航

| 你跟到了哪课 | 先看 |
|---|---|
| 第 17 课（能力骨架） | `xiaopaw/runner.py` + `xiaopaw/agents/` |
| 第 22 课（三层记忆） | `xiaopaw/memory/` + [DESIGN.md](DESIGN.md) |
| 第 29 课（零编排协作） | `xiaopaw/agents/skill_crew.py` |
| 第 30 课（Hook 框架） | `xiaopaw/hook_framework/` + [docs/12-hook-hardening.md](docs/12-hook-hardening.md) §1-§5 |
| 第 31 课（策略模式） | `xiaopaw/hook_framework/crew_adapter.py` + §6-§8 |
| 第 32 课（安全策略） | `shared_hooks/sandbox_guard.py` + `shared_hooks/permission_gate.py` |
| **第 33 课（系统加固）** | **`shared_hooks/hooks.yaml` → 9 个策略文件** |

## 角色导航

| 你的角色 | 先读 |
|---|---|
| 第一次接触项目 | [DESIGN.md](DESIGN.md) §1-§4 + v2.0→v2.1 变更日志 |
| 准备实施 | [docs/02-modules.md](docs/02-modules.md) + [docs/05-concurrency.md](docs/05-concurrency.md) + [docs/ssot/](docs/ssot/) |
| 负责部署 | [docs/08-deployment.md](docs/08-deployment.md) + [docs/11-migration-v1-to-v2.md §2](docs/11-migration-v1-to-v2.md) |
| 负责安全 | [docs/12-hook-hardening.md](docs/12-hook-hardening.md) §9-§10 + `shared_hooks/` |
| 从 v1 迁移 | [docs/11-migration-v1-to-v2.md](docs/11-migration-v1-to-v2.md) |
| 写测试 | [docs/10-testing.md](docs/10-testing.md) + [docs/test-cases-for-known-risks.md](docs/test-cases-for-known-risks.md) |

### SSOT 权威清单（所有数值与规则引用这里）

- [`docs/ssot/locks.md`](docs/ssot/locks.md) — 所有锁
- [`docs/ssot/tasks.md`](docs/ssot/tasks.md) — 所有 asyncio Task + shutdown 顺序
- [`docs/ssot/ports.md`](docs/ssot/ports.md) — 所有端口（8090 / 9090 / 8080）
- [`docs/ssot/feature-flags.md`](docs/ssot/feature-flags.md) — feature flags（F1-F18）
- [`docs/ssot/threats.md`](docs/ssot/threats.md) — 威胁模型（T1-T14）

### Phase 0 专题报告

- [`docs/sdk-verification-report.md`](docs/sdk-verification-report.md) — SDK 真相（lark/crewai/psycopg）
- [`docs/concurrency-verification-report.md`](docs/concurrency-verification-report.md) — 并发真相
- [`docs/iteration-v2.1-plan.md`](docs/iteration-v2.1-plan.md) — v2.1 迭代计划

---

## 技术栈

| 组件 | 用途 |
|---|---|
| Python 3.11+ | 主语言（async / asyncio） |
| CrewAI | Agent 编排（`@CrewBase` + `@before_llm_call`） |
| lark-oapi | 飞书 SDK |
| Qwen3-max | 主 LLM（DashScope 兼容） |
| AIO-Sandbox | MCP 执行沙盒（Docker） |
| pgvector | 记忆搜索（PostgreSQL 扩展） |
| Langfuse | 可观测性（trace / generation / span） |
| croniter | 定时任务 |
| prometheus_client | Metrics |
| cachetools | LRUCache（session lock） |
| tenacity | 重试 |
| filelock | 跨进程锁 |

---

## 快速开始（开发）

### 1. 克隆 & 安装依赖

```bash
git clone <repo> xiaopaw-v2
cd xiaopaw-v2
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 准备凭证

```bash
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入:
#   feishu.app_id / feishu.app_secret
#   agent.model（默认 qwen3-max）

# 环境变量:
export QWEN_API_KEY="your-key"
export FEISHU_APP_ID="your-app-id"
export FEISHU_APP_SECRET="your-secret"

# Langfuse 可观测（可选，推荐）:
export XIAOPAW_LANGFUSE_PUBLIC_KEY="pk-lf-..."
export XIAOPAW_LANGFUSE_SECRET_KEY="sk-lf-..."
export TRACE_TO_LANGFUSE=true
# 也支持通用变量名 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY（XIAOPAW_ 前缀优先）
```

### 3. 启动依赖服务

```bash
# pgvector
docker compose -f pgvector-docker-compose.yaml up -d
sleep 5
psql "$MEMORY_DB_DSN" -f schema.sql

# AIO-Sandbox
docker compose -f sandbox-docker-compose.yaml up -d
```

### 4. 配置 Langfuse（可观测）

如果你已有 Langfuse 实例（自托管或 Cloud），需要为 XiaoPaw 创建独立 project：

1. 打开 Langfuse Web UI → Settings → Projects → **New Project**，命名为 `xiaopaw`
2. 进入新 project → Settings → API Keys → **Create API Key**
3. 将生成的 Public Key 和 Secret Key 填入环境变量：

```bash
export XIAOPAW_LANGFUSE_PUBLIC_KEY="pk-lf-..."
export XIAOPAW_LANGFUSE_SECRET_KEY="sk-lf-..."
export TRACE_TO_LANGFUSE=true
```

> **为什么用 `XIAOPAW_` 前缀？** 如果你的机器上还运行了其他使用 Langfuse 的服务（如 cc-workspace-bot），通用的 `LANGFUSE_PUBLIC_KEY` 会冲突。`XIAOPAW_` 前缀的变量优先级更高，确保 trace 写入正确的 project。如果你的环境只有 XiaoPaw，用通用变量名也可以。

### 5. 启动 XiaoPaw

```bash
export XIAOPAW_ENV=dev
python -m xiaopaw.main

# 或用 docker compose 一键
docker compose -f xiaopaw-docker-compose.yaml up -d
```

### 6. 验证

```bash
# 健康检查
curl http://127.0.0.1:9091/health

# 发测试消息（TestAPI）
curl -X POST http://127.0.0.1:9090/api/test/message \
  -H "Authorization: Bearer $XIAOPAW_TESTAPI_TOKEN" \
  -d '{"routing_key": "p2p:ou_dev_user", "text": "你好"}'
```

---

## 命令速查

```bash
# 全量单元测试
pytest tests/unit/ -v --cov=xiaopaw

# 加固层单元测试（shared_hooks）
pytest tests/unit/shared_hooks/ -v

# 集成测试（不含 llm / sandbox）
pytest tests/integration/ -m "not llm and not sandbox"

# 集成测试（含 llm）
export QWEN_API_KEY=xxx
pytest tests/integration/ -m "llm" -v

# E2E 测试（需要 Langfuse + LLM）
pytest tests/e2e/ -m "not llm_dependent" -v    # 无 LLM 部分
pytest tests/e2e/ -v                             # 全量

# 代码质量
ruff check .
black --check .
bandit -r xiaopaw/

# 启动前安全检查
python -m xiaopaw.config.safety
```

---

## 目录结构

```
xiaopaw-v2/
├── DESIGN.md                 # 设计总纲
├── docs/                     # 详细设计文档（12 篇 + 5 专题）
├── xiaopaw/                  # 主代码
│   ├── hook_framework/       #   Hook 框架（L30-31）
│   ├── agents/               #   Agent 编排
│   ├── memory/               #   三层记忆（L22）
│   ├── session/              #   会话管理
│   ├── llm/                  #   LLM 接入
│   └── runner.py             #   主循环（+pending_deny 检查）
├── shared_hooks/             # 加固层（L33，零业务代码修改）
│   ├── hooks.yaml            #   两段式配置入口
│   ├── structured_log.py     #   JSON 事件日志
│   ├── langfuse_trace.py     #   Langfuse REST ingestion
│   ├── audit_logger.py       #   JSONL 审计日志
│   ├── sandbox_guard.py      #   输入消毒（路径穿越/shell/prompt注入）
│   ├── permission_gate.py    #   工具权限三级控制
│   ├── cost_guard.py         #   成本围栏
│   ├── loop_detector.py      #   循环检测
│   └── retry_tracker.py      #   重试追踪
├── workspace-init/           # workspace 模板
├── tests/                    # 单元 + 集成 + E2E 测试
├── config.yaml.example       # 配置模板
├── schema.sql                # pgvector 表结构
└── docker-compose 系列        # pgvector / sandbox / xiaopaw 三套 compose
```

完整结构见 [DESIGN.md §3](DESIGN.md)。

---

## 数据本地化披露（合规）

XiaoPaw 在处理消息时，会将对话内容发送到以下外部服务：

- **阿里云 DashScope**（Qwen API）：对话内容 + embedding
- **Langfuse**（可观测）：trace 元数据（不含原始对话）
- **百度千帆**（可选）：搜索查询
- **飞书开放平台**：消息收发（飞书本身就是入口）

**企业部署前必须评估**：
- 对话内容是否可包含商业机密（若是，考虑私有化 LLM）
- 数据出境要求（跨境传输合规）
- 数据主体权利（PIPL 导出/删除接口）

详见 [docs/compliance-baseline.md](docs/compliance-baseline.md)。

---

## 贡献指南

- 所有代码变更必须有对应 **设计文档改动**（PR 模板检查）
- 新功能必须先写测试，后写实现（TDD 强制）
- 提交前跑 `pre-commit run --all-files`
- 凭证、密钥、敏感信息**永远不要**提交到 git（`.gitignore` 已配置，但请自查）

---

## License

与原课程示例保持一致。

---

## 致谢

- 极客时间课程组
- CrewAI 社区
- AIO-Sandbox 项目
- 所有在 v1 review 中提供独立视角的 sub-agent review（architect / planner / code-reviewer / security-reviewer）

---

> 问题或建议？请先读 [DESIGN.md](DESIGN.md) 和对应专题文档，再在 issue 中附上你看到的设计章节引用。
