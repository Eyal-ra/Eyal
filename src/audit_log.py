"""Append-only record of every message the agent sent, so there is always an
answer to "what exactly did it write to that customer, and when"."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AuditLog:
    def __init__(self, path: Optional[str]):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, action: str, chat_id: str, display_name: str, text: str = "", **extra) -> None:
        if not self.path:
            return
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "chat_id": chat_id,
            "name": display_name,
            "text": text,
            **extra,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
