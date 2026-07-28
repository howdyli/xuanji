# 玄机 × 记忆系统 全场景集成测试报告

- 日期：2026-07-28
- 测试方式：真实链路端到端（浏览器/API 向玄机发消息 → 检查玄机日志 + 记忆后端 API + SQLite 落库）
- 环境：玄机 `127.0.0.1:8080`（admin，routing_key `p2p:web_admin` → 记忆侧 user 9943 / workspace 134）；记忆后端 `127.0.0.1:8000`（SQLite + Chroma + Redis）
- 配置：`enable_remote_memory` / `enable_structured_tables` / direct-answer bypass 均开启；`remote_timeout: 10.0`；片段 TTL 90 天

## 一、场景清单（代码梳理）

| # | 场景 | 调用点 | 记忆 API |
|---|------|--------|----------|
| S1 | 主链路召回 + 偏好注入 | `main_crew.agent_fn` 预取 → backstory `<long_term_memory>` / `<user_preferences>` | recall / variables |
| S2 | 直答旁路召回 + 偏好注入 | `direct_answer.direct_answer_fn` → system_prompt 注入 | recall / variables |
| S3 | 每轮对话落长期记忆 | `save_turn_background`（LLM 摘要 → importance 打分 → remember_fragment，fire-and-forget） | fragments |
| S4 | 用户偏好保存 | `SaveUserPreferenceTool`（LLM 工具调用） | variables upsert |
| S5 | 结构化记录写入 | `SaveStructuredRecordTool`（白名单 todo/expense） | tables insert |
| S6 | 结构化记录查询 | `QueryStructuredRecordsTool`（filters） | tables query |
| S7 | 全路径异常降级 | 所有调用点吞异常/超时，不阻断对话 | — |

## 二、测试结果（T1–T8）

| 用例 | 输入 | 覆盖 | 结果 | 证据 |
|------|------|------|------|------|
| T1 | 「以后请叫我队长」 | S4 + S3 | ✅ | Variables `preferred_name=队长`；片段 37644（importance 0.7，命中重要模式） |
| T2 | 混合 query（含称呼确认） | S1 | ✅* | 回答"队长"（偏好注入生效）；过敏片段未进 top10（排序稀释，见观察项 O2） |
| T3 | 「你好呀」（bypass 路径） | S2 | ✅ | 直答回复"队长你好"，偏好注入生效 |
| T4 | 「记个待办：周五提交测试报告」 | S5 | ✅ | 工具调用 `save_structured_record`，todo 表 record id=7 |
| T5 | 「我有哪些没完成的待办」 | S6 | ✅ | `query_structured_records filters={'status':'pending'}`，准确返回 2 条 |
| T6 | 「我对什么食物过敏来着」 | S1 聚焦召回 | ✅ | 正确回答"您对花生过敏" |
| T7 | kill 记忆后端后对话 | S7 | ✅ | 对话正常返回，仅 WARNING 日志，无阻断/报错 |
| T8 | 重启后端后对话 | S7 恢复自愈 | ✅ | 无需重启玄机，偏好注入立即恢复（答"队长"） |

## 三、BUG

### BUG-M1：direct-answer 旁路只读不写记忆（已修复 ✅）

- **现象**：bypass 路径（`is_simple_chat` 命中的短消息）注入了记忆但返回前不调 `save_turn_background`。日志比对：7 条消息仅 3 次 "saved turn"。
- **实锤**：bypass 路径说「我对芒果也过敏哦」→ 回复"已更新记忆"，但 fragments 37→37，**信息实际丢失**。
- **影响**：用户在简单闲聊中陈述的重要事实（过敏、称呼等）静默丢失，且助手口头确认"已记住"，属高风险数据丢失。
- **修复**：`xiaopaw/agents/direct_answer.py` 返回前补 `save_turn_background`（与 main_crew 行为一致，fire-and-forget）。
- **复测**：「我对海鲜也过敏」→ fragments 37→38（片段 37647）✅；后续「我对什么过敏」可召回海鲜信息。
- **遗留**：修复前丢失的"芒果过敏"未入库，需用户重新告知或手工补录。

## 四、观察项（非玄机侧 bug，供记忆系统侧参考）

| # | 观察项 | 详情 | 建议 |
|---|--------|------|------|
| O1 | recall 间歇超时 10s | 新 query 的 embedding 冷计算需 1.8~7s+（缓存命中仅 9ms），间歇超过玄机 `remote_timeout: 10.0`，该轮降级为无记忆 | 记忆后端预热/常驻 embedding 模型；或玄机侧超时上调 |
| O2 | 混合 query 排序稀释 | 多主题混合提问时目标片段可能不进 top10（直接 API 验证 37644 相似度 0.81 正常）| 聚焦提问可召回；属向量检索固有特性 |
| O3 | fragment metadata 静默丢弃（**已修复 ✅**） | `save_turn` 传入的 metadata（session_id/routing_key/source）后端未落库：`memory_fragment_service.py` 构建了 `meta_json` 但 INSERT 未包含，且 `memory_fragments` 表无对应列，API 读回 `metadata: null` | 已修复：表加 `extra_data` 列（DDL/兼容 ALTER/迁移 v9）+ INSERT 补字段 + 读路径解析回 `metadata`；端到端验证写入/读回均正确 |
| O4 | Variables 存 Redis | `memory_variables` SQLite 表为空是正常的——Variables 实际持久化在 Redis（`set_memory_variable`），T8 重启后仍可读回 | 无需处理，注意备份策略需覆盖 Redis |

## 五、数据快照（测试结束时）

- fragments（全库 active）：34714 条；本次新增 37644–37648，TTL 均 7776000（90 天）、expires_at 正确、importance 打分正确（37644=0.7 其余 0.4）
- Variables：`preferred_name=队长`（Redis）
- todo 表（`memory_9943_w134_todo`）：4 条（done×2 / pending×2，含本次 T4 写入 id=7）
- expense 表：1 条（此前测试遗留）

## 六、结论

7 类调用场景全部验证通过；发现并修复 1 个数据丢失级 BUG（BUG-M1）；观察项 O3（metadata 丢弃）已在记忆后端修复并验证，O1（embedding 冷启动延迟）影响召回稳定性建议优先处理。玄机侧降级策略（S7）表现良好：后端宕机不阻断对话、恢复后免重启自愈。

> 改动文件：`xiaopaw/agents/direct_answer.py`（BUG-M1 修复）；记忆后端 `memory_fragment_service.py` / `db_client.py` / `schema_ddl.py` / `migrations.py`（O3 metadata 落库修复）。均尚未 git 提交。
