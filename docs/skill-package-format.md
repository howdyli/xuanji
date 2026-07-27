# 玄机技能包格式规范（Skill Package Format v1）

> 短期建议 #10「技能生态自举」交付物之一。本文定义技能包的目录结构、元数据
> 格式与分发方式，是本地导入、市场安装、社区发布三条链路共同遵循的契约。

## 1. 技能包是什么

一个技能包 = **一个目录**（分发时打包为 `.zip`），目录内必须包含一个
`SKILL.md`，可选包含脚本与资源文件。

```
my-skill/
├── SKILL.md          # 必需：frontmatter 元数据 + 技能说明文档
├── scripts/          # 可选：可执行脚本（.py/.sh/.js/.ts）
│   └── run.py
└── assets/           # 可选：模板、参考资料等任意资源
    └── template.md
```

含可执行脚本的 `task` 类技能会被识别为「套件」(bundle)，前端用紫色标签突出。

## 2. SKILL.md 格式

YAML frontmatter + Markdown 正文：

```markdown
---
name: my-skill            # 必需：^[a-z][a-z0-9_-]{0,63}$（kebab-case / 下划线）
description: 一句话描述    # 建议：≤500 字符，展示在技能列表
type: task                # task（可执行）| reference（参考知识）
version: 1.0.0            # 语义化版本
author: your-name
enabled: true             # 安装后默认启用状态
---

# 技能文档正文

Agent 加载本技能时读取的说明：使用场景、步骤、注意事项。
```

字段规则（`skills_mgmt/registry.py` / `packager.py` 强制校验）：

| 字段 | 必需 | 校验 |
|---|---|---|
| `name` | ✅ | 正则 `^[a-z][a-z0-9_-]{0,63}$`；与 zip 解包目录名一致；市场安装时必须与市场条目名一致（防伪装） |
| `description` | 建议 | 截断至 500 字符 |
| `type` | 否 | `task`（默认）/ `reference` |
| `version` | 否 | 默认 `1.0.0` |
| `author` / `enabled` | 否 | 默认 `""` / `true` |

## 3. 打包与安全限制

打包：`zip -r my-skill.zip my-skill/`（SKILL.md 在 zip 根或唯一一级目录下均可）。

服务端解包安全校验（`packager.unpack_skill`）：

- 压缩包 ≤ 5 MB（可配 `skills.max_upload_mb`），解压后 ≤ 20 MB，≤ 200 个文件
- 拒绝路径穿越（`../`）、绝对路径成员
- `SKILL.md` 缺失或 frontmatter 无合法 `name` → 拒绝
- 同名技能已存在 → 409（可用 `?overwrite=true` 覆盖）

## 4. 分发链路

| 链路 | 入口 | 说明 |
|---|---|---|
| **本地导入** | 技能管理页「上传技能压缩包」按钮；`POST /api/frontend/skills/upload`（multipart `file` 字段或裸 zip body） | 解包到 `data/user_skills/<name>/` 并同步 DB |
| **导出/分享** | 技能卡片下载；`GET /api/frontend/skills/{name}/download` | 服务端重新打包为 zip |
| **市场安装** | 市场页安装；`POST /api/frontend/market/skills/{name}/install` | 从 Vercel/ClawHub 索引拉取 archive，同样走 `unpack_skill` 校验 |
| **社区发布** | `POST /api/frontend/community/skills/publish` → 管理员审核（`/community/admin/*`）→ 上架 | 依赖 PostgreSQL |

存储两层：内置技能 `xiaopaw/skills/`（受保护，不可删除），用户技能
`data/user_skills/`（同名时用户技能覆盖内置）。

## 5. 端到端自测（已验证 2026-07-27）

```bash
# 1. 构造并打包
mkdir -p hello-demo && $EDITOR hello-demo/SKILL.md
zip -qr hello-demo.zip hello-demo
# 2. 上传（返回 {"ok": true, "name": "hello-demo"}）
curl -X POST http://127.0.0.1:8080/api/frontend/skills/upload \
  -H "Authorization: Bearer $TOKEN" -F "file=@hello-demo.zip"
# 3. 列表可见 → 4. 下载 zip → 5. 删除
curl http://127.0.0.1:8080/api/frontend/skills -H "Authorization: Bearer $TOKEN"
curl -O http://127.0.0.1:8080/api/frontend/skills/hello-demo/download -H "Authorization: Bearer $TOKEN"
curl -X DELETE http://127.0.0.1:8080/api/frontend/skills/hello-demo -H "Authorization: Bearer $TOKEN"
```

## 6. 与外部生态的兼容性

frontmatter 字段与 Anthropic Agent Skills / Claude Code 的 SKILL.md 约定
（`name` + `description` 为核心）保持兼容：多数社区 SKILL.md 技能目录直接
zip 后即可导入玄机；玄机技能导出后也可被其他兼容 SKILL.md 的运行时使用。
差异点：玄机额外识别 `type/version/author/enabled` 字段，忽略未知字段。
