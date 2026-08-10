"""Remembers which scheduling proposals were already sent, so the agent does not
nag the same customer twice and can match their answer back to the offered slots."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class ProposalStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, dict] = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded = {}
            if isinstance(loaded, dict):
                self._items = loaded

    def get(self, chat_id: str) -> Optional[dict]:
        return self._items.get(chat_id)

    def items(self) -> list[tuple[str, dict]]:
        return sorted(self._items.items(), key=lambda item: item[1].get("sent_at", ""))

    def awaiting_answer(self) -> list[tuple[str, dict]]:
        return [(chat_id, record) for chat_id, record in self.items() if not record.get("answer")]

    def is_booked(self, chat_id: str) -> bool:
        """True once the customer picked one of the offered slots."""
        answer = (self._items.get(chat_id) or {}).get("answer") or {}
        return answer.get("choice") in (1, 2)

    def sent_recently(self, chat_id: str, within_hours: int, now: Optional[datetime] = None) -> bool:
        record = self._items.get(chat_id)
        if not record or not record.get("sent_at"):
            return False
        now = now or datetime.now(timezone.utc)
        return (now - _aware(record["sent_at"])).total_seconds() < within_hours * 3600

    def should_skip(self, chat_id: str, resend_after_hours: int, now: Optional[datetime] = None) -> Optional[str]:
        """Reason to skip this chat when sending proposals, or None to go ahead."""
        if self.is_booked(chat_id):
            return "כבר נקבעה פגישה"
        if self.sent_recently(chat_id, resend_after_hours, now):
            return "כבר נשלחה הצעה לאחרונה"
        return None

    def record(self, chat_id: str, display_name: str, slots_iso: list[str], sent_at: datetime) -> None:
        self._items[chat_id] = {
            "display_name": display_name,
            "slots": slots_iso,
            "sent_at": sent_at.isoformat(),
            "answer": None,
        }
        self._flush()

    def record_answer(self, chat_id: str, kind: str, choice: Optional[int], text: str,
                      answered_at: Optional[datetime] = None) -> None:
        record = self._items.get(chat_id)
        if record is None:
            return
        record["answer"] = {
            "kind": kind,
            "choice": choice,
            "text": text,
            "at": (answered_at or datetime.now(timezone.utc)).isoformat(),
        }
        self._flush()

    def mark_confirmation_sent(self, chat_id: str) -> None:
        record = self._items.get(chat_id)
        if record is not None:
            record["confirmation_sent"] = True
            self._flush()

    def booked_for(self, day_iso_prefix: str) -> list[tuple[str, dict]]:
        """Everything booked on a given date, e.g. day_iso_prefix='2026-08-11'."""
        booked = []
        for chat_id, record in self.items():
            answer = record.get("answer") or {}
            choice = answer.get("choice")
            if choice in (1, 2) and record.get("slots"):
                slot_iso = record["slots"][choice - 1]
                if slot_iso.startswith(day_iso_prefix):
                    booked.append((chat_id, record))
        return booked

    def _flush(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
