"""Hebrew message text for the scheduling proposal, and reading the customer's answer."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .slots import Slot

_OPTION_WORDS = {
    "1": 1, "١": 1, "א": 1, "א'": 1, "ראשונה": 1, "ראשון": 1, "אחת": 1, "one": 1,
    "2": 2, "٢": 2, "ב": 2, "ב'": 2, "שניה": 2, "שנייה": 2, "שתיים": 2, "two": 2,
}

_NEGATIVE_PATTERNS = (
    "לא מתאים", "לא מסתדר", "לא יכול", "לא נוח", "לא אוכל", "אף אחת", "אף אחד",
    "שתיהן לא", "שניהם לא", "לא השעות", "אולי בפעם", "לא מחר",
)

_MORNING_WORDS = ("בוקר", "בבוקר", "מוקדם")
_AFTERNOON_WORDS = ("צהריים", "צהרים", "אחהצ", 'אחה"צ', "אחרי הצהריים", "אחר הצהריים", "מאוחר", "ערב")

# "בעשר", "ב-10", "בשעה 10:30"
_HEBREW_HOURS = {
    "תשע": 9, "עשר": 10, "אחת עשרה": 11, "אחד עשרה": 11, "שתים עשרה": 12, "שתיים עשרה": 12,
    "אחת": 13, "שתיים": 14, "שתים": 14, "שלוש": 15, "ארבע": 16, "חמש": 17, "שש": 18,
}

_PREFIX = "[בהלמו]?"      # ב/ה/ל prefixes that Hebrew glues onto a word

# Hour and part-of-day hints are only trusted in a short reply. In a long
# message "בערב" is usually part of a sentence, not an answer to the question.
_HINT_MAX_WORDS = 6

CONFIRMED = "confirmed"
DECLINED = "declined"
UNCLEAR = "unclear"


@dataclass
class Answer:
    kind: str                      # confirmed / declined / unclear
    option: Optional[int] = None   # 1 or 2, only when kind == confirmed
    text: str = ""

    @property
    def is_confirmed(self) -> bool:
        return self.kind == CONFIRMED


def first_name(display_name: str) -> str:
    cleaned = re.sub(r"[^\w\s'\"-]", " ", display_name or "", flags=re.UNICODE).strip()
    return cleaned.split()[0] if cleaned else ""


def render_proposal(display_name: str, slots: list[Slot], today: date, cfg: dict, waiting_hours: float = 0.0) -> str:
    scheduling = cfg.get("scheduling", {})
    greeting_name = first_name(display_name)
    greeting = f"היי {greeting_name}," if greeting_name else "היי,"

    late_after = scheduling.get("apology_after_hours", 12)
    if waiting_hours >= late_after:
        opening = scheduling.get("opening_line_late", "מצטער על העיכוב בתשובה. אשמח שנסגור פגישה קצרה.")
    else:
        opening = scheduling.get("opening_line", "אשמח שנסגור פגישה קצרה.")

    lines = [greeting, opening, "", "שתי אפשרויות:"]
    for index, slot in enumerate(slots, start=1):
        lines.append(f"{index}. {slot.label(today)}")
    lines += ["", scheduling.get("closing_line", "מה מתאים לך יותר? אפשר להשיב 1 או 2 ואשלח אישור.")]

    signature = scheduling.get("signature")
    if signature:
        lines += ["", signature]
    return "\n".join(lines)


def render_confirmation(slot: Slot, today: date, cfg: dict) -> str:
    location = cfg.get("scheduling", {}).get("location_line", "")
    text = f"מעולה, קבענו ל{slot.label(today)}. נשמח לראותך."
    return f"{text}\n{location}" if location else text


def render_no_fit(cfg: dict) -> str:
    return cfg.get("scheduling", {}).get(
        "no_fit_line",
        "אין בעיה. מתי נוח לך? תכתוב לי יום ושעה ואתאם.",
    )


def _hour_from_text(text: str) -> Optional[int]:
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\b", text)
    if match:
        hour = int(match.group(1))
        if 6 <= hour <= 21:
            return hour
        if 1 <= hour <= 5:  # "ב-3" means 15:00 in an afternoon context
            return hour + 12
    # Hebrew glues prefixes onto the word ("בעשר", "לשלוש"), so \b never fires;
    # longest first, so "אחת עשרה" is not read as "אחת".
    for word in sorted(_HEBREW_HOURS, key=len, reverse=True):
        if re.search(rf"(?:^|[\s,.\-]){_PREFIX}{word}(?![א-ת])", text):
            return _HEBREW_HOURS[word]
    return None


def parse_answer(text: str, slots: Optional[list[Slot]] = None) -> Answer:
    """Read a WhatsApp reply to the two-option proposal.

    Understands a bare "1"/"2", "אפשרות 2", "א"/"ב", a time that matches one of
    the offered slots ("בעשר", "ב-15:00"), and a part-of-day hint when exactly
    one option falls in that part of the day.
    """
    if not text or not text.strip():
        return Answer(UNCLEAR, text=text or "")
    normalized = text.strip().lower()

    if any(pattern in normalized for pattern in _NEGATIVE_PATTERNS):
        return Answer(DECLINED, text=text)

    direct = _OPTION_WORDS.get(normalized.rstrip(".!,?"))
    if direct:
        return Answer(CONFIRMED, direct, text)

    match = re.search(r"(?:אפשרות|opt(?:ion)?|מספר)\s*([12])\b", normalized)
    if match:
        return Answer(CONFIRMED, int(match.group(1)), text)

    if slots and len(normalized.split()) <= _HINT_MAX_WORDS:
        hour = _hour_from_text(normalized)
        if hour is not None:
            matching = [i for i, slot in enumerate(slots, start=1) if slot.start.hour == hour]
            if len(matching) == 1:
                return Answer(CONFIRMED, matching[0], text)

        if any(word in normalized for word in _MORNING_WORDS):
            morning = [i for i, slot in enumerate(slots, start=1) if slot.start.hour < 12]
            if len(morning) == 1:
                return Answer(CONFIRMED, morning[0], text)
        if any(word in normalized for word in _AFTERNOON_WORDS):
            afternoon = [i for i, slot in enumerate(slots, start=1) if slot.start.hour >= 12]
            if len(afternoon) == 1:
                return Answer(CONFIRMED, afternoon[0], text)

    # A bare digit inside a short reply ("בוא נגיד 2", "2 בבקשה")
    if len(normalized) <= 25:
        digits = set(re.findall(r"\b([12])\b", normalized))
        if len(digits) == 1:
            return Answer(CONFIRMED, int(digits.pop()), text)

    return Answer(UNCLEAR, text=text)
