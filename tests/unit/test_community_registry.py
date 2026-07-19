"""Unit tests for ``xiaopaw.skills_mgmt.community.CommunityRegistry``.

Covers: list/search, detail, review, publish, favorites, permissions.
All database access is mocked via ``unittest.mock`` — no real PostgreSQL required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import psycopg2

from xiaopaw.skills_mgmt.community import (
    CommunityError,
    CommunityRegistry,
    _SORT_MAP,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


class _CursorCtx:
    """Helper to make mock cursor work as both regular and context-manager cursor."""

    def __init__(self, cur: MagicMock):
        self._cur = cur

    def __enter__(self):
        return self._cur

    def __exit__(self, *args):
        return False


class _ConnCtx:
    """Helper to make mock connection work as context manager."""

    def __init__(self, conn: MagicMock):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *args):
        return False


@pytest.fixture
def mock_pg():
    """Mock psycopg2.connect → (conn, cur) pair with context-manager support."""
    conn = MagicMock()
    cur = MagicMock()
    # cursor() returns an object usable as context manager
    conn.cursor.return_value = _CursorCtx(cur)
    # Make conn itself usable as context manager
    conn_cm = _ConnCtx(conn)
    with patch(
        "xiaopaw.skills_mgmt.community.psycopg2.connect",
        return_value=conn_cm,
    ):
        yield conn, cur


@pytest.fixture
def registry(mock_pg, tmp_path):
    """Create a CommunityRegistry instance backed by mocked PG."""
    conn, cur = mock_pg
    # Patch mkdir so storage_dir creation doesn't pollute tmp_path
    storage = tmp_path / "community"
    storage.mkdir(parents=True, exist_ok=True)
    reg = CommunityRegistry(
        pg_dsn="postgresql://test",
        market_registry=MagicMock(),
        user_dir=tmp_path,
        event_bus=MagicMock(),
        storage_dir=storage,
    )
    return reg


# ─── 列表与搜索 ──────────────────────────────────────────────────────────────


class TestListSkills:
    """list_skills — 分页、搜索、排序、过滤。"""

    def test_list_skills_default(self, registry, mock_pg):
        """默认参数返回分页结果，无额外过滤。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = {"count": 5}
        cur.fetchall.return_value = [
            {"name": "skill-a", "status": "approved"},
            {"name": "skill-b", "status": "approved"},
        ]
        result = registry.list_skills()
        assert result["total"] == 5
        assert len(result["skills"]) == 2
        # Verify SQL contains ORDER BY install_count DESC (default sort)
        call_args = cur.execute.call_args_list
        assert any("install_count DESC" in str(c) for c in call_args)

    def test_list_skills_with_search(self, registry, mock_pg):
        """search 参数通过 plainto_tsquery 传入 SQL。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = {"count": 1}
        cur.fetchall.return_value = [{"name": "search-hit"}]
        result = registry.list_skills(search="pdf converter")
        assert result["total"] == 1
        # Check that search parameter was passed to execute
        calls = cur.execute.call_args_list
        assert any("plainto_tsquery" in str(c) for c in calls)
        # Verify the search term appears in params
        all_params = [str(c) for c in calls]
        assert any("pdf converter" in p for p in all_params)

    def test_list_skills_with_category_filter(self, registry, mock_pg):
        """category 过滤生成正确的 WHERE 子句。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = {"count": 3}
        cur.fetchall.return_value = []
        registry.list_skills(category="data")
        calls = cur.execute.call_args_list
        assert any("category = %s" in str(c) for c in calls)

    def test_list_skills_sort_options(self, registry, mock_pg):
        """4 种排序选项生成正确的 ORDER BY。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = {"count": 0}
        cur.fetchall.return_value = []
        for sort_key, expected_order in _SORT_MAP.items():
            cur.execute.reset_mock()
            registry.list_skills(sort=sort_key)
            calls = cur.execute.call_args_list
            assert any(expected_order in str(c) for c in calls), (
                f"sort={sort_key} should produce ORDER BY {expected_order}"
            )

    def test_list_skills_pagination(self, registry, mock_pg):
        """page/page_size 参数正确计算 OFFSET。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = {"count": 100}
        cur.fetchall.return_value = []
        registry.list_skills(page=3, page_size=10)
        # OFFSET = (3 - 1) * 10 = 20
        calls = cur.execute.call_args_list
        # The main query (second execute) should have LIMIT 10 OFFSET 20
        main_call = calls[-1]
        args = main_call[0]  # positional args to execute
        assert 10 in args[1] or args[1][-2] == 10  # LIMIT
        assert args[1][-1] == 20  # OFFSET

    def test_list_skills_only_approved(self, registry, mock_pg):
        """只返回 status='approved' 的技能。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = {"count": 0}
        cur.fetchall.return_value = []
        registry.list_skills()
        calls = cur.execute.call_args_list
        assert all("status = 'approved'" in str(c) for c in calls)

    def test_list_skills_db_error_returns_empty(self, registry):
        """DB 异常时返回空结果。"""
        with patch.object(
            CommunityRegistry, "_connect", side_effect=RuntimeError("pg down")
        ):
            result = registry.list_skills()
        assert result == {"skills": [], "total": 0}


# ─── 详情 ────────────────────────────────────────────────────────────────────


class TestGetSkill:
    """get_skill — 存在/不存在。"""

    def test_get_skill_found(self, registry, mock_pg):
        """存在时返回完整字段 + 评分分布。"""
        conn, cur = mock_pg
        skill_row = {"name": "pdf-tool", "rating_avg": 4.5, "status": "approved"}
        rating_dist = [
            {"rating": 1, "cnt": 0},
            {"rating": 4, "cnt": 3},
            {"rating": 5, "cnt": 2},
        ]
        # First fetchone returns skill row, second set is fetchall for dist
        cur.fetchone.return_value = skill_row
        cur.fetchall.return_value = rating_dist
        result = registry.get_skill("pdf-tool")
        assert result is not None
        assert result["name"] == "pdf-tool"
        assert "rating_distribution" in result
        dist = result["rating_distribution"]
        assert dist[1] == 0
        assert dist[4] == 3
        assert dist[5] == 2
        # Ratings without reviews should be 0
        assert dist[2] == 0
        assert dist[3] == 0

    def test_get_skill_not_found(self, registry, mock_pg):
        """不存在时返回 None。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = None
        result = registry.get_skill("nonexistent")
        assert result is None


# ─── 评价 ────────────────────────────────────────────────────────────────────


class TestReviews:
    """add_review / list_reviews / mark_helpful。"""

    def test_add_review_success(self, registry, mock_pg):
        """正常提交评价，验证 SQL INSERT + rating_avg 更新。"""
        conn, cur = mock_pg
        review_row = {"id": 1, "skill_name": "pdf", "user_id": "u1", "rating": 5}
        avg_row = {"avg": 4.5, "cnt": 2}
        cur.fetchone.side_effect = [review_row, avg_row]
        result = registry.add_review("pdf", "u1", 5, "Great!")
        assert result["rating"] == 5
        # Verify 3 execute calls: INSERT, AVG query, UPDATE
        assert cur.execute.call_count == 3
        # Third call should update rating_avg
        update_call = cur.execute.call_args_list[2]
        assert "rating_avg" in str(update_call)

    def test_add_review_duplicate_raises(self, registry, mock_pg):
        """重复评价（IntegrityError）转换为 CommunityError。"""
        conn, cur = mock_pg
        cur.fetchone.side_effect = psycopg2.IntegrityError("duplicate")
        with pytest.raises(CommunityError, match="skill not found"):
            registry.add_review("pdf", "u1", 5)

    def test_add_review_rating_range(self, registry):
        """rating 必须在 1-5 之间。"""
        with pytest.raises(CommunityError, match="rating must be 1-5"):
            registry.add_review("pdf", "u1", 0)
        with pytest.raises(CommunityError, match="rating must be 1-5"):
            registry.add_review("pdf", "u1", 6)
        with pytest.raises(CommunityError, match="rating must be 1-5"):
            registry.add_review("pdf", "u1", -1)

    def test_list_reviews_pagination(self, registry, mock_pg):
        """分页参数正确。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = {"count": 25}
        cur.fetchall.return_value = []
        result = registry.list_reviews("pdf", page=3, page_size=10)
        assert result["total"] == 25
        # OFFSET = (3-1) * 10 = 20
        calls = cur.execute.call_args_list
        last_call = calls[-1]
        assert last_call[0][1][-1] == 20  # OFFSET
        assert last_call[0][1][-2] == 10  # LIMIT

    def test_mark_helpful(self, registry, mock_pg):
        """helpful_count 递增，返回 True。"""
        conn, cur = mock_pg
        cur.rowcount = 1
        result = registry.mark_helpful(42, "u1")
        assert result is True
        call = cur.execute.call_args
        assert "helpful_count" in str(call)

    def test_mark_helpful_not_found(self, registry, mock_pg):
        """不存在的 review 返回 False。"""
        conn, cur = mock_pg
        cur.rowcount = 0
        result = registry.mark_helpful(999, "u1")
        assert result is False


# ─── 发布 ────────────────────────────────────────────────────────────────────


class TestPublishSkill:
    """publish_skill — 正常发布 + 异常处理。"""

    def test_publish_skill_success(self, registry, mock_pg, tmp_path):
        """合法发布 → status='pending'，archive_hash 正确。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = {"name": "my-skill", "status": "pending"}
        # Create a dummy zip file
        zip_path = tmp_path / "test.zip"
        zip_path.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        # Mock unpack_skill and validate_archive_size
        with patch("xiaopaw.skills_mgmt.community.unpack_skill", return_value=("my-skill", None)), \
             patch("xiaopaw.skills_mgmt.community.validate_archive_size"):
            result = registry.publish_skill(
                publisher="alice",
                metadata={"name": "my-skill", "description": "test"},
                zip_path=zip_path,
            )
        assert result["status"] == "pending"
        # Verify INSERT was called
        insert_call = cur.execute.call_args_list[0]
        assert "INSERT INTO community_skills" in str(insert_call)

    def test_publish_skill_missing_name(self, registry, tmp_path):
        """缺少 name 字段抛出 CommunityError。"""
        zip_path = tmp_path / "test.zip"
        zip_path.write_bytes(b"data")
        with pytest.raises(CommunityError, match="metadata must include"):
            registry.publish_skill(publisher="alice", metadata={}, zip_path=zip_path)

    def test_publish_skill_name_conflict(self, registry, mock_pg, tmp_path):
        """名称冲突抛出 CommunityError(duplicate_name)。"""
        conn, cur = mock_pg
        cur.fetchone.side_effect = psycopg2.IntegrityError("duplicate key")
        zip_path = tmp_path / "test.zip"
        zip_path.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        with patch("xiaopaw.skills_mgmt.community.unpack_skill", return_value=("dup", None)), \
             patch("xiaopaw.skills_mgmt.community.validate_archive_size"):
            with pytest.raises(CommunityError, match="skill already exists"):
                registry.publish_skill(
                    publisher="alice",
                    metadata={"name": "dup", "description": "test"},
                    zip_path=zip_path,
                )


# ─── 收藏 ────────────────────────────────────────────────────────────────────


class TestFavorites:
    """add_favorite / remove_favorite / list_favorites。"""

    def test_add_favorite(self, registry, mock_pg):
        """正常收藏返回 True。"""
        conn, cur = mock_pg
        result = registry.add_favorite("u1", "pdf-tool")
        assert result is True
        call = cur.execute.call_args
        assert "INSERT INTO user_favorites" in str(call)

    def test_remove_favorite(self, registry, mock_pg):
        """正常取消收藏。"""
        conn, cur = mock_pg
        cur.rowcount = 1
        result = registry.remove_favorite("u1", "pdf-tool")
        assert result is True
        call = cur.execute.call_args
        assert "DELETE FROM user_favorites" in str(call)

    def test_remove_favorite_not_found(self, registry, mock_pg):
        """取消不存在的收藏返回 False。"""
        conn, cur = mock_pg
        cur.rowcount = 0
        result = registry.remove_favorite("u1", "nonexistent")
        assert result is False

    def test_list_favorites(self, registry, mock_pg):
        """返回用户收藏列表。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = [
            {"name": "skill-a", "status": "approved"},
            {"name": "skill-b", "status": "approved"},
        ]
        result = registry.list_favorites("u1")
        assert len(result) == 2
        call = cur.execute.call_args
        assert "user_favorites" in str(call)


# ─── 权限 ────────────────────────────────────────────────────────────────────


class TestPermissions:
    """update_skill / withdraw_skill — 仅发布者可操作。"""

    def test_update_skill_owner_only(self, registry, mock_pg):
        """非发布者更新 → CommunityError(not_owner)。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = None  # No row matched → not owner
        with pytest.raises(CommunityError, match="not the publisher"):
            registry.update_skill("pdf", publisher="not_owner", updates={"description": "hacked"})

    def test_update_skill_success(self, registry, mock_pg):
        """发布者正常更新。"""
        conn, cur = mock_pg
        cur.fetchone.return_value = {"name": "pdf", "description": "updated"}
        result = registry.update_skill("pdf", publisher="alice", updates={"description": "updated"})
        assert result["description"] == "updated"

    def test_update_skill_no_valid_fields(self, registry):
        """无有效字段抛出 CommunityError(no_fields)。"""
        with pytest.raises(CommunityError, match="no valid fields"):
            registry.update_skill("pdf", publisher="alice", updates={"invalid_field": "x"})

    def test_withdraw_skill_owner_only(self, registry, mock_pg):
        """非发布者下架 → 返回 False (affected=0)。"""
        conn, cur = mock_pg
        cur.rowcount = 0
        result = registry.withdraw_skill("pdf", publisher="not_owner")
        assert result is False

    def test_withdraw_skill_success(self, registry, mock_pg):
        """发布者正常下架。"""
        conn, cur = mock_pg
        cur.rowcount = 1
        result = registry.withdraw_skill("pdf", publisher="alice")
        assert result is True


# ─── 分类与排行 ──────────────────────────────────────────────────────────────


class TestCategoriesAndRankings:
    """get_categories / get_rankings / get_featured / list_my_skills。"""

    def test_get_categories(self, registry, mock_pg):
        conn, cur = mock_pg
        cur.fetchall.return_value = [
            {"id": "data", "name": "数据分析", "sort_order": 1},
        ]
        result = registry.get_categories()
        assert len(result) == 1
        assert result[0]["id"] == "data"

    def test_get_rankings_week(self, registry, mock_pg):
        conn, cur = mock_pg
        cur.fetchall.return_value = [{"name": "top-skill", "install_count": 100}]
        result = registry.get_rankings(period="week")
        assert len(result) == 1
        call = cur.execute.call_args
        assert "install_count DESC" in str(call)

    def test_get_featured(self, registry, mock_pg):
        conn, cur = mock_pg
        cur.fetchall.return_value = [{"name": "featured-skill", "featured": True}]
        result = registry.get_featured()
        assert len(result) == 1
        call = cur.execute.call_args
        assert "featured" in str(call).lower()

    def test_list_my_skills(self, registry, mock_pg):
        conn, cur = mock_pg
        cur.fetchall.return_value = [
            {"name": "my-skill-1", "publisher": "alice", "status": "pending"},
            {"name": "my-skill-2", "publisher": "alice", "status": "approved"},
        ]
        result = registry.list_my_skills("alice")
        assert len(result) == 2
        call = cur.execute.call_args
        assert "publisher" in str(call)
