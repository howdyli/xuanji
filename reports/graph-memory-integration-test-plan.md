# 知识图谱（Graph Memory）集成测试计划

> 日期：2026-07-28
> 范围说明：调研确认 **xiaopaw-v2 尚未对接图谱 API**（`xiaopaw/memory/remote_memory.py` 无任何 graph 调用），
> 因此本轮测试对象为 agent-memory-system 内部的图谱全链路集成：
> **REST API（权限/CRUD/遍历/时序/抽取/NL 查询/社区检测）→ 召回引擎图谱扩展 → 前端图谱页 UI**。
> xiaopaw 侧对接列为遗留事项，待后续 PRD 排期。

## 一、被测环境

| 组件 | 地址 | 状态 |
|---|---|---|
| 记忆系统后端 | http://localhost:8000 (uvicorn PID 23626) | health 200 |
| 记忆系统前端 | http://localhost:5173 (Vite) | 200 |
| 测试身份 | tester / tester2026，workspace_id=134 | - |
| API Key | amk_aadac012...（scope: read+write，**无 delete**） | - |

## 二、测试前基线

`GET /memory/graph/statistics`：entity_count=0，relationship_count=0（图谱为空，干净基线）。

## 三、测试用例

| # | 用例 | 操作 | 预期 | 判定通道 |
|---|---|---|---|---|
| G1 | 实体创建 | POST /graph/entities 创建 张三(person)、老虎科技(organization) | 201，返回 id，created=true | API 响应 + statistics 计数 |
| G2 | 实体幂等 | 重复创建 张三(person) | created=false，返回同 id | API 响应 |
| G3 | 实体搜索/详情 | GET /graph/entities?query=张；GET /graph/entities/{id} | 命中张三；详情含 relation_counts | API 响应 |
| G4 | 关系创建 | POST /graph/relationships：张三-[同事]->李四、张三-[subordinate]->老虎科技、李四-[colleague]->老虎科技、张三-[friend]->王五 | 201，中文"同事"规范化为 colleague，自动 ensure 新实体 | API 响应 + relationships 列表 |
| G5 | 关系去重 | 重复创建 张三-[colleague]->李四 | created=false，"关系已存在" | API 响应 |
| G6 | 邻居遍历 | GET /graph/neighbors?entity_name=张三&depth=1 及 depth=2 | depth1 含李四/老虎科技/王五；depth2 经李四扩展 | API 响应 |
| G7 | NL 图查询 | GET /graph/query?q=张三的同事 | query_type=neighbors，命中李四 | API 响应 |
| G8 | 关系停用+历史 | DELETE /graph/relationships/{张三-老虎科技}（用有 delete 权限的身份或验证 403）；GET /graph/history?entity1=张三&entity2=老虎科技 | 停用后 valid_to/expired_at 写入；history 含 created/ended 两条 | API 响应 |
| G9 | 时序点查询 | GET /graph/temporal?at=停用前时刻&entity=张三（event 模式）；at=停用后时刻 | 停用前时刻关系成立，停用后时刻不返回 | API 响应 |
| G10 | 权限校验 | 用 read+write Key 调 DELETE /graph/entities/{id} | 403（缺 MEMORY_DELETE scope） | HTTP 状态码 |
| G11 | 文本抽取 | POST /graph/extract：一段含人物/组织/关系的中文文本 | entities/relationships 非空，extraction_method=llm 或 regex（DeepSeek 欠费预期回退 regex），stored 计数>0 | API 响应 + statistics 增量 |
| G12 | 去重检测 | 创建相近名实体（张三丰），GET /graph/duplicates?threshold=3 | 检出 张三/张三丰 相似对 | API 响应 |
| G13 | 统计 | GET /graph/statistics | 计数与已建数据一致，top_entities 含张三 | API 响应 |
| G14 | 社区检测 | POST /graph/communities/detect；GET /communities、/communities/stats | success，社区数≥1，label 为度数 Top3 实体名拼接 | API 响应 |
| G15 | 召回集成 | 调用 recall/search 类端点（compress/auto-recall），query 提及"张三" | 召回候选含 source=graph_memory 的关联信息 | API 响应/日志 |
| G16 | 前端 UI 核对 | Playwright 登录 5173 → 知识图谱页 5 个 Tab：可视化/实体管理/关系管理/实体抽取/图谱浏览 | 统计卡片与 API 一致；实体/关系表格正确；抽取与 NL 查询可用；截图留档 | 页面截图 + 数据比对 |

## 四、判定标准

- API 用例：HTTP 状态码 + 响应体字段与预期一致，且 `statistics` 增量吻合。
- 权限用例：403 且响应含权限错误信息。
- UI 用例：页面数据与 API 数据一致，交互无报错，截图存 `screenshots/`。
- LLM 依赖用例（G11）：DeepSeek 账户欠费时回退 regex 属预期行为，不判 FAIL。

## 五、清理策略

测试数据（张三/李四/王五/老虎科技等实体及关系）测试后保留供 UI 核对；如需清理需 delete scope，列入报告遗留事项。
