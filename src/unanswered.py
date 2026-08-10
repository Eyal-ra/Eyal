"""
Decide which WhatsApp conversations are still waiting for a reply from me.

A chat is "pending" when its newest inbound message has no outbound message
after it. The decision itself is pure (it takes an already-normalized message
list) so it can be tested without touching the bridge.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .whatsapp_client import WhatsAppChat, WhatsAppClient, WhatsAppError, WhatsAppMessage


@dataclass
class PendingChat:
    chat_id: str
    display_name: str
    phone: str
    last_inbound_at: datetime
    last_inbound_text: str
    unread: int = 0
    inbound_streak: int = 1

    def waiting_hours(self, now: datetime) -> float:
        return max(0.0, (now - self.last_inbound_at).total_seconds() / 3600.0)

    def waiting_label(self, now: datetime) -> str:
        hours = self.waiting_hours(now)
        if hours < 1:
            return f"{int(hours * 60)} דק'"
        if hours < 24:
            return f"{hours:.1f} שע'"
        return f"{hours / 24:.1f} ימים"

    def preview(self, width: int = 70) -> str:
        text = " ".join(self.last_inbound_text.split())
        if not text:
            return "(ללא טקסט - מדיה/הקלטה)"
        return text if len(text) <= width else text[: width - 1] + "…"

    def to_dict(self, now: datetime) -> dict:
        return {
            "chat_id": self.chat_id,
            "name": self.display_name,
            "phone": self.phone,
            "waiting_hours": round(self.waiting_hours(now), 2),
            "last_inbound_at": self.last_inbound_at.isoformat(),
            "last_message": self.last_inbound_text,
            "unread": self.unread,
            "inbound_streak": self.inbound_streak,
        }


@dataclass
class ScanResult:
    pending: list[PendingChat] = field(default_factory=list)
    scanned: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def last_inbound_without_reply(messages: list[WhatsAppMessage]) -> Optional[WhatsAppMessage]:
    """Newest inbound message, unless I already answered at or after its timestamp."""
    inbound = [m for m in messages if not m.from_me and m.sent_at]
    if not inbound:
        return None
    latest_inbound = max(inbound, key=lambda m: m.sent_at)
    for message in messages:
        if message.from_me and message.sent_at and message.sent_at >= latest_inbound.sent_at:
            return None
    return latest_inbound


def count_trailing_inbound(messages: list[WhatsAppMessage]) -> int:
    """How many messages in a row they sent without an answer - a rough urgency hint."""
    streak = 0
    for message in sorted(messages, key=lambda m: m.sent_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        if message.from_me:
            break
        streak += 1
    return streak


def evaluate_chat(
    chat: WhatsAppChat,
    messages: list[WhatsAppMessage],
    now: datetime,
    min_waiting_minutes: int = 0,
    max_age_days: int = 14,
) -> Optional[PendingChat]:
    pending = last_inbound_without_reply(messages)
    if pending is None:
        return None
    waiting_minutes = (now - pending.sent_at).total_seconds() / 60.0
    if waiting_minutes < min_waiting_minutes or waiting_minutes > max_age_days * 24 * 60:
        return None
    return PendingChat(
        chat_id=chat.chat_id,
        display_name=chat.name,
        phone=chat.phone,
        last_inbound_at=pending.sent_at,
        last_inbound_text=pending.text,
        unread=chat.unread,
        inbound_streak=count_trailing_inbound(messages),
    )


def scan_pending(
    client: WhatsAppClient,
    cfg: dict,
    now: Optional[datetime] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> ScanResult:
    """Walk the recent chats and collect the ones waiting for my reply.

    A chat that fails to load does not abort the scan - it is reported at the end,
    so one broken conversation never hides the rest of the list.
    """
    now = now or datetime.now(timezone.utc)
    scan = cfg.get("scan", {})
    include_groups = scan.get("include_groups", False)
    skip_ids = set(scan.get("skip_chat_ids") or [])

    result = ScanResult()
    chats = client.fetch_chats(limit=scan.get("chat_limit", 50))
    candidates = [
        chat for chat in chats
        if chat.chat_id not in skip_ids and (include_groups or not chat.is_group)
    ]

    for index, chat in enumerate(candidates, start=1):
        if on_progress:
            on_progress(index, len(candidates))
        try:
            messages = client.fetch_messages(chat.chat_id, limit=scan.get("message_limit", 30))
        except WhatsAppError as exc:
            result.errors.append((chat.name or chat.chat_id, str(exc)))
            continue
        result.scanned += 1
        found = evaluate_chat(
            chat,
            messages,
            now,
            min_waiting_minutes=scan.get("min_waiting_minutes", 0),
            max_age_days=scan.get("max_age_days", 14),
        )
        if found:
            result.pending.append(found)

    result.pending.sort(key=lambda p: p.last_inbound_at)
    return result


def find_pending_chats(client: WhatsAppClient, cfg: dict, now: Optional[datetime] = None) -> list[PendingChat]:
    return scan_pending(client, cfg, now).pending
