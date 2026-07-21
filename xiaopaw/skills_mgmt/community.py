"""CommunityRegistry —— 技能市场社区平台核心后端逻辑。

提供社区技能的发布、安装、搜索、评价、收藏等功能。
数据库使用 PostgreSQL（psycopg2），连接模式参照 MarketRegistry。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

from xiaopaw.event_bus import CommunityEvent, EventBus, EventPayload
from xiaopaw.skills_mgmt.market import MarketRegistry
from xiaopaw.skills_mgmt.packager import unpack_skill
from xiaopaw.skills_mgmt.validator import ValidationError, validate_archive_size

logger = logging.getLogger(__name__)

_SORT_MAP = {
    "popular": "install_count DESC",
    "newest": "created_at DESC",
    "rating": "rating_avg DESC",
    "name": "name ASC",
}


class CommunityError(Exception):
    """社区操作错误，带 code 供 HTTP 层映射。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class CommunityRegistry:
    """社区技能市场：发布 / 搜索 / 安装 / 评价 / 收藏。"""

    def __init__(
        self,
        pg_dsn: str,
        market_registry: MarketRegistry,
        user_dir: Path,
        event_bus: EventBus | None = None,
        storage_dir: Path | None = None,
        install_max_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        self._pg_dsn = pg_dsn
        self._market = market_registry
        self._user_dir = user_dir
        self._bus = event_bus or EventBus()
        self._storage_dir = storage_dir or Path("data/community_skills")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._install_max_bytes = install_max_bytes

    # ─── 内部工具 ────────────────────────────────────────────────

    def _connect(self):
        return psycopg2.connect(self._pg_dsn)

    def _emit(self, event: CommunityEvent, **data: Any) -> None:
        try:
            self._bus.publish(EventPayload(event=event, data=data))
        except Exception as exc:
            logger.warning("CommunityRegistry: emit %s failed: %s", event.value, exc)

    def _read_local_archive(self, install_url: str) -> bytes:
        """读取 local:// 归档，路径必须限定在 _storage_dir 内以防目录穿越。"""
        raw = install_url[len("local://"):]
        target = Path(raw).resolve()
        root = self._storage_dir.resolve()
        if root != target and root not in target.parents:
            raise CommunityError("invalid_install_url", "install path escapes storage dir")
        try:
            return target.read_bytes()
        except OSError as exc:
            raise CommunityError("download_failed", str(exc))

    # ─── 列表与搜索 ──────────────────────────────────────────────

    def list_skills(
        self, search: str | None = None, category: str | None = None,
        sort: str = "popular", page: int = 1, page_size: int = 20,
    ) -> dict[str, Any]:
        """分页查询已审核通过的社区技能。"""
        order = _SORT_MAP.get(sort, _SORT_MAP["popular"])
        base = "SELECT * FROM community_skills WHERE status = 'approved'"
        count_base = "SELECT COUNT(*) FROM community_skills WHERE status = 'approved'"
        clauses, params, cparams = [], [], []
        if category:
            clauses.append("category = %s"); params.append(category); cparams.append(category)
        if search:
            fts = ("to_tsvector('simple', coalesce(name,'') || ' ' || "
                   "coalesce(description,'')) @@ plainto_tsquery('simple', %s)")
            clauses.append(fts); params.append(search); cparams.append(search)
        if clauses:
            w = " AND " + " AND ".join(clauses)
            base += w; count_base += w
        offset = (max(1, page) - 1) * page_size
        base += f" ORDER BY {order} LIMIT %s OFFSET %s"
        params.extend([page_size, offset])

        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(count_base, cparams)
                    total = cur.fetchone()["count"]
                    cur.execute(base, params)
                    rows = [dict(r) for r in cur.fetchall()]
            return {"skills": rows, "total": total}
        except Exception as exc:
            logger.error("list_skills failed: %s", exc)
            return {"skills": [], "total": 0}

    def get_skill(self, name: str) -> dict[str, Any] | None:
        """获取单条技能详情，含评分分布。"""
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM community_skills WHERE name = %s", (name,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    skill = dict(row)
                    cur.execute(
                        "SELECT rating, COUNT(*) AS cnt FROM skill_reviews "
                        "WHERE skill_name = %s GROUP BY rating ORDER BY rating", (name,),
                    )
                    dist = {i: 0 for i in range(1, 6)}
                    for r in cur.fetchall():
                        dist[r["rating"]] = r["cnt"]
                    skill["rating_distribution"] = dist
            return skill
        except Exception as exc:
            logger.error("get_skill failed: %s", exc)
            return None

    def get_categories(self) -> list[dict[str, Any]]:
        """查询技能分类。"""
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM skill_categories ORDER BY sort_order")
                    return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error("get_categories failed: %s", exc)
            return []

    def get_rankings(self, period: str = "week") -> list[dict[str, Any]]:
        """安装量排行榜 top 10。period: 'week' | 'month' | 'all'。"""
        sql = "SELECT * FROM community_skills WHERE status = 'approved'"
        params: list[Any] = []
        if period == "week":
            sql += " AND created_at >= %s"; params.append(datetime.now(timezone.utc) - timedelta(weeks=1))
        elif period == "month":
            sql += " AND created_at >= %s"; params.append(datetime.now(timezone.utc) - timedelta(days=30))
        sql += " ORDER BY install_count DESC LIMIT 10"
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error("get_rankings failed: %s", exc)
            return []

    def get_featured(self) -> list[dict[str, Any]]:
        """获取精选技能。"""
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM community_skills "
                        "WHERE featured AND status = 'approved' ORDER BY install_count DESC"
                    )
                    return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error("get_featured failed: %s", exc)
            return []

    # ─── 安装 ────────────────────────────────────────────────────

    async def install_skill(self, name: str, user_id: str) -> str:
        """安装社区技能：下载→校验→解压→计数+1→发事件。"""
        skill = self.get_skill(name)
        if not skill:
            raise CommunityError("not_found", f"community skill not found: {name}")
        install_url = skill.get("install_url", "")
        if not install_url:
            raise CommunityError("no_install_url", f"no install_url for: {name}")
        if install_url.startswith("local://"):
            archive_bytes = await asyncio.to_thread(
                self._read_local_archive, install_url
            )
        else:
            try:
                archive_bytes = await self._market._archive_fetcher(install_url, self._install_max_bytes)
            except Exception as exc:
                raise CommunityError("download_failed", str(exc))
        if not archive_bytes:
            raise CommunityError("empty_archive", "downloaded archive is empty")
        # 校验哈希
        expected = skill.get("archive_hash")
        if expected:
            actual = hashlib.sha256(archive_bytes).hexdigest()
            if actual != expected:
                raise CommunityError("hash_mismatch", f"hash mismatch: {expected} != {actual}")
        # 解压安装
        import asyncio
        try:
            unpacked_name, _ = await asyncio.to_thread(
                unpack_skill, archive_bytes, self._user_dir,
                max_archive_bytes=self._install_max_bytes, overwrite=True,
            )
        except ValidationError as exc:
            raise CommunityError(exc.code, exc.message)
        # 更新安装计数
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE community_skills SET install_count = install_count + 1 WHERE name = %s",
                        (name,),
                    )
                conn.commit()
        except Exception as exc:
            logger.warning("install_skill: update count failed: %s", exc)
        self._emit(CommunityEvent.SKILL_INSTALLED, skill_name=name, user_id=user_id)
        return unpacked_name

    # ─── 发布 ────────────────────────────────────────────────────

    def publish_skill(self, publisher: str, metadata: dict[str, Any], zip_path: Path) -> dict[str, Any]:
        """发布技能：校验→存储→入库→发事件。"""
        name = metadata.get("name", "")
        if not name:
            raise CommunityError("missing_name", "metadata must include 'name'")
        try:
            archive_bytes = zip_path.read_bytes()
        except OSError as exc:
            raise CommunityError("read_failed", str(exc))
        validate_archive_size(len(archive_bytes), self._install_max_bytes)
        # 完整结构校验
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            try:
                unpack_skill(archive_bytes, Path(tmp), max_archive_bytes=self._install_max_bytes)
            except ValidationError as exc:
                raise CommunityError(exc.code, exc.message)
        archive_hash = hashlib.sha256(archive_bytes).hexdigest()
        dest = self._storage_dir / f"{name}.zip"
        try:
            dest.write_bytes(archive_bytes)
        except OSError as exc:
            raise CommunityError("storage_failed", str(exc))
        install_url = metadata.get("install_url") or f"local://{dest}"
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """INSERT INTO community_skills
                            (name,publisher,category,tags,description,version,
                             icon_url,screenshots,repo_url,install_url,
                             archive_hash,status,license,manifest_json)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s::jsonb)
                           RETURNING *""",
                        (name, publisher, metadata.get("category", "general"),
                         metadata.get("tags", []), metadata.get("description", ""),
                         metadata.get("version", "1.0.0"), metadata.get("icon_url"),
                         metadata.get("screenshots", []), metadata.get("repo_url"),
                         install_url, archive_hash, metadata.get("license", "MIT"), "{}"),
                    )
                    row = dict(cur.fetchone())
                conn.commit()
        except psycopg2.IntegrityError:
            dest.unlink(missing_ok=True)
            try: conn.rollback()
            except Exception: pass
            raise CommunityError("duplicate_name", f"skill already exists: {name}")
        except Exception as exc:
            dest.unlink(missing_ok=True)
            logger.error("publish_skill failed: %s", exc)
            raise CommunityError("db_error", str(exc))
        self._emit(CommunityEvent.SKILL_PUBLISHED, skill_name=name, publisher=publisher)
        return row

    def update_skill(self, name: str, publisher: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """更新技能（仅限发布者）。

        展示字段（description/category/tags/icon_url/screenshots/repo_url/license）
        立即写入线上行。安装产物字段（version/install_url/archive_hash）若技能已
        ``approved``，则暂存到 ``pending_*`` 等待管理员复审，期间线上继续服务旧版本；
        否则（pending/rejected）直接写入线上行，rejected 会重新排队为 pending。
        """
        display_allowed = {"description", "category", "tags", "icon_url",
                           "screenshots", "repo_url", "license"}
        artifact_allowed = {"version", "install_url", "archive_hash"}
        display = {k: v for k, v in updates.items() if k in display_allowed}
        artifact = {k: v for k, v in updates.items() if k in artifact_allowed}
        if not display and not artifact:
            raise CommunityError("no_fields", "no valid fields to update")
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT status FROM community_skills "
                        "WHERE name = %s AND publisher = %s",
                        (name, publisher),
                    )
                    current = cur.fetchone()
                    if not current:
                        raise CommunityError("not_owner", "skill not found or not the publisher")

                    parts, params = [], []
                    # 展示字段始终立即生效。
                    for k, v in display.items():
                        parts.append(f"{k} = %s"); params.append(v)

                    if artifact:
                        if current["status"] == "approved":
                            # 暂存产物变更等待复审；线上已通过版本保持不变。
                            for k, v in artifact.items():
                                parts.append(f"pending_{k} = %s"); params.append(v)
                            parts.append("has_pending_update = TRUE")
                            parts.append("pending_submitted_at = NOW()")
                        else:
                            # 无已通过版本需保护：直接写入线上行。
                            for k, v in artifact.items():
                                parts.append(f"{k} = %s"); params.append(v)
                            if current["status"] == "rejected":
                                parts.append("status = 'pending'")

                    parts.append("updated_at = NOW()")
                    params.extend([name, publisher])
                    cur.execute(
                        f"UPDATE community_skills SET {', '.join(parts)} "
                        f"WHERE name = %s AND publisher = %s RETURNING *",
                        params,
                    )
                    row = cur.fetchone()
                conn.commit()
            return dict(row) if row else None
        except CommunityError: raise
        except Exception as exc:
            logger.error("update_skill failed: %s", exc)
            raise CommunityError("db_error", str(exc))

    def withdraw_skill(self, name: str, publisher: str) -> bool:
        """下架技能（suspended）。"""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE community_skills SET status='suspended', updated_at=NOW() "
                        "WHERE name=%s AND publisher=%s", (name, publisher),
                    )
                    affected = cur.rowcount
                conn.commit()
            if affected:
                self._emit(CommunityEvent.SKILL_SUSPENDED, skill_name=name, publisher=publisher)
            return affected > 0
        except Exception as exc:
            logger.error("withdraw_skill failed: %s", exc)
            return False

    # ─── 评价系统 ────────────────────────────────────────────────

    def add_review(self, skill_name: str, user_id: str, rating: int, comment: str = "") -> dict[str, Any]:
        """添加评价并更新评分均值。"""
        if not 1 <= rating <= 5:
            raise CommunityError("invalid_rating", "rating must be 1-5")
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """INSERT INTO skill_reviews (skill_name, user_id, rating, comment)
                           VALUES (%s,%s,%s,%s)
                           ON CONFLICT (skill_name, user_id) DO UPDATE
                             SET rating=EXCLUDED.rating, comment=EXCLUDED.comment, created_at=NOW()
                           RETURNING *""",
                        (skill_name, user_id, rating, comment),
                    )
                    review = dict(cur.fetchone())
                    cur.execute(
                        "SELECT AVG(rating)::NUMERIC(2,1) AS avg, COUNT(*) AS cnt "
                        "FROM skill_reviews WHERE skill_name=%s", (skill_name,),
                    )
                    s = cur.fetchone()
                    cur.execute(
                        "UPDATE community_skills SET rating_avg=%s, rating_count=%s, "
                        "updated_at=NOW() WHERE name=%s", (s["avg"], s["cnt"], skill_name),
                    )
                conn.commit()
            self._emit(CommunityEvent.SKILL_REVIEWED, skill_name=skill_name, user_id=user_id, rating=rating)
            return review
        except CommunityError: raise
        except psycopg2.IntegrityError:
            try: conn.rollback()
            except Exception: pass
            raise CommunityError("skill_not_found", f"skill not found: {skill_name}")
        except Exception as exc:
            logger.error("add_review failed: %s", exc)
            raise CommunityError("db_error", str(exc))

    def list_reviews(self, skill_name: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        """分页查询评价。"""
        offset = (max(1, page) - 1) * page_size
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT COUNT(*) FROM skill_reviews WHERE skill_name=%s", (skill_name,))
                    total = cur.fetchone()["count"]
                    cur.execute(
                        "SELECT * FROM skill_reviews WHERE skill_name=%s "
                        "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                        (skill_name, page_size, offset),
                    )
                    return {"reviews": [dict(r) for r in cur.fetchall()], "total": total}
        except Exception as exc:
            logger.error("list_reviews failed: %s", exc)
            return {"reviews": [], "total": 0}

    def mark_helpful(self, review_id: int, user_id: str) -> bool:
        """标记评价为有帮助。"""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE skill_reviews SET helpful_count=helpful_count+1 WHERE id=%s", (review_id,))
                    affected = cur.rowcount
                conn.commit()
            return affected > 0
        except Exception as exc:
            logger.error("mark_helpful failed: %s", exc)
            return False

    # ─── 收藏 ────────────────────────────────────────────────────

    def add_favorite(self, user_id: str, skill_name: str) -> bool:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO user_favorites (user_id,skill_name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                        (user_id, skill_name),
                    )
                conn.commit()
            return True
        except Exception as exc:
            logger.error("add_favorite failed: %s", exc)
            return False

    def remove_favorite(self, user_id: str, skill_name: str) -> bool:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM user_favorites WHERE user_id=%s AND skill_name=%s", (user_id, skill_name))
                    affected = cur.rowcount
                conn.commit()
            return affected > 0
        except Exception as exc:
            logger.error("remove_favorite failed: %s", exc)
            return False

    def list_favorites(self, user_id: str) -> list[dict[str, Any]]:
        """查询用户收藏列表。"""
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT cs.* FROM community_skills cs "
                        "INNER JOIN user_favorites uf ON uf.skill_name=cs.name "
                        "WHERE uf.user_id=%s AND cs.status='approved' ORDER BY uf.created_at DESC",
                        (user_id,),
                    )
                    return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error("list_favorites failed: %s", exc)
            return []

    # ─── 我的技能 ────────────────────────────────────────────────

    def list_my_skills(self, publisher: str) -> list[dict[str, Any]]:
        """查询用户发布的所有技能（含所有状态）。"""
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM community_skills WHERE publisher=%s ORDER BY created_at DESC",
                        (publisher,),
                    )
                    return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error("list_my_skills failed: %s", exc)
            return []

    # ─── 审核（管理员） ──────────────────────────────────────────

    def list_pending(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """分页查询待审核技能（首次待审 + 待审版本更新），先到先审。"""
        offset = (max(1, page) - 1) * page_size
        where = "status = 'pending' OR has_pending_update = TRUE"
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(f"SELECT COUNT(*) FROM community_skills WHERE {where}")
                    total = cur.fetchone()["count"]
                    cur.execute(
                        f"SELECT * FROM community_skills WHERE {where} "
                        "ORDER BY COALESCE(pending_submitted_at, created_at) ASC "
                        "LIMIT %s OFFSET %s",
                        (page_size, offset),
                    )
                    rows = [dict(r) for r in cur.fetchall()]
            return {"skills": rows, "total": total}
        except Exception as exc:
            logger.error("list_pending failed: %s", exc)
            return {"skills": [], "total": 0}

    def moderate_skill(
        self, name: str, action: str, reviewer: str, note: str = ""
    ) -> dict[str, Any]:
        """审核技能：action in ('approve','reject')，区分首发审核与版本更新复审。

        若存在待审更新（has_pending_update）：approve 将 pending_* 提升为线上
        版本，reject 丢弃 pending_* 并保留已通过版本（status 仍 approved）。
        否则为首次审核：pending → approved / rejected。
        """
        if action not in ("approve", "reject"):
            raise CommunityError("invalid_action", f"invalid action: {action}")
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT publisher, has_pending_update FROM community_skills "
                        "WHERE name = %s",
                        (name,),
                    )
                    current = cur.fetchone()
                    if not current:
                        raise CommunityError("not_found", f"community skill not found: {name}")
                    is_update = bool(current["has_pending_update"])
                    publisher = current["publisher"]

                    if action == "approve" and is_update:
                        # 将暂存产物提升为线上版本，status 保持 approved。
                        cur.execute(
                            "UPDATE community_skills SET "
                            "version = COALESCE(pending_version, version), "
                            "install_url = COALESCE(pending_install_url, install_url), "
                            "archive_hash = COALESCE(pending_archive_hash, archive_hash), "
                            "pending_version = NULL, pending_install_url = NULL, "
                            "pending_archive_hash = NULL, has_pending_update = FALSE, "
                            "pending_submitted_at = NULL, reviewed_by = %s, "
                            "reviewed_at = NOW(), review_note = %s, updated_at = NOW() "
                            "WHERE name = %s RETURNING *",
                            (reviewer, note, name),
                        )
                    elif action == "reject" and is_update:
                        # 丢弃待审更新，保留线上已通过版本（status 仍 approved）。
                        cur.execute(
                            "UPDATE community_skills SET "
                            "pending_version = NULL, pending_install_url = NULL, "
                            "pending_archive_hash = NULL, has_pending_update = FALSE, "
                            "pending_submitted_at = NULL, reviewed_by = %s, "
                            "reviewed_at = NOW(), review_note = %s, updated_at = NOW() "
                            "WHERE name = %s RETURNING *",
                            (reviewer, note, name),
                        )
                    else:
                        # 首次审核：pending → approved / rejected。
                        new_status = "approved" if action == "approve" else "rejected"
                        cur.execute(
                            "UPDATE community_skills SET status = %s, reviewed_by = %s, "
                            "reviewed_at = NOW(), review_note = %s, updated_at = NOW() "
                            "WHERE name = %s RETURNING *",
                            (new_status, reviewer, note, name),
                        )
                    row = cur.fetchone()
                conn.commit()
            event = CommunityEvent.SKILL_APPROVED if action == "approve" else CommunityEvent.SKILL_REJECTED
            self._emit(event, skill_name=name, publisher=publisher,
                       reviewer=reviewer, note=note, is_update=is_update)
            return dict(row)
        except CommunityError:
            raise
        except Exception as exc:
            logger.error("moderate_skill failed: %s", exc)
            raise CommunityError("db_error", str(exc))

    def set_featured(self, name: str, featured: bool) -> bool:
        """切换技能精选标记（仅管理员用）。"""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE community_skills SET featured=%s, updated_at=NOW() "
                        "WHERE name=%s",
                        (featured, name),
                    )
                    affected = cur.rowcount
                conn.commit()
            if affected:
                self._emit(CommunityEvent.SKILL_FEATURED, skill_name=name, featured=featured)
            return affected > 0
        except Exception as exc:
            logger.error("set_featured failed: %s", exc)
            return False
