from dataclasses import dataclass
from typing import Iterator
import requests


@dataclass
class CustomerSubmission:
    submission_id: str
    created_at: str
    full_name: str
    phone: str
    id_number: str
    raw: dict


class JotformClient:
    def __init__(self, api_key: str, form_id: str, field_map: dict, base_url: str = "https://api.jotform.com"):
        self.api_key = api_key
        self.form_id = form_id
        self.field_map = field_map
        self.base_url = base_url.rstrip("/")

    def fetch_submissions(self, limit: int = 100) -> Iterator[CustomerSubmission]:
        url = f"{self.base_url}/form/{self.form_id}/submissions"
        params = {"apiKey": self.api_key, "limit": limit, "orderby": "created_at"}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        for item in resp.json().get("content", []):
            yield self._parse(item)

    def _parse(self, item: dict) -> CustomerSubmission:
        answers = item.get("answers", {})
        return CustomerSubmission(
            submission_id=item["id"],
            created_at=item.get("created_at", ""),
            full_name=self._extract(answers, self.field_map["full_name"]),
            phone=self._extract(answers, self.field_map["phone"]),
            id_number=self._extract(answers, self.field_map["id_number"]),
            raw=item,
        )

    @staticmethod
    def _extract(answers: dict, qkey: str) -> str:
        for entry in answers.values():
            if entry.get("name") == qkey or entry.get("text") == qkey:
                ans = entry.get("answer", "")
                if isinstance(ans, dict):
                    return " ".join(str(v) for v in ans.values() if v).strip()
                return str(ans).strip()
        return ""
