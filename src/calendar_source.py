"""
Where the agent learns which hours are already taken.

Providers, chosen by `scheduling.calendar.provider` in config.yaml:

  none     - no calendar; every configured option time counts as free
  file     - a local JSON file of busy blocks (no credentials needed)
  outlook  - the Outlook desktop app on this machine, over COM
  graph    - Microsoft 365 over Microsoft Graph
  google   - Google Calendar free/busy

Every provider's libraries are imported lazily, so the agent runs without them
installed as long as that provider is not selected.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

Interval = tuple[datetime, datetime]

READ_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
WRITE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

INSTALL_HINT = (
    "חסרות ספריות Google. התקן: pip install -r requirements-google.txt"
)


class CalendarError(RuntimeError):
    """Raised when the calendar cannot be read or written."""


# --- file provider ------------------------------------------------------


def load_busy_intervals(busy_file: Optional[str], tz: ZoneInfo) -> list[Interval]:
    """Read busy blocks from a local JSON file: [{"start": ISO, "end": ISO}, ...]."""
    if not busy_file:
        return []
    path = Path(busy_file)
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    intervals: list[Interval] = []
    for entry in entries if isinstance(entries, list) else []:
        try:
            start = datetime.fromisoformat(entry["start"])
            end = datetime.fromisoformat(entry["end"])
        except (KeyError, TypeError, ValueError):
            continue
        intervals.append((
            start if start.tzinfo else start.replace(tzinfo=tz),
            end if end.tzinfo else end.replace(tzinfo=tz),
        ))
    return intervals


# --- google provider ----------------------------------------------------


class GoogleCalendar:
    """Thin wrapper over the Google Calendar API: free/busy in, event out.

    Credentials come from one of two places:
      - service_account_file - for a Workspace service account with domain-wide
        delegation; it impersonates `calendar_id`. No browser, good for cron.
      - credentials_file - a desktop OAuth client. The first run opens a browser
        once and caches the result in token_file.
    """

    def __init__(self, config: dict):
        raw_ids = config.get("calendar_id", "primary")
        # Availability usually spans more than one calendar (a personal one, a
        # shared office one), so calendar_id accepts a list as well as a string.
        self.calendar_ids = [str(raw_ids)] if isinstance(raw_ids, str) else [str(x) for x in raw_ids]
        self.calendar_id = self.calendar_ids[0]
        self.write_calendar_id = config.get("write_calendar_id") or self.calendar_id
        self.credentials_file = config.get("credentials_file", "credentials.json")
        self.token_file = config.get("token_file", "state/google_token.json")
        self.service_account_file = config.get("service_account_file")
        self.create_events = bool(config.get("create_events", False))
        self._services: dict[tuple[str, ...], object] = {}

    # -- credentials --

    def _scopes(self) -> list[str]:
        return READ_SCOPES + WRITE_SCOPES if self.create_events else READ_SCOPES

    def _credentials(self, scopes: list[str]):
        if self.service_account_file:
            try:
                from google.oauth2 import service_account
            except ImportError as exc:
                raise CalendarError(INSTALL_HINT) from exc
            creds = service_account.Credentials.from_service_account_file(
                self.service_account_file, scopes=scopes
            )
            # Workspace delegation: act as the calendar owner, not as the robot.
            return creds.with_subject(self.calendar_id) if "@" in self.calendar_id else creds

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise CalendarError(INSTALL_HINT) from exc

        token_path = Path(self.token_file)
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(self.credentials_file).exists():
                raise CalendarError(
                    f"לא נמצא קובץ ההרשאות {self.credentials_file}. "
                    "הורד OAuth client (Desktop app) מ-Google Cloud Console ושמור אותו שם."
                )
            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, scopes)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _service(self):
        scopes = self._scopes()
        key = tuple(scopes)
        if key not in self._services:
            try:
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise CalendarError(INSTALL_HINT) from exc
            self._services[key] = build(
                "calendar", "v3", credentials=self._credentials(scopes), cache_discovery=False
            )
        return self._services[key]

    # -- reading --

    def busy(self, start: datetime, end: datetime, tz: ZoneInfo) -> list[Interval]:
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "timeZone": str(tz),
            "items": [{"id": calendar_id} for calendar_id in self.calendar_ids],
        }
        try:
            response = self._service().freebusy().query(body=body).execute()
        except CalendarError:
            raise
        except Exception as exc:  # googleapiclient raises a wide range of errors
            raise CalendarError(f"קריאת היומן נכשלה: {exc}") from exc
        return parse_freebusy(response, self.calendar_ids, tz)

    # -- writing --

    def create_event(self, summary: str, start: datetime, end: datetime, description: str = "") -> str:
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": str(start.tzinfo)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(end.tzinfo)},
        }
        try:
            event = self._service().events().insert(calendarId=self.write_calendar_id, body=body).execute()
        except CalendarError:
            raise
        except Exception as exc:
            raise CalendarError(f"יצירת האירוע נכשלה: {exc}") from exc
        return event.get("htmlLink", "")


def parse_freebusy(response: dict, calendar_ids, tz: ZoneInfo) -> list[Interval]:
    """Turn a freeBusy response into (start, end) pairs across every requested
    calendar, raising on per-calendar errors."""
    wanted = [calendar_ids] if isinstance(calendar_ids, str) else list(calendar_ids)
    calendars = (response or {}).get("calendars") or {}

    intervals: list[Interval] = []
    for calendar_id in wanted:
        entry = calendars.get(calendar_id)
        if entry is None and len(wanted) == 1 and len(calendars) == 1:
            entry = next(iter(calendars.values()))   # the API may answer under a resolved id
        if entry is None:
            raise CalendarError(f"היומן {calendar_id} לא הוחזר בתשובה. בדוק את calendar_id וההרשאות.")
        if entry.get("errors"):
            reasons = ", ".join(error.get("reason", "?") for error in entry["errors"])
            raise CalendarError(f"היומן {calendar_id} החזיר שגיאה: {reasons}")

        for block in entry.get("busy", []):
            try:
                start = datetime.fromisoformat(str(block["start"]).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(block["end"]).replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError):
                continue
            intervals.append((start.astimezone(tz), end.astimezone(tz)))
    return sorted(intervals)


# --- provider selection -------------------------------------------------


def calendar_config(cfg: dict) -> dict:
    return (cfg.get("scheduling", {}) or {}).get("calendar", {}) or {}


def resolve_provider(cfg: dict) -> str:
    scheduling = cfg.get("scheduling", {}) or {}
    provider = calendar_config(cfg).get("provider")
    if provider:
        return str(provider)
    return "file" if scheduling.get("busy_file") else "none"


def calendar_backend(cfg: dict):
    """The provider object that can read busy hours and create events, or None
    for the providers that cannot (`none` and `file`)."""
    provider = resolve_provider(cfg)
    config = calendar_config(cfg)
    if provider == "google":
        return GoogleCalendar(config)
    if provider == "outlook":
        from .calendar_outlook import OutlookLocal
        return OutlookLocal(config)
    if provider == "graph":
        from .calendar_outlook import OutlookGraph
        return OutlookGraph(config)
    return None


def google_calendar(cfg: dict) -> Optional[GoogleCalendar]:
    backend = calendar_backend(cfg)
    return backend if isinstance(backend, GoogleCalendar) else None


def load_busy(cfg: dict, tz: ZoneInfo, start: datetime, end: datetime) -> list[Interval]:
    """Busy blocks between `start` and `end`, from whichever provider is configured."""
    provider = resolve_provider(cfg)
    if provider == "none":
        return []
    if provider == "file":
        busy_file = calendar_config(cfg).get("busy_file") or cfg.get("scheduling", {}).get("busy_file")
        return load_busy_intervals(busy_file, tz)
    backend = calendar_backend(cfg)
    if backend is None:
        raise CalendarError(
            f"provider לא מוכר ב-config: {provider!r} (none / file / outlook / graph / google)"
        )
    return backend.busy(start, end, tz)
