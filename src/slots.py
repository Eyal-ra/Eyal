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
    intervals = []
    for entry in json.loads(path.read_text(encoding="utf-8")):
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
    return any(slot.start < end and interval_start < slot.end for interval_start, end in intervals)


def build_slots(cfg: dict, today: Optional[date] = None, now: Optional[datetime] = None) -> tuple[list[Slot], date]:
    """Return (two slots, target date). Target date is tomorrow, rolled forward
    past non-working days (in Israel: Friday and Saturday by default)."""
    scheduling = cfg.get("scheduling", {})
    tz = ZoneInfo(scheduling.get("timezone", "Asia/Jerusalem"))
    today = today or datetime.now(tz).date()
    now = now or datetime.now(tz)

    target = next_working_day(today + timedelta(days=1), scheduling.get("skip_weekdays", [4, 5]))
    duration = timedelta(minutes=scheduling.get("meeting_minutes", 30))
    busy = load_busy_intervals(scheduling.get("busy_file"), tz)

    slots: list[Slot] = []
    for raw_time in scheduling.get("option_times", ["10:00", "15:00", "11:30", "16:30", "09:00"]):
        hour, minute = (int(part) for part in str(raw_time).split(":"))
        start = datetime.combine(target, time(hour, minute), tzinfo=tz)
        candidate = Slot(start=start, end=start + duration)
        if candidate.start <= now or _overlaps(candidate, busy):
            continue
        slots.append(candidate)
        if len(slots) == 2:
            break
    return slots, target
