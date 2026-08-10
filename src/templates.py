"""Hebrew message text for the scheduling proposal, and parsing of the answer."""

import re
from datetime import date
from typing import Optional

from .slots import Slot

_OPTION_WORDS = {
    "1": 1, "١": 1, "א": 1, "א'": 1, "ראשונה": 1, "ראשון": 1, "אחת": 1, "one": 1,
    "2": 2, "٢": 2, "ב": 2, "ב'": 2, "שניה": 2, "שנייה": 2, "שתיים": 2, "two": 2,
}
_NEGATIVE_WORDS = ("לא מתאים", "לא מסתדר", "לא יכול", "לא נוח", "אף אחת", "שתיהן לא", "לא אף")


def first_name(display_name: str) -> str:
    cleaned = re.sub(r"[^\w\s'\"-]", " ", display_name or "").strip()
    return cleaned.split()[0] if cleaned else ""


def render_proposal(display_name: str, slots: list[Slot], today: date, cfg: dict) -> str:
    scheduling = cfg.get("scheduling", {})
    greeting_name = first_name(display_name)
    greeting = f"היי {greeting_name}," if greeting_name else "היי,"

    lines = [
        greeting,
        scheduling.get("opening_line", "מצטער על העיכוב בתשובה. אשמח שנסגור פגישה קצרה."),
        "",
        "שתי אפשרויות:",
    ]
    for index, slot in enumerate(slots, start=1):
        lines.append(f"{index}. {slot.label(today)}")
    lines += [
        "",
        scheduling.get("closing_line", "מה מתאים לך יותר? אפשר להשיב 1 או 2 ואשלח אישור."),
    ]
    signature = scheduling.get("signature")
    if signature:
        lines += ["", signature]
    return "\n".join(lines)


def render_confirmation(slot: Slot, today: date, cfg: dict) -> str:
    location = cfg.get("scheduling", {}).get("location_line", "")
    text = f"מעולה, קבענו ל{slot.label(today)}. נשמח לראותך."
    return f"{text}\n{location}" if location else text


def parse_choice(text: str) -> Optional[int]:
    """Return 1 or 2 if the reply picks an option, else None."""
    if not text:
        return None
    normalized = text.strip().lower()
    if any(word in normalized for word in _NEGATIVE_WORDS):
        return None

    direct = _OPTION_WORDS.get(normalized.rstrip(".!,"))
    if direct:
        return direct

    match = re.search(r"(?:אפשרות|opt(?:ion)?|מספר)\s*([12])", normalized)
    if match:
        return int(match.group(1))
    # A bare digit inside a short reply ("בוא נגיד 2", "2 בבקשה")
    if len(normalized) <= 25:
        digits = re.findall(r"\b([12])\b", normalized)
        if len(set(digits)) == 1:
            return int(digits[0])
    return None
