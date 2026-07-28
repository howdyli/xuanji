# 记忆 Playground 集成测试报告

- 日期：2026-07-28
- 测试对象：agent-memory-system 记忆 Playground（3 个只读模拟端点 + 演变链端点 + 前端 4 Tab）
- 环境：后端 127.0.0.1:8000（SQLite backend/agent_memory.db）、前端 localhost:5173
- 账号：tester（user_id 9943）/ workspace 134；API Key `amk_aada...ff04`（read+write）
- 测试计划：`reports/playground-integration-test-plan.md`（P1-P16）

## 一、结果总览

**16/16 用例通过**（P7 在修复 BUG-P1 后复测通过），发现并修复 1 个后端 BUG，另发现 3 个数据质量问题（正则实体抽取缺陷所致，未修复、已记录）。

| # | 用例 | 结果 | 备注 |
|---|------|------|------|
| P1 | 注入模拟-实体抽取 | ✅ PASS | entity=location/"杭州了"（观察项①：值带尾巴"了"） |
| P2 | 注入模拟-时间推断 | ✅ PASS | "明天出差" → valid_until=2026-07-29T23:59:59，has_expiry=true |
| P3 | 注入模拟-矛盾预判 | ✅ PASS | 北京了→杭州了，latest_wins/superseded_old，would_supersede=[37643] |
| P4 | 注入模拟-只读验证 | ✅ PASS | 多次模拟后 fragments 总数不变 |
| P5 | 注入模拟-参数校验 | ✅ PASS | 空 content → 400 VALIDATION_ERROR |
| P6 | 召回调试-三层结构 | ✅ PASS | L1/L2/L3/budget 四段齐全；L3 3 条 graph_ 来源（BUG-G1 回归通过） |
| P7 | 召回调试-跨层去重 | ✅ PASS* | 首测 L2 恒为 0 → 定位 **BUG-P1**（L2 未传 workspace_id）→ 修复后 L2=10 条、excluded_ids 与 L2 命中 ID 完全一致 |
| P8 | 召回调试-预算控制 | ✅ PASS | budget=200 → utilization=0.255；budget=2000 → 0.4255，均 ≤1 |
| P9 | 召回调试-参数校验 | ✅ PASS | 空 query → 400 |
| P10 | 衰减模拟-plan 90 天 | ✅ PASS | half_life=90；day180=0.25 精确；day87=0.5117≈2^(-87/90)；有效寿命 388.8=90×4.32；61 采样点 |
| P11 | 衰减模拟-info 永久 | ✅ PASS | is_permanent=true，全曲线 1.0，effective_life=null |
| P12 | 衰减模拟-自定义半衰期 | ✅ PASS | half_life_days=30 覆盖生效：day30=0.5、day60=0.25、寿命 129.6 |
| P13 | 演变链 | ✅ PASS | location 链 13 条，链尾 9916/9917 = 37641/37642→37643"北京了"（观察项③：链被垃圾记录污染） |
| P14 | 演变统计 | ✅ PASS | total=19，location=13 与 chain 长度一致；pattern=14/semantic=5 |
| P15 | 认证校验 | ✅ PASS | 无 Authorization → 401 AUTH_INVALID_CREDENTIALS |
| P16 | 前端 UI 4 Tab | ✅ PASS | 见下节，4 张截图，无功能性 console 错误 |

## 二、BUG

### BUG-P1（已修复）：simulate-recall 的 L2 语义召回未传 workspace_id，L2 恒为 0

- 位置：`backend/app/api/playground.py` `_simulate_recall` 中 `engine.recall(...)` 调用
- 现象：任何 query 的 L2 均 0 条（如"我对什么食物过敏？"命不中 active 记忆 37633），`excluded_ids` 恒为空，跨层去重形同虚设
- 根因：`RecallEngine.recall` 的 `workspace_id=None` 时回退到 `workspace_id IS NULL` 过滤，而测试数据全在 workspace 134。与图谱测试的 BUG-G1（L3 丢 workspace_id）同一模式——L3 修了但 L2 漏了
- 修复：L2 调用补传 `workspace_id=workspace_id`
- 复测：L2=10 条（首条即 37633 花生过敏），excluded_ids=[37610,...,37643] 与 L2 命中 ID 完全一致；"张三是谁" L2=10 + L3=3（graph_747/748/754）

### BUG-P2（数据损害，未修复）："住"字正则误匹配导致无关记忆被错误 superseded

- 位置：`backend/app/services/advanced_recall.py` `_UPDATABLE_PATTERNS` 中 `(?:住|搬到|居住在|搬家到)\s*([\w\u4e00-\u9fff]+)`
- 现象：P3 前置真实注入"我搬到北京了"（fragment 37643）时，真实矛盾解决把两条无关的"请**记住**这个集成测试标记"记忆（37641/37642）错误标记为 superseded（evolution_records 9916/9917）
- 根因："记**住**"命中 location 模式，被抽取为 location="这个集成测试标记"，与新 location 冲突后被取代
- 影响：**真实数据损害**——正常记忆被静默停用；且历史上已产生大量垃圾演变记录（见观察项③）
- 建议：正则加否定前瞻排除"记住/居住证"等（如 `(?<![记])住`），或改用 LLM 抽取路径

## 三、观察项

1. **实体值不去尾**："我搬到杭州了" → entity_value="杭州了"（含语气词"了"），抽取值未做后缀清理
2. **L2 召回结果无 score 字段**：simulate-recall 返回的 L2 memories 不含 score，前端 Score 列显示 "-"（L3 有 0.8/0.9 分值），信息量不对称
3. **演变链污染**：location 演变链 13 条中 11 条为"住"误匹配产生的垃圾记录（old/new_value 如"该信息并愿随时提供帮助"、"李伟等8人的电话号码"、"并遵守此偏好"等），BUG-P2 的历史累积后果
4. antd 弃用警告：`Space direction`、`Alert message`、静态 message 函数，均非功能性问题

## 四、前端 UI（P16）明细

| Tab | 操作 | 核对结果 | 截图 |
|-----|------|----------|------|
| ① 注入模拟器 | 输入"我搬到杭州了"→模拟注入 | ①实体 location/杭州了 ②矛盾"北京了→杭州了" latest_wins ③永久有效 ④预览 JSON 含 would_supersede=[37643] + Alert"将取代 1 条旧记忆" | pg_ui_01_injection.png |
| ② 召回调试器 | query"张三是谁" budget=2000 | 预算条 851/2000（43%）；L1 0 条；L2 10/候选10；L3 3 条紫色来源实体 Tag + 橙色"跨层去重排除 10 条" | pg_ui_02_recall.png |
| ③ 生命周期模拟器 | plan/180 天 + 切 info 复测 | plan：半衰期 90/寿命 388.8/day180=0.25，双曲线渲染；info：永久/∞/全 1.0 | pg_ui_03_lifecycle_plan.png |
| ④ 冲突演变链 | location → 加载演变链 | "共 13 个版本" Timeline v1→v13，链尾 v12/v13 为"这个集成测试标记→北京了"，与 API 完全一致 | pg_ui_04_evolution.png |

截图归档：`xiaopaw-v2/screenshots/pg_ui_01~04*.png`

## 五、判定标准复核

- ✅ 只读性：三个 simulate 端点多次调用后 fragments 总数保持 34 不变
- ✅ 衰减数学：decay=2^(-d/half_life) 逐点精确（day87=0.5117、day30=0.5、day180=0.25）；有效寿命=half_life×4.32
- ✅ L3 图谱来源：graph_747/748/754，BUG-G1 修复回归通过

## 六、遗留事项

- BUG-P2 及其历史垃圾演变记录未清理（37641/37642 仍为 superseded 状态，location 演变链含 11 条垃圾记录）
- 本轮改动（playground.py 一行修复）及此前图谱 BUG 修复均未 git 提交
- 测试期间误从项目根目录重启过一次后端（产生了空库与根目录 .venv），已纠正为 `backend/` 目录下 `.venv/bin/python -m uvicorn` 启动、误建空库已删除；根目录多出的 `.venv` 未删除

## 七、测试数据快照

- fragments：总 34（本轮新增 37643"我搬到北京了"，保留作演变链回归数据）
- 演变记录：total=19（location 13 / preference 1 / semantic 5；pattern 14 / semantic 5），链尾 9916/9917
- 后端进程：PID 82698（含 BUG-G1 + BUG-P1 两处 workspace_id 修复）
