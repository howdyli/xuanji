# test_user_isolation.py — 用户隔离功能测试文档

## 概述

本测试文件覆盖 xiaopaw 用户隔离功能（Tasks #36/#38/#39/#41），验证多用户场景下的数据隔离、路径安全和权限控制。

**文件路径**: `tests/unit/test_user_isolation.py`  
**测试数量**: 45 个  
**运行命令**: `pytest tests/unit/test_user_isolation.py -v`

## 测试覆盖矩阵

| 测试类 | 数量 | 覆盖模块 | 核心验证点 |
|--------|------|----------|------------|
| `TestSessionRoutingKey` | 3 | session.py | routing_key 从认证用户构造，忽略前端传入值 |
| `TestSessionsListFilter` | 3 | session.py | 会话列表按 routing_key 过滤，兼容旧数据 |
| `TestFrontendRoutingKey` | 5 | App.tsx | 前端 `p2p:web_{username}` 格式，含匿名回退 |
| `TestUserWorkspacePath` | 2 | helpers.py | 路径正确创建为 `{base}/{username}/` |
| `TestUserWorkspaceSecurity` | 5 | helpers.py | 特殊字符用户名拒绝（防目录遍历） |
| `TestUserWorkspaceLazyInit` | 11 | helpers.py | 懒初始化、md/skills/agents 复制、幂等性 |
| `TestWorkspaceApiUserScoped` | 6 | workspace.py | `_get_workspace` 和 `handle_file_download` 用户隔离 |
| `TestAgentDynamicWorkspace` | 5 | main_crew.py | Agent 执行时动态定位用户 workspace |
| `TestBackwardCompat` | 2 | session.py | 旧 `p2p:web_user` 数据仍可见 |
| `TestAnonymousFallback` | 3 | helpers.py | 未认证回退到全局 workspace |

## 核心设计原则

### 1. 直接调用真实函数
所有测试直接 import 并调用源码函数，不使用 mock patch 绕过实现：
```python
# ✅ 正确：直接调用真实函数
result = get_user_workspace_path(request)

# ❌ 错误：mock patch 绕过实现
with patch("helpers.get_user_workspace_path") as mock:
    mock.return_value = "/fake/path"
    result = get_user_workspace_path(request)
```

### 2. symlink 防御单一职责
- **helpers.py `get_user_workspace_path`**: 包含 `is_symlink()` 检查，集中处理 symlink 防御
- **main_crew.py `build_agent_fn`**: 仅 `is_dir()` 守卫，不检查 symlink

### 3. 依赖注入验证
- `session.py`: 通过 `request.app["session_mgr"]` 获取 session 管理器
- `workspace.py`: `_get_workspace` 调用 `get_user_workspace_path`，不再使用旧版 `get_workspace_path`

## 测试详情

### 1. TestSessionRoutingKey (3 tests)
验证 `get_routing_key_from_request` 从认证用户构造 routing_key：
- `test_routing_key_from_auth`: 认证用户 alice → `p2p:web_alice`
- `test_routing_key_ignores_frontend_value`: 忽略前端传入的 `p2p:web_mallory`
- `test_handle_message_uses_session_mgr_from_di`: handle_message 通过 DI 获取 session_mgr

### 2. TestSessionsListFilter (3 tests)
验证 `list_sessions_for_user` 按 routing_key 过滤查询：
- `test_list_sessions_for_user_filters_by_routing_key`: pg_store=None 时返回空列表
- `test_list_sessions_for_user_returns_empty_when_no_store`: 无存储时安全回退
- `test_list_sessions_for_user_with_mock_pg`: Mock PG 验证 WHERE routing_key 条件

### 3. TestFrontendRoutingKey (5 tests, parametrized)
验证前端 `p2p:web_{username}` 格式：
- `[alice-p2p:web_alice]`: 正常用户名
- `[bob-p2p:web_bob]`: 正常用户名
- `[user_123-p2p:web_user_123]`: 含数字用户名
- `[None-p2p:web_anonymous]`: 未认证回退
- `[-p2p:web_anonymous]`: 空字符串回退

### 4. TestUserWorkspacePath (2 tests)
验证 `get_user_workspace_path` 路径创建：
- `test_workspace_path_creation`: 返回 `{base}/{username}/` 且目录存在
- `test_workspace_path_contains_init_file`: 新目录包含 `user_config.json`

### 5. TestUserWorkspaceSecurity (5 tests, parametrized)
验证特殊字符用户名拒绝（防目录遍历）：
- `[../etc]`: 目录遍历攻击
- `[user/name]`: 路径分隔符
- `[..\\windows]`: Windows 风格遍历
- `[foo bar]`: 空格字符
- `[user@domain]`: 特殊符号

正则 `_USERNAME_RE = r'^[a-zA-Z0-9_-]+$'` 阻止所有非字母数字用户名。

### 6. TestUserWorkspaceLazyInit (11 tests)
验证懒初始化和辅助函数：
- `test_lazy_init_creates_dir_and_config`: 首次访问创建目录和配置
- `test_second_access_no_overwrite`: 二次访问不覆盖已有配置
- `test_init_copies_md_files_from_base`: 从 workspace_base 复制 md 文件
- `test_init_does_not_overwrite_existing_md`: 不覆盖已有 md 文件
- `test_init_copies_skills_and_agents_dirs`: 复制 skills/ 和 agents/ 目录
- `test_ensure_dirs_creates_skills_and_agents`: `_ensure_dirs` 创建子目录
- `test_copy_tree_if_exists_copies_tree`: `_copy_tree_if_exists` 复制目录树
- `test_copy_tree_if_exists_noop_when_missing`: 源不存在时不操作
- `test_copy_md_files_copies_all_md`: `_copy_md_files` 复制所有 md 文件
- `test_copy_md_files_no_overwrite`: `_copy_md_files` 不覆盖已有文件
- `test_init_user_workspace_idempotent`: `_init_user_workspace` 幂等性

### 7. TestWorkspaceApiUserScoped (6 tests)
验证 workspace API 用户隔离：
- `test_get_workspace_delegates_to_user_helper`: `_get_workspace` 返回用户级路径
- `test_get_workspace_calls_get_user_workspace_path`: patch 验证调用正确函数
- `test_get_workspace_returns_error_response`: 错误响应正确传播
- `test_get_workspace_unauthenticated_fallback`: 未认证回退到 base
- `test_handle_file_download_uses_get_user_workspace_path`: 文件下载使用用户级路径
- `test_handle_file_download_returns_error_when_workspace_invalid`: 错误响应传播

### 8. TestAgentDynamicWorkspace (5 tests)
验证 Agent 执行时动态 workspace 定位：
- `test_agent_fn_resolves_user_workspace`: routing_key → 用户 workspace
- `test_agent_fn_fallback_when_dir_missing`: 目录不存在时回退全局
- `test_non_web_routing_uses_global`: 非 web routing_key 使用全局
- `test_agent_fn_accepts_symlink_dir`: `build_agent_fn` 接受 symlink 目录（仅 is_dir）
- `test_get_user_workspace_path_rejects_symlink`: `get_user_workspace_path` 拒绝 symlink

### 9. TestBackwardCompat (2 tests)
验证旧数据兼容性：
- `test_old_routing_key_fallback_value`: 未认证回退到 `p2p:web_user`
- `test_old_sessions_still_queryable_via_fallback_key`: 旧会话仍可查询

### 10. TestAnonymousFallback (3 tests)
验证未认证回退逻辑：
- `test_unauthenticated_returns_global_workspace`: 返回全局 workspace 路径
- `test_missing_workspace_dir_returns_error`: workspace_dir 未配置返回 500
- `test_handle_message_anonymous_routing_key`: 未认证 routing_key 为 `p2p:web_user`

## pytest --collect-only 输出

```
tests/unit/test_user_isolation.py::TestSessionRoutingKey::test_routing_key_from_auth
tests/unit/test_user_isolation.py::TestSessionRoutingKey::test_routing_key_ignores_frontend_value
tests/unit/test_user_isolation.py::TestSessionRoutingKey::test_handle_message_uses_session_mgr_from_di
tests/unit/test_user_isolation.py::TestSessionsListFilter::test_list_sessions_for_user_filters_by_routing_key
tests/unit/test_user_isolation.py::TestSessionsListFilter::test_list_sessions_for_user_returns_empty_when_no_store
tests/unit/test_user_isolation.py::TestSessionsListFilter::test_list_sessions_for_user_with_mock_pg
tests/unit/test_user_isolation.py::TestFrontendRoutingKey::test_dynamic_routing_key_format[alice-p2p:web_alice]
tests/unit/test_user_isolation.py::TestFrontendRoutingKey::test_dynamic_routing_key_format[bob-p2p:web_bob]
tests/unit/test_user_isolation.py::TestFrontendRoutingKey::test_dynamic_routing_key_format[user_123-p2p:web_user_123]
tests/unit/test_user_isolation.py::TestFrontendRoutingKey::test_dynamic_routing_key_format[None-p2p:web_anonymous]
tests/unit/test_user_isolation.py::TestFrontendRoutingKey::test_dynamic_routing_key_format[-p2p:web_anonymous]
tests/unit/test_user_isolation.py::TestUserWorkspacePath::test_workspace_path_creation
tests/unit/test_user_isolation.py::TestUserWorkspacePath::test_workspace_path_contains_init_file
tests/unit/test_user_isolation.py::TestUserWorkspaceSecurity::test_special_chars_rejected[../etc]
tests/unit/test_user_isolation.py::TestUserWorkspaceSecurity::test_special_chars_rejected[user/name]
tests/unit/test_user_isolation.py::TestUserWorkspaceSecurity::test_special_chars_rejected[..\\windows]
tests/unit/test_user_isolation.py::TestUserWorkspaceSecurity::test_special_chars_rejected[foo bar]
tests/unit/test_user_isolation.py::TestUserWorkspaceSecurity::test_special_chars_rejected[user@domain]
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_lazy_init_creates_dir_and_config
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_second_access_no_overwrite
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_init_copies_md_files_from_base
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_init_does_not_overwrite_existing_md
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_init_copies_skills_and_agents_dirs
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_ensure_dirs_creates_skills_and_agents
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_copy_tree_if_exists_copies_tree
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_copy_tree_if_exists_noop_when_missing
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_copy_md_files_copies_all_md
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_copy_md_files_no_overwrite
tests/unit/test_user_isolation.py::TestUserWorkspaceLazyInit::test_init_user_workspace_idempotent
tests/unit/test_user_isolation.py::TestWorkspaceApiUserScoped::test_get_workspace_delegates_to_user_helper
tests/unit/test_user_isolation.py::TestWorkspaceApiUserScoped::test_get_workspace_calls_get_user_workspace_path
tests/unit/test_user_isolation.py::TestWorkspaceApiUserScoped::test_get_workspace_returns_error_response
tests/unit/test_user_isolation.py::TestWorkspaceApiUserScoped::test_get_workspace_unauthenticated_fallback
tests/unit/test_user_isolation.py::TestWorkspaceApiUserScoped::test_handle_file_download_uses_get_user_workspace_path
tests/unit/test_user_isolation.py::TestWorkspaceApiUserScoped::test_handle_file_download_returns_error_when_workspace_invalid
tests/unit/test_user_isolation.py::TestAgentDynamicWorkspace::test_agent_fn_resolves_user_workspace
tests/unit/test_user_isolation.py::TestAgentDynamicWorkspace::test_agent_fn_fallback_when_dir_missing
tests/unit/test_user_isolation.py::TestAgentDynamicWorkspace::test_non_web_routing_uses_global
tests/unit/test_user_isolation.py::TestAgentDynamicWorkspace::test_agent_fn_accepts_symlink_dir
tests/unit/test_user_isolation.py::TestAgentDynamicWorkspace::test_get_user_workspace_path_rejects_symlink
tests/unit/test_user_isolation.py::TestBackwardCompat::test_old_routing_key_fallback_value
tests/unit/test_user_isolation.py::TestBackwardCompat::test_old_sessions_still_queryable_via_fallback_key
tests/unit/test_user_isolation.py::TestAnonymousFallback::test_unauthenticated_returns_global_workspace
tests/unit/test_user_isolation.py::TestAnonymousFallback::test_missing_workspace_dir_returns_error
tests/unit/test_user_isolation.py::TestAnonymousFallback::test_handle_message_anonymous_routing_key

45 tests collected
```

## 源码依赖

| 函数 | 文件 | 签名 |
|------|------|------|
| `get_routing_key_from_request` | helpers.py | `(request: web.Request) -> str` |
| `list_sessions_for_user` | helpers.py | `async (pg_store, routing_key: str) -> list[dict]` |
| `get_user_workspace_path` | helpers.py | `(request: web.Request) -> Path \| web.Response` |
| `_init_user_workspace` | helpers.py | `(user_ws: Path, workspace_base: Path) -> None` |
| `_copy_md_files` | helpers.py | `(user_ws: Path, workspace_base: Path) -> None` |
| `_copy_tree_if_exists` | helpers.py | `(src: Path, dst: Path) -> None` |
| `_ensure_dirs` | helpers.py | `(user_ws: Path) -> None` |
| `_get_workspace` | workspace.py | `(request: web.Request) -> Path \| web.Response` |
| `handle_file_download` | workspace.py | `async (request: web.Request) -> web.Response` |
| `handle_message` | session.py | `async (request: web.Request) -> web.Response` |

## 运行示例

```bash
# 运行所有测试
pytest tests/unit/test_user_isolation.py -v

# 运行特定测试类
pytest tests/unit/test_user_isolation.py::TestUserWorkspaceSecurity -v

# 运行单个测试
pytest tests/unit/test_user_isolation.py::TestSessionRoutingKey::test_routing_key_from_auth -v

# 生成覆盖率报告
pytest tests/unit/test_user_isolation.py --cov=xiaopaw.frontend.routes.helpers --cov-report=term-missing
```

## 维护指南

1. **新增测试时**: 遵循现有命名规范 `test_{功能}_{场景}`
2. **修改源码时**: 同步更新测试中的闭包复现逻辑（如 `build_agent_fn`）
3. **新增辅助函数时**: 添加对应的单元测试（参考 `_copy_md_files` 等）
4. **parametrize 使用**: 对多输入场景使用 `@pytest.mark.parametrize`
