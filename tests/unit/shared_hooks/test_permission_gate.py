"""UT-PMG-001 ~ UT-PMG-010: PermissionGate unit tests."""

import pytest

from xiaopaw.hook_framework.registry import EventType, GuardrailDeny, HookContext

from shared_hooks.permission_gate import PermissionGate


def _tool_ctx(tool_name):
    return HookContext(
        event_type=EventType.BEFORE_TOOL_CALL,
        tool_name=tool_name,
    )


def _role_ctx(tool_name, role):
    return HookContext(
        event_type=EventType.BEFORE_TOOL_CALL,
        tool_name=tool_name,
        role=role,
    )


class TestThreeLevels:
    def test_pmg001_deny_blocked(self):
        gate = PermissionGate(tools={"shell_executor": "deny"})
        with pytest.raises(GuardrailDeny, match="permission_denied"):
            gate.before_tool_handler(_tool_ctx("shell_executor"))

    def test_pmg002_allow_passes(self):
        gate = PermissionGate(tools={"knowledge_search": "allow"})
        gate.before_tool_handler(_tool_ctx("knowledge_search"))

    def test_pmg003_warn_passes_with_record(self):
        gate = PermissionGate(tools={"file_reader": "warn"})
        gate.before_tool_handler(_tool_ctx("file_reader"))
        assert len(gate.decisions) >= 1
        assert gate.decisions[-1]["permission"] == "warn"


class TestDefaultPolicy:
    def test_pmg004_default_warn(self):
        gate = PermissionGate(
            tools={"shell_executor": "deny"}, default="warn"
        )
        gate.before_tool_handler(_tool_ctx("new_tool"))
        assert gate.decisions[-1]["policy_source"] == "default"
        assert gate.decisions[-1]["permission"] == "warn"

    def test_pmg005_default_deny(self):
        gate = PermissionGate(default="deny")
        with pytest.raises(GuardrailDeny):
            gate.before_tool_handler(_tool_ctx("any_tool"))

    def test_pmg006_default_allow(self):
        gate = PermissionGate(default="allow")
        gate.before_tool_handler(_tool_ctx("any_tool"))


class TestYamlLoading:
    def test_pmg007_load_from_yaml(self, tmp_path):
        policy_file = tmp_path / "security.yaml"
        policy_file.write_text(
            "permissions:\n"
            "  default: warn\n"
            "  tools:\n"
            "    knowledge_search: allow\n"
            "    shell_executor: deny\n"
        )
        gate = PermissionGate.from_yaml(policy_file)
        gate.before_tool_handler(_tool_ctx("knowledge_search"))
        with pytest.raises(GuardrailDeny):
            gate.before_tool_handler(_tool_ctx("shell_executor"))

    def test_pmg008_yaml_default_overrides_constructor(self, tmp_path):
        policy_file = tmp_path / "security.yaml"
        policy_file.write_text(
            "permissions:\n"
            "  default: deny\n"
            "  tools: {}\n"
        )
        gate = PermissionGate.from_yaml(policy_file)
        with pytest.raises(GuardrailDeny):
            gate.before_tool_handler(_tool_ctx("unlisted_tool"))


class TestToolNameCase:
    def test_pmg009_case_insensitive(self):
        gate = PermissionGate(tools={"Shell_Executor": "deny"})
        with pytest.raises(GuardrailDeny):
            gate.before_tool_handler(_tool_ctx("shell_executor"))


class TestMetrics:
    def test_pmg010_metrics(self):
        gate = PermissionGate(
            tools={"a": "allow", "b": "allow", "c": "allow", "d": "deny"}
        )
        for name in ["a", "b", "c"]:
            gate.before_tool_handler(_tool_ctx(name))
        with pytest.raises(GuardrailDeny):
            gate.before_tool_handler(_tool_ctx("d"))
        m = gate.get_metrics()
        assert m["total_decisions"] == 4
        assert m["allow_count"] == 3
        assert m["deny_count"] == 1
        assert "d" in m["denied_tools"]


class TestRoleOverlay:
    """P1-2: 细粒度 RBAC 角色叠加（仅收紧，向后兼容）。"""

    def test_no_roles_config_is_unchanged(self):
        # 未配置 roles => 即使 ctx 带 role 也不影响基础行为。
        gate = PermissionGate(tools={"shell_executor": "allow"})
        gate.before_tool_handler(_role_ctx("shell_executor", "viewer"))
        assert gate.decisions[-1]["permission"] == "allow"

    def test_empty_role_uses_base(self):
        gate = PermissionGate(
            tools={"shell_executor": "allow"},
            roles={"viewer": {"default": "deny"}},
        )
        # role="" => 不参与角色判定，走基础权限。
        gate.before_tool_handler(_tool_ctx("shell_executor"))
        assert gate.decisions[-1]["permission"] == "allow"

    def test_role_default_tightens_to_deny(self):
        gate = PermissionGate(
            tools={"shell_executor": "allow"},
            roles={"viewer": {"default": "deny"}},
        )
        with pytest.raises(GuardrailDeny):
            gate.before_tool_handler(_role_ctx("shell_executor", "viewer"))
        assert gate.decisions[-1]["policy_source"] == "role:viewer"

    def test_role_tool_specific_override(self):
        gate = PermissionGate(
            tools={"shell_executor": "allow", "file_reader": "allow"},
            roles={"editor": {"tools": {"shell_executor": "warn"}}},
        )
        gate.before_tool_handler(_role_ctx("shell_executor", "editor"))
        assert gate.decisions[-1]["permission"] == "warn"
        # 未在角色里声明的工具保持基础权限。
        gate.before_tool_handler(_role_ctx("file_reader", "editor"))
        assert gate.decisions[-1]["permission"] == "allow"

    def test_role_cannot_loosen(self):
        # base=deny，role 想放到 allow => 仍然 deny（只收紧不放松）。
        gate = PermissionGate(
            tools={"shell_executor": "deny"},
            roles={"admin": {"tools": {"shell_executor": "allow"}}},
        )
        with pytest.raises(GuardrailDeny):
            gate.before_tool_handler(_role_ctx("shell_executor", "admin"))

    def test_unknown_role_falls_back_to_base(self):
        gate = PermissionGate(
            tools={"shell_executor": "allow"},
            roles={"viewer": {"default": "deny"}},
        )
        # role 未在配置中 => 走基础权限。
        gate.before_tool_handler(_role_ctx("shell_executor", "superuser"))
        assert gate.decisions[-1]["permission"] == "allow"

    def test_roles_loaded_from_yaml(self, tmp_path):
        policy_file = tmp_path / "security.yaml"
        policy_file.write_text(
            "permissions:\n"
            "  default: warn\n"
            "  tools:\n"
            "    shell_executor: allow\n"
            "  roles:\n"
            "    viewer:\n"
            "      default: deny\n"
        )
        gate = PermissionGate.from_yaml(policy_file)
        gate.before_tool_handler(_tool_ctx("shell_executor"))  # no role -> allow
        assert gate.decisions[-1]["permission"] == "allow"
        with pytest.raises(GuardrailDeny):
            gate.before_tool_handler(_role_ctx("shell_executor", "viewer"))
