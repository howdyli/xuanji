"""EnvironmentDiagnostic —— 启动时环境自检与运行时诊断。

【设计理念】借鉴 Proma 的 environment-checker + runtime-init 模式：
- 启动时检测关键环境依赖（Python 版本、API Key、数据库、Docker 等）
- 运行时状态聚合（各服务是否就绪）
- 诊断结果可序列化给前端展示

【使用方式】
    diag = EnvironmentDiagnostic(config)
    report = diag.run_all_checks()
    for check in report.checks:
        print(f"{check.name}: {check.status} - {check.detail}")
    if not report.all_ok:
        logger.warning("环境检查发现 %d 个问题", report.issue_count)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class CheckStatus(str, Enum):
    """检查项状态。"""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class CheckResult:
    """单项检查结果。"""

    name: str            # 检查项名称
    status: CheckStatus  # 状态
    detail: str = ""     # 详情
    required: bool = True  # 是否为必需项

    def __str__(self) -> str:
        icon = {"ok": "✓", "warning": "⚠", "error": "✗", "skipped": "○"}
        return f"[{icon.get(self.status.value, '?')}] {self.name}: {self.detail}"


@dataclass
class DiagnosticReport:
    """完整诊断报告。"""

    checks: list[CheckResult] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def all_ok(self) -> bool:
        return all(
            c.status in (CheckStatus.OK, CheckStatus.SKIPPED)
            or not c.required
            for c in self.checks
        )

    @property
    def issue_count(self) -> int:
        return sum(
            1 for c in self.checks
            if c.status in (CheckStatus.ERROR, CheckStatus.WARNING) and c.required
        )

    @property
    def error_count(self) -> int:
        return sum(
            1 for c in self.checks
            if c.status == CheckStatus.ERROR and c.required
        )

    def to_dict(self) -> dict:
        """序列化为字典（供前端 API 使用）。"""
        return {
            "timestamp": self.timestamp,
            "all_ok": self.all_ok,
            "issue_count": self.issue_count,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "detail": c.detail,
                    "required": c.required,
                }
                for c in self.checks
            ],
        }


class EnvironmentDiagnostic:
    """环境诊断器 —— 启动时运行一组检查项。

    可通过 add_check() 注册自定义检查项，
    也可通过 run_all_checks() 运行所有内置 + 自定义检查。
    """

    def __init__(self) -> None:
        self._custom_checks: list[tuple[str, callable, bool]] = []

    def add_check(self, name: str, check_fn: callable, required: bool = True) -> None:
        """注册自定义检查项。

        Args:
            name: 检查项名称
            check_fn: 检查函数，返回 (CheckStatus, detail_str)
            required: 是否为必需项
        """
        self._custom_checks.append((name, check_fn, required))

    def run_all_checks(self) -> DiagnosticReport:
        """运行所有检查项，返回完整诊断报告。"""
        report = DiagnosticReport()

        # 内置检查
        report.checks.append(self._check_python_version())
        report.checks.append(self._check_api_keys())
        report.checks.append(self._check_config_file())
        report.checks.append(self._check_data_dirs())
        report.checks.append(self._check_git())
        report.checks.append(self._check_docker())
        report.checks.append(self._check_node())

        # 自定义检查
        for name, check_fn, required in self._custom_checks:
            try:
                status, detail = check_fn()
                report.checks.append(CheckResult(
                    name=name, status=status, detail=detail, required=required,
                ))
            except Exception as exc:
                report.checks.append(CheckResult(
                    name=name, status=CheckStatus.ERROR,
                    detail=f"检查函数异常: {exc}", required=required,
                ))

        logger.info(
            "[Diagnostic] completed: %d checks, %d issues",
            len(report.checks), report.issue_count,
        )
        return report

    # ---- 内置检查项 ----

    def _check_python_version(self) -> CheckResult:
        v = sys.version_info
        version_str = f"{v.major}.{v.minor}.{v.micro}"
        if v.major < 3 or (v.major == 3 and v.minor < 10):
            return CheckResult(
                name="Python 版本",
                status=CheckStatus.ERROR,
                detail=f"{version_str} (需要 3.10+)",
            )
        return CheckResult(
            name="Python 版本",
            status=CheckStatus.OK,
            detail=version_str,
        )

    def _check_api_keys(self) -> CheckResult:
        keys_found = []
        keys_missing = []

        key_names = [
            ("DEEPSEEK_API_KEY", "DeepSeek"),
            ("QWEN_API_KEY", "通义千问"),
            ("DASHSCOPE_API_KEY", "DashScope"),
        ]

        for env_name, display_name in key_names:
            if os.environ.get(env_name):
                keys_found.append(display_name)
            else:
                keys_missing.append(display_name)

        if keys_found:
            return CheckResult(
                name="API Key 配置",
                status=CheckStatus.OK,
                detail=f"已配置: {', '.join(keys_found)}",
            )
        return CheckResult(
            name="API Key 配置",
            status=CheckStatus.ERROR,
            detail=f"未找到任何 LLM API Key ({', '.join(k for k, _ in key_names)})",
        )

    def _check_config_file(self) -> CheckResult:
        config_path = Path("config.yaml")
        if config_path.exists():
            return CheckResult(
                name="配置文件",
                status=CheckStatus.OK,
                detail=str(config_path.absolute()),
            )
        example = Path("config.yaml.example")
        if example.exists():
            return CheckResult(
                name="配置文件",
                status=CheckStatus.WARNING,
                detail="config.yaml 不存在，请先从 config.yaml.example 复制",
            )
        return CheckResult(
            name="配置文件",
            status=CheckStatus.ERROR,
            detail="config.yaml 和 config.yaml.example 均不存在",
        )

    def _check_data_dirs(self) -> CheckResult:
        data_dir = Path("data")
        if data_dir.exists() and data_dir.is_dir():
            subdirs = [d.name for d in data_dir.iterdir() if d.is_dir()]
            return CheckResult(
                name="数据目录",
                status=CheckStatus.OK,
                detail=f"data/ 存在，子目录: {', '.join(subdirs) or '无'}",
            )
        return CheckResult(
            name="数据目录",
            status=CheckStatus.WARNING,
            detail="data/ 目录不存在（首次启动时会自动创建）",
            required=False,
        )

    def _check_git(self) -> CheckResult:
        git_path = shutil.which("git")
        if git_path:
            try:
                result = subprocess.run(
                    ["git", "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                version = result.stdout.strip()
                return CheckResult(
                    name="Git",
                    status=CheckStatus.OK,
                    detail=version,
                    required=False,
                )
            except Exception:
                pass
        return CheckResult(
            name="Git",
            status=CheckStatus.WARNING,
            detail="未找到 git（部分功能不可用）",
            required=False,
        )

    def _check_docker(self) -> CheckResult:
        docker_path = shutil.which("docker")
        if not docker_path:
            return CheckResult(
                name="Docker",
                status=CheckStatus.WARNING,
                detail="未找到 docker（sandbox 功能不可用）",
                required=False,
            )
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return CheckResult(
                    name="Docker",
                    status=CheckStatus.OK,
                    detail=f"Docker {result.stdout.strip()}",
                    required=False,
                )
            return CheckResult(
                name="Docker",
                status=CheckStatus.WARNING,
                detail="Docker daemon 未启动",
                required=False,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                name="Docker",
                status=CheckStatus.WARNING,
                detail="Docker 检查超时",
                required=False,
            )
        except Exception as exc:
            return CheckResult(
                name="Docker",
                status=CheckStatus.WARNING,
                detail=f"Docker 检查失败: {exc}",
                required=False,
            )

    def _check_node(self) -> CheckResult:
        node_path = shutil.which("node")
        if node_path:
            try:
                result = subprocess.run(
                    ["node", "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                version = result.stdout.strip()
                return CheckResult(
                    name="Node.js",
                    status=CheckStatus.OK,
                    detail=version,
                    required=False,
                )
            except Exception:
                pass
        return CheckResult(
            name="Node.js",
            status=CheckStatus.SKIPPED,
            detail="未找到 node（前端功能不可用）",
            required=False,
        )


def run_startup_diagnostic() -> DiagnosticReport:
    """便捷函数：运行启动诊断并打印结果。"""
    diag = EnvironmentDiagnostic()
    report = diag.run_all_checks()

    for check in report.checks:
        level = logging.WARNING if check.status == CheckStatus.ERROR else logging.INFO
        logger.log(level, "  %s", check)

    if not report.all_ok:
        logger.warning(
            "环境检查发现 %d 个问题（%d 个严重），请检查上述输出",
            report.issue_count, report.error_count,
        )
    else:
        logger.info("环境检查全部通过 (%d 项)", len(report.checks))

    return report
