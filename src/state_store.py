import json
from pathlib import Path


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        if self.path.exists():
            self._seen = set(json.loads(self.path.read_text(encoding="utf-8")))

    def has_seen(self, submission_id: str) -> bool:
        return submission_id in self._seen

    def mark_seen(self, submission_id: str) -> None:
        self._seen.add(submission_id)
        self.path.write_text(
            json.dumps(sorted(self._seen), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
