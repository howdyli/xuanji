# 记忆 Playground 集成测试计划

- 日期：2026-07-28
- 测试对象：agent-memory-system 记忆 Playground（后端 3 个只读模拟端点 + 演变链复用端点 + 前端 4 Tab）
- 环境：后端 127.0.0.1:8000（PID 65752）、前端 localhost:5173
- 账号：tester（user_id 9943）/ workspace 134；API Key `amk_aada...ff04`（read+write）

## 被测面

| 端点/页面 | 说明 |
|-----------|------|
| POST /api/v1/playground/simulate-injection | 注入模拟：实体抽取→矛盾预判→时间推断→片段预览（只读） |
| POST /api/v1/playground/simulate-recall | 召回调试：L1 变量 / L2 语义 / L3 实体扩展 + Token 预算 |
| POST /api/v1/playground/simulate-decay | 生命周期：半衰期衰减曲线（纯计算） |
| GET /api/v1/memory/evolution/chain | 冲突演变链追溯（需 MEMORY_READ） |
| GET /api/v1/memory/evolution/statistics | 演变统计 |
| 前端 /playground | 4 Tab：注入模拟器 / 召回调试器 / 生命周期模拟器 / 冲突演变链 |

## 用例（P1-P16）

| # | 用例 | 步骤 | 预期 |
|---|------|------|------|
| P1 | 注入模拟-实体抽取 | POST simulate-injection content="我搬到杭州了" | entity=location/杭州；lifecycle info 永久 |
| P2 | 注入模拟-时间推断 | content="我明天要去上海出差" type=plan | valid_until=明日 23:59，has_expiry=true |
| P3 | 注入模拟-矛盾预判 | 先真实注入"我搬到北京了"，再模拟"我搬到杭州了" | contradictions 检出 北京→杭州，predicted_action 合理 |
| P4 | 注入模拟-只读验证 | 模拟前后 fragments 总数对比 | 数量不变（模拟不落库） |
| P5 | 注入模拟-参数校验 | content 为空 | 400 "content 不能为空" |
| P6 | 召回调试-三层结构 | query="张三是谁" budget=2000 | level1/2/3 + budget 四段齐全；L3 出现 graph_ 来源 |
| P7 | 召回调试-跨层去重 | 检查 level3.excluded_ids | = L2 命中的 fragment id 集合 |
| P8 | 召回调试-预算控制 | budget_tokens=200 | token_used/utilization 合理，utilization≤1 |
| P9 | 召回调试-参数校验 | query 为空 | 400 "query 不能为空" |
| P10 | 衰减模拟-plan 90 天 | type=plan days=180 | half_life=90；day180 decay≈0.25；有效寿命≈388.8 天；曲线 61 点 |
| P11 | 衰减模拟-info 永久 | type=info | is_permanent=true，全曲线 decay=1.0，effective_life=null |
| P12 | 衰减模拟-自定义半衰期 | half_life_days=30 | half_life=30 覆盖默认值；day30 decay≈0.5 |
| P13 | 演变链 | 基于 P3 真实注入产生的 superseded 事件，GET chain?entity_type=location | chain 含 北京→杭州 版本记录 |
| P14 | 演变统计 | GET evolution/statistics | 总数/类型分布与 chain 一致 |
| P15 | 认证校验 | 无 Authorization 调 simulate-recall | 401 |
| P16 | 前端 UI 4 Tab | Playwright 登录 → /playground 逐 Tab 操作+截图 | 与 API 数据一致，无 console 崩溃 |

## 判定标准

- 三个 simulate 端点必须只读：任何调用不改变 memory_fragments / graph_* 表数据量
- 衰减数学验证：decay = 2^(-d/half_life)，5% 阈值有效寿命 = half_life × 4.32
- L3 必须走图谱来源（BUG-G1 修复回归点）

## 数据与清理

- P3/P13 会真实注入 2 条 location 记忆（北京→杭州）产生演变链，保留作回归数据
- 其余用例全部只读
