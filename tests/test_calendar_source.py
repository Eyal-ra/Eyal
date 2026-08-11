from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.calendar_source import (
    CalendarError,
    GoogleCalendar,
    google_calendar,
    load_busy,
    parse_freebusy,
    resolve_provider,
)
from src.slots import build_slots
from src.tz import TimezoneMissing, get_timezone

TZ = ZoneInfo("Asia/Jerusalem")
CALENDAR_ID = "eyal@cpateam.co.il"


class FakeService:
    """Imitates the googleapiclient chain: freebusy().query(body=...).execute()."""

    def __init__(self, freebusy_response=None, inserted_event=None, raises=None):
        self.freebusy_response = freebusy_response or {}
        self.inserted_event = inserted_event or {}
        self.raises = raises
        self.query_body = None
        self.insert_kwargs = None

    def freebusy(self):
        return self

    def query(self, body):
        self.query_body = body
        return self

    def events(self):
        return self

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        return self

    def execute(self):
        if self.raises:
            raise self.raises
        return self.inserted_event if self.insert_kwargs else self.freebusy_response


def google(cfg=None, service=None):
    calendar = GoogleCalendar({"calendar_id": CALENDAR_ID, **(cfg or {})})
    if service is not None:
        calendar._service = lambda: service
    return calendar


# --- reading the free/busy response -------------------------------------

def test_parse_freebusy_converts_blocks_to_local_intervals():
    response = {"calendars": {CALENDAR_ID: {"busy": [
        {"start": "2026-08-11T07:00:00Z", "end": "2026-08-11T08:00:00Z"},
    ]}}}
    (start, end), = parse_freebusy(response, CALENDAR_ID, TZ)
    assert (start.hour, end.hour) == (10, 11)      # 07:00Z is 10:00 in Jerusalem
    assert start.tzinfo is TZ


def test_parse_freebusy_accepts_a_resolved_calendar_id():
    response = {"calendars": {"primary-resolved@group.calendar.google.com": {"busy": []}}}
    assert parse_freebusy(response, "primary", TZ) == []


def test_parse_freebusy_raises_on_a_calendar_error():
    response = {"calendars": {CALENDAR_ID: {"errors": [{"reason": "notFound"}], "busy": []}}}
    with pytest.raises(CalendarError) as excinfo:
        parse_freebusy(response, CALENDAR_ID, TZ)
    assert "notFound" in str(excinfo.value)


def test_parse_freebusy_raises_when_the_calendar_is_missing():
    with pytest.raises(CalendarError):
        parse_freebusy({"calendars": {"a@x": {}, "b@x": {}}}, CALENDAR_ID, TZ)


def test_parse_freebusy_skips_malformed_blocks():
    response = {"calendars": {CALENDAR_ID: {"busy": [
        {"start": "not-a-date", "end": "2026-08-11T08:00:00Z"},
        {"start": "2026-08-11T09:00:00Z", "end": "2026-08-11T10:00:00Z"},
    ]}}}
    assert len(parse_freebusy(response, CALENDAR_ID, TZ)) == 1


# --- the Google provider ------------------------------------------------

def test_google_busy_queries_the_right_window():
    service = FakeService({"calendars": {CALENDAR_ID: {"busy": [
        {"start": "2026-08-11T06:00:00Z", "end": "2026-08-11T07:00:00Z"},
    ]}}})
    calendar = google(service=service)
    start = datetime(2026, 8, 11, 0, 0, tzinfo=TZ)
    busy = calendar.busy(start, start + timedelta(days=1), TZ)

    assert service.query_body["items"] == [{"id": CALENDAR_ID}]
    assert service.query_body["timeZone"] == "Asia/Jerusalem"
    assert busy[0][0].hour == 9


def test_google_busy_wraps_api_failures():
    calendar = google(service=FakeService(raises=RuntimeError("quota exceeded")))
    start = datetime(2026, 8, 11, 0, 0, tzinfo=TZ)
    with pytest.raises(CalendarError) as excinfo:
        calendar.busy(start, start + timedelta(days=1), TZ)
    assert "quota exceeded" in str(excinfo.value)


def test_google_create_event_sends_the_slot_and_returns_the_link():
    service = FakeService(inserted_event={"htmlLink": "https://calendar.google.com/event?eid=1"})
    calendar = google({"create_events": True}, service=service)
    start = datetime(2026, 8, 11, 10, 0, tzinfo=TZ)

    link = calendar.create_event("פגישה - דנה", start, start + timedelta(minutes=30), "טלפון: 0501111111")

    assert link.startswith("https://calendar.google.com/")
    body = service.insert_kwargs["body"]
    assert service.insert_kwargs["calendarId"] == CALENDAR_ID
    assert body["summary"] == "פגישה - דנה"
    assert body["start"]["dateTime"].startswith("2026-08-11T10:00")
    assert "0501111111" in body["description"]


def test_busy_is_merged_across_several_calendars():
    office = "79pf3unmcqq60gm5m67n16pjug@group.calendar.google.com"
    service = FakeService({"calendars": {
        CALENDAR_ID: {"busy": [{"start": "2026-08-12T16:30:00Z", "end": "2026-08-12T20:30:00Z"}]},
        office: {"busy": [{"start": "2026-08-12T09:30:00Z", "end": "2026-08-12T10:30:00Z"}]},
    }})
    calendar = google({"calendar_id": [CALENDAR_ID, office]}, service=service)
    start = datetime(2026, 8, 12, 0, 0, tzinfo=TZ)
    busy = calendar.busy(start, start + timedelta(days=1), TZ)

    assert service.query_body["items"] == [{"id": CALENDAR_ID}, {"id": office}]
    assert [interval[0].strftime("%H:%M") for interval in busy] == ["12:30", "19:30"]   # sorted, both calendars


def test_events_are_created_on_the_first_calendar_unless_overridden():
    assert google({"calendar_id": ["a@x", "b@x"]}).write_calendar_id == "a@x"
    assert google({"calendar_id": ["a@x", "b@x"], "write_calendar_id": "b@x"}).write_calendar_id == "b@x"


def test_write_scope_is_only_requested_when_events_are_enabled():
    assert len(google({"create_events": False})._scopes()) == 1
    assert len(google({"create_events": True})._scopes()) == 2


# --- provider selection -------------------------------------------------

def test_provider_defaults_to_none_and_honors_a_legacy_busy_file():
    assert resolve_provider({}) == "none"
    assert resolve_provider({"scheduling": {"busy_file": "state/busy.json"}}) == "file"
    assert resolve_provider({"scheduling": {"calendar": {"provider": "google"}}}) == "google"


def test_load_busy_returns_nothing_without_a_calendar():
    start = datetime(2026, 8, 11, 0, 0, tzinfo=TZ)
    assert load_busy({}, TZ, start, start + timedelta(days=1)) == []


def test_load_busy_reads_the_file_provider(tmp_path):
    busy_file = tmp_path / "busy.json"
    busy_file.write_text('[{"start": "2026-08-11T10:00", "end": "2026-08-11T11:00"}]', encoding="utf-8")
    cfg = {"scheduling": {"calendar": {"provider": "file", "busy_file": str(busy_file)}}}
    start = datetime(2026, 8, 11, 0, 0, tzinfo=TZ)
    (busy_start, _), = load_busy(cfg, TZ, start, start + timedelta(days=1))
    assert busy_start.hour == 10


def test_unknown_provider_is_rejected():
    start = datetime(2026, 8, 11, 0, 0, tzinfo=TZ)
    with pytest.raises(CalendarError):
        load_busy({"scheduling": {"calendar": {"provider": "outlook"}}}, TZ, start, start)


def test_google_calendar_is_only_built_for_the_google_provider():
    assert google_calendar({"scheduling": {"calendar": {"provider": "file"}}}) is None
    calendar = google_calendar({"scheduling": {"calendar": {"provider": "google", "calendar_id": CALENDAR_ID}}})
    assert calendar.calendar_id == CALENDAR_ID


# --- calendar busy blocks actually move the offered slots ---------------

def test_busy_hours_from_the_calendar_change_what_is_offered():
    cfg = {"scheduling": {"option_times": ["10:00", "15:00", "16:30"], "meeting_minutes": 30}}
    busy = [(datetime(2026, 8, 11, 9, 30, tzinfo=TZ), datetime(2026, 8, 11, 10, 30, tzinfo=TZ))]
    slots, target = build_slots(cfg, today=date(2026, 8, 10),
                                now=datetime(2026, 8, 10, 9, 0, tzinfo=TZ), busy=busy)
    assert target == date(2026, 8, 11)
    assert [slot.time_range for slot in slots] == ["15:00–15:30", "16:30–17:00"]


# --- timezone lookup ----------------------------------------------------

def test_get_timezone_returns_a_real_zone():
    assert str(get_timezone("Asia/Jerusalem")) == "Asia/Jerusalem"


def test_missing_timezone_explains_how_to_fix_it():
    with pytest.raises(TimezoneMissing) as excinfo:
        get_timezone("Mars/Olympus_Mons")
    assert "pip install tzdata" in str(excinfo.value)
