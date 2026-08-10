"""Remembers which scheduling proposals were already sent, so the agent does not
nag the same customer twice and can match their answer back to the offered slots."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ProposalStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, dict] = {}
        if self.path.exists():
            self._items = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, chat_id: str) -> Optional[dict]:
        return self._items.get(chat_id)

    def items(self) -> list[tuple[str, dict]]:
        return sorted(self._items.items(), key=lambda item: item[1].get("sent_at", ""))

    def sent_recently(self, chat_id: str, within_hours: int, now: Optional[datetime] = None) -> bool:
        record = self._items.get(chat_id)
        if not record or not record.get("sent_at"):
            return False
        now = now or datetime.now(timezone.utc)
        sent_at = datetime.fromisoformat(record["sent_at"])
        if not sent_at.tzinfo:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        return (now - sent_at).total_seconds() < within_hours * 3600

    def record(self, chat_id: str, display_name: str, slots_iso: list[str], sent_at: datetime) -> None:
        self._items[chat_id] = {
            "display_name": display_name,
            "slots": slots_iso,
            "sent_at": sent_at.isoformat(),
            "answer": None,
        }
        self._flush()

    def record_answer(self, chat_id: str, choice: Optional[int], text: str) -> None:
        record = self._items.get(chat_id)
        if record is None:
            return
        record["answer"] = {"choice": choice, "text": text}
        self._flush()

    def _flush(self) -> None:
        self.path.write_text(
            json.dumps(self._items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
