"""Unit tests for the ``skill_hints`` body-field sanitizer.

The sanitizer is deliberately lenient: a malformed field degrades to "no
hints" and never produces a 4xx. Whitelist enforcement lives in
SkillLoaderTool, not here.
"""

from __future__ import annotations

import pytest

from xiaopaw.frontend.routes.session import _sanitize_skill_hints


def test_valid_hints_pass_through():
    assert _sanitize_skill_hints(["skill-a", "skill-b"]) == ["skill-a", "skill-b"]


@pytest.mark.parametrize("raw", ["skill-a", 42, None, {"a": 1}, True])
def test_non_list_is_ignored_entirely(raw):
    assert _sanitize_skill_hints(raw) == []


def test_non_string_items_are_dropped():
    assert _sanitize_skill_hints([1, "skill-a", None, ["x"]]) == ["skill-a"]


def test_blank_items_are_dropped():
    assert _sanitize_skill_hints(["", "   ", "skill-a"]) == ["skill-a"]


def test_overlong_items_are_dropped():
    assert _sanitize_skill_hints(["x" * 65, "skill-a"]) == ["skill-a"]
    # Exactly 64 chars is still accepted.
    assert _sanitize_skill_hints(["y" * 64]) == ["y" * 64]


def test_capped_at_three_hints():
    raw = [f"skill-{i}" for i in range(6)]
    assert _sanitize_skill_hints(raw) == ["skill-0", "skill-1", "skill-2"]


def test_duplicates_deduped_preserving_order():
    assert _sanitize_skill_hints(["b", "a", "b", "a", "c"]) == ["b", "a", "c"]


def test_items_are_stripped():
    assert _sanitize_skill_hints(["  skill-a  "]) == ["skill-a"]
