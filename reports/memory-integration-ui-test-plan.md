# xiaopaw ↔ agent-memory-system 记忆对接 UI 全场景测试计划

日期：2026-07-28 ｜ 执行方式：xiaopaw Web 聊天界面（8080）驱动对话 + 记忆系统前端（5173）/ API 双重核对

## 1. 被测环境

| 组件 | 地址 | 状态 |
|---|---|---|
| 记忆后端 | http://127.0.0.1:8000/api/v1 | health 200 |
| 记忆前端 | http://localhost:5173（账号 tester/tester2026，工作区 xiaopaw-test） | 200 |
| 玄机（xiaopaw） | http://127.0.0.1:8080 | 200 |
| TestAPI（辅助） | http://127.0.0.1:9090 | 在线 |

Flag 状态：`enable_remote_memory=true`、`enable_structured_tables=true`（本机 config.yaml）。

## 2. 测试前基线（记忆系统当前数据）

- Variables 5 条：smoke_test / occupation=程序员 / gender=女 / nickname=老虎 / remembered_programs
- Fragments：17 条（均为一句话摘要形态）
- Tables：仅 todo 表，1 条记录 (#4 交周报 done)

## 3. 测试用例

| 编号 | 场景 | 操作（聊天输入） | 预期 | 判定通道 |
|---|---|---|---|---|
| T1 | 偏好保存（Variables upsert） | "以后回复我尽量用简短的要点式中文" | 调 save_user_preference；Variables 新增 reply_style 类键 | 工具日志 + API + 前端 Variables 页 |
| T2 | 偏好注入生效 | 同会话/新会话问任意问题 | 回复呈现要点式风格；`<user_preferences>` 注入 | 回复形态 + save 日志 |
| T3 | 片段写入（摘要+TTL+importance） | "记住：我对花生过敏" | 新片段为一句话摘要、TTL 90d、importance=0.7（命中"记住"） | API 片段字段核对 |
| T4 | 跨会话召回 | 新会话问"我有什么忌口/过敏吗？" | 回复提及花生过敏（本地无历史，只能来自远程召回） | 回复内容 |
| T5 | todo 表写入 | "帮我记个待办：下周三下午3点开产品评审会" | 调 save_structured_record；todo 表新增记录 | 工具日志 + API + 前端 Tables 页 |
| T6 | expense 表写入（懒建表） | "记一笔账：今天打车花了45块" | expense 表自动创建并插入记录 | API：表出现 + 记录正确 |
| T7 | 表查询 | "我的待办都有哪些？" | 调 query_structured_records；回复与表数据一致 | 回复 vs API |
| T8 | 表更新（record_id 分支） | "产品评审会那条待办改成已完成" | 原记录 status 变更、总数不变 | API 前后对比 |
| T9 | 白名单拒绝 | "帮我建一个日记表，把今天的日记存进去" | 不产生白名单外新表；回复礼貌说明 | API tables 列表不变 |
| T10 | 降级安全 | 暂停记忆后端（SIGSTOP）后发"记个待办：测试降级" | 对话正常返回降级提示不崩溃；恢复（SIGCONT）后功能自愈 | 回复 + 日志 warning + 恢复后重试成功 |
| T11 | 前端可视化核对 | 登录 5173 逐页核对 | Variables/Fragments/Tables 页数据与上述一致 | 浏览器截图 |

## 4. 判定标准

- 每用例给出 PASS / FAIL / PARTIAL；FAIL 需附日志与根因初判；
- 工具调用以 xiaopaw 日志 `before_tool_call` 事件为准；
- 服务端数据以记忆系统 API 返回为准，前端页面作可视化佐证。

## 5. 结果

执行完成后见同目录《memory-integration-ui-test-report.md》。
