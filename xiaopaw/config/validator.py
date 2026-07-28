"""Pydantic configuration schemas with startup validation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from xiaopaw.config.flags import FeatureFlags

# Matches ${VAR} and ${VAR:-default} shell-style placeholders.
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class FeishuConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_id: str = Field(min_length=8)
    app_secret: str = Field(min_length=8)
    allowed_chats: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "deepseek-v4-flash"
    max_iter: int = Field(default=50, ge=1, le=200)
    max_input_tokens: int = Field(default=30000, ge=1000, le=128000)
    sub_agent_model: str = "deepseek-v4-flash"
    sub_agent_max_iter: int = Field(default=20, ge=1, le=100)
    timeout_s: int = Field(default=300, ge=30, le=3600)
    llm_timeout_s: int = Field(default=120, ge=10, le=600)


class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = "http://localhost:8030/mcp"
    timeout_s: int = Field(default=120, ge=10, le=600)
    # 短期#9：会话级沙箱隔离（实验性）。开启后每个会话独占一个沙箱容器，
    # 需要本机 docker 与 AIO-Sandbox 镜像；任何失败自动回退共享沙箱。
    per_session: bool = False
    image: str = "ghcr.io/agent-infra/sandbox:latest"
    pool_port_start: int = Field(default=8100, ge=1024, le=65000)
    pool_max_containers: int = Field(default=5, ge=1, le=32)
    pool_idle_ttl_s: int = Field(default=1800, ge=60)


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_dsn: str = ""
    hard_limit_lines: int = 250
    max_save_length: int = 2000
    compress_threshold: float = 0.45
    context_window_tokens: int = 32000
    fresh_keep_turns: int = 10
    # 远程长期记忆（agent-memory-system）对接配置。base_url 需含 /api/v1
    # 前缀（如 http://localhost:8000/api/v1）；两者都非空且 feature flag
    # enable_remote_memory 开启时才生效。
    remote_base_url: str = ""
    remote_api_key: str = ""
    remote_timeout: float = Field(default=10.0, ge=1.0, le=120.0)
    recall_top_k: int = Field(default=5, ge=1, le=20)
    # 召回注入的长期记忆最大字符数（防止挤占上下文窗口）
    recall_max_chars: int = Field(default=4000, ge=200, le=20000)
    # Phase 4 片段生命周期治理：普通对话片段 TTL（天）0 = 永久保存
    fragment_ttl_days: int = Field(default=90, ge=0, le=3650)
    # 启发式 importance 打分：命中显式陈述模式（记住/我是/以后…）用 high
    importance_default: float = Field(default=0.4, ge=0.0, le=1.0)
    importance_high: float = Field(default=0.7, ge=0.0, le=1.0)
    # 摘要化写入：LLM 一句话摘要超时（秒），失败/超时回退原文拼接
    summary_timeout: float = Field(default=5.0, ge=1.0, le=30.0)
    # Phase 5 结构化记忆表白名单：表名 → 字段 schema（name/type）。
    # 模型只能写入白名单内的表，防 schema 泛滥；需同时开启
    # feature_flags.enable_structured_tables。
    structured_tables: dict[str, list[dict[str, str]]] = Field(
        default_factory=lambda: {
            "todo": [
                {"name": "title", "type": "TEXT"},
                {"name": "due_date", "type": "TEXT"},
                {"name": "status", "type": "TEXT"},
            ],
            "expense": [
                {"name": "item", "type": "TEXT"},
                {"name": "amount", "type": "REAL"},
                {"name": "date", "type": "TEXT"},
            ],
        }
    )


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_active_sessions: int = Field(default=1000, ge=1)
    max_history_turns: int = Field(default=20, ge=1)


class RunnerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_queue_size: int = Field(default=10, ge=1, le=100)
    idle_timeout_s: float = Field(default=300.0, ge=10)


class SenderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(default=3, ge=1, le=10)
    retry_backoff: list[float] = Field(default_factory=lambda: [1.0, 2.0, 4.0])
    max_concurrent: int = Field(default=5, ge=1, le=20)


class DebugConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enable_test_api: bool = False
    test_api_host: str = "127.0.0.1"
    test_api_port: int = Field(default=9090, ge=1024, le=65535)
    test_api_token: str = ""


class FrontendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1024, le=65535)


class ObservabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics_host: str = "0.0.0.0"
    log_json: bool = True
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    enable_langfuse: bool = True
    metrics_port: int = Field(default=8090, ge=1024, le=65535)


class RateLimitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_user_per_minute: int = Field(default=20, ge=1)


class ReplayCacheConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maxsize: int = Field(default=10000, ge=100)
    ttl_sec: float = Field(default=300.0, ge=10)


class CronConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    check_interval_s: float = Field(default=30.0, ge=5)
    filelock_timeout_s: float = Field(default=10.0, ge=1)
    max_dlq_retries: int = Field(default=3, ge=0)


class CleanupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    session_ttl_days: int = Field(default=180, ge=1)
    trace_ttl_days: int = Field(default=30, ge=1)
    raw_ttl_days: int = Field(default=30, ge=1)
    run_hour_utc: int = Field(default=3, ge=0, le=23)


class SkillsConfig(BaseModel):
    """Skill management configuration.

    user_dir: directory for user-uploaded/created skills (relative paths
    are resolved against the project root).
    max_upload_mb: maximum upload archive size in MB (zip compressed).
    """
    model_config = ConfigDict(extra="forbid")

    user_dir: str = "data/user_skills"
    max_upload_mb: int = Field(default=5, ge=1, le=50)


class SkillMarketConfig(BaseModel):
    """Skill market sync configuration.

    Pulls index from Vercel Skills + ClawHub every ``sync_interval_hours``
    and persists into the ``skill_market`` table. URLs are placeholders
    until upstream protocols are confirmed; allow env override for dev.
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    vercel_index_url: str = (
        "https://raw.githubusercontent.com/vercel/skills/main/index.json"
    )
    clawhub_index_url: str = ""
    sync_interval_hours: float = Field(default=6.0, ge=0.1, le=168.0)
    fetch_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    install_max_bytes: int = Field(
        default=20 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024
    )


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = "data/workspace"
    data_dir: str = "data"
    feishu: FeishuConfig = Field(default_factory=lambda: FeishuConfig(app_id="placeholder", app_secret="placeholder"))
    agent: AgentConfig = Field(default_factory=AgentConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    sender: SenderConfig = Field(default_factory=SenderConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
    frontend: FrontendConfig = Field(default_factory=FrontendConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    replay_cache: ReplayCacheConfig = Field(default_factory=ReplayCacheConfig)
    cron: CronConfig = Field(default_factory=CronConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    skill_market: SkillMarketConfig = Field(default_factory=SkillMarketConfig)
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)
    routing: dict[str, Any] = Field(default_factory=dict)


def _expand_env(value: Any) -> Any:
    """Recursively expand ${VAR} and ${VAR:-default} placeholders in config values.

    An unset variable with no default resolves to an empty string, matching
    shell semantics. This ensures placeholders like ``${MEMORY_DB_DSN:-}`` become
    an empty string (feature disabled) instead of being passed through verbatim.
    """
    if isinstance(value, str):
        def _sub(match: re.Match[str]) -> str:
            var_name, default = match.group(1), match.group(2)
            return os.environ.get(var_name, default if default is not None else "")
        return _ENV_VAR_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: Path) -> AppConfig:
    """Load and validate configuration from YAML file."""
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = _expand_env(raw)
    return AppConfig(**raw)
