"""Thin Microsoft Graph client for reading the Sent Items folder.

Only the bit the invoice router needs: iterate sent messages with their
recipients and plain-text body. Authentication is intentionally minimal —
either a pre-acquired delegated access token, or an app-only
client-credentials token for a specified mailbox.
"""

import time

import requests

from src.invoice_routing import SentMessage

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


class GraphAuthError(RuntimeError):
    pass


def _acquire_app_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    resp = requests.post(
        _TOKEN_URL.format(tenant=tenant_id),
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise GraphAuthError(f"token request failed: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


class GraphClient:
    """Minimal Graph reader scoped to one mailbox's Sent Items."""

    def __init__(self, access_token: str, mailbox: str | None = None):
        self.access_token = access_token
        # Delegated tokens act on /me; app-only tokens must name the user.
        self.base = f"{GRAPH_ROOT}/users/{mailbox}" if mailbox else f"{GRAPH_ROOT}/me"

    @classmethod
    def from_config(cls, cfg: dict) -> "GraphClient":
        graph = cfg.get("graph", {})
        mailbox = graph.get("mailbox")
        token = graph.get("access_token")
        if token:
            return cls(token, mailbox)
        token = _acquire_app_token(
            graph["tenant_id"], graph["client_id"], graph["client_secret"]
        )
        if not mailbox:
            raise GraphAuthError("app-only auth requires graph.mailbox in config")
        return cls(token, mailbox)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            # Ask Graph for a plain-text body so "לכבוד:" is easy to parse.
            "Prefer": 'outlook.body-content-type="text"',
        }

    def iter_sent_messages(self, limit: int = 500, since: str | None = None):
        """Yield up to *limit* SentMessage records, newest first.

        *since* is an optional ISO-8601 timestamp ("2026-01-01T00:00:00Z").
        """
        params = {
            "$select": "subject,body,toRecipients,ccRecipients,bccRecipients,sentDateTime",
            "$orderby": "sentDateTime desc",
            "$top": "50",
        }
        if since:
            params["$filter"] = f"sentDateTime ge {since}"
        url = f"{self.base}/mailFolders/SentItems/messages"
        fetched = 0

        while url and fetched < limit:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=60)
            if resp.status_code == 429:  # throttled
                time.sleep(int(resp.headers.get("Retry-After", "5")))
                continue
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("value", []):
                yield _to_sent_message(item)
                fetched += 1
                if fetched >= limit:
                    break
            url = payload.get("@odata.nextLink")
            params = None  # nextLink already encodes the query


def _flatten_recipients(item: dict) -> list[str]:
    out: list[str] = []
    for key in ("toRecipients", "ccRecipients", "bccRecipients"):
        for r in item.get(key) or []:
            addr = (r.get("emailAddress") or {}).get("address")
            if addr:
                out.append(addr)
    return out


def _to_sent_message(item: dict) -> SentMessage:
    return SentMessage(
        subject=item.get("subject") or "",
        body=(item.get("body") or {}).get("content") or "",
        recipients=_flatten_recipients(item),
    )
