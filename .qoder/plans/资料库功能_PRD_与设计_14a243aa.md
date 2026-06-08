# 资料库功能 - PRD 与详细设计

## 一、PRD 产品需求文档

### 1.1 背景与定位

**当前状态：** "资料库"为 `ComingSoonView` 占位页面（[App.tsx L1216](file:///Users/howdy/work-source/xiaopaw-v2/frontend/src/App.tsx#L1216)），尚未实现任何功能。

**产品定位：** 资料库是玄机的"任务资产中心"，集中管理 AI 在各任务中产出的文件，并支持用户上传文档供 AI 引用，形成可持续积累的知识记忆。

**核心价值：**
- 让用户快速找到、查看、下载 AI 产出的文件（PPT/Word/报告等）
- 为 AI 提供持久化的文档上下文（用户上传的参考资料）
- 构建用户个人的知识库，实现跨任务的知识复用

### 1.2 用户场景

| 场景 | 用户行为 | 期望结果 |
|------|---------|---------|
| 查看产出 | 完成 PPT 生成任务后，想找到文件 | 按任务分组展示，一键下载 |
| 搜索文件 | 记得文件名关键词，想快速定位 | 全文搜索文件名+任务名 |
| 上传参考 | 想让 AI 基于已有文档分析 | 上传文件，AI 在后续对话中可引用 |
| 整理归档 | 文件太多，想按项目/类型分类 | 文件夹管理，批量移动/删除 |

### 1.3 功能模块（分阶段）

**Phase 1 — 任务成果（MVP，本次实现）：**
- 按任务（session）分组的文件列表视图
- 文件类型筛选 + 关键词搜索
- 文件下载
- 文件元信息展示（名称、类型、大小、更新时间）

**Phase 2 — 用户文档上传：**
- 文件上传到 `data/library/uploads/`
- 上传文件列表（独立"我的文档"标签页）
- 支持 .pdf / .docx / .xlsx / .md / .txt / .csv

**Phase 3 — AI 知识库集成：**
- 上传文件自动解析为文本 chunks
- 嵌入向量索引，支持语义搜索
- AI 对话时自动检索相关文档作为上下文

### 1.4 信息架构

```
资料库
├── 任务成果（默认 tab）  ← Phase 1
│   ├── 按 session 分组
│   ├── 文件列表（名称/类型/大小/时间）
│   ├── 搜索 + 类型筛选 + 收藏
│   └── 文件下载
├── 我的文档             ← Phase 2
│   ├── 用户上传的文件
│   ├── 文件上传/删除
│   └── 文件夹管理
└── 知识库               ← Phase 3
    ├── 已索引文档
    ├── 搜索测试
    └── 与 AI 对话的集成配置
```

---

## 二、详细技术设计

### 2.1 数据架构

**现有数据结构（可直接利用）：**

```
data/workspace/sessions/
├── s-{session_id}/
│   └── outputs/           ← 技能产出的文件
│       ├── report.docx
│       ├── slides.pptx
│       └── search_result.json
```

Session 元数据存储在 PostgreSQL `sessions` 表：
- `id`, `routing_key`, `title`, `message_count`, `created_at`, `updated_at`

**新增数据结构（Phase 2）：**

```
data/library/
├── uploads/               ← 用户上传的文件
│   ├── {user_id}/
│   │   ├── project-spec.pdf
│   │   └── meeting-notes.md
├── folders/               ← 文件夹元数据（JSON）
│   └── {user_id}.json
└── index/                 ← Phase 3: 向量索引
    └── {user_id}/
```

### 2.2 后端 API 设计

**Phase 1 新增接口：**

```
GET /api/frontend/library/files
  Query: ?type=doc|pptx|image|all (可选)
         ?search=关键词 (可选)
         ?favorites=true (可选)
         ?sort=mtime|size|name (默认 mtime)
         ?order=asc|desc (默认 desc)
  Response: {
    groups: [
      {
        session_id: "s-xxx",
        title: "生成PPT部署架构图",
        icon: "pptx",          // 主产出物类型决定图标
        file_count: 3,
        files: [
          {
            name: "PMO_部署架构.pptx",
            path: "/sessions/s-xxx/outputs/PMO_部署架构.pptx",
            type: "幻灯片",     // 中文类型名
            ext: ".pptx",
            size: 72704,
            mtime: "2026-05-28T10:30:00Z",
            icon: "pptx"       // 文件类型图标标识
          }
        ]
      }
    ],
    total: 23,
    type_options: ["all", "document", "spreadsheet", "presentation", "image", "other"]
  }

POST /api/frontend/library/favorites
  Body: { "path": "/sessions/s-xxx/outputs/file.docx", "action": "add|remove" }
  Response: { "success": true }

GET /api/frontend/library/favorites
  Response: { "paths": ["/sessions/...", ...] }
```

**实现位置：** 在 [api.py](file:///Users/howdy/work-source/xiaopaw-v2/xiaopaw/frontend/api.py) 新增 `handle_library_files` 等 handler。

**核心逻辑：**
1. 扫描 `data/workspace/sessions/*/outputs/` 目录
2. 关联 PGStore 获取 session title（任务名）
3. 按文件扩展名分类：`.docx/.md/.txt` → 文档，`.pptx` → 幻灯片，`.xlsx/.csv` → 表格，`.jpg/.png/.svg` → 图片，其余 → 其他
4. 支持 `type` 和 `search` 过滤
5. 收藏功能用 JSON 文件持久化 `data/library/favorites.json`

### 2.3 前端组件设计

**文件结构：**

```
frontend/src/components/
└── LibraryView.tsx         ← 新建：资料库主视图
```

**组件层级：**

```
LibraryView
├── LibraryHeader           ← 标题 + 标签页切换 + 筛选栏
│   ├── TabSwitcher         ← "任务成果" | "我的文档"
│   ├── TypeFilter          ← 下拉筛选：全部类型 / 文档 / 幻灯片 / ...
│   ├── SearchBar           ← 搜索输入框
│   └── FavoritesToggle     ← "我的收藏" 复选框
├── FileGroupList           ← 按任务分组的文件列表
│   └── FileGroup           ← 单个任务分组（可折叠）
│       ├── GroupHeader     ← 任务图标 + 任务名 + 文件数 + 折叠箭头
│       └── FileRow         ← 单行文件信息
│           ├── FileIcon    ← 按扩展名渲染图标
│           ├── FileName    ← 文件名（截断+tooltip）
│           ├── FileType    ← 类型标签
│           ├── FileSize    ← 人类可读大小
│           ├── FileTime    ← 相对/绝对时间
│           └── FileActions ← 下载 + 收藏按钮
└── EmptyState              ← 无文件时的空状态引导
```

**关键交互：**
- 分组默认展开，点击 GroupHeader 折叠/展开
- 文件行 hover 显示下载+收藏按钮
- 点击文件名触发下载（复用现有 `/api/frontend/files/download`）
- 搜索实时过滤（300ms debounce）
- 类型筛选即时生效
- 空状态："暂无任务产出文件，试试让玄机帮你生成一份报告？"

### 2.4 路由注册

在 [api.py register_routes](file:///Users/howdy/work-source/xiaopaw-v2/xiaopaw/frontend/api.py#L911) 新增：

```python
# Library (File Management)
app.router.add_get("/api/frontend/library/files", handle_library_files)
app.router.add_get("/api/frontend/library/favorites", handle_library_favorites_get)
app.router.add_post("/api/frontend/library/favorites", handle_library_favorites_update)
```

### 2.5 App.tsx 集成

将 [L1214-1216](file:///Users/howdy/work-source/xiaopaw-v2/frontend/src/App.tsx#L1214) 的 `ComingSoonView` 替换为：

```tsx
<LibraryView />
```

---

## 三、实现任务拆解

### Task 1: 后端 — 资料库文件列表 API
- 文件：`xiaopaw/frontend/api.py`
- 新增 `handle_library_files` handler
- 扫描 sessions 目录，关联 session title
- 支持 type/search/sort 过滤
- 文件类型分类逻辑

### Task 2: 后端 — 收藏功能 API
- 文件：`xiaopaw/frontend/api.py`
- 新增 `handle_library_favorites_get` / `handle_library_favorites_update`
- JSON 文件持久化收藏列表

### Task 3: 前端 — LibraryView 组件
- 文件：`frontend/src/components/LibraryView.tsx`（新建）
- 实现完整组件树：Header + FileGroupList + FileRow
- 文件类型图标映射
- 相对时间格式化
- 人类可读文件大小

### Task 4: 前端 — 集成与替换占位页
- 文件：`frontend/src/App.tsx`
- 替换 `ComingSoonView` 为 `LibraryView`
- 添加 API 调用（fetch + 状态管理）

### Task 5: 构建验证
- `npm run build` 确保无编译错误
- 重启后端，验证 API 返回正确数据
- 截图验证 UI 效果
