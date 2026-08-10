"""
HTTP client for a self-hosted WhatsApp bridge (WPPConnect / whatsapp-web.js /
Green API style servers that expose a small REST surface).

The exact paths and JSON field names differ between bridges, so everything is
config driven with sensible defaults, and the parsers accept several common
aliases for every field. Run `python -m src.whatsapp_agent probe` against the
live server to see which endpoints answer and what the payloads look like.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import requests

DEFAULT_ENDPOINTS = {
    "chats": "/chats",
    "messages": "/chats/{chat_id}/messages",
    "send": "/send-message",
}

PROBE_CHAT_PATHS = [
    "/chats",
    "/api/chats",
    "/all-chats",
    "/api/all-chats",
    "/chat/list",
    "/messages/chats",
]

_ID_KEYS = ("id", "chatId", "chat_id", "remoteJid", "jid", "_serialized")
_NAME_KEYS = ("name", "formattedTitle", "chatName", "pushname", "pushName", "contactName", "subject")
_TEXT_KEYS = ("body", "text", "message", "content", "caption", "conversation")
_TIME_KEYS = ("timestamp", "messageTimestamp", "t", "time", "date", "createdAt")
_FROM_ME_KEYS = ("fromMe", "from_me", "isFromMe", "self", "outgoing")


def _get(source: Any, keys: Iterable[str]) -> Any:
    """Return the first present, non-empty value among `keys`, digging into nested dicts."""
    if not isinstance(source, dict):
        return None
    for key in keys:
        if key in source and source[key] not in (None, "", {}, []):
            return source[key]
    for nested_key in ("key", "id", "chat", "contact", "message", "data"):
        nested = source.get(nested_key)
        if isinstance(nested, dict):
            found = _get(nested, keys)
            if found is not None:
                return found
    return None


def _as_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(_get(value, _ID_KEYS) or "")
    return str(value or "")


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        # Baileys-style: {"conversation": "..."} / {"extendedTextMessage": {"text": "..."}}
        for key in ("conversation", "text", "caption", "body"):
            if isinstance(value.get(key), str):
                return value[key].strip()
        for nested in value.values():
            if isinstance(nested, dict):
                found = _as_text(nested)
                if found:
                    return found
    return ""


def _as_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        seconds = float(value)
        if seconds > 1e11:  # milliseconds
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


@dataclass
class WhatsAppChat:
    chat_id: str
    name: str
    is_group: bool
    unread: int
    raw: dict

    @property
    def phone(self) -> str:
        return self.chat_id.split("@", 1)[0]


@dataclass
class WhatsAppMessage:
    message_id: str
    chat_id: str
    from_me: bool
    sent_at: Optional[datetime]
    text: str
    raw: dict


def parse_chat(item: dict) -> WhatsAppChat:
    chat_id = _as_id(_get(item, _ID_KEYS))
    is_group = bool(_get(item, ("isGroup", "is_group", "group"))) or chat_id.endswith("@g.us")
    unread = _get(item, ("unreadCount", "unread_count", "unread"))
    return WhatsAppChat(
        chat_id=chat_id,
        name=str(_get(item, _NAME_KEYS) or chat_id.split("@", 1)[0]),
        is_group=is_group,
        unread=int(unread) if isinstance(unread, (int, float, str)) and str(unread).isdigit() else 0,
        raw=item,
    )


def parse_message(item: dict, fallback_chat_id: str = "") -> WhatsAppMessage:
    return WhatsAppMessage(
        message_id=_as_id(_get(item, ("id", "messageId", "message_id", "_serialized"))),
        chat_id=_as_id(_get(item, ("chatId", "chat_id", "remoteJid", "from"))) or fallback_chat_id,
        from_me=bool(_get(item, _FROM_ME_KEYS)),
        sent_at=_as_datetime(_get(item, _TIME_KEYS)),
        text=_as_text(_get(item, _TEXT_KEYS)),
        raw=item,
    )


def unwrap_list(payload: Any) -> list:
    """Bridges wrap collections differently: [...] / {"response": [...]} / {"data": {"chats": [...]}}."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("response", "data", "result", "chats", "messages", "items", "content"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return nested
            if isinstance(nested, dict):
                found = unwrap_list(nested)
                if found:
                    return found
    return []


class WhatsAppClient:
    def __init__(self, config: dict):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.endpoints = {**DEFAULT_ENDPOINTS, **(config.get("endpoints") or {})}
        self.timeout = config.get("timeout_seconds", 30)
        self.send_chat_field = config.get("send_chat_field", "chatId")
        self.send_text_field = config.get("send_text_field", "message")
        self.session = requests.Session()
        token = config.get("token")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        for header, value in (config.get("headers") or {}).items():
            self.session.headers[header] = str(value)

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def fetch_chats(self, limit: int = 100) -> list[WhatsAppChat]:
        resp = self.session.get(self._url(self.endpoints["chats"]), params={"limit": limit}, timeout=self.timeout)
        resp.raise_for_status()
        return [parse_chat(item) for item in unwrap_list(resp.json()) if isinstance(item, dict)]

    def fetch_messages(self, chat_id: str, limit: int = 30) -> list[WhatsAppMessage]:
        path = self.endpoints["messages"].format(chat_id=chat_id)
        params = {"limit": limit}
        if "{chat_id}" not in self.endpoints["messages"]:
            params["chatId"] = chat_id
        resp = self.session.get(self._url(path), params=params, timeout=self.timeout)
        resp.raise_for_status()
        messages = [parse_message(item, chat_id) for item in unwrap_list(resp.json()) if isinstance(item, dict)]
        return sorted(messages, key=lambda m: m.sent_at or datetime.min.replace(tzinfo=timezone.utc))

    def send_message(self, chat_id: str, text: str) -> dict:
        payload = {self.send_chat_field: chat_id, self.send_text_field: text}
        resp = self.session.post(self._url(self.endpoints["send"]), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {"status": resp.status_code}

    def probe(self) -> list[dict]:
        """Try the common chat-list paths and report what the server answers, so the
        endpoints/field names in config.yaml can be filled in against a real response."""
        results = []
        for path in dict.fromkeys([self.endpoints["chats"], *PROBE_CHAT_PATHS]):
            entry: dict = {"path": path}
            try:
                resp = self.session.get(self._url(path), params={"limit": 1}, timeout=self.timeout)
                entry["status"] = resp.status_code
                try:
                    body = resp.json()
                except ValueError:
                    entry["note"] = f"תשובה שאינה JSON: {resp.text[:120]!r}"
                    results.append(entry)
                    continue
                items = unwrap_list(body)
                entry["items"] = len(items)
                if items and isinstance(items[0], dict):
                    entry["sample_keys"] = sorted(items[0].keys())[:20]
            except requests.RequestException as exc:
                entry["error"] = str(exc)
            results.append(entry)
        return results
