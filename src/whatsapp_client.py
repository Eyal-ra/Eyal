"""
HTTP client for a self-hosted WhatsApp bridge (WPPConnect / whatsapp-web.js /
Green API style servers that expose a small REST surface).

The exact paths and JSON field names differ between bridges, so everything is
config driven with sensible defaults, and the parsers accept several common
aliases for every field. Run `python -m src.whatsapp_agent probe` against the
live server to see which endpoints answer and get a config block to paste.

Two things this client insists on, because the bridge talks to a real WhatsApp
account: transient network errors are retried with backoff, and outgoing
messages are paced (`send_delay_seconds`) so a batch never looks like a burst.
"""

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

import requests

DEFAULT_ENDPOINTS = {
    "chats": "/chats",
    "messages": "/chats/{chat_id}/messages",
    "send": "/send-message",
}

# Asked first, to find out WHICH bridge this is: most of them answer their name,
# version or session list on one of these.
PROBE_DISCOVERY_PATHS = [
    "/",
    "/api",
    "/health",
    "/status",
    "/ping",
    "/version",
    "/sessions",
    "/api/sessions",
    "/instance/fetchInstances",
    "/api-docs",
    "/swagger.json",
    "/openapi.json",
]

# {session} is filled in from whatsapp.session in config.yaml - WPPConnect, WAHA
# and Evolution all put the session or instance name inside the path.
PROBE_CHAT_PATHS = [
    "/chats",
    "/api/chats",
    "/all-chats",
    "/api/all-chats",
    "/chat/list",
    "/messages/chats",
    "/api/{session}/all-chats",
    "/api/{session}/chats",
    "/api/{session}/list-chats",
    "/{session}/chats",
    "/api/v1/chats",
    "/chat/findChats/{session}",
]

PROBE_MESSAGE_PATHS = [
    "/chats/{chat_id}/messages",
    "/api/chats/{chat_id}/messages",
    "/messages/{chat_id}",
    "/api/messages/{chat_id}",
    "/chat-messages",
    "/all-messages-in-chat/{chat_id}",
    "/api/{session}/chat-messages/{chat_id}",
    "/api/{session}/all-messages-in-chat/{chat_id}",
    "/api/{session}/messages/{chat_id}",
]

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_ID_KEYS = ("id", "chatId", "chat_id", "remoteJid", "jid", "_serialized")
_NAME_KEYS = ("name", "formattedTitle", "chatName", "pushname", "pushName", "contactName", "subject")
_TEXT_KEYS = ("body", "text", "message", "content", "caption", "conversation")
_TIME_KEYS = ("timestamp", "messageTimestamp", "t", "time", "date", "createdAt")
_FROM_ME_KEYS = ("fromMe", "from_me", "isFromMe", "self", "outgoing")


class WhatsAppError(RuntimeError):
    """Raised when the bridge cannot be reached or answers with an error."""


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
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        seconds = float(value)
        if seconds > 1e11:  # milliseconds
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
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
    raw: dict = field(repr=False, default_factory=dict)

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
    raw: dict = field(repr=False, default_factory=dict)


def parse_chat(item: dict) -> WhatsAppChat:
    chat_id = _as_id(_get(item, _ID_KEYS))
    is_group = bool(_get(item, ("isGroup", "is_group", "group"))) or chat_id.endswith("@g.us")
    unread = _get(item, ("unreadCount", "unread_count", "unread"))
    return WhatsAppChat(
        chat_id=chat_id,
        name=str(_get(item, _NAME_KEYS) or chat_id.split("@", 1)[0]),
        is_group=is_group,
        unread=int(unread) if isinstance(unread, (int, float)) or str(unread).isdigit() else 0,
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
    def __init__(self, config: dict, sleeper: Callable[[float], None] = time.sleep):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.endpoints = {**DEFAULT_ENDPOINTS, **(config.get("endpoints") or {})}
        self.timeout = config.get("timeout_seconds", 30)
        self.retries = config.get("retries", 3)
        self.send_delay_seconds = config.get("send_delay_seconds", 8)
        self.session_name = str(config.get("session", "default"))
        self.send_chat_field = config.get("send_chat_field", "chatId")
        self.send_text_field = config.get("send_text_field", "message")
        # Some connectors need more than chat+text in the body - WAHA, for one,
        # wants the session name in every send.
        self.send_extra = dict(config.get("send_extra") or {})
        self.sleeper = sleeper
        self._last_send_at: Optional[float] = None
        self.session = requests.Session()
        token = config.get("token")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        for header, value in (config.get("headers") or {}).items():
            self.session.headers[header] = str(value)

    # --- plumbing -------------------------------------------------------

    def _path(self, template: str, **values) -> str:
        """Fill {session} / {chat_id} placeholders; templates without them pass through."""
        try:
            return template.format(session=self.session_name, **values)
        except (KeyError, IndexError):
            return template

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """One request with backoff on connection errors and transient 5xx/429."""
        last_error = ""
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.request(method, self._url(path), timeout=self.timeout, **kwargs)
                if resp.status_code in RETRYABLE_STATUS and attempt < self.retries:
                    last_error = f"HTTP {resp.status_code}"
                else:
                    resp.raise_for_status()
                    return resp
            except requests.HTTPError as exc:
                raise WhatsAppError(f"{method} {path}: {exc}") from exc
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt >= self.retries:
                    raise WhatsAppError(f"{method} {path}: {exc}") from exc
            self.sleeper(2 ** attempt)
        raise WhatsAppError(f"{method} {path}: {last_error}")

    @staticmethod
    def _json(resp: requests.Response) -> Any:
        try:
            return resp.json()
        except ValueError as exc:
            raise WhatsAppError(f"תשובה שאינה JSON מהבריג': {resp.text[:120]!r}") from exc

    # --- reading --------------------------------------------------------

    def fetch_chats(self, limit: int = 100) -> list[WhatsAppChat]:
        resp = self._request("GET", self._path(self.endpoints["chats"]), params={"limit": limit})
        chats = [parse_chat(item) for item in unwrap_list(self._json(resp)) if isinstance(item, dict)]
        return [chat for chat in chats if chat.chat_id]

    def fetch_messages(self, chat_id: str, limit: int = 30) -> list[WhatsAppMessage]:
        template = self.endpoints["messages"]
        params: dict = {"limit": limit}
        if "{chat_id}" not in template:
            params["chatId"] = chat_id
        resp = self._request("GET", self._path(template, chat_id=chat_id), params=params)
        messages = [parse_message(item, chat_id) for item in unwrap_list(self._json(resp)) if isinstance(item, dict)]
        return sorted(messages, key=lambda m: m.sent_at or datetime.min.replace(tzinfo=timezone.utc))

    # --- writing --------------------------------------------------------

    def _pace(self) -> None:
        """Keep a human-looking gap between outgoing messages. Bridges that drive a
        real account get rate limited (or banned) when a batch goes out at once."""
        if self.send_delay_seconds <= 0:
            return
        if self._last_send_at is not None:
            target = self.send_delay_seconds * random.uniform(0.7, 1.3)
            waited = time.monotonic() - self._last_send_at
            if waited < target:
                self.sleeper(target - waited)
        self._last_send_at = time.monotonic()

    def send_message(self, chat_id: str, text: str) -> dict:
        self._pace()
        payload = {self.send_chat_field: chat_id, self.send_text_field: text}
        for key, value in self.send_extra.items():
            payload[key] = self._path(str(value)) if isinstance(value, str) else value
        resp = self._request("POST", self._path(self.endpoints["send"]), json=payload)
        try:
            return resp.json()
        except ValueError:
            return {"status": resp.status_code}

    # --- setup helper ---------------------------------------------------

    def probe(self) -> dict:
        """Try the common paths and report what the server answers, so config.yaml
        can be filled in against a real response instead of by guesswork.

        Starts with discovery paths, because when no chat path answers the useful
        question is no longer "which path" but "which bridge is this at all" -
        and the raw body of / or /health usually says so.
        """
        report: dict = {"discovery": [], "chats": [], "messages": [], "sample_chat_id": None, "suggested": {}}

        for path in PROBE_DISCOVERY_PATHS:
            entry = self._probe_path(self._path(path), want_body=True)
            entry.pop("first_id", None)
            if entry.get("status") not in (404, None) or entry.get("body"):
                report["discovery"].append(entry)

        for path in dict.fromkeys([self.endpoints["chats"], *PROBE_CHAT_PATHS]):
            entry = self._probe_path(self._path(path))
            report["chats"].append(entry)
            if entry.get("items") and report["sample_chat_id"] is None:
                report["sample_chat_id"] = entry.pop("first_id", None)
                if report["sample_chat_id"]:
                    report["suggested"]["chats"] = path
            entry.pop("first_id", None)

        chat_id = report["sample_chat_id"]
        if chat_id:
            for template in dict.fromkeys([self.endpoints["messages"], *PROBE_MESSAGE_PATHS]):
                path = self._path(template, chat_id=chat_id)
                entry = self._probe_path(path, extra_params=None if "{chat_id}" in template else {"chatId": chat_id})
                entry["template"] = template
                entry.pop("first_id", None)
                report["messages"].append(entry)
                if entry.get("items") and "messages" not in report["suggested"]:
                    report["suggested"]["messages"] = template
        return report

    def _probe_path(self, path: str, extra_params: Optional[dict] = None, want_body: bool = False) -> dict:
        entry: dict = {"path": path}
        params = {"limit": 1, **(extra_params or {})}
        try:
            resp = self.session.get(self._url(path), params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            entry["error"] = str(exc)
            return entry
        entry["status"] = resp.status_code
        if want_body:
            body_text = " ".join(resp.text.split())
            if body_text and body_text not in ('"not found"', "not found", "{}"):
                entry["body"] = body_text[:200]
        try:
            body = resp.json()
        except ValueError:
            entry["note"] = f"תשובה שאינה JSON: {resp.text[:80]!r}"
            return entry
        items = unwrap_list(body)
        entry["items"] = len(items)
        if items and isinstance(items[0], dict):
            entry["sample_keys"] = sorted(items[0].keys())[:20]
            entry["first_id"] = _as_id(_get(items[0], _ID_KEYS)) or None
        return entry
