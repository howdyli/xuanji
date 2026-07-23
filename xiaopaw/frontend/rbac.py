"""RBAC role resolution for the shared Runner.

The Runner's ``role_resolver`` maps an inbound message to a role string that
``permission_gate`` consumes (role overlay only *tightens*, never loosens).
This module keeps that policy in one testable place instead of a closure
buried in ``main.py``.

Role mapping
------------
- platform administrators  -> ``"admin"`` (no tightening unless configured)
- authenticated web users  -> ``"member"``
- feishu open_ids / cron / anonymous / unknown -> ``""`` (no role)

Only frontend-originated messages carry a *username* in ``sender_id``; other
sources resolve to ``""`` so the gate behaves exactly as before unless roles
are configured in ``hooks.yaml``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xiaopaw.frontend.auth import UserAuth

# Sender ids that are never real usernames (system actors / unauthenticated).
_NON_USER_SENDERS = frozenset({"", "cron", "anonymous"})


def resolve_rbac_role(user_auth: "UserAuth", sender_id: str) -> str:
    """Resolve the RBAC role for an inbound ``sender_id``.

    Never raises: any lookup failure degrades to ``""`` (no role), keeping the
    turn unblocked and the permission gate at its baseline behaviour.
    """
    username = (sender_id or "").strip()
    if username in _NON_USER_SENDERS:
        return ""
    try:
        user = user_auth.get_user_by_username(username)
    except Exception:
        return ""
    if not user:
        return ""
    return "admin" if user.get("is_admin") else "member"
