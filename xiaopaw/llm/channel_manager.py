"""ChannelManager —— LLM 渠道管理与连通性检测。

【设计理念】借鉴 Proma 的 ChannelManager 模式：
- 渠道 CRUD：管理多个 LLM Provider 配置
- 连通性测试：一键验证 API Key + Endpoint 是否可用
- 动态模型列表：从 Provider API 拉取可用模型
- 渠道健康度追踪：记录最近调用成功率

【与现有 aliyun_llm.py 的关系】
aliyun_llm.py 是 CrewAI 的 LLM 适配器（负责"怎么调"），
channel_manager 是渠道管理层（负责"调哪个、能不能调"）。
channel_manager 可以在 aliyun_llm 初始化前验证渠道可用性。

【使用方式】
    mgr = ChannelManager()
    mgr.add_channel("deepseek", base_url="https://api.deepseek.com", api_key="sk-xxx")
    result = await mgr.test_channel("deepseek")
    if result.ok:
        models = await mgr.fetch_models("deepseek")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """单个 LLM 渠道配置。"""

    name: str                           # 渠道标识名（如 "deepseek", "qwen-cn"）
    base_url: str = ""                  # API Base URL
    api_key: str = ""                   # API Key
    provider: str = "openai_compatible" # 协议类型: openai_compatible / anthropic / deepseek
    models: list[str] = field(default_factory=list)  # 可用模型列表
    default_model: str = ""             # 默认模型
    timeout: int = 30                   # 请求超时秒数
    enabled: bool = True
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # 健康度追踪
    last_test_at: str = ""
    last_test_ok: bool | None = None
    consecutive_failures: int = 0


@dataclass
class TestResult:
    """渠道连通性测试结果。"""

    ok: bool
    channel_name: str
    latency_ms: float = 0
    models: list[str] = field(default_factory=list)
    error: str = ""
    status_code: int = 0

    def __str__(self) -> str:
        if self.ok:
            return f"[OK] {self.channel_name} ({self.latency_ms:.0f}ms, {len(self.models)} models)"
        return f"[FAIL] {self.channel_name}: {self.error} (HTTP {self.status_code})"


class ChannelManager:
    """LLM 渠道管理器。

    管理多个 LLM Provider 的配置、连通性测试和模型列表获取。
    配置可持久化到 JSON 文件，支持热加载。
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        self._config_path = Path(config_path) if config_path else None
        self._channels: dict[str, ChannelConfig] = {}
        if self._config_path and self._config_path.exists():
            self._load_from_file()

    def _load_from_file(self) -> None:
        """从 JSON 文件加载渠道配置。"""
        import json
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
            for ch_data in data.get("channels", []):
                ch = ChannelConfig(**ch_data)
                self._channels[ch.name] = ch
            logger.info("[ChannelManager] loaded %d channels from %s", len(self._channels), self._config_path)
        except Exception as exc:
            logger.warning("[ChannelManager] failed to load config: %s", exc)

    def _save_to_file(self) -> None:
        """持久化渠道配置到 JSON 文件。"""
        if not self._config_path:
            return
        import json
        data = {
            "channels": [
                {k: v for k, v in ch.__dict__.items() if k != "api_key"}
                | {"api_key": _mask_key(ch.api_key)}
                for ch in self._channels.values()
            ]
        }
        try:
            self._config_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("[ChannelManager] failed to save config: %s", exc)

    # ---- CRUD ----

    def add_channel(
        self,
        name: str,
        base_url: str = "",
        api_key: str = "",
        provider: str = "openai_compatible",
        models: list[str] | None = None,
        default_model: str = "",
        timeout: int = 30,
    ) -> ChannelConfig:
        """添加或更新渠道配置。"""
        ch = ChannelConfig(
            name=name,
            base_url=base_url,
            api_key=api_key,
            provider=provider,
            models=models or [],
            default_model=default_model,
            timeout=timeout,
        )
        self._channels[name] = ch
        self._save_to_file()
        logger.info("[ChannelManager] added channel: %s (%s)", name, base_url)
        return ch

    def remove_channel(self, name: str) -> bool:
        """移除渠道。"""
        if name in self._channels:
            del self._channels[name]
            self._save_to_file()
            return True
        return False

    def get_channel(self, name: str) -> ChannelConfig | None:
        """获取渠道配置。"""
        return self._channels.get(name)

    def list_channels(self) -> list[ChannelConfig]:
        """列出所有渠道。"""
        return list(self._channels.values())

    def get_enabled_channels(self) -> list[ChannelConfig]:
        """列出所有已启用的渠道。"""
        return [ch for ch in self._channels.values() if ch.enabled]

    # ---- 连通性测试 ----

    async def test_channel(self, name: str) -> TestResult:
        """异步测试渠道连通性。

        发送一个最小化的 chat completion 请求，验证：
        1. API Key 有效
        2. Endpoint 可达
        3. 模型列表可用

        Args:
            name: 渠道名称

        Returns:
            TestResult 测试结果
        """
        ch = self._channels.get(name)
        if not ch:
            return TestResult(ok=False, channel_name=name, error="渠道不存在")

        return await asyncio.to_thread(self._test_channel_sync, ch)

    def _test_channel_sync(self, ch: ChannelConfig) -> TestResult:
        """同步版连通性测试。"""
        start = time.monotonic()

        # 构建最小测试请求
        test_model = ch.default_model or (ch.models[0] if ch.models else "deepseek-chat")
        payload = {
            "model": test_model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ch.api_key}",
        }

        url = ch.base_url.rstrip("/")
        # 自动补全 chat/completions 路径
        if not url.endswith("/chat/completions"):
            if not url.endswith("/v1"):
                url += "/v1"
            url += "/chat/completions"

        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=ch.timeout,
            )
            latency = (time.monotonic() - start) * 1000

            if resp.status_code == 200:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                # 更新健康状态
                ch.last_test_at = datetime.now(timezone.utc).isoformat()
                ch.last_test_ok = True
                ch.consecutive_failures = 0
                self._save_to_file()

                return TestResult(
                    ok=True,
                    channel_name=ch.name,
                    latency_ms=latency,
                    models=ch.models,
                )

            # 非 200
            error_text = resp.text[:500]
            ch.last_test_at = datetime.now(timezone.utc).isoformat()
            ch.last_test_ok = False
            ch.consecutive_failures += 1
            self._save_to_file()

            return TestResult(
                ok=False,
                channel_name=ch.name,
                latency_ms=latency,
                error=f"HTTP {resp.status_code}: {error_text[:200]}",
                status_code=resp.status_code,
            )

        except requests.Timeout:
            latency = (time.monotonic() - start) * 1000
            ch.last_test_ok = False
            ch.consecutive_failures += 1
            return TestResult(
                ok=False, channel_name=ch.name,
                latency_ms=latency,
                error=f"请求超时 ({ch.timeout}s)",
            )

        except requests.RequestException as exc:
            latency = (time.monotonic() - start) * 1000
            ch.last_test_ok = False
            ch.consecutive_failures += 1
            return TestResult(
                ok=False, channel_name=ch.name,
                latency_ms=latency,
                error=f"网络错误: {exc}",
            )

    # ---- 模型列表获取 ----

    async def fetch_models(self, name: str) -> list[str]:
        """从 Provider API 拉取可用模型列表。

        调用 /v1/models 端点获取模型列表。
        """
        ch = self._channels.get(name)
        if not ch:
            return []

        return await asyncio.to_thread(self._fetch_models_sync, ch)

    def _fetch_models_sync(self, ch: ChannelConfig) -> list[str]:
        """同步版模型列表获取。"""
        url = ch.base_url.rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        url += "/models"

        headers = {
            "Authorization": f"Bearer {ch.api_key}",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=ch.timeout)
            if resp.status_code == 200:
                data = resp.json()
                models = []
                for item in data.get("data", []):
                    model_id = item.get("id", "")
                    if model_id:
                        models.append(model_id)
                models.sort()

                # 更新渠道的模型列表
                ch.models = models
                self._save_to_file()

                logger.info("[ChannelManager] fetched %d models for %s", len(models), ch.name)
                return models

            logger.warning(
                "[ChannelManager] fetch models failed for %s: HTTP %d",
                ch.name, resp.status_code,
            )
            return ch.models  # 返回缓存的列表

        except Exception as exc:
            logger.warning("[ChannelManager] fetch models error for %s: %s", ch.name, exc)
            return ch.models

    # ---- 健康度 ----

    def get_health_summary(self) -> dict:
        """返回所有渠道的健康度摘要。"""
        result = {}
        for ch in self._channels.values():
            result[ch.name] = {
                "enabled": ch.enabled,
                "last_test_ok": ch.last_test_ok,
                "consecutive_failures": ch.consecutive_failures,
                "last_test_at": ch.last_test_at,
                "model_count": len(ch.models),
            }
        return result


def _mask_key(key: str) -> str:
    """掩码 API Key，只显示前后各 4 位。"""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"
