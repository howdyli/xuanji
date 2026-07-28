# xiaopaw ↔ agent-memory-system 记忆对接 UI 全场景测试报告

日期：2026-07-28 ｜ 计划：同目录《memory-integration-ui-test-plan.md》
执行方式：Playwright 驱动玄机 Web 聊天界面（8080）真实对话 + 记忆系统前端（5173）核对 + API/日志双重存证

## 1. 结论总览

**11 个用例全部最终 PASS；过程中发现并修复 3 个缺陷（均为直答旁路相关），复测通过。**

| 编号 | 场景 | 结果 | 关键证据 |
|---|---|---|---|
| T1 | 偏好保存 | ✅ PASS（修复 BUG-1 后） | `save_user_preference {reply_style: 简短要点式中文}`，Variables 落库 |
| T2 | 偏好注入生效 | ✅ PASS | 新会话问"容器化部署"，回复为要点式列表风格 |
| T3 | 片段写入 | ✅ PASS | "花生过敏"生成一句话摘要片段 + 同步存偏好 food_allergies |
| T4a | 跨会话召回 | ✅ PASS（修复 BUG-2 后） | 新会话问忌口 → "你有花生过敏"（直答旁路 1.17s + 记忆注入） |
| T4b | todo 表写入 | ✅ PASS | 记录 #5 产品评审会 `2026-08-05 15:00` pending（相对日期推算正确） |
| T4c | expense 表懒建+写入 | ✅ PASS | expense 表自动创建，记录 (打车, 45.0, 今天) |
| T5 | 表查询 | ✅ PASS | `query_structured_records` 回复 2 条待办与服务端一致 |
| T6 | 表更新（id 分支） | ✅ PASS | `{'id': 5, 'status': 'done'}`，pending→done 总数不变 |
| T7 | 白名单拒绝 | ✅ PASS（修复 BUG-3 后） | diary 表未创建；模型如实说明并降级用 memory-save 技能存档 |
| T8 | 降级安全+自愈 | ✅ PASS | 后端 SIGSTOP：超时→warning→回退技能，对话不崩；恢复后新会话写入 #6 成功 |
| T9 | 前端可视化核对 | ✅ PASS | Variables 7 条 / todo 3 条 / expense 1 条 / 片段含测试摘要，三页与 API 一致 |

截图存证：`screenshots/t1_preference_save.png`、`t3_cross_session_recall.png`、`t456_structured_tables.png`、`t9_variables_page.png`、`t9_tables_todo.png`、`t9_fragments_page.png`

## 2. 发现并修复的缺陷（均在 xiaopaw/agents/direct_answer.py）

### BUG-1 偏好表达被直答旁路吞掉（严重：静默数据丢失）
- 现象："以后回复我尽量用简短的要点式中文" 被分类为闲聊 → 直答无工具 → 模型口头答应"将遵循"，但偏好**并未保存**。
- 根因：`_TASK_KEYWORDS` 缺偏好类词。
- 修复：补 `以后/叫我/别忘了/我喜欢/我不喜欢/偏好/习惯`。

### BUG-2 直答旁路无记忆上下文（严重：跨会话记忆形同虚设）
- 现象："我有什么忌口或过敏吗？" 走旁路 → 回复"无法获取您的个人健康信息"，而远程记忆里明明有。
- 根因：旁路路径只发裸 system prompt，编排路径的 `<user_preferences>`/`<long_term_memory>` 注入完全缺失。
- 修复：`direct_answer_fn` 内同样调 `remote_memory_store.recall + get_preferences` 注入 system prompt（失败/超时降级为无记忆，不阻断直答）。复测：同问题 1.17s 命中"花生过敏"。

### BUG-3 旁路模型捏造写入成功（中：诚实性）
- 现象："帮我建一个日记表，把今天的日记存进去" 走旁路后回复"已创建日记表并存入 ✅"——实际什么都没发生。
- 根因：关键词缺"建一个/存进去"类词 + 系统提示对"声称已保存"约束不够硬。
- 修复：补 `建一个/建个/存进/存到/存一下` 关键词；系统提示追加"严禁声称已保存/已创建/已记录任何内容"。复测：进编排、白名单正确拒绝 diary、回复如实说明。

## 3. 值得记录的观察（非缺陷）

- T7 白名单拒绝后，模型自发改用 memory-save 技能把日记落沙箱文件并向用户说明"内置表没有日记类别"——降级路径体验良好。
- T8 恢复后在**同一会话**里说"再记个待办"，模型凭上下文直接答"已记下"未再调工具（上下文污染）；新会话则正常写库。多轮内重复指令的工具触发一致性可作为后续观察项。
- expense 记录 date 字段存了字面量"今天"而非解析后的日期（todo 的 due_date 却推算成功），属模型行为波动，可在工具描述中强化"日期需转 ISO 格式"。
- 记忆后端 SIGSTOP 期间 recall 超时 10s + get_preferences 超时会拖慢首响，符合设计（有超时上限），但极端情况下单轮多次超时叠加约 20s，可考虑失败后短暂熔断。

## 4. 回归

- 单元测试：`tests/unit` **863 passed / 4 skipped**（含 direct_answer 27 例）。
- 全量 `pytest`：1081 passed / **6 failed（全部为 e2e，根因 DeepSeek API HTTP 402 Insufficient Balance，环境配额问题，与本次改动无关）** / 10 skipped。上轮基线 1020 通过时 e2e 因服务未运行被跳过，本轮服务在线故 e2e 实跑并撞配额。

## 5. 遗留事项

- e2e 需在 LLM 账户充值后重跑确认。
- 本次 3 处修复 + 此前 Phase 2-5 全部改动仍未 git 提交。
- 测试数据保留在服务端（todo #4/#5/#6、expense #1、Variables 7 条），如需清库可用 tester Key 调 DELETE /records。
