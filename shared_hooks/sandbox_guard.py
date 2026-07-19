"""SandboxGuard —— 确定性输入消毒（不依赖 LLM）。

【课程对应】
- L32《项目实战 4：三层安全》第一节"沙箱守卫"
- L33《项目实战 5》：作为 hooks.yaml strategies 段第一个安全策略，fail_closed=True

【核心思想：Prompt is advice, Hook is law】
soul.md 里写"NEVER 执行 shell 命令"对 LLM 来说是"建议"——LLM 在任务压力下会违规。
SandboxGuard 用硬编码正则在 BEFORE_TOOL_CALL 兜底拦截，命中即抛 GuardrailDeny。

【版本更新 v1.1】(2026-07-01)
- 新增 Base64/Hex 编码检测
- 新增 Python 反序列化攻击检测（pickle/yaml/eval）
- 新增网络连接模式检测
- 增强危险命令列表
- 添加文件系统路径白名单验证
- 改进日志记录和审计追踪

【挂载事件】BEFORE_TOOL_CALL（fail_closed=True）

【检测项】
1. 路径穿越：../  ..\
2. 危险命令：rm -rf, sudo, chmod 777, curl|sh, eval(), exec() ...
3. Shell 注入：; | && $( ` （沙箱原生工具豁免）
4. 编码绕过：Base64/Hex/Unicode 绕过尝试
5. Python 攻击：pickle.loads, yaml.load, __import__, os.system ...
6. 网络连接：wget/curl/requests/urllib 外连请求
7. Prompt 注入：[SYSTEM]、忽略以上指令、ignore previous instructions ...

【输入预处理】
NFKC Unicode 归一化 + 最多 3 轮 URL 解码 + null byte 拦截。
这是为了防止攻击者用 %2E%2E%2F 这种编码绕过正则。
"""

import logging
import re
import sys
import unicodedata
import hashlib
from collections import deque
from urllib.parse import unquote
from pathlib import Path, PurePosixPath

from xiaopaw.hook_framework.registry import DenyReason, GuardrailDeny

logger = logging.getLogger(__name__)

# ── 配置常量 ──────────────────────────────────────────────
# 可通过环境变量或配置覆盖的参数

# 文件系统白名单：允许访问的目录前缀（防止逃逸到沙箱外部）
_ALLOWED_PATH_PREFIXES = [
    "/workspace",
    "/mnt/skills",
    "/tmp",
    "/dev/null",  # 特殊设备文件
]

# 最大输入长度（防止超长 payload DoS）
_MAX_INPUT_LENGTH = 100000  # 100KB

# ── 检测正则表达式组 ──────────────────────────────────────
# 灵感来源：Claude Code 的 cyberRiskInstruction.ts —— 在工业实战里被反复打磨的清单

# 路径穿越：匹配 ../ 或 ..\
_PATH_TRAVERSAL = re.compile(r"\.\.[/\\]")

# 危险命令：删除/提权/管道执行/动态执行/磁盘操作/进程管理（v1.1 增强）
# 注意：括号需转义 \( \) 以匹配字面量，而非分组
_DANGEROUS_COMMANDS = re.compile(
    r"\b(rm\s+-rf|sudo\b|chmod\s+777|curl\s.*\|\s*sh|eval\s*\(|exec\s*\(|"
    r"dd\s+if=|mkfs\b|shred\b|doas\b|pkexec\b|su\s+\w+|"
    r"pkill\b|killall\b|kill\s+-9\s|systemctl\b|service\b|"
    r"iptables\b|ufw\b|firewall-cmd\b|"        # 防火墙操作
    r"crontab\s|-e\b|at\b|batch\b|"            # 定时任务
    r"useradd\b|userdel\b|passwd\b\w*|"         # 用户管理
    r"mount\b|umount\b|swapon\b|"              # 存储操作
    r"nohup\b|screen\b|tmux\b\s+"              # 会话管理
    r"|nc\s+-e\s+/bin/"                         # 反弹 Shell (netcat)
    r")",
    re.IGNORECASE,
)

# Shell 注入：分号、管道、AND 链、命令替换、子命令
_SHELL_INJECTION = re.compile(r"[;|]|&&|`|\$\(")

# 环境变量引用：$VAR / ${VAR}（仅告警不拦截，因为合法用例多）
_ENV_VAR = re.compile(r"\$\{?\w+\}?")

# Prompt 注入：role 标签、控制 token、忽略指令的中英文表达
_PROMPT_INJECTION = re.compile(
    r"\[(SYSTEM|INST|/INST)\]|"
    r"<\|?(system|im_start|im_end)\|?>|"
    r"忽略(之前|以上|上面|所有)(的)?(所有)?指令|"
    r"ignore\s+(previous|all|above)\s+instructions",
    re.IGNORECASE,
)

# [v1.1] Base64/Hex 编码检测：可能用于绕过过滤
_ENCODING_DETECTION = re.compile(
    r"[A-Za-z0-9+/]{40,}={0,2}\b|"  # Base64 长字符串（≥40字符）
    r"(?:0x[0-9a-fA-F]{20,})|"      # Hex 编码长字符串
    r"base64\.(decode|b64decode)|"   # 显式 base64 解码调用
    r"codecs\.encode|decode",         # codecs 编解码
    re.IGNORECASE,
)

# [v1.1] Python 安全相关危险调用
# 注意：\( 和 \) 匹配字面量括号
_PYTHON_SECURITY_RISK = re.compile(
    r"pickle\.loads?\(|"
    r"yaml\.load\([^)]*\)|"           # yaml.load (可能不安全)
    r"__import__\(|"
    r"os\.(system|popen)\(|"
    r"subprocess\.(call|run|Popen).*shell=True|"
    r"eval\s*\(|"
    r"exec\s*\(|"
    r"compile\s*\(|"
    r"getattr\s*\(|setattr\s*\(|"
    r"__class__|__mro__|__subclasses__|"
    r"__builtins__",
    re.IGNORECASE,
)

# [v1.1] 网络连接模式（沙箱内通常不应主动外连）
_NETWORK_PATTERNS = re.compile(
    r"\b(wget|curl|requests\.get|requests\.post|urllib\.request|"
    r"httpx|aiohttp|socket\.connect|telnet|ftp)\b",
    re.IGNORECASE,
)

# Shell 注入检查的豁免列表 —— 以下"工具"本身不是 shell，输入是自然语言，不应用 [;|&&`$(] 规则：
#   sandbox_xxx / mcp_xxx ：在隔离容器里跑的 shell，出现这些字符是合法的。
#   agent_execution    ：Runner 包装整个 Agent 执行的虚拟 pre-flight 检查点，
#                       输入是用户在前端发的自然语言（可能包含 markdown 表格、
#                       列表分隔符 ; 、中文全角括号）。仅这一环节豁免 shell injection；
#                       路径穿越/危险命令/Prompt 注入等其他检查依然生效。
#   skill_loader       ：LLM 传给子 Crew 的任务描述，是自然语言/JSON，不是 shell。
#   history_reader     ：只接受 page / page_size 参数。
_SHELL_INJECTION_EXEMPT = re.compile(
    r"sandbox_|mcp_"
    r"|^agent_execution$"
    r"|^skill_loader$"
    r"|^history_reader$"
)


def _normalize(raw: str) -> str:
    """输入预处理：NFKC + 多轮 URL 解码 + null byte 检测。

    【为什么要做这一步】
    攻击者会用编码绕过正则。比如 ../ 可以编码为：
        %2E%2E%2F        （URL 编码一次）
        %252E%252E%252F  （URL 编码两次，绕过单次解码）
        ．．／            （Unicode 全角字符）
    所以先归一化、迭代解码，再扔给正则匹配。

    【为什么最多 3 轮】
    实战中 3 轮已能覆盖绝大多数嵌套编码，再多就性能浪费。
    """
    # NFKC 把全角/兼容字符归一化为标准形式（'．' → '.', 'Ｆｕｌｌ' → 'Full'）
    normalized = unicodedata.normalize("NFKC", raw)
    # 多轮 URL 解码：直到稳定或达到 3 轮上限
    prev = normalized
    for _ in range(3):
        decoded = unquote(prev)
        if decoded == prev:
            break
        prev = decoded
    # null byte（\x00）会让某些 C 库提前截断字符串，导致后续校验被绕过
    if "\x00" in prev:
        raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "Null byte in input")
    return prev


class SandboxGuard:
    """输入消毒策略 —— 命中即抛 GuardrailDeny。

    【v1.1 更新】
    - 增加编码绕过检测（Base64/Hex）
    - 增加 Python 安全风险检测（反序列化/代码执行）
    - 增加网络连接模式检测
    - 添加文件系统路径白名单验证
    - 输入长度限制防止 DoS

    【deps 共享 audit_logger】
    构造参数 audit 由 HookLoader 通过 deps 注入，
    与 PermissionGate 共享同一个 SecurityAuditLogger 实例，
    所有违规事件会写到同一个 security_audit.jsonl 文件，便于事后分析。
    """

    _MAX_VIOLATIONS = 1000  # 内存里只保留最近 1000 条违规记录（避免长 session 内存膨胀）

    def __init__(self, audit=None, allowed_path_prefixes=None):
        self._audit = audit
        self._allowed_prefixes = allowed_path_prefixes or _ALLOWED_PATH_PREFIXES
        # deque(maxlen=N)：达到上限自动淘汰最早的元素
        self._violations: deque[dict] = deque(maxlen=self._MAX_VIOLATIONS)

    def before_tool_handler(self, ctx):
        """BEFORE_TOOL_CALL 入口 —— 多组检测短路求值。

        【v1.1 检测顺序】
        输入长度检查 → 路径穿越 → 危险命令 → Shell 注入 → Python 安全风险 → 编码绕过 → 网络连接 → 环境变量（仅告警）→ Prompt 注入 → 路径白名单验证

        命中前面的就直接抛，不会到后面——dispatch_gate 见 deny 立即中止整条链路。
        """
        # 把所有参数值拼成一个字符串做整体扫描——攻击 payload 可能藏在任意字段里
        raw = " ".join(str(v) for v in ctx.tool_input.values()) if ctx.tool_input else ""
        if not raw:
            return

        # [v1.1] 输入长度限制：防止超长 payload DoS
        if len(raw) > _MAX_INPUT_LENGTH:
            self._record("input_too_long", ctx.tool_name, raw[:200])
            raise GuardrailDeny(
                DenyReason.SANDBOX_VIOLATION,
                f"Input too large: {len(raw)} bytes (max {_MAX_INPUT_LENGTH})"
            )

        text = _normalize(raw)

        if _PATH_TRAVERSAL.search(text):
            self._record("path_traversal", ctx.tool_name, text)
            raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "Path traversal detected")

        if _DANGEROUS_COMMANDS.search(text):
            self._record("dangerous_command", ctx.tool_name, text)
            raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "Dangerous command detected")

        # Shell injection 检查豁免：sandbox_xxx / mcp_xxx 是在隔离容器里的真 shell；
        # agent_execution / skill_loader / history_reader 本身不是 shell，输入是
        # 自然语言、JSON 或参数对象，误拦率高。
        if not _SHELL_INJECTION_EXEMPT.search(ctx.tool_name) and _SHELL_INJECTION.search(text):
            self._record("shell_injection", ctx.tool_name, text)
            raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "Shell injection detected")

        # [v1.1] Python 安全风险检测：反序列化/代码执行/危险导入
        if _PYTHON_SECURITY_RISK.search(text):
            self._record("python_security_risk", ctx.tool_name, text)
            raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "Python security risk detected")

        # [v1.1] 编码绕过检测：Base64/Hex 长字符串可能用于隐藏恶意载荷
        if _ENCODING_DETECTION.search(text):
            # 仅告警不拦截（合法用例如文件哈希校验），但记录审计日志
            logger.warning(
                "[SandboxGuard] Suspicious encoding pattern detected in %s: %s",
                ctx.tool_name,
                text[:150],
            )
            self._record("encoding_detected", ctx.tool_name, text)

        # [v1.1] 网络连接模式检测（沙箱内通常不应主动外连）
        if _NETWORK_PATTERNS.search(text) and not _SHELL_INJECTION_EXEMPT.search(ctx.tool_name):
            # 仅告警：某些 Skill 可能需要网络访问（如 web_browse, baidu_search）
            logger.info(
                "[SandboxGuard] Network operation detected in %s: %s",
                ctx.tool_name,
                text[:100],
            )
            self._record("network_operation", ctx.tool_name, text)

        # 环境变量引用只告警不拦截（合法用例：用户让 Agent 读取配置）
        if _ENV_VAR.search(text):
            print(
                f"[SandboxGuard] WARNING: environment variable reference in input: {text[:100]}",
                file=sys.stderr,
            )

        # Prompt 注入用 PROMPT_INJECTION 这个原因码（与沙箱违规区分，便于审计归类）
        if _PROMPT_INJECTION.search(text):
            self._record("prompt_injection", ctx.tool_name, text)
            raise GuardrailDeny(DenyReason.PROMPT_INJECTION, "Prompt injection detected")

        # [v1.1] 文件路径白名单验证：确保所有路径都在允许的目录下
        self._validate_paths(ctx.tool_input, ctx.tool_name)

    def _record(self, violation_type: str, tool_name: str, text: str):
        preview = text[:200]
        # 诊断为重点：把被拦截的 tool_name 和输入预览输出到主日志，
        # 运维不需额外启用 SECURITY_AUDIT_FILE 就能定位误拦
        logger.warning(
            "sandbox_guard deny: type=%s tool=%s preview=%r",
            violation_type, tool_name, preview,
        )
        self._violations.append({
            "type": violation_type,
            "tool": tool_name,
            "input_preview": preview,
        })
        if self._audit:
            self._audit.record_event(
                f"sandbox_{violation_type}",
                tool=tool_name,
                input_preview=preview,
            )

    def _validate_paths(self, tool_input: dict, tool_name: str):
        """[v1.1] 验证文件路径是否在白名单目录内。

        防止通过文件操作逃逸沙箱，例如：
          - 写入 /etc/passwd
          - 读取 /root/.ssh/id_rsa
          - 访问 /proc/self/mem

        仅对包含 'path', 'file', 'dir' 等关键字的参数进行检查。
        """
        path_keywords = ['path', 'file', 'dir', 'filename', 'output', 'target']

        for key, value in tool_input.items():
            # 只检查看起来像路径的参数值（字符串类型且包含路径分隔符）
            if not isinstance(value, str) or not any(kw in key.lower() for kw in path_keywords):
                continue

            # 跳过 URL 和非本地路径
            if value.startswith(('http://', 'https://', 'ftp://')):
                continue
            if value.startswith(('/', './')):
                try:
                    parsed = PurePosixPath(value)
                    # 检查是否以允许的前缀开头或为相对路径
                    is_relative = not str(parsed).startswith('/')
                    is_allowed = any(
                        str(parsed).startswith(prefix)
                        for prefix in self._allowed_prefixes
                    )

                    if not (is_relative or is_allowed):
                        self._record("path_escape_attempt", tool_name, f"{key}={value}")
                        raise GuardrailDeny(
                            DenyReason.SANDBOX_VIOLATION,
                            f"Path outside sandbox allowed directories: {key}={value}"
                        )

                except Exception as e:
                    logger.debug("Path validation error for %s=%s: %s", key, value, e)

    def get_metrics(self) -> dict:
        violations_by_type: dict[str, int] = {}
        for v in self._violations:
            violations_by_type[v["type"]] = violations_by_type.get(v["type"], 0) + 1
        return {
            "version": "1.1",
            "total_violations": len(self._violations),
            "violations_by_type": violations_by_type,
            # [v1.1] 新增：返回检测能力清单
            "detection_capabilities": [
                "path_traversal",
                "dangerous_command",
                "shell_injection",
                "python_security_risk",      # v1.1 新增
                "encoding_detected",          # v1.1 新增（仅告警）
                "network_operation",          # v1.1 新增（仅告警）
                "prompt_injection",
                "path_escape_attempt",        # v1.1 新增
                "input_too_long",             # v1.1 新增
            ],
        }
