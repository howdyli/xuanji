# 知识图谱集成测试报告

- 日期：2026-07-28
- 测试对象：agent-memory-system 知识图谱全链路（REST API → 召回引擎 L3 → 前端 UI）
- 测试环境：后端 http://127.0.0.1:8000（uvicorn，PID 65752）、前端 http://localhost:5173（Vite）
- 测试账号：tester（user_id 9943）/ workspace 134（xiaopaw-test）
- 凭证：API Key `amk_aada...ff04`（memory:read + memory:write，无 delete）；JWT（POST /api/v1/auth/login，全权限）
- 测试计划：`reports/graph-memory-integration-test-plan.md`（G1-G16）

## 一、结论

**16 个用例全部通过（其中 G15、G16 为修复后复测通过）。**

发现并修复 4 个 BUG（1 个后端严重缺陷 + 3 个前端缺陷），另有 5 项观察项待后续处理。
xiaopaw-v2 目前完全未对接图谱 API，本轮仅覆盖记忆系统内部链路，xiaopaw 侧对接列为遗留事项。

## 二、用例结果总表

| # | 用例 | 结果 | 关键证据 |
|---|------|------|---------|
| G1 | 实体创建（person/organization） | ✅ | 张三 id=745、老虎科技 id=746，201 created=true |
| G2 | 实体幂等（重复创建） | ✅ | 重复建张三 → created=false，返回同 id=745 |
| G3 | 实体搜索+详情 | ✅ | `curl -G --data-urlencode` 中文查询成功；详情含 relation_counts |
| G4 | 关系创建+中文类型规范化 | ✅ | "同事"→colleague；目标实体李四(747)自动创建；valid_from 生效 |
| G5 | 关系去重 | ✅ | 重复创建 → created=false "关系已存在" |
| G6 | 邻居遍历 depth 1/2 | ✅ | 张三 depth1 三邻居；depth2 去重无重复 |
| G7 | NL 查询 | ✅ | "张三的同事" → 李四 colleague（rel 467） |
| G8 | 关系停用+历史 | ✅ | JWT DELETE rel 468 reason=张三离职 → valid_to/expired_at 落盘；history 2 条（created + 张三离职） |
| G9 | 双时序查询 event/system | ✅ | event@2026-06-01 关系成立、event@2026-07-29 空；system@2026-06-01 空（尚未观测）——语义精确 |
| G10 | 权限校验 | ✅ | read+write Key DELETE → 403 "API key missing permission: memory:delete" |
| G11 | 文本抽取 | ✅ | method=llm，5 实体 2 关系入库（赵敏/明教科技公司/周芷若/张无忌/光明顶大厦） |
| G12 | 重复实体检测 | ✅ | threshold=3 检出 张三↔张三丰 dist=1 |
| G13 | 图谱统计 | ✅ | 10 实体 / 5 活跃关系（停用的 468 正确不计入）/ top_entities 正确 |
| G14 | 社区检测（Louvain） | ✅ | run_id=19，2 社区，modularity 0.495，成员划分精准（张三系 vs 赵敏系） |
| G15 | 召回集成（L3 图谱来源） | ✅（修复后） | BUG-G1 修复后，simulate-recall "张三是谁" → L3 3 条 graph 来源（graph_747/748/754） |
| G16 | 前端 UI 5 Tab 核对 | ✅（修复后） | 见下文 UI 明细；BUG-G2/G3/G4 修复后复验通过 |

## 三、前端 UI 核对明细（G16）

| Tab | 核对内容 | 结果 |
|-----|---------|------|
| 图谱可视化 | 统计卡片 实体/关系/类型/分布 与 API statistics 一致；力导向图渲染全部节点+边标签 | ✅ |
| 实体管理 | 表格全量实体、类型/时间列正确、分页正常；「邻居」按钮修复后触发 `GET /neighbors?entity_id=747` | ✅（修复后） |
| 关系管理 | 修复后：源/目标显示实体名称、停用关系显示红色 inactive | ✅（修复后） |
| 实体抽取 | 输入"鲁迅在北京大学任教，胡适是他的同事。" → method=llm，3 实体 1 关系入库，统计卡片同步更新为 13/6 | ✅ |
| 图谱浏览 | NL 查询"张三的同事"→ 李四；邻居查询 747 → 张三(0.90)+老虎科技(0.70) | ✅（修复后） |

截图（`xiaopaw-v2/screenshots/`）：
- `graph_ui_01_visualization.png` 可视化 Tab（统计卡片+力导向图）
- `graph_ui_02_entities.png` 实体管理表格
- `graph_ui_03_relationships.png` 关系管理（修复前，显示裸 ID + 全 active）
- `graph_ui_04_extract.png` 实体抽取结果
- `graph_ui_05_explore.png` 图谱浏览 NL 查询
- `graph_ui_06_relationships_fixed.png` 关系管理（修复后，名称 + inactive 标红）

## 四、BUG 与修复

### BUG-G1（严重，后端）：召回链路丢失 workspace_id，L3 图谱召回永远失效

- **现象**：`POST /api/v1/playground/simulate-recall` 的 L3 层从不返回图谱来源，全部静默回退语义搜索。
- **根因**：`playground.py → recall_engine.recall_with_entities → context_compressor.search_related_memories → _use_graph_memory` 全链路不透传 workspace_id；`get_neighbors`/`search_entities` 以 `workspace_id=None` 生成 `workspace_id IS NULL` 过滤，workspace 134 下的图数据永远查不到且无任何报错。
- **修复**（3 文件，参数均带默认 None 向后兼容）：
  - `backend/app/services/context_compressor.py`：`search_related_memories` 与 `_use_graph_memory` 增加 workspace_id 参数并传给 get_neighbors/search_entities
  - `backend/app/services/recall_engine.py`：`recall_with_entities` 增加 workspace_id 并透传
  - `backend/app/api/playground.py`：L3 调用点传 `workspace_id=workspace_id`
- **复测**：重启后端后 "张三是谁" → L3 candidates=3，全部 `graph_` 前缀（张三的colleague:李四、张三的friend:王五、实体:张三丰）；已停用的 subordinate 关系正确不出现。

### BUG-G2（前端）：关系管理状态列永远显示 active

- **现象**：已停用关系（rel 468，is_active=0）在关系管理表中仍显示绿色 "active"。
- **根因**：列定义 `dataIndex: 'status'`，但后端返回字段是 `is_active`，render 兜底 `s || 'active'` 掩盖问题。
- **修复**：`frontend/src/pages/GraphMemory.tsx` 状态列改为基于 `is_active` 判断（兼容 status 字段）。

### BUG-G3（前端）：实体表「邻居」按钮点击无效 / 报 TypeError

- **现象**：首次点击无任何请求；从图谱浏览 Tab 再点「查询邻居」时控制台报 `neighborEntityId.trim is not a function`。
- **根因**：① `setNeighborEntityId(r.id); handleNeighbors()` stale closure——useCallback 闭包内仍是旧值；② `r.id` 为数字，存入 state 后对数字调 `.trim()` 崩溃。
- **修复**：`handleNeighbors` 支持直接传入 ID 参数并统一 `String()` 转换；三处调用点同步修改。

### BUG-G4（前端）：关系管理源/目标实体显示裸 ID

- **现象**：源/目标列显示 745/746 等数字而非实体名称。
- **根因**：render 读 `source_entity_name`/`target_entity_name`，后端实际返回 `source_name`/`target_name`。
- **修复**：render 优先读 `source_name`/`target_name`（保留旧字段名兜底）。

## 五、观察项（未修复，建议后续处理）

1. **`EntityGraphTraverser.extract_entities` 正则不覆盖「XX的同事有哪些」句式**——该 query 提不出实体导致 L3 为空；建议补充「XX的YY」类句式或接 LLM 抽取。
2. **`duplicates` 接口 threshold=3 会把相似度为 0 的对也列入**（如 张三↔李四 dist=2 进列表），建议叠加相似度下限过滤。
3. **`_use_graph_memory` 开头的存在性检查 `SELECT COUNT(*) ... WHERE user_id = ?` 未按 workspace 过滤**——仅影响快速短路判断，不影响正确性。
4. **compress 主链路 `_inject_level3` 仍不传 workspace_id**——本轮只修了 playground 调用路径（最小修复）；若 Agent 对话压缩链路需要图谱 L3，需把 workspace_id 接入 `compress → _build_memory_context → _inject_level3`。
5. **可视化 Tab 画布角标「N 关系」统计含已停用关系**（画布 7 关系 vs 统计卡片 6）——语义上可接受（画布展示全量边），如需一致可按 is_active 过滤。

## 六、遗留事项

- **xiaopaw-v2 未对接图谱 API**：sdk-python 已封装 `graph.py`，但 xiaopaw 侧（shared_hooks / 召回注入）没有任何图谱调用；后续可在消息处理链路加实体抽取（POST /extract）与图谱召回。
- **所有代码改动未 git 提交**（含前几轮 Phase 2-5、直答旁路修复、本轮 BUG-G1~G4 修复），请确认后统一提交。
- 测试数据保留在 workspace 134（实体 745-757、关系 467-473、社区 run_id=19），可复用于回归；如需清理可按计划中的清理策略执行。

## 七、测试数据快照（供回归参考）

- 实体：745 张三 / 746 老虎科技 / 747 李四 / 748 王五 / 749 赵敏 / 750 明教科技公司 / 751 周芷若 / 752 张无忌 / 753 光明顶大厦 / 754 张三丰 / 755+ 鲁迅、北京大学、胡适（UI 抽取产生）
- 关系：467 张三-colleague-李四（active）/ 468 张三-subordinate-老虎科技（**已停用**，valid_to=2026-07-28T21:13:17）/ 469 李四-colleague-老虎科技 / 470 张三-friend-王五 / 471 赵敏-colleague-周芷若 / 472 张无忌-superior-赵敏 / 473 鲁迅-colleague-胡适
- 社区检测：run_id=19，2 社区，modularity 0.495
