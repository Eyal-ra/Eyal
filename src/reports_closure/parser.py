"""המרת הערות סקירה שנכתבו כטקסט חופשי לרשימת הערות מובנית.

בפועל ההערות נרשמות בסקירה כרשימת שורות - מהסשן, מהמייל או מהפנקס.
המודול הזה מקבל את הטקסט כמו שהוא ומחזיר הערות מוכנות למערכת, בלי
לדרוש הקלדה מחדש של כל שורה.

מה מזוהה בשורה:
  * תבליטים ומספור בתחילת השורה (``-``, ``*``, ``•``, ``1.``, ``2)``) - מוסרים
  * סיווג בסוגריים מרובעים או לפני נקודתיים: ``[מאזן]`` / ``מאזן:``
  * חשיבות: ``!`` בתחילת השורה, או המילים "קריטי" / "דחוף" בסוגריים
  * סכום כספי - רק כשצמוד לו ₪ או ש"ח
  * שורת המשך (מוזחת ברווחים) מתחברת להערה שמעליה
"""

from __future__ import annotations

import re

from .models import CATEGORIES, SEV_CRITICAL, SEV_INFO, SEV_NORMAL, find_amount_in_text

# תבליט או מספור בתחילת שורה
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d{1,3}[.)])\s+")
# סיווג בסוגריים מרובעים בתחילת השורה
_BRACKET_CAT_RE = re.compile(r"^\s*\[([^\]]{1,30})\]\s*")
# תווי כיווניות שמגיעים מהעתקה מ-Word/WhatsApp ומבלבלים את הפרסור
_BIDI_CHARS = "‎‏‪‫‬⁦⁧⁨⁩"

_CRITICAL_WORDS = ("קריטי", "דחוף", "חובה")
_INFO_WORDS = ("לבירור", "לבדיקה", "לשאול", "להתייעץ")

# התאמת סיווג ללא תלות במרכאות (מע"מ מול מעמ)
_CATEGORY_LOOKUP = {c.replace('"', "").replace("'", ""): c for c in CATEGORIES}


def _clean(line: str) -> str:
    for ch in _BIDI_CHARS:
        line = line.replace(ch, "")
    return line


def _is_separator(line: str) -> bool:
    """שורה שכולה תווי קו (``====``, ``----``) - מפריד, לא הערה."""
    stripped = line.strip()
    return len(stripped) >= 3 and set(stripped) <= set("=-_*~")


def _followed_by_separator(lines: list[str], index: int) -> bool:
    """האם השורה הבאה שאינה ריקה היא קו מפריד - כלומר השורה הזו היא כותרת."""
    for nxt in lines[index + 1:]:
        if not nxt.strip():
            continue
        return _is_separator(nxt)
    return False


def _match_category(raw: str) -> str | None:
    key = raw.strip().replace('"', "").replace("'", "")
    return _CATEGORY_LOOKUP.get(key)


def _extract_category(text: str) -> tuple[str, str | None]:
    """מפריד סיווג מתחילת השורה. מחזיר (הטקסט_בלי_הסיווג, הסיווג_או_None)."""
    bracket = _BRACKET_CAT_RE.match(text)
    if bracket:
        rest = text[bracket.end():].strip()
        # סיווג בסוגריים מתקבל גם אם אינו ברשימה - זו כתיבה מפורשת של המשתמש
        return rest, bracket.group(1).strip()

    # ``מאזן: ...`` מתקבל רק כשהמילה שלפני הנקודתיים היא סיווג מוכר,
    # אחרת "הערה: לבדוק" היה נקלט כסיווג.
    if ":" in text:
        head, _, rest = text.partition(":")
        if len(head) <= 30:
            category = _match_category(head)
            if category and rest.strip():
                return rest.strip(), category
    return text, None


def _extract_severity(text: str) -> tuple[str, str]:
    """מפריד סימון חשיבות. מחזיר (הטקסט_הנקי, רמת_החשיבות)."""
    severity = SEV_NORMAL
    stripped = text.lstrip()
    if stripped.startswith("!"):
        severity = SEV_CRITICAL
        text = stripped.lstrip("!").strip()

    lowered = text
    for word in _CRITICAL_WORDS:
        if f"({word})" in lowered or f"[{word}]" in lowered:
            severity = SEV_CRITICAL
            text = text.replace(f"({word})", "").replace(f"[{word}]", "").strip()
    if severity == SEV_NORMAL:
        for word in _INFO_WORDS:
            if f"({word})" in lowered or f"[{word}]" in lowered:
                severity = SEV_INFO
                text = text.replace(f"({word})", "").replace(f"[{word}]", "").strip()
    return text, severity


def parse_notes_text(raw_text: str, default_category: str = "כללי") -> list[dict]:
    """ממיר טקסט חופשי לרשימת מילוני הערות מוכנים ל-``ClosureStore.add_note``.

    שורות ריקות ושורות כותרת (``===``, ``---``) מדולגות. שורה מוזחת נחשבת
    להמשך ההערה שמעליה, כדי שהערה רב-שורתית לא תישבר לשתי הערות.
    """
    notes: list[dict] = []
    lines = [_clean(l) for l in (raw_text or "").splitlines()]
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if _is_separator(line):  # קו מפריד
            continue
        if _followed_by_separator(lines, index):  # כותרת מעל קו מפריד - לא הערה
            continue

        bullet = _BULLET_RE.match(line)
        indented = line[:1].isspace() and not bullet

        if indented and notes:
            notes[-1]["text"] = f"{notes[-1]['text']} {line.strip()}".strip()
            if notes[-1].get("amount") is None:
                notes[-1]["amount"] = find_amount_in_text(line)
            continue

        text = line[bullet.end():] if bullet else line.strip()
        text, category = _extract_category(text)
        text, severity = _extract_severity(text)
        text = text.strip(" .;،")
        if not text:
            continue

        notes.append(
            {
                "text": text,
                "category": category or default_category,
                "severity": severity,
                "amount": find_amount_in_text(text),
            }
        )
    return notes
