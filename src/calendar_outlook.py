"""
Outlook / Microsoft 365 as the source of busy hours.

Two ways in, because they suit different machines:

  outlook  - the Outlook desktop app on this PC, over COM. Needs no registration
             and no admin: if Outlook is installed and signed in, it works.
  graph    - Microsoft Graph over the network. Survives Outlook being closed and
             runs on any machine, at the cost of a one-time app registration.

Both are imported lazily, so the agent runs without pywin32 or msal installed
unless one of these providers is selected.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .calendar_source import CalendarError, Interval

# Outlook's OlBusyStatus: 0 free, 1 tentative, 2 busy, 3 out of office, 4 elsewhere.
BUSY_STATUSES = {2, 3}
TENTATIVE_STATUS = 1

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = ["Calendars.Read"]
GRAPH_WRITE_SCOPES = ["Calendars.ReadWrite"]

COM_HINT = "חסרה ספריית pywin32. התקן: python -m pip install pywin32"
MSAL_HINT = "חסרות ספריות Graph. התקן: python -m pip install msal requests"


def _aware(value: datetime, tz: ZoneInfo) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=tz)


def _com_datetime(value, tz: ZoneInfo) -> datetime:
    """A pywintypes datetime is datetime-like, but it may be UTC-aware or a naive
    local wall time depending on the pywin32 version. Round-tripping through a
    timestamp would silently shift the hour, so read the fields directly."""
    if getattr(value, "tzinfo", None) is not None:
        return value.astimezone(tz)
    return datetime(value.year, value.month, value.day,
                    value.hour, value.minute, getattr(value, "second", 0), tzinfo=tz)


def _com_failure_hint(exc: Exception) -> str:
    """COM's error codes are opaque, and the most common one here has nothing to
    do with Outlook being installed - it is an elevation mismatch."""
    text = str(exc)
    if "-2146959355" in text or "Server execution failed" in text:
        return (
            "זו כמעט תמיד אי-התאמת הרשאות: PowerShell רץ כמנהל ו-Outlook רץ כמשתמש רגיל.\n"
            "הרץ מחלון PowerShell רגיל (לא 'הפעל כמנהל'), כשה-Outlook פתוח."
        )
    if "-2147221005" in text or "Invalid class string" in text:
        return "לא נמצא Outlook מותקן במחשב הזה. השתמש ב-provider: \"graph\" במקום."
    return "ודא ש-Outlook מותקן, פתוח, ומחובר לחשבון במחשב הזה."


class OutlookLocal:
    """Reads the calendar of the Outlook profile signed in on this machine."""

    def __init__(self, config: dict):
        self.include_tentative = bool(config.get("include_tentative", True))
        self.create_events = bool(config.get("create_events", False))
        self.folder_name = config.get("calendar_name")   # None = the default calendar

    def _calendar_folder(self):
        try:
            import win32com.client
        except ImportError as exc:
            raise CalendarError(COM_HINT) from exc
        try:
            namespace = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
            folder = namespace.GetDefaultFolder(9)       # olFolderCalendar
            if self.folder_name:
                folder = folder.Folders[self.folder_name]
            return folder
        except Exception as exc:
            raise CalendarError(
                f"לא ניתן לפתוח את היומן ב-Outlook: {exc}\n" + _com_failure_hint(exc)
            ) from exc

    def busy(self, start: datetime, end: datetime, tz: ZoneInfo) -> list[Interval]:
        items = self._calendar_folder().Items
        items.IncludeRecurrences = True          # must be set before Sort, or series are missed
        items.Sort("[Start]")
        # Outlook's Restrict only understands US-formatted local times.
        window = "[Start] <= '{}' AND [End] >= '{}'".format(
            end.strftime("%m/%d/%Y %I:%M %p"), start.strftime("%m/%d/%Y %I:%M %p")
        )
        try:
            found = items.Restrict(window)
        except Exception as exc:
            raise CalendarError(f"קריאת היומן מ-Outlook נכשלה: {exc}") from exc
        return self._to_intervals(found, start, end, tz)

    def _to_intervals(self, appointments, start: datetime, end: datetime, tz: ZoneInfo) -> list[Interval]:
        allowed = set(BUSY_STATUSES) | ({TENTATIVE_STATUS} if self.include_tentative else set())
        intervals: list[Interval] = []
        for appointment in appointments:
            try:
                status = int(getattr(appointment, "BusyStatus", 2))
                if status not in allowed:
                    continue                      # "free" markers such as "מאיה בחו\"ל"
                item_start = _com_datetime(appointment.Start, tz)
                item_end = _com_datetime(appointment.End, tz)
            except (AttributeError, TypeError, ValueError, OSError):
                continue
            if item_end > start and item_start < end:
                intervals.append((item_start.astimezone(tz), item_end.astimezone(tz)))
        return sorted(intervals)

    def create_event(self, summary: str, start: datetime, end: datetime, description: str = "") -> str:
        try:
            import win32com.client
        except ImportError as exc:
            raise CalendarError(COM_HINT) from exc
        try:
            appointment = win32com.client.Dispatch("Outlook.Application").CreateItem(1)
            appointment.Subject = summary
            appointment.Body = description
            appointment.Start = start.strftime("%Y-%m-%d %H:%M")
            appointment.Duration = int((end - start).total_seconds() // 60)
            appointment.Save()
        except Exception as exc:
            raise CalendarError(f"יצירת האירוע ב-Outlook נכשלה: {exc}") from exc
        return "outlook:appointment"


class OutlookGraph:
    """Reads free/busy from Microsoft 365 over Graph, using a device-code sign-in."""

    def __init__(self, config: dict):
        self.client_id = config.get("client_id")
        self.tenant_id = config.get("tenant_id", "common")
        self.user = config.get("calendar_id") or config.get("user") or "me"
        self.token_cache = config.get("token_cache", "state/graph_token.json")
        self.include_tentative = bool(config.get("include_tentative", True))
        self.create_events = bool(config.get("create_events", False))
        self._token: Optional[str] = None

    def _scopes(self) -> list[str]:
        return GRAPH_WRITE_SCOPES if self.create_events else GRAPH_SCOPES

    def _access_token(self) -> str:
        if self._token:
            return self._token
        if not self.client_id:
            raise CalendarError(
                "חסר client_id ב-config. רשום אפליקציה ב-Azure Portal "
                "(App registrations → New → Public client) עם הרשאת Calendars.Read."
            )
        try:
            import msal
        except ImportError as exc:
            raise CalendarError(MSAL_HINT) from exc

        cache = msal.SerializableTokenCache()
        cache_path = Path(self.token_cache)
        if cache_path.exists():
            cache.deserialize(cache_path.read_text(encoding="utf-8"))

        app = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=cache,
        )
        accounts = app.get_accounts()
        result = app.acquire_token_silent(self._scopes(), account=accounts[0]) if accounts else None
        if not result:
            flow = app.initiate_device_flow(scopes=self._scopes())
            if "user_code" not in flow:
                raise CalendarError(f"פתיחת ההתחברות נכשלה: {flow.get('error_description', flow)}")
            print(flow["message"])          # "open microsoft.com/devicelogin and enter CODE"
            result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise CalendarError(f"ההתחברות נכשלה: {result.get('error_description', result)}")

        if cache.has_state_changed:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(cache.serialize(), encoding="utf-8")
        self._token = result["access_token"]
        return self._token

    def _post(self, path: str, body: dict) -> dict:
        try:
            import requests
        except ImportError as exc:
            raise CalendarError(MSAL_HINT) from exc
        try:
            resp = requests.post(
                f"{GRAPH_ROOT}{path}",
                json=body,
                headers={"Authorization": f"Bearer {self._access_token()}"},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except CalendarError:
            raise
        except Exception as exc:
            raise CalendarError(f"קריאה ל-Microsoft Graph נכשלה: {exc}") from exc

    def busy(self, start: datetime, end: datetime, tz: ZoneInfo) -> list[Interval]:
        who = self.user if "@" in str(self.user) else "me"
        body = {
            "schedules": [who],
            "startTime": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": str(tz)},
            "endTime": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": str(tz)},
            "availabilityViewInterval": 15,
        }
        response = self._post("/me/calendar/getSchedule", body)
        return parse_schedule(response, tz, self.include_tentative)

    def create_event(self, summary: str, start: datetime, end: datetime, description: str = "") -> str:
        body = {
            "subject": summary,
            "body": {"contentType": "text", "content": description},
            "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": str(start.tzinfo)},
            "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": str(end.tzinfo)},
        }
        event = self._post("/me/events", body)
        return event.get("webLink", "outlook:event")


def parse_schedule(response: dict, tz: ZoneInfo, include_tentative: bool = True) -> list[Interval]:
    """Turn a Graph getSchedule response into (start, end) pairs in local time."""
    allowed = {"busy", "oof"} | ({"tentative"} if include_tentative else set())
    schedules = (response or {}).get("value") or []
    if not schedules:
        raise CalendarError("Graph לא החזיר יומן. בדוק את ההרשאות ואת calendar_id.")

    intervals: list[Interval] = []
    for schedule in schedules:
        if schedule.get("error"):
            raise CalendarError(f"היומן החזיר שגיאה: {schedule['error'].get('message', '?')}")
        for item in schedule.get("scheduleItems") or []:
            if str(item.get("status", "busy")).lower() not in allowed:
                continue
            try:
                start = _graph_time(item["start"], tz)
                end = _graph_time(item["end"], tz)
            except (KeyError, TypeError, ValueError):
                continue
            intervals.append((start, end))
    return sorted(intervals)


def _graph_time(value: dict, tz: ZoneInfo) -> datetime:
    """Graph returns {"dateTime": "...", "timeZone": "UTC"} with no offset in the string."""
    raw = str(value["dateTime"]).split(".")[0]
    parsed = datetime.fromisoformat(raw)
    zone = str(value.get("timeZone") or "UTC")
    try:
        source_tz = ZoneInfo("UTC" if zone.upper() == "UTC" else zone)
    except Exception:
        source_tz = ZoneInfo("UTC")
    return parsed.replace(tzinfo=source_tz).astimezone(tz)


def working_hours_gaps(busy: list[Interval], day_start: datetime, day_end: datetime,
                       minimum: timedelta) -> list[tuple[datetime, datetime]]:
    """Free gaps of at least `minimum` between the busy blocks - used by `calendar`
    to show what is actually open, not only whether the fixed option times are."""
    gaps = []
    cursor = day_start
    for start, end in sorted(busy):
        edge = min(start, day_end)
        if edge > cursor and edge - cursor >= minimum:
            gaps.append((cursor, edge))
        cursor = max(cursor, end)
        if cursor >= day_end:
            return gaps
    if day_end > cursor and day_end - cursor >= minimum:
        gaps.append((cursor, day_end))
    return gaps
