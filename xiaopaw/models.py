"""Core data models for XiaoPaw v2."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Attachment:
    msg_type: str  # "image" | "file"
    file_key: str
    file_name: str


@dataclass(frozen=True)
class InboundMessage:
    routing_key: str  # "p2p:ou_xxx" | "group:oc_xxx" | "thread:oc_xxx:ot_xxx"
    content: str
    msg_id: str
    root_id: str = ""
    sender_id: str = ""
    ts: int = 0
    is_cron: bool = False
    attachment: Attachment | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    # Expert context injected out-of-band: the prompt is prepended only when
    # feeding the agent, never written into ``content`` (keeps persisted
    # messages and session titles free of the system prompt).
    expert_prompt: str = ""
    expert_name: str = ""
    # Per-message skill hints (transient): names the user @-mentioned for this
    # message only. Injected as an instruction line when feeding the agent;
    # enforcement stays with SkillLoaderTool's enabled_skills whitelist.
    skill_hints: list[str] = field(default_factory=list)


class SenderProtocol(Protocol):
    async def send(self, routing_key: str, content: str) -> str: ...
    async def send_thinking(self, routing_key: str, text: str = "...") -> str | None: ...
    async def update_card(self, card_msg_id: str, content: str) -> None: ...
    async def send_text(self, routing_key: str, text: str) -> None: ...
