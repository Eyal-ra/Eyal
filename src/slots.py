"""
Build the two meeting slots offered to a customer for tomorrow.

The agent never books anything by itself: it proposes two options, the customer
picks one in WhatsApp, and the meeting is coordinated from there.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

HEBREW_DAYS = {
    0: "יום שני",
    1: "יום שלישי",
    2: "יום רביעי",
    3: "יום חמישי",
    4: "יום שישי",
    5: "שבת",
    6: "יום ראשון",
}

DEFAULT_OPTION_TIMES = ["10:00", "15:00", "11:30", "16:30", "09:00"]


@dataclass
class Slot:
    start: datetime
    end: datetime

    @property
    def time_range(self) -> str:
        return f"{self.start:%H:%M}–{self.end:%H:%M}"

    def label(self, today: date) -> str:
        day = HEBREW_DAYS[self.start.weekday()]
        prefix = "מחר" if self.start.date() == today + timedelta(days=1) else day
        return f"{prefix} ({day} {self.start:%d/%m}) בשעה {self.time_range}"

    def to_iso(self) -> str:
        return self.start.isoformat()


def next_working_day(start: date, skip_weekdays: list[int]) -> date:
    """First date on/after `start` that is not a non-working weekday (Python weekday numbers)."""
    day = start
    for _ in range(14):
        if day.weekday() not in skip_weekdays:
            return day
        day += timedelta(days=1)
    return start


def load_busy_intervals(busy_file: Optional[str], tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    """Optional JSON file of already-booked times: [{"start": ISO, "end": ISO}, ...]."""
    if not busy_file:
        return []
    path = Path(busy_file)
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    intervals = []
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


def _overlaps(slot: Slot, intervals: list[tuple[datetime, datetime]]) -> bool:
    return any(slot.start < busy_end and busy_start < slot.end for busy_start, busy_end in intervals)


def _slots_for_day(day: date, cfg: dict, tz: ZoneInfo, now: datetime, busy) -> list[Slot]:
    scheduling = cfg.get("scheduling", {})
    duration = timedelta(minutes=scheduling.get("meeting_minutes", 30))
    found: list[Slot] = []
    for raw_time in scheduling.get("option_times", DEFAULT_OPTION_TIMES):
        try:
            hour, minute = (int(part) for part in str(raw_time).split(":"))
            start = datetime.combine(day, time(hour, minute), tzinfo=tz)
        except ValueError:
            continue
        candidate = Slot(start=start, end=start + duration)
        if candidate.start <= now or _overlaps(candidate, busy):
            continue
        found.append(candidate)
        if len(found) == 2:
            break
    return found


def build_slots(cfg: dict, today: Optional[date] = None, now: Optional[datetime] = None) -> tuple[list[Slot], date]:
    """Return (two slots, the date they are on).

    Starts at tomorrow, rolls past non-working days (in Israel: Friday and
    Saturday by default), and rolls on again if fewer than two options are left
    free on that day - so a fully booked tomorrow becomes the day after.
    """
    scheduling = cfg.get("scheduling", {})
    tz = ZoneInfo(scheduling.get("timezone", "Asia/Jerusalem"))
    today = today or datetime.now(tz).date()
    now = now or datetime.now(tz)
    skip_weekdays = scheduling.get("skip_weekdays", [4, 5])
    busy = load_busy_intervals(scheduling.get("busy_file"), tz)

    target = next_working_day(today + timedelta(days=1), skip_weekdays)
    for _ in range(scheduling.get("lookahead_days", 5)):
        slots = _slots_for_day(target, cfg, tz, now, busy)
        if len(slots) == 2:
            return slots, target
        target = next_working_day(target + timedelta(days=1), skip_weekdays)
    return [], target
