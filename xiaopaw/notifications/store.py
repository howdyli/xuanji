"""NotificationStore + NotificationService —— 站内拉取式通知。

NotificationStore 是纯 PostgreSQL CRUD（psycopg2，连接模式参照
CommunityRegistry）；所有方法在 DB 异常时降级（记 warning + 返回空/False/0），
不向上抛出，与现有 registry 风格一致。

NotificationService 是 EventBus 的同步订阅者（与 ActivityRecorder.handle_event
同模式），把技能审核事件（SKILL_APPROVED / SKILL_REJECTED）落地为发布者可拉取的
一条通知。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2
import psycopg2.extras

from xiaopaw.event_bus import CommunityEvent, EventPayload

logger = logging.getLogger(__name__)


class NotificationStore:
    """通知持久化：per-user 站内通知的增查改。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        return psycopg2.connect(self._dsn)

    def create(
        self,
        recipient: str,
        type: str,
        title: str,
        body: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """新建一条通知，返回落地行；失败返回 None。"""
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "INSERT INTO notifications (recipient, type, title, body, payload) "
                        "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING *",
                        (recipient, type, title, body, json.dumps(payload or {})),
                    )
                    row = cur.fetchone()
                conn.commit()
            return dict(row) if row else None
        except Exception as exc:
            logger.warning("NotificationStore.create failed: %s", exc)
            return None

    def list(
        self,
        recipient: str,
        unread_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """分页查询某用户的通知，按 created_at DESC。"""
        offset = (max(1, page) - 1) * page_size
        where = "recipient = %s"
        params: list[Any] = [recipient]
        if unread_only:
            where += " AND read = FALSE"
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(f"SELECT COUNT(*) FROM notifications WHERE {where}", params)
                    total = cur.fetchone()["count"]
                    cur.execute(
                        f"SELECT * FROM notifications WHERE {where} "
                        "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                        (*params, page_size, offset),
                    )
                    rows = [dict(r) for r in cur.fetchall()]
            return {"notifications": rows, "total": total}
        except Exception as exc:
            logger.warning("NotificationStore.list failed: %s", exc)
            return {"notifications": [], "total": 0}

    def unread_count(self, recipient: str) -> int:
        """某用户的未读通知数。"""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM notifications "
                        "WHERE recipient = %s AND read = FALSE",
                        (recipient,),
                    )
                    return int(cur.fetchone()[0])
        except Exception as exc:
            logger.warning("NotificationStore.unread_count failed: %s", exc)
            return 0

    def mark_read(self, notification_id: int, recipient: str) -> bool:
        """标记单条已读；带 recipient 条件防越权改他人通知。"""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE notifications SET read = TRUE "
                        "WHERE id = %s AND recipient = %s",
                        (notification_id, recipient),
                    )
                    affected = cur.rowcount
                conn.commit()
            return affected > 0
        except Exception as exc:
            logger.warning("NotificationStore.mark_read failed: %s", exc)
            return False

    def mark_all_read(self, recipient: str) -> int:
        """标记某用户全部未读为已读，返回更新条数。"""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE notifications SET read = TRUE "
                        "WHERE recipient = %s AND read = FALSE",
                        (recipient,),
                    )
                    affected = cur.rowcount
                conn.commit()
            return affected
        except Exception as exc:
            logger.warning("NotificationStore.mark_all_read failed: %s", exc)
            return 0


# 事件 type → (通知 type, 标题动词)
_MODERATION_EVENTS = {
    CommunityEvent.SKILL_APPROVED.value: ("skill_approved", "通过"),
    CommunityEvent.SKILL_REJECTED.value: ("skill_rejected", "驳回"),
}


class NotificationService:
    """EventBus 同步订阅者：把技能审核结果落地为发布者通知。"""

    def __init__(self, store: NotificationStore) -> None:
        self._store = store

    def handle_event(self, payload: EventPayload) -> None:
        """仅处理 SKILL_APPROVED / SKILL_REJECTED，其他忽略。"""
        event_key = getattr(payload.event, "value", str(payload.event))
        mapping = _MODERATION_EVENTS.get(event_key)
        if not mapping:
            return

        notif_type, verb = mapping
        data = payload.data or {}
        publisher = data.get("publisher")
        if not publisher:
            # 缺发布者无从投递，忽略（不落地）。
            return

        skill_name = data.get("skill_name", "")
        note = data.get("note", "")
        is_update = bool(data.get("is_update"))
        scope = "版本更新" if is_update else "技能"
        title = f"你的{scope}「{skill_name}」审核{verb}"
        if notif_type == "skill_rejected" and note:
            body = f"审核意见：{note}"
        else:
            body = ""

        try:
            self._store.create(
                recipient=publisher,
                type=notif_type,
                title=title,
                body=body,
                payload={
                    "skill_name": skill_name,
                    "reviewer": data.get("reviewer", ""),
                    "note": note,
                    "is_update": is_update,
                },
            )
        except Exception as exc:
            # 吞掉异常，不影响 EventBus 其他订阅者。
            logger.warning("NotificationService.handle_event failed: %s", exc)
