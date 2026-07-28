# 玄机资料库（Library）与知识库（Knowledge Base）功能测试报告

- 测试日期：2026-07-29
- 测试方式：REST API 实测（curl，admin token / Bearer）+ 端到端 agent 对话验证 + 日志与磁盘现场核对
- 被测服务：xiaopaw-v2 @ http://127.0.0.1:8080（测试中重启，最终 PID 53573）
- 依赖状态：PostgreSQL/pgvector 可用；`KNOWLEDGE_EMBED_API_KEY` / `KNOWLEDGE_EMBED_BASE_URL` 已配置

## 一、结论

| 模块 | 用例数 | 通过 | 缺陷 |
|---|---|---|---|
| 资料库 Library | 9 | 9 | 0 |
| 知识库 Knowledge | 25 | 25 | 1（KB-B1：删库不清理磁盘源文件） |
| 环境问题 | — | — | 1（ENV-1：沙箱内启动进程导致 CrewAI 存储只读，非功能缺陷） |

核心链路全部打通：**上传文档 → 异步 ingest ready → 混合检索命中 → 会话绑定 → agent 对话内调用 `search_knowledge_base` 检索并按引用回答**（成功答出测试口令 ZHIJI-KB-TEST-42 并标注来源）。

## 二、资料库测试明细（L1-L9，全部通过）

| # | 用例 | 请求 | 预期 | 实际 |
|---|---|---|---|---|
| L1 | 文件列表 | GET /api/frontend/library/files | 按 session 分组返回 outputs 文件 | ✅ 返回 groups（含 title/icon/file_count/files 元数据） |
| L2 | 未认证列表 | 同上，无 token | 401 | ✅ 401 |
| L3 | 收藏列表（初始） | GET /library/favorites | 空列表 | ✅ `{"paths": []}` |
| L4 | 收藏增/查/删 | POST favorites `{path, action: add\|remove}` | 写入并回读一致 | ✅ add→列表出现→remove→列表清空 |
| L5 | 文件下载 | GET /files/download?path=/workspace/sessions/.../search_result.json | 200 + 完整内容 | ✅ 200，23449 字节与列表 size 一致 |
| L6 | 路径穿越 | path=/workspace/../../../etc/passwd | 拒绝 | ✅ 400 `invalid path`，日志记录 `path traversal blocked` |
| L7 | 下载不存在文件 | path=/workspace/sessions/nonexist/... | 404 | ✅ 404 |
| L8 | 收藏非法 action | action=toggle | 参数校验 | ✅ 400 `path and action (add\|remove) required` |
| L9 | 未认证写收藏 | POST favorites 无 token | 401 | ✅ 401 |

接口约定备注：
- 下载 path 必须带 `/workspace/` 前缀（资料库列表返回的 path 不含该前缀，前端拼接）。
- 收藏参数为 `action: add|remove`，传 `favorite: true/false` 会被拒绝。

## 三、知识库测试明细（K1-K25，全部通过；1 个缺陷）

### 3.1 库 CRUD
| # | 用例 | 预期 | 实际 |
|---|---|---|---|
| K1 | 未认证列库 | 401 | ✅ |
| K2 | 建库空名 | 422 | ✅ `name is required` |
| K3 | 非法 scope=global | 422 | ✅ `scope must be 'personal' or 'org'` |
| K4 | 建个人库 | 201 | ✅ 创建 kb-164b79310328「KB功能测试库」 |

### 3.2 文档上传与入库
| # | 用例 | 预期 | 实际 |
|---|---|---|---|
| K5 | 上传 .md | 202 pending | ✅ doc-f197317973f9 |
| K6 | 上传 .txt | 202 pending | ✅ doc-4b056f469342 |
| K7 | 上传 .exe | 415 | ✅ `unsupported file type: .exe` |
| K8 | 表单无文件 | 422 | ✅ `no file provided` |
| K9 | 非 multipart | 400 | ✅ `multipart/form-data required` |
| K10 | 上传到不存在库 | 404 | ✅ |
| K11 | ingest 状态 | 数秒内转 ready | ✅ 约 1 秒内两文档均 ready，chunk_count=1，源文件落 `data/workspace/.knowledge/{kb_id}/{doc_id}{ext}` |
| K12 | 文档详情分块 | 返回 document+chunks | ✅ chunk 内容与原文一致 |

### 3.3 调试检索
| # | 用例 | 预期 | 实际 |
|---|---|---|---|
| K13 | 指定库检索"测试口令" | 命中测试文档 | ✅ 2 条 citation，[1] 即含口令的 chunk |
| K14 | kb_id 不存在/不可读 | 403 | ✅ `forbidden` |
| K16 | 空 query | 422 | ✅ `query is required` |
| K17 | 省略 kb_id（全租户检索） | 跨库命中 | ✅ 命中测试库 + 存量库「源启智能体平台版本说明V2.2.0.docx」 |
| K15 | 文档详情 404 | 404 | ✅ |

接口约定备注：检索参数为**单数 `kb_id`**（传 `kb_ids` 数组会被忽略并回落全租户检索——租户内合法，非越权，但前端/调用方需注意）；响应字段为 `citations`（n/document_id/chunk_index/title/snippet）。

### 3.4 会话绑定
| # | 用例 | 预期 | 实际 |
|---|---|---|---|
| K18 | GET 绑定（初始） | 空 | ✅ |
| K19 | PUT 绑定 1 库 | 200 | ✅ |
| K20 | GET 回读 | kb_ids + bases 详情 | ✅ |
| K21 | 绑定 6 个 | 422 | ✅ `at most 5 knowledge bases per session` |
| K22 | 绑定不可访问库 | 403 | ✅ `knowledge base not accessible: kb-nonexist` |

### 3.5 端到端对话检索（K23）
新会话 s-20260729-001 绑定测试库后提问"本文档的专属测试口令是什么"：
- hook 日志确认 agent 调用 `search_knowledge_base`（query='本文档的专属测试口令', top_k=6）
- 回复：**「本文档的专属测试口令是：ZHIJI-KB-TEST-42（来源：kb_test_doc.md 第三章·测试口令）」** ✅ 内容与引用均正确

消息接口约定：POST /api/frontend/message 参数为 `content`（传 `text` 返回 `content is required`）。

### 3.6 删除与级联
| # | 用例 | 预期 | 实际 |
|---|---|---|---|
| K24 | 删除单文档 | DB 删除 + 源文件清理 | ✅ 列表移除、磁盘 .txt 已删 |
| K25 | 删库 | 级联清理 | ⚠️ DB 记录/文档/会话绑定均级联清除，**但磁盘源文件目录残留**（见 KB-B1） |

## 四、缺陷与问题

### KB-B1（中）：删除知识库不清理磁盘源文件目录
- 现象：DELETE /knowledge/bases/{kb_id} 后 `data/workspace/.knowledge/{kb_id}/` 及其中源文件残留（本次 doc-f197317973f9.md 残留，已手工清理）。
- 佐证：`.knowledge/` 下存在 kb-87b35858de8d、kb-d31437ef08a5 两个孤儿目录，对应库在当前库列表中已不存在，说明历史删库均泄漏。
- 根因：`routes/knowledge.py` 的 `handle_base_delete` 只调 `store.delete_base(kb_id)`；对比 `handle_document_delete` 有 best-effort 删源文件逻辑。
- 建议：删库时 best-effort `shutil.rmtree(_kb_storage_dir(request, kb_id))`；可另加启动期孤儿目录清扫。

### ENV-1（环境问题，非功能缺陷）：沙箱启动的进程 CrewAI 存储只读
- 现象：对话报"AI 引擎初始化存储失败"，日志 `unable to open database file` / `attempt to write a readonly database`（`~/Library/Application Support/xiaopaw-v2/latest_kickoff_task_outputs.db`）。
- 根因：玄机进程此前由沙箱受限 shell 启动，无法写工作区之外的 CrewAI 存储目录。在非受限环境重启后恢复正常。
- 建议：部署脚本/文档注明玄机需以具备 `~/Library/Application Support` 写权限的方式启动。

### 观察项（不计缺陷）
1. 资料库"我的文档"tab 为前端占位符，无后端支撑。
2. 检索接口 `kb_id` 单数与会话绑定 `kb_ids` 复数命名不一致，易误用（本次 K13 首测即踩中）。
3. favorites.json 存于 workspace.parent/library/ 全局共享，多用户场景下收藏互相可见（当前单管理员使用无实际影响）。

## 五、测试数据与清理

- 测试库 kb-164b79310328 及两份文档已通过 API 删除；残留源文件目录已手工清理；两个会话（s-20260728-027 / s-20260729-001）的 KB 绑定已解除。
- 存量库 kb-14b17f5119f0、kb-73c6fd1e2d4e 及其数据未受影响。
- 会话 s-20260729-001 为本次测试创建，含 4 轮测试消息，保留供追溯。
- 玄机进程已重启：PID 53573，日志 /tmp/xiaopaw_kbtest.log。
