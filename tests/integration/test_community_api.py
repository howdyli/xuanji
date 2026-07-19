"""Integration tests for community market API handlers.

Tests the full request->response chain via aiohttp.test_utils.
All CommunityRegistry methods are mocked - no real PostgreSQL required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.skills_mgmt.api import register_community_routes
from xiaopaw.skills_mgmt.community import CommunityError, CommunityRegistry


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def mock_registry():
    """Fully mocked CommunityRegistry."""
    reg = MagicMock(spec=CommunityRegistry)
    reg._install_max_bytes = 20 * 1024 * 1024
    return reg


@pytest.fixture
def app(mock_registry):
    """aiohttp app with community routes + static token auth."""
    application = web.Application()
    application["frontend_token"] = "test-token"
    application["community_registry"] = mock_registry
    register_community_routes(application, mock_registry)
    return application


@pytest.fixture
async def client(app):
    """TestClient wrapping the app."""
    async with TestClient(TestServer(app)) as c:
        yield c


AUTH = {"Authorization": "Bearer test-token"}


# --- Helper ------------------------------------------------------------------


async def _json(resp):
    return json.loads(await resp.text())


# --- Tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_skills_api(client, mock_registry):
    """GET /skills returns 200 + correct JSON structure."""
    mock_registry.list_skills.return_value = {
        "skills": [{"name": "pdf-tool", "status": "approved"}],
        "total": 1,
    }
    resp = await client.get("/api/frontend/market/community/skills", headers=AUTH)
    assert resp.status == 200
    data = await _json(resp)
    assert data["total"] == 1
    assert data["skills"][0]["name"] == "pdf-tool"


@pytest.mark.asyncio
async def test_get_skill_api_found(client, mock_registry):
    """GET /skills/{name} returns 200 when skill exists."""
    mock_registry.get_skill.return_value = {
        "name": "pdf-tool",
        "rating_avg": 4.5,
        "rating_distribution": {1: 0, 2: 0, 3: 1, 4: 3, 5: 2},
    }
    resp = await client.get(
        "/api/frontend/market/community/skills/pdf-tool", headers=AUTH
    )
    assert resp.status == 200
    data = await _json(resp)
    assert data["name"] == "pdf-tool"
    assert "rating_distribution" in data


@pytest.mark.asyncio
async def test_get_skill_api_not_found(client, mock_registry):
    """GET /skills/{name} returns 404 when skill doesn't exist."""
    mock_registry.get_skill.return_value = None
    resp = await client.get(
        "/api/frontend/market/community/skills/nonexistent", headers=AUTH
    )
    assert resp.status == 404
    data = await _json(resp)
    assert data["error"] == "not_found"


@pytest.mark.asyncio
async def test_install_skill_api(client, mock_registry):
    """POST /skills/{name}/install returns 200 on success."""
    mock_registry.install_skill = AsyncMock(return_value="pdf-tool")
    resp = await client.post(
        "/api/frontend/market/community/skills/pdf-tool/install",
        headers=AUTH,
        json={"user_id": "u1"},
    )
    assert resp.status == 200
    data = await _json(resp)
    assert data["ok"] is True
    assert data["name"] == "pdf-tool"


@pytest.mark.asyncio
async def test_get_categories_api(client, mock_registry):
    """GET /categories returns 200 + category list."""
    mock_registry.get_categories.return_value = [
        {"id": "data", "name": "data-analysis", "sort_order": 1},
        {"id": "code", "name": "code-dev", "sort_order": 2},
    ]
    resp = await client.get(
        "/api/frontend/market/community/categories", headers=AUTH
    )
    assert resp.status == 200
    data = await _json(resp)
    assert len(data["categories"]) == 2


@pytest.mark.asyncio
async def test_add_review_api_success(client, mock_registry):
    """POST /skills/{name}/reviews returns 200."""
    mock_registry.add_review.return_value = {
        "id": 1, "skill_name": "pdf-tool", "rating": 5, "comment": "Great!",
    }
    resp = await client.post(
        "/api/frontend/market/community/skills/pdf-tool/reviews",
        headers=AUTH,
        json={"rating": 5, "comment": "Great!"},
    )
    assert resp.status == 200
    data = await _json(resp)
    assert data["ok"] is True
    assert data["review"]["rating"] == 5


@pytest.mark.asyncio
async def test_add_review_api_invalid_rating(client, mock_registry):
    """POST /skills/{name}/reviews returns 400 for invalid rating."""
    mock_registry.add_review.side_effect = CommunityError(
        "invalid_rating", "rating must be 1-5"
    )
    resp = await client.post(
        "/api/frontend/market/community/skills/pdf-tool/reviews",
        headers=AUTH,
        json={"rating": 0, "comment": "Bad"},
    )
    assert resp.status == 400
    data = await _json(resp)
    assert data["error"] == "invalid_rating"


@pytest.mark.asyncio
async def test_unauthorized_access(client):
    """Requests without valid Bearer token return 401."""
    resp = await client.get("/api/frontend/market/community/skills")
    assert resp.status == 401
    data = await _json(resp)
    assert data["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_forbidden_update(client, mock_registry):
    """PUT /skills/{name} returns 403 when not the publisher."""
    mock_registry.update_skill.side_effect = CommunityError(
        "not_owner", "skill not found or not the publisher"
    )
    resp = await client.put(
        "/api/frontend/market/community/skills/pdf-tool",
        headers=AUTH,
        json={"description": "hacked"},
    )
    assert resp.status == 403
    data = await _json(resp)
    assert data["error"] == "not_owner"


@pytest.mark.asyncio
async def test_withdraw_skill_api(client, mock_registry):
    """DELETE /skills/{name} returns 200 on successful withdraw."""
    mock_registry.withdraw_skill.return_value = True
    resp = await client.delete(
        "/api/frontend/market/community/skills/pdf-tool", headers=AUTH
    )
    assert resp.status == 200
    data = await _json(resp)
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_withdraw_skill_forbidden(client, mock_registry):
    """DELETE /skills/{name} returns 403 when not the publisher."""
    mock_registry.withdraw_skill.return_value = False
    resp = await client.delete(
        "/api/frontend/market/community/skills/pdf-tool", headers=AUTH
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_list_favorites_api(client, mock_registry):
    """GET /favorites returns user's favorite skills."""
    mock_registry.list_favorites.return_value = [
        {"name": "pdf-tool", "status": "approved"},
    ]
    resp = await client.get(
        "/api/frontend/market/community/favorites", headers=AUTH
    )
    assert resp.status == 200
    data = await _json(resp)
    assert len(data["skills"]) == 1


@pytest.mark.asyncio
async def test_mark_helpful_api(client, mock_registry):
    """POST /reviews/{id}/helpful returns 200."""
    mock_registry.mark_helpful.return_value = True
    resp = await client.post(
        "/api/frontend/market/community/reviews/42/helpful",
        headers=AUTH,
        json={},
    )
    assert resp.status == 200
    data = await _json(resp)
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_get_rankings_api(client, mock_registry):
    """GET /rankings returns top skills."""
    mock_registry.get_rankings.return_value = [
        {"name": "top-skill", "install_count": 100},
    ]
    resp = await client.get(
        "/api/frontend/market/community/rankings", headers=AUTH
    )
    assert resp.status == 200
    data = await _json(resp)
    assert len(data["rankings"]) == 1
