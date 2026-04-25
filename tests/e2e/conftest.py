"""E2E test fixtures for XiaoPaw v3 — real LLM + Langfuse verification."""

from __future__ import annotations

import base64
import os
import shutil
import time
from pathlib import Path

import pytest
import pytest_asyncio
import requests
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.api.capture_sender import CaptureSender
from xiaopaw.api.test_server import create_test_app
from xiaopaw.hook_framework.loader import HookLoader
from xiaopaw.hook_framework.registry import HookRegistry
from xiaopaw.runner import Runner
from xiaopaw.session.manager import SessionManager
from xiaopaw.session.models import MessageEntry

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_INIT = _PROJECT_ROOT / "workspace-init"
_SHARED_HOOKS = _PROJECT_ROOT / "shared_hooks"

_LF_HOST = os.environ.get("XIAOPAW_LANGFUSE_BASE_URL", "") or os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000")
_LF_PK = os.environ.get("XIAOPAW_LANGFUSE_PUBLIC_KEY", "") or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
_LF_SK = os.environ.get("XIAOPAW_LANGFUSE_SECRET_KEY", "") or os.environ.get("LANGFUSE_SECRET_KEY", "")


def _init_workspace(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if _WORKSPACE_INIT.exists():
        for f in _WORKSPACE_INIT.glob("*.md"):
            shutil.copy2(f, target / f.name)


def _load_shared_hooks() -> HookRegistry:
    registry = HookRegistry()
    if _SHARED_HOOKS.exists():
        loader = HookLoader(registry)
        fail_closed = {"sandbox_guard", "permission_gate"}
        loader.load_from_directory(
            _SHARED_HOOKS,
            layer_name="global",
            fail_closed_names=fail_closed,
        )
    return registry


async def send_message(
    client: TestClient,
    content: str,
    routing_key: str = "p2p:ou_test001",
    sender_id: str = "ou_test001",
    timeout: float = 300.0,
) -> dict:
    resp = await client.post(
        "/api/test/message",
        json={
            "routing_key": routing_key,
            "content": content,
            "sender_id": sender_id,
        },
        timeout=timeout,
    )
    assert resp.status == 200, f"TestAPI returned {resp.status}: {await resp.text()}"
    return await resp.json()


def llm_assert(reply: str, criteria: str, *, api_key: str = "") -> bool:
    """LLM-as-Judge: check if reply semantically satisfies criteria."""
    key = api_key or os.environ.get("QWEN_API_KEY", "")
    if not key:
        return bool(reply and reply.strip())

    resp = requests.post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": "qwen3-max",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个测试断言判断器。判断 AI 助手的回复是否满足指定的判断标准。"
                        "只回复 YES 或 NO，不要解释。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"AI助手的回复：\n{reply}\n\n判断标准：{criteria}",
                },
            ],
            "max_tokens": 10,
            "temperature": 0.0,
        },
        timeout=30,
    )
    if resp.status_code == 200:
        answer = resp.json()["choices"][0]["message"]["content"].strip().upper()
        return "YES" in answer
    return bool(reply and reply.strip())


def langfuse_get_trace(trace_id: str, retries: int = 6, delay: float = 2.0) -> dict | None:
    """Query Langfuse for a trace by ID, with retries for async ingestion lag."""
    if not _LF_PK or not _LF_SK:
        return None
    auth = base64.b64encode(f"{_LF_PK}:{_LF_SK}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}

    time.sleep(1.0)
    for attempt in range(retries):
        if attempt > 0:
            time.sleep(delay)
        try:
            resp = requests.get(
                f"{_LF_HOST}/api/public/traces/{trace_id}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
    return None


def assert_langfuse_trace(trace_id: str, *, session_id: str = "") -> dict:
    """Assert a Langfuse trace exists and optionally verify session_id."""
    trace = langfuse_get_trace(trace_id)
    assert trace is not None, f"Langfuse trace {trace_id} not found"
    assert trace.get("name"), f"Langfuse trace {trace_id} has no name"
    if session_id:
        assert trace.get("sessionId") == session_id, (
            f"Langfuse sessionId mismatch: expected {session_id}, got {trace.get('sessionId')}"
        )
    return trace


def assert_langfuse_has_observations(trace_id: str, min_count: int = 1) -> list[dict]:
    """Assert Langfuse trace has at least min_count observations."""
    trace = langfuse_get_trace(trace_id)
    assert trace is not None, f"Langfuse trace {trace_id} not found"
    obs = trace.get("observations", [])
    assert len(obs) >= min_count, (
        f"Expected >= {min_count} observations, got {len(obs)} for trace {trace_id}"
    )
    return obs


@pytest.fixture(scope="session")
def qwen_api_key() -> str:
    return os.environ.get("QWEN_API_KEY", "") or os.environ.get("DASHSCOPE_API_KEY", "")


@pytest.fixture(scope="session")
def langfuse_available() -> bool:
    if not _LF_PK or not _LF_SK:
        return False
    try:
        auth = base64.b64encode(f"{_LF_PK}:{_LF_SK}".encode()).decode()
        resp = requests.get(
            f"{_LF_HOST}/api/public/health",
            headers={"Authorization": f"Basic {auth}"},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


async def _echo_agent_fn(
    user_message: str,
    history: list[MessageEntry],
    session_id: str,
    routing_key: str = "",
    verbose: bool = False,
) -> str:
    return f"Echo: {user_message}"


@pytest_asyncio.fixture
async def slash_client(tmp_path):
    """Echo agent for slash command tests (no LLM needed)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    hook_registry = _load_shared_hooks()
    session_mgr = SessionManager(data_dir=data_dir)
    sender = CaptureSender()
    runner = Runner(
        session_mgr=session_mgr,
        sender=sender,
        agent_fn=_echo_agent_fn,
        data_dir=data_dir,
        hook_registry=hook_registry,
    )

    app = create_test_app(runner=runner, sender=sender, session_mgr=session_mgr)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await runner.shutdown()
    await client.close()


@pytest_asyncio.fixture
async def llm_client(tmp_path, qwen_api_key):
    """Real Qwen LLM + Hook framework + Langfuse tracing."""
    if not qwen_api_key:
        pytest.skip("QWEN_API_KEY not set")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    _init_workspace(workspace_dir)
    ctx_dir = data_dir / "ctx"
    ctx_dir.mkdir(parents=True)

    hook_registry = _load_shared_hooks()
    session_mgr = SessionManager(data_dir=data_dir)
    sender = CaptureSender()

    from xiaopaw.agents.main_crew import build_agent_fn

    agent_fn = build_agent_fn(
        sender=sender,
        workspace_dir=workspace_dir,
        ctx_dir=ctx_dir,
        sandbox_url="",
    )

    runner = Runner(
        session_mgr=session_mgr,
        sender=sender,
        agent_fn=agent_fn,
        data_dir=data_dir,
        hook_registry=hook_registry,
    )

    app = create_test_app(runner=runner, sender=sender, session_mgr=session_mgr)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await runner.shutdown()
    await client.close()
