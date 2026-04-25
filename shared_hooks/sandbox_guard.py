"""SandboxGuard: deterministic input sanitization for BEFORE_TOOL_CALL.

Checks: path traversal, dangerous commands, shell injection, prompt injection.
Pre-processes with NFKC normalization + iterative URL decode (max 3 rounds).
"""

import re
import sys
import unicodedata
from collections import deque
from urllib.parse import unquote

from xiaopaw.hook_framework.registry import DenyReason, GuardrailDeny

_PATH_TRAVERSAL = re.compile(r"\.\.[/\\]")

_DANGEROUS_COMMANDS = re.compile(
    r"\b(rm\s+-rf|sudo\b|chmod\s+777|curl\s.*\|\s*sh|eval\s*\(|exec\s*\(|"
    r"dd\s+if=|mkfs\b|shred\b|doas\b|pkexec\b|su\s+)",
    re.IGNORECASE,
)

_SHELL_INJECTION = re.compile(r"[;|]|&&|`|\$\(")

_ENV_VAR = re.compile(r"\$\{?\w+\}?")

_PROMPT_INJECTION = re.compile(
    r"\[(SYSTEM|INST|/INST)\]|"
    r"<\|?(system|im_start|im_end)\|?>|"
    r"忽略(之前|以上|上面|所有)(的)?(所有)?指令|"
    r"ignore\s+(previous|all|above)\s+instructions",
    re.IGNORECASE,
)


def _normalize(raw: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw)
    prev = normalized
    for _ in range(3):
        decoded = unquote(prev)
        if decoded == prev:
            break
        prev = decoded
    if "\x00" in prev:
        raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "Null byte in input")
    return prev


class SandboxGuard:
    _MAX_VIOLATIONS = 1000

    def __init__(self, audit=None):
        self._audit = audit
        self._violations: deque[dict] = deque(maxlen=self._MAX_VIOLATIONS)

    def before_tool_handler(self, ctx):
        raw = " ".join(str(v) for v in ctx.tool_input.values()) if ctx.tool_input else ""
        if not raw:
            return

        text = _normalize(raw)

        if _PATH_TRAVERSAL.search(text):
            self._record("path_traversal", ctx.tool_name, text)
            raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "Path traversal detected")

        if _DANGEROUS_COMMANDS.search(text):
            self._record("dangerous_command", ctx.tool_name, text)
            raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "Dangerous command detected")

        if _SHELL_INJECTION.search(text):
            self._record("shell_injection", ctx.tool_name, text)
            raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "Shell injection detected")

        if _ENV_VAR.search(text):
            print(
                f"[SandboxGuard] WARNING: environment variable reference in input: {text[:100]}",
                file=sys.stderr,
            )

        if _PROMPT_INJECTION.search(text):
            self._record("prompt_injection", ctx.tool_name, text)
            raise GuardrailDeny(DenyReason.PROMPT_INJECTION, "Prompt injection detected")

    def _record(self, violation_type: str, tool_name: str, text: str):
        self._violations.append({
            "type": violation_type,
            "tool": tool_name,
            "input_preview": text[:200],
        })
        if self._audit:
            self._audit.record_event(
                f"sandbox_{violation_type}",
                tool=tool_name,
                input_preview=text[:200],
            )

    def get_metrics(self) -> dict:
        violations_by_type: dict[str, int] = {}
        for v in self._violations:
            violations_by_type[v["type"]] = violations_by_type.get(v["type"], 0) + 1
        return {
            "total_violations": len(self._violations),
            "violations_by_type": violations_by_type,
        }
