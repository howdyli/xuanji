"""Unit tests for NotificationService.handle_event (pure logic, no PG)."""

from __future__ import annotations

from unittest.mock import MagicMock

from xiaopaw.event_bus import AgentEvent, CommunityEvent, EventPayload
from xiaopaw.notifications.store import NotificationService


def _service():
    store = MagicMock()
    return NotificationService(store), store


def test_approved_creates_notification_for_publisher():
    svc, store = _service()
    svc.handle_event(EventPayload(
        event=CommunityEvent.SKILL_APPROVED,
        data={"skill_name": "pdf", "publisher": "alice",
              "reviewer": "admin", "note": "", "is_update": False},
    ))
    store.create.assert_called_once()
    kwargs = store.create.call_args.kwargs
    assert kwargs["recipient"] == "alice"
    assert kwargs["type"] == "skill_approved"
    assert "pdf" in kwargs["title"]
    assert kwargs["payload"]["is_update"] is False


def test_rejected_carries_note_and_is_update():
    svc, store = _service()
    svc.handle_event(EventPayload(
        event=CommunityEvent.SKILL_REJECTED,
        data={"skill_name": "docx", "publisher": "bob",
              "reviewer": "admin", "note": "unsafe", "is_update": True},
    ))
    store.create.assert_called_once()
    kwargs = store.create.call_args.kwargs
    assert kwargs["recipient"] == "bob"
    assert kwargs["type"] == "skill_rejected"
    assert "版本更新" in kwargs["title"]
    assert "unsafe" in kwargs["body"]
    assert kwargs["payload"]["note"] == "unsafe"
    assert kwargs["payload"]["is_update"] is True


def test_missing_publisher_is_ignored():
    svc, store = _service()
    svc.handle_event(EventPayload(
        event=CommunityEvent.SKILL_APPROVED,
        data={"skill_name": "pdf", "note": ""},
    ))
    store.create.assert_not_called()


def test_non_moderation_events_ignored():
    svc, store = _service()
    # A different community event is ignored.
    svc.handle_event(EventPayload(
        event=CommunityEvent.SKILL_INSTALLED,
        data={"skill_name": "pdf", "publisher": "alice"},
    ))
    # An unrelated agent event is ignored.
    svc.handle_event(EventPayload(
        event=AgentEvent.AGENT_COMPLETE,
        data={"publisher": "alice"},
    ))
    store.create.assert_not_called()


def test_store_exception_is_swallowed():
    svc, store = _service()
    store.create.side_effect = RuntimeError("db down")
    # Must not raise — EventBus siblings should be unaffected.
    svc.handle_event(EventPayload(
        event=CommunityEvent.SKILL_APPROVED,
        data={"skill_name": "pdf", "publisher": "alice"},
    ))
    store.create.assert_called_once()
