from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.calendar_outlook import (
    _com_failure_hint,
    OutlookGraph,
    OutlookLocal,
    parse_schedule,
    working_hours_gaps,
)
from src.calendar_source import CalendarError, calendar_backend, resolve_provider
from src.slots import build_slots

TZ = ZoneInfo("Asia/Jerusalem")


def graph_item(start_utc: str, end_utc: str, status: str = "busy", subject: str = ""):
    return {
        "status": status,
        "subject": subject,
        "start": {"dateTime": start_utc, "timeZone": "UTC"},
        "end": {"dateTime": end_utc, "timeZone": "UTC"},
    }


# The real shape of tomorrow in the office calendar: a mix of busy meetings,
# tentative invitations forwarded from Google, and all-day "free" markers.
TOMORROW = {"value": [{"scheduleItems": [
    graph_item("2026-08-12T06:00:00.0000000", "2026-08-12T06:30:00.0000000", "busy", "זום גבריאל"),
    graph_item("2026-08-12T07:00:00.0000000", "2026-08-12T08:00:00.0000000", "busy", "רועי ואלה"),
    graph_item("2026-08-12T09:30:00.0000000", "2026-08-12T10:30:00.0000000", "tentative", "מאיה אולי"),
    graph_item("2026-08-12T11:30:00.0000000", "2026-08-12T12:15:00.0000000", "busy", "אדר אלוני"),
    graph_item("2026-08-12T16:30:00.0000000", "2026-08-12T20:30:00.0000000", "tentative", "חתונה"),
    graph_item("2026-08-09T00:00:00.0000000", "2026-08-19T00:00:00.0000000", "free", "מאיה בחו\"ל"),
]}]}


# --- reading a Graph getSchedule response -------------------------------

def test_schedule_is_converted_to_local_time():
    busy = parse_schedule(TOMORROW, TZ)
    assert [f"{start:%H:%M}-{end:%H:%M}" for start, end in busy] == [
        "09:00-09:30", "10:00-11:00", "12:30-13:30", "14:30-15:15", "19:30-23:30",
    ]


def test_free_markers_are_not_treated_as_busy():
    # The all-day "away" entries are marked free and must not block the day.
    assert all(start.day == 12 for start, _ in parse_schedule(TOMORROW, TZ))


def test_tentative_can_be_ignored():
    busy = parse_schedule(TOMORROW, TZ, include_tentative=False)
    assert [f"{start:%H:%M}" for start, _ in busy] == ["09:00", "10:00", "14:30"]


def test_schedule_raises_on_a_calendar_error():
    response = {"value": [{"error": {"message": "MailboxNotEnabled"}}]}
    with pytest.raises(CalendarError) as excinfo:
        parse_schedule(response, TZ)
    assert "MailboxNotEnabled" in str(excinfo.value)


def test_schedule_raises_when_nothing_comes_back():
    with pytest.raises(CalendarError):
        parse_schedule({"value": []}, TZ)


def test_schedule_skips_malformed_items():
    response = {"value": [{"scheduleItems": [
        {"status": "busy", "start": {"dateTime": "nonsense"}, "end": {"dateTime": "nonsense"}},
        graph_item("2026-08-12T06:00:00", "2026-08-12T06:30:00"),
    ]}]}
    assert len(parse_schedule(response, TZ)) == 1


# --- the Graph provider -------------------------------------------------

def test_graph_asks_for_the_window_in_the_local_timezone():
    calendar = OutlookGraph({"client_id": "abc", "calendar_id": "eyal@cpateam.co.il"})
    sent = {}

    def fake_post(path, body):
        sent["path"], sent["body"] = path, body
        return TOMORROW

    calendar._post = fake_post
    start = datetime(2026, 8, 12, 0, 0, tzinfo=TZ)
    busy = calendar.busy(start, start + timedelta(days=1), TZ)

    assert sent["path"] == "/me/calendar/getSchedule"
    assert sent["body"]["schedules"] == ["eyal@cpateam.co.il"]
    assert sent["body"]["startTime"]["timeZone"] == "Asia/Jerusalem"
    assert len(busy) == 5


def test_graph_creates_an_event_and_returns_the_link():
    calendar = OutlookGraph({"client_id": "abc", "create_events": True})
    sent = {}

    def fake_post(path, body):
        sent["path"], sent["body"] = path, body
        return {"webLink": "https://outlook.office365.com/owa/?itemid=1"}

    calendar._post = fake_post
    start = datetime(2026, 8, 12, 11, 0, tzinfo=TZ)
    link = calendar.create_event("פגישה - דנה", start, start + timedelta(minutes=30), "טלפון: 050")

    assert sent["path"] == "/me/events"
    assert sent["body"]["subject"] == "פגישה - דנה"
    assert sent["body"]["start"]["dateTime"] == "2026-08-12T11:00:00"
    assert link.startswith("https://outlook.office365.com/")


def test_graph_asks_for_write_scope_only_when_creating_events():
    assert OutlookGraph({"client_id": "a"})._scopes() == ["Calendars.Read"]
    assert OutlookGraph({"client_id": "a", "create_events": True})._scopes() == ["Calendars.ReadWrite"]


def test_graph_without_a_client_id_explains_the_registration():
    with pytest.raises(CalendarError) as excinfo:
        OutlookGraph({}).busy(datetime.now(TZ), datetime.now(TZ), TZ)
    assert "client_id" in str(excinfo.value)


# --- the local Outlook provider -----------------------------------------

class FakeAppointment:
    """Stands in for an Outlook COM appointment item."""

    def __init__(self, start: datetime, end: datetime, busy_status: int = 2):
        self.Start = start
        self.End = end
        self.BusyStatus = busy_status


def test_local_outlook_keeps_busy_and_drops_free_appointments():
    outlook = OutlookLocal({})
    day = datetime(2026, 8, 12, 0, 0, tzinfo=TZ)
    appointments = [
        FakeAppointment(datetime(2026, 8, 12, 9, 0, tzinfo=TZ), datetime(2026, 8, 12, 9, 30, tzinfo=TZ), 2),
        FakeAppointment(datetime(2026, 8, 12, 12, 30, tzinfo=TZ), datetime(2026, 8, 12, 13, 30, tzinfo=TZ), 1),
        FakeAppointment(datetime(2026, 8, 12, 0, 0, tzinfo=TZ), datetime(2026, 8, 19, 0, 0, tzinfo=TZ), 0),
    ]
    busy = outlook._to_intervals(appointments, day, day + timedelta(days=1), TZ)
    assert [f"{start:%H:%M}" for start, _ in busy] == ["09:00", "12:30"]


def test_local_outlook_can_ignore_tentative():
    outlook = OutlookLocal({"include_tentative": False})
    day = datetime(2026, 8, 12, 0, 0, tzinfo=TZ)
    appointments = [
        FakeAppointment(datetime(2026, 8, 12, 9, 0, tzinfo=TZ), datetime(2026, 8, 12, 9, 30, tzinfo=TZ), 2),
        FakeAppointment(datetime(2026, 8, 12, 12, 30, tzinfo=TZ), datetime(2026, 8, 12, 13, 30, tzinfo=TZ), 1),
    ]
    assert len(outlook._to_intervals(appointments, day, day + timedelta(days=1), TZ)) == 1


def test_local_outlook_drops_appointments_outside_the_window():
    outlook = OutlookLocal({})
    day = datetime(2026, 8, 12, 0, 0, tzinfo=TZ)
    far_off = FakeAppointment(datetime(2026, 9, 1, 9, 0, tzinfo=TZ), datetime(2026, 9, 1, 10, 0, tzinfo=TZ))
    assert outlook._to_intervals([far_off], day, day + timedelta(days=1), TZ) == []


# --- provider wiring ----------------------------------------------------

def test_outlook_providers_are_resolved_from_config():
    assert resolve_provider({"scheduling": {"calendar": {"provider": "outlook"}}}) == "outlook"
    assert isinstance(calendar_backend({"scheduling": {"calendar": {"provider": "outlook"}}}), OutlookLocal)
    assert isinstance(calendar_backend({"scheduling": {"calendar": {"provider": "graph"}}}), OutlookGraph)
    assert calendar_backend({"scheduling": {"calendar": {"provider": "file"}}}) is None


# --- what this actually changes for the customer ------------------------

def test_tomorrows_real_calendar_moves_both_default_options():
    """Both configured option times are taken tomorrow, so the agent must offer
    different hours rather than double-book."""
    cfg = {"scheduling": {"option_times": ["10:00", "15:00", "11:30", "16:30"], "meeting_minutes": 30}}
    busy = parse_schedule(TOMORROW, TZ)
    slots, target = build_slots(cfg, today=datetime(2026, 8, 11).date(),
                                now=datetime(2026, 8, 11, 9, 0, tzinfo=TZ), busy=busy)
    assert target.day == 12
    assert [slot.time_range for slot in slots] == ["11:30–12:00", "16:30–17:00"]


def test_free_gaps_are_reported_between_meetings():
    busy = parse_schedule(TOMORROW, TZ)
    day_start = datetime(2026, 8, 12, 8, 0, tzinfo=TZ)
    day_end = datetime(2026, 8, 12, 19, 0, tzinfo=TZ)
    gaps = working_hours_gaps(busy, day_start, day_end, timedelta(minutes=30))
    assert [f"{start:%H:%M}-{end:%H:%M}" for start, end in gaps] == [
        "08:00-09:00", "09:30-10:00", "11:00-12:30", "13:30-14:30", "15:15-19:00",
    ]


def test_a_gap_shorter_than_the_meeting_is_not_offered():
    busy = [(datetime(2026, 8, 12, 9, 0, tzinfo=TZ), datetime(2026, 8, 12, 9, 45, tzinfo=TZ))]
    gaps = working_hours_gaps(busy, datetime(2026, 8, 12, 8, 40, tzinfo=TZ),
                              datetime(2026, 8, 12, 10, 0, tzinfo=TZ), timedelta(minutes=30))
    assert [f"{start:%H:%M}" for start, _ in gaps] == []   # 20m before, 15m after - neither fits


# --- COM error codes, translated -----------------------------------------

def test_server_execution_failed_points_at_the_elevation_mismatch():
    hint = _com_failure_hint(Exception("(-2146959355, 'Server execution failed', None, None)"))
    assert "כמנהל" in hint and "רגיל" in hint


def test_missing_outlook_points_at_the_graph_provider():
    assert "graph" in _com_failure_hint(Exception("(-2147221005, 'Invalid class string')"))


def test_an_unknown_com_error_falls_back_to_the_general_advice():
    assert "Outlook" in _com_failure_hint(Exception("something else entirely"))
