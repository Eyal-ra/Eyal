"""
Decide which WhatsApp conversations are still waiting for a reply from me.

A chat is "pending" when its newest inbound message has no outbound message
after it. The logic is kept pure (it takes an already-normalized message list)
so it can be tested without touching the bridge.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .whatsapp_client import WhatsAppChat, WhatsAppClient, WhatsAppMessage


@dataclass
class PendingChat:
    chat_id: str
    display_name: str
    phone: str
    last_inbound_at: datetime
    last_inbound_text: str
    unread: int

    def waiting_hours(self, now: datetime) -> float:
        return max(0.0, (now - self.last_inbound_at).total_seconds() / 3600.0)

    def waiting_label(self, now: datetime) -> str:
        hours = self.waiting_hours(now)
        if hours < 1:
            return f"{int(hours * 60)} דק'"
        if hours < 24:
            return f"{hours:.1f} שע'"
        return f"{hours / 24:.1f} ימים"


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
    )


def find_pending_chats(client: WhatsAppClient, cfg: dict, now: Optional[datetime] = None) -> list[PendingChat]:
    now = now or datetime.now(timezone.utc)
    scan = cfg.get("scan", {})
    include_groups = scan.get("include_groups", False)
    skip_ids = set(scan.get("skip_chat_ids", []) or [])

    pending: list[PendingChat] = []
    for chat in client.fetch_chats(limit=scan.get("chat_limit", 50)):
        if not chat.chat_id or chat.chat_id in skip_ids:
            continue
        if chat.is_group and not include_groups:
            continue
        messages = client.fetch_messages(chat.chat_id, limit=scan.get("message_limit", 30))
        found = evaluate_chat(
            chat,
            messages,
            now,
            min_waiting_minutes=scan.get("min_waiting_minutes", 0),
            max_age_days=scan.get("max_age_days", 14),
        )
        if found:
            pending.append(found)

    pending.sort(key=lambda p: p.last_inbound_at)
    return pending
