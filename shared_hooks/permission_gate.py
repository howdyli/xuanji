"""PermissionGate: tool permission gateway (DENY > WARN > ALLOW)."""

from collections import deque
from pathlib import Path

import yaml

from xiaopaw.hook_framework.registry import DenyReason, GuardrailDeny


class PermissionGate:
    def __init__(self, tools: dict[str, str] | None = None, default: str = "warn", audit=None):
        self._tool_permissions: dict[str, str] = {
            k.lower(): v.lower() for k, v in (tools or {}).items()
        }
        self._default = default.lower()
        self._audit = audit
        self.decisions: deque[dict] = deque(maxlen=10000)

    @classmethod
    def from_yaml(cls, path: Path, audit=None):
        try:
            with open(path) as f:
                config = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as e:
            raise ValueError(f"Failed to load permission config from {path}: {e}") from e
        if not isinstance(config, dict):
            raise ValueError(f"Permission config must be a YAML dict, got {type(config).__name__}")
        perms = config.get("permissions", {})
        return cls(
            tools=perms.get("tools", {}),
            default=perms.get("default", "warn"),
            audit=audit,
        )

    def before_tool_handler(self, ctx):
        tool = ctx.tool_name.lower()
        permission = self._tool_permissions.get(tool, self._default)
        policy_source = "explicit" if tool in self._tool_permissions else "default"

        decision = {
            "tool": ctx.tool_name,
            "permission": permission,
            "policy_source": policy_source,
        }
        self.decisions.append(decision)

        if permission == "deny":
            if self._audit:
                self._audit.record_event(
                    "permission_deny", tool=ctx.tool_name
                )
            raise GuardrailDeny(
                DenyReason.PERMISSION_DENIED,
                f"Permission denied for tool: {ctx.tool_name}",
            )

        if permission == "warn":
            if self._audit:
                self._audit.record_event(
                    "permission_warn", tool=ctx.tool_name
                )

    def get_metrics(self) -> dict:
        allow_count = sum(1 for d in self.decisions if d["permission"] == "allow")
        warn_count = sum(1 for d in self.decisions if d["permission"] == "warn")
        deny_count = sum(1 for d in self.decisions if d["permission"] == "deny")
        denied_tools = [d["tool"] for d in self.decisions if d["permission"] == "deny"]
        return {
            "total_decisions": len(self.decisions),
            "allow_count": allow_count,
            "warn_count": warn_count,
            "deny_count": deny_count,
            "denied_tools": denied_tools,
        }
