"""Integration tests for the featured-scenario API route.

Real ``UserAuth`` + real ``ExpertRegistry`` / ``ScenarioRegistry`` on a temp db.
"""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.frontend.auth import UserAuth
from xiaopaw.frontend.expert import ExpertRegistry, ScenarioRegistry
from xiaopaw.frontend.routes.scenario import register_scenario_routes

SCENARIO_URL = "/api/frontend/expert-scenarios"


@pytest.fixture
def scenario_app(tmp_path):
    """App with real experts + scenarios registries and an authed user."""
    db = tmp_path / "auth.db"
    auth = UserAuth(db)
    token, _ = auth.register("alice", "password123")

    app = web.Application()
    app["user_auth"] = auth
    app["expert_registry"] = ExpertRegistry(db)
    app["scenario_registry"] = ScenarioRegistry(db)
    register_scenario_routes(app)
    return app, token


@pytest.mark.asyncio
async def test_list_requires_auth(scenario_app):
    app, _ = scenario_app
    async with TestClient(TestServer(app)) as client:
        r = await client.get(SCENARIO_URL)
        assert r.status == 401


@pytest.mark.asyncio
async def test_list_returns_scenarios_with_inlined_experts(scenario_app):
    app, token = scenario_app
    async with TestClient(TestServer(app)) as client:
        r = await client.get(SCENARIO_URL, headers={"Authorization": f"Bearer {token}"})
        assert r.status == 200
        data = await r.json()
        scenarios = data["scenarios"]
        assert len(scenarios) == 5

        # ordering by sort_order ascending
        assert scenarios[0]["key"] == "content_create"

        for sc in scenarios:
            assert set(sc.keys()) == {"key", "title", "subtitle", "icon", "gradient", "experts"}
            assert 1 <= len(sc["experts"]) <= 3
            for ex in sc["experts"]:
                # only the compact projection is exposed
                assert set(ex.keys()) == {"name", "display_name", "icon", "team"}


@pytest.mark.asyncio
async def test_invalid_expert_refs_filtered_and_empty_scenarios_omitted(tmp_path):
    """Scenario referencing only missing experts is omitted; partial refs trimmed."""
    db = tmp_path / "auth.db"
    auth = UserAuth(db)
    token, _ = auth.register("alice", "password123")

    expert_reg = ExpertRegistry(db)
    scenario_reg = ScenarioRegistry(db)
    # Wipe defaults and craft two custom scenarios directly in the db.
    import sqlite3

    with sqlite3.connect(str(db)) as conn:
        conn.execute("DELETE FROM expert_scenarios")
        conn.execute(
            """INSERT INTO expert_scenarios
               (key, title, subtitle, icon, gradient, expert_names, sort_order, created_at, updated_at)
               VALUES ('mixed', 'Mixed', '', 'expert', 'sky',
                       '["dev_team", "ghost_a", "cloud_support"]', 1, 't', 't')"""
        )
        conn.execute(
            """INSERT INTO expert_scenarios
               (key, title, subtitle, icon, gradient, expert_names, sort_order, created_at, updated_at)
               VALUES ('all_ghost', 'Ghosts', '', 'expert', 'sky',
                       '["ghost_a", "ghost_b"]', 2, 't', 't')"""
        )

    app = web.Application()
    app["user_auth"] = auth
    app["expert_registry"] = expert_reg
    app["scenario_registry"] = scenario_reg
    register_scenario_routes(app)

    async with TestClient(TestServer(app)) as client:
        r = await client.get(SCENARIO_URL, headers={"Authorization": f"Bearer {token}"})
        assert r.status == 200
        scenarios = (await r.json())["scenarios"]

    # all-ghost scenario omitted; mixed keeps only the two valid experts
    assert [s["key"] for s in scenarios] == ["mixed"]
    names = [e["name"] for e in scenarios[0]["experts"]]
    assert names == ["dev_team", "cloud_support"]


@pytest.mark.asyncio
async def test_missing_scenario_registry_returns_empty(tmp_path):
    db = tmp_path / "auth.db"
    auth = UserAuth(db)
    token, _ = auth.register("alice", "password123")
    app = web.Application()
    app["user_auth"] = auth
    app["scenario_registry"] = None  # not assembled
    register_scenario_routes(app)
    async with TestClient(TestServer(app)) as client:
        r = await client.get(SCENARIO_URL, headers={"Authorization": f"Bearer {token}"})
        assert r.status == 200
        assert (await r.json())["scenarios"] == []
