"""Featured-scenario route handlers (read-only).

Each scenario groups a few experts under a usage theme. The handler expands the
scenario's ``expert_names`` against the expert registry, keeps only valid
references (max 3), and omits scenarios that end up with no valid experts.
"""

from __future__ import annotations

import logging

from aiohttp import web

from xiaopaw.frontend.routes.helpers import check_auth

logger = logging.getLogger(__name__)

_MAX_EXPERTS_PER_SCENARIO = 3


def _expand_experts(expert_registry, names: list[str]) -> list[dict]:
    """Resolve expert names to compact cards; drop invalid refs; cap at 3."""
    if not expert_registry:
        return []
    experts: list[dict] = []
    for name in names:
        expert = expert_registry.get(name)
        if not expert:
            continue
        experts.append(
            {
                "name": expert["name"],
                "display_name": expert["display_name"],
                "icon": expert["icon"],
                "team": expert["team"],
            }
        )
        if len(experts) >= _MAX_EXPERTS_PER_SCENARIO:
            break
    return experts


async def handle_scenarios_list(request: web.Request) -> web.Response:
    """GET /api/frontend/expert-scenarios — list featured scenarios.

    Each scenario inlines its (max 3) valid experts. Scenarios with no valid
    experts are omitted.
    """
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("scenario_registry")
    if not registry:
        return web.json_response({"scenarios": []})
    expert_registry = request.app.get("expert_registry")
    scenarios = []
    for sc in registry.list_all():
        experts = _expand_experts(expert_registry, sc.get("expert_names", []))
        if not experts:
            continue
        scenarios.append(
            {
                "key": sc["key"],
                "title": sc["title"],
                "subtitle": sc["subtitle"],
                "icon": sc["icon"],
                "gradient": sc["gradient"],
                "experts": experts,
            }
        )
    return web.json_response({"scenarios": scenarios})


def register_scenario_routes(app: web.Application) -> None:
    """Register featured-scenario routes."""
    app.router.add_get("/api/frontend/expert-scenarios", handle_scenarios_list)
