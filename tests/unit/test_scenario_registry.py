"""Unit tests for ``xiaopaw.frontend.expert.ScenarioRegistry``.

Uses a real temporary SQLite db (same style as ``ExpertRegistry``).
Covers: table creation + default injection, idempotent init, ordering,
and JSON decoding of ``expert_names``.
"""

from __future__ import annotations

import sqlite3

import pytest

from xiaopaw.frontend.expert import (
    ExpertRegistry,
    ScenarioRegistry,
    _DEFAULT_SCENARIOS,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "auth.db"


def test_creates_table_and_injects_defaults(db_path):
    reg = ScenarioRegistry(db_path)
    scenarios = reg.list_all()
    assert len(scenarios) == len(_DEFAULT_SCENARIOS)
    keys = {s["key"] for s in scenarios}
    assert keys == {s["key"] for s in _DEFAULT_SCENARIOS}


def test_scenarios_ordered_by_sort_order(db_path):
    reg = ScenarioRegistry(db_path)
    orders = [s["sort_order"] for s in reg.list_all()]
    assert orders == sorted(orders)
    # first default scenario has the smallest sort_order
    assert reg.list_all()[0]["key"] == "content_create"


def test_expert_names_decoded_as_list(db_path):
    reg = ScenarioRegistry(db_path)
    for s in reg.list_all():
        assert isinstance(s["expert_names"], list)
        assert all(isinstance(n, str) for n in s["expert_names"])


def test_init_is_idempotent(db_path):
    ScenarioRegistry(db_path)
    ScenarioRegistry(db_path)  # second init must not duplicate
    reg = ScenarioRegistry(db_path)
    assert len(reg.list_all()) == len(_DEFAULT_SCENARIOS)
    # verify raw row count too
    with sqlite3.connect(str(db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM expert_scenarios").fetchone()[0]
    assert count == len(_DEFAULT_SCENARIOS)


def test_default_scenarios_reference_existing_experts(db_path):
    """Every default scenario must resolve to >=1 real built-in expert."""
    expert_reg = ExpertRegistry(db_path)
    scenario_reg = ScenarioRegistry(db_path)
    for s in scenario_reg.list_all():
        valid = [n for n in s["expert_names"] if expert_reg.get(n)]
        assert valid, f"scenario {s['key']} has no valid experts"


def test_corrupt_expert_names_falls_back_to_empty_list(db_path):
    reg = ScenarioRegistry(db_path)
    # Inject a row with invalid JSON in expert_names
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """INSERT INTO expert_scenarios
               (key, title, subtitle, icon, gradient, expert_names,
                sort_order, created_at, updated_at)
               VALUES ('broken', 'X', '', 'expert', 'sky', 'not-json',
                       999, '2026-01-01', '2026-01-01')"""
        )
    broken = next(s for s in reg.list_all() if s["key"] == "broken")
    assert broken["expert_names"] == []
