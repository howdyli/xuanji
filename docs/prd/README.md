# PRD 索引：xiaopaw-v2 接入 agent-memory-system 远程长期记忆

| 文档 | 阶段 | 主题 | 状态 |
|---|---|---|---|
| [phase1-sdk-integration-prd.md](./phase1-sdk-integration-prd.md) | Phase 1 | SDK 接入与配置层 | ✅ 已实施 |
| [phase2-memory-write-prd.md](./phase2-memory-write-prd.md) | Phase 2 | 记忆写入（双写） | ✅ 已实施 |
| [phase3-memory-recall-prd.md](./phase3-memory-recall-prd.md) | Phase 3 | 记忆召回注入（闭环） | ✅ 已实施 |
| [phase4-advanced-capabilities-prd.md](./phase4-advanced-capabilities-prd.md) | Phase 4 | 高级能力与 pgvector 收敛 | 📝 待实施 |

## 项目总目标

让 xiaopaw-v2 智能体操作平台的长期记忆能力，通过 `agent-memory-sdk`（HTTP
模式 + 异步客户端）对接 agent-memory-system 记忆基础设施，形成
**写入 → 召回 → 注入** 的完整记忆闭环，替代当前"只写不读"的 pgvector
索引路径。

## 总体原则（贯穿全部阶段）

1. **零风险回退**：`feature_flags.enable_remote_memory` 默认 `false`；
   关闭时行为与现状逐字节一致。
2. **故障隔离**：记忆服务任何故障（宕机/超时/鉴权失败/SDK 未安装）
   永不阻断对话主流程。
3. **渐进切换**：双写过渡期 pgvector 与远程记忆并行，数据双轨积累，
   稳定后再收敛（Phase 4）。
4. **单点映射**：routing_key → 记忆系统租户的映射策略集中在
   `xiaopaw/memory/remote_memory.py`，演进时只改一处。

## 关联文档

- 实施计划：`.qoder plans/xiaopaw_接入记忆_SDK`（已获批准并实施）
- 运维指南：[docs/16-remote-memory-guide.md](../16-remote-memory-guide.md)
- 记忆系统：`pm/agent-memory-system/`（后端 + sdk-python）
