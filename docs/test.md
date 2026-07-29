
写入成功。验证工具确实被调用，再测读取：
写入和读取都端到端验证通过了。日志确认模型调用了 `save_structured_record`（table=todo），查询则召回了包括之前测试留下的共 3 条待办。

## 使用方法总结

**触发写入**——话里带明确的"记录"意图 + 待办/开销内容：
- 「帮我记一下：周五要交周报」→ 写入 `todo` 表
- 「今天午饭花了 35 块，记个账」→ 写入 `expense` 表
- 「把"交周报"标记为已完成」→ 模型先查出 record_id 再带 id 更新

**触发读取**——询问自己记过的东西：
- 「我还有哪些待办没完成？」→ 查 `todo` 表（filters `status=pending`）
- 「看看我这周记的所有开销」→ 查 `expense` 表

**注意两点**：

1. **措辞要含任务型关键词**。简短闲聊会走[直答旁路](file:///Users/howdy/merge-agent/xiaopaw-v2/xiaopaw/agents/direct_answer.py#L40-L50)（无工具、更快），旁路的系统提示明确禁止模型假装"已记录"。「记一下、记录、待办、开销、花了、记账、存到」等词都能穿透旁路进入完整编排；像「周五交周报」这种没有记录意图的说法，模型可能只当聊天。

2. **目前只有两张白名单表**：`todo(title, due_date, status)` 和 `expense(item, amount, date)`。这是 [validator.py](file:///Users/howdy/merge-agent/xiaopaw-v2/xiaopaw/config/validator.py#L81-L94) 的默认值，模型无法自行建表。想加新表（比如书单、健身打卡），在 config 的 `memory` 段下加：

```yaml
memory:
  structured_tables:
    todo:
      - {name: title, type: TEXT}
      - {name: due_date, type: TEXT}
      - {name: status, type: TEXT}
    expense:
      - {name: item, type: TEXT}
      - {name: amount, type: REAL}
      - {name: date, type: TEXT}
    reading_list:            # 新增示例
      - {name: book, type: TEXT}
      - {name: status, type: TEXT}
```

注意：配置里写了 `structured_tables` 会**整体覆盖**默认值，所以要把 todo/expense 一并写上；另外工具的 description 里硬编码了可用表说明（[structured_record_tools.py](file:///Users/howdy/merge-agent/xiaopaw-v2/xiaopaw/tools/structured_record_tools.py#L72-L84)），加新表后最好同步改一下描述，否则模型不知道有新表可用。改完重启容器（`docker restart xiaopaw-main`，config.docker.yaml 是挂载的，改宿主机文件即可）。

数据最终落在记忆系统的 Tables API 里，你也可以在记忆后台（:8000）或玄机 Web 控制台的结构化记录页直接查看。