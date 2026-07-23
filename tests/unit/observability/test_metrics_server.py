"""Unit tests for the /health and /metrics aiohttp endpoints.

Regression guard for the /metrics 500: aiohttp forbids a charset inside the
``content_type`` argument, so the handler must set the Prometheus content type
via headers. See xiaopaw/observability/metrics_server.py.
"""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.observability.metrics_server import create_metrics_app


@pytest.mark.asyncio
async def test_health_ok():
    async with TestClient(TestServer(create_metrics_app())) as client:
        r = await client.get("/health")
        assert r.status == 200
        assert await r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_metrics_returns_200_prometheus_text():
    """The core regression: /metrics must not 500 and must expose Prometheus text."""
    async with TestClient(TestServer(create_metrics_app())) as client:
        r = await client.get("/metrics")
        assert r.status == 200
        assert r.content_type == "text/plain"
        body = await r.text()
        # Prometheus exposition format always emits HELP/TYPE comment lines.
        assert "# HELP" in body or "# TYPE" in body


@pytest.mark.asyncio
async def test_metrics_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("XIAOPAW_METRICS_TOKEN", "s3cret-token-value")
    async with TestClient(TestServer(create_metrics_app())) as client:
        # Missing/blank Authorization is rejected.
        r = await client.get("/metrics")
        assert r.status == 401
        # Correct bearer token is accepted.
        r = await client.get(
            "/metrics", headers={"Authorization": "Bearer s3cret-token-value"}
        )
        assert r.status == 200
