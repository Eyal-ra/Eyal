"""המרת הערות סקירה לרשימת הערות מובנית.

שני פורמטים נתמכים, והבחירה ביניהם אוטומטית:

1. **טבלת הערות** - הפורמט של טבלאות ההערות לטיוטה, בין אם הודבקה מגיליון
   (מופרדת טאבים) ובין אם ממסמך (מופרדת ``|``). הכותרות מזוהות לפי שמן,
   בכל סדר, וכל עמודה שאינה מוכרת נשמטת::

       # | חשיבות | נושא | הממצא / ההערה | השלכה כספית / מס | המלצה לפעולה | הפניה

2. **רשימת שורות** - הערה בשורה, כשההערות נרשמו כרשימה חופשית. מזוהים
   תבליטים ומספור, ``[נושא]`` או ``נושא:`` בתחילת שורה, ``!`` לחשיבות גבוהה,
   וסכום עם ₪. שורה מוזחת מתחברת להערה שמעליה.
"""

from __future__ import annotations

import re

from .models import (
    SEV_HIGH,
    SEV_LOW,
    SEV_MEDIUM,
    find_amount_in_text,
    normalize_severity,
)

_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d{1,3}[.)])\s+")
_BRACKET_TOPIC_RE = re.compile(r"^\s*\[([^\]]{1,40})\]\s*")
# תווי כיווניות שמגיעים מהעתקה מ-Word/WhatsApp ומבלבלים את הפרסור
_BIDI_CHARS = "‎‏‪‫‬⁦⁧⁨⁩"

_HIGH_WORDS = ("קריטי", "דחוף", "חובה", "גבוהה")
_LOW_WORDS = ("לבירור", "לבדיקה", "לשאול", "להתייעץ", "נמוכה")

# נושאים מוכרים, לזיהוי ``נושא:`` בתחילת שורה ברשימה חופשית
KNOWN_TOPICS = [
    "מאזן",
    "רווח והפסד",
    "תזרים",
    "ביאורים",
    "מס הכנסה",
    'מע"מ',
    "ביטוח לאומי",
    "שכר",
    "לקוחות",
    "ספקים",
    "מלאי",
    "רכוש קבוע",
    "הלוואות",
    "הון",
    "התאמות בנק",
    "כרטיסי אשראי",
    "תיעוד",
    "כללי",
]
_TOPIC_LOOKUP = {t.replace('"', "").replace("'", ""): t for t in KNOWN_TOPICS}

# שמות עמודות בטבלת ההערות. המפתח הוא שם השדה, הערכים הם כינויים אפשריים.
_COLUMN_ALIASES = {
    "severity": ("חשיבות", "דחיפות", "רמת חשיבות", "עדיפות"),
    "topic": ("נושא", "סעיף", "תחום", "סיווג"),
    "text": ("הממצא / ההערה", "הממצא", "ההערה", "הערה", "ממצא", "תיאור"),
    "impact": ("השלכה כספית / מס", "השלכה כספית", "השלכה", "השפעה כספית", "סכום"),
    "recommendation": ("המלצה לפעולה", "המלצה", "פעולה נדרשת", "מה לעשות"),
    "reference": ("הפניה", "הפנייה", "מקור", "ביאור"),
}
_INDEX_HEADERS = ("#", "מס'", "מספר", "מס")


def _clean(line: str) -> str:
    for ch in _BIDI_CHARS:
        line = line.replace(ch, "")
    return line


def _is_separator(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= 3 and set(stripped) <= set("=-_*~")


def _followed_by_separator(lines: list[str], index: int) -> bool:
    for nxt in lines[index + 1:]:
        if not nxt.strip():
            continue
        return _is_separator(nxt)
    return False


# ----------------------------------------------------------------------
# טבלת הערות
# ----------------------------------------------------------------------


def _split_row(line: str) -> list[str]:
    """מפצל שורת טבלה, בין אם היא מופרדת ``|`` ובין אם טאבים."""
    if "|" in line:
        cells = line.split("|")
        # שורת markdown פותחת ונסגרת ב-| ולכן נוצרים תאים ריקים בקצוות
        if cells and not cells[0].strip():
            cells = cells[1:]
        if cells and not cells[-1].strip():
            cells = cells[:-1]
    elif "\t" in line:
        cells = line.split("\t")
    else:
        return []
    return [c.strip().strip("*").replace("\\|", "|").strip() for c in cells]


def _match_column(header: str) -> str | None:
    normalized = header.strip().strip("*").lower()
    normalized = re.sub(r"\s*\([^)]*\)\s*$", "", normalized).strip()
    for field_name, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if normalized == alias.lower():
                return field_name
    # התאמה חלקית, לכותרות עם תוספות ("הממצא / ההערה בטיוטה")
    for field_name, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in normalized:
                return field_name
    return None


def _find_header(rows: list[list[str]]) -> tuple[int, dict[int, str]] | None:
    """מאתר את שורת הכותרות ואת מיפוי העמודות. מחזיר None כשאין טבלה."""
    for row_index, cells in enumerate(rows):
        mapping: dict[int, str] = {}
        for col_index, cell in enumerate(cells):
            if cell.strip() in _INDEX_HEADERS:
                continue
            field_name = _match_column(cell)
            if field_name and field_name not in mapping.values():
                mapping[col_index] = field_name
        # דורשים לפחות את עמודת הממצא ועוד אחת, כדי לא לזהות טבלה בטעות
        if "text" in mapping.values() and len(mapping) >= 2:
            return row_index, mapping
    return None


def _is_markdown_rule(cells: list[str]) -> bool:
    return bool(cells) and all(set(c) <= set(":- ") and c for c in cells)


def parse_notes_table(raw_text: str) -> list[dict] | None:
    """מפרסר טבלת הערות. מחזיר None כשהטקסט אינו טבלה מזוהה."""
    lines = [_clean(l) for l in (raw_text or "").splitlines() if l.strip()]
    rows = [cells for cells in (_split_row(l) for l in lines) if cells]
    if len(rows) < 2:
        return None
    header = _find_header(rows)
    if header is None:
        return None
    header_index, mapping = header

    notes: list[dict] = []
    for cells in rows[header_index + 1:]:
        if _is_markdown_rule(cells):
            continue
        # שורות כותרת ממוזגות בגיליון חוזרות על אותו ערך בכל התאים
        if len(set(c for c in cells if c)) == 1 and len(cells) > 2:
            continue
        values = {
            field_name: cells[col].strip()
            for col, field_name in mapping.items()
            if col < len(cells)
        }
        text = values.get("text", "").strip()
        if not text:
            continue
        impact = values.get("impact", "")
        notes.append(
            {
                "text": text,
                "topic": values.get("topic", ""),
                "severity": normalize_severity(values.get("severity")),
                "impact": impact,
                "recommendation": values.get("recommendation", ""),
                "reference": values.get("reference", ""),
                # הסכום נלקח קודם מעמודת ההשלכה הכספית, ורק אחריה מהממצא
                "amount": find_amount_in_text(impact) or find_amount_in_text(text),
            }
        )
    return notes or None


# ----------------------------------------------------------------------
# רשימת שורות
# ----------------------------------------------------------------------


def _match_topic(raw: str) -> str | None:
    key = raw.strip().replace('"', "").replace("'", "")
    return _TOPIC_LOOKUP.get(key)


def _extract_topic(text: str) -> tuple[str, str | None]:
    bracket = _BRACKET_TOPIC_RE.match(text)
    if bracket:
        return text[bracket.end():].strip(), bracket.group(1).strip()

    # ``מאזן: ...`` מתקבל רק כשהמילה שלפני הנקודתיים היא נושא מוכר,
    # אחרת "הערה: לבדוק" היה נקלט כנושא.
    if ":" in text:
        head, _, rest = text.partition(":")
        if len(head) <= 30:
            topic = _match_topic(head)
            if topic and rest.strip():
                return rest.strip(), topic
    return text, None


def _extract_severity(text: str) -> tuple[str, str]:
    severity = SEV_MEDIUM
    stripped = text.lstrip()
    if stripped.startswith("!"):
        severity = SEV_HIGH
        text = stripped.lstrip("!").strip()

    for word in _HIGH_WORDS:
        if f"({word})" in text or f"[{word}]" in text:
            severity = SEV_HIGH
            text = text.replace(f"({word})", "").replace(f"[{word}]", "").strip()
    if severity == SEV_MEDIUM:
        for word in _LOW_WORDS:
            if f"({word})" in text or f"[{word}]" in text:
                severity = SEV_LOW
                text = text.replace(f"({word})", "").replace(f"[{word}]", "").strip()
    return text, severity


def parse_notes_lines(raw_text: str, default_topic: str = "") -> list[dict]:
    """ממיר רשימת הערות חופשית לרשימת מילונים."""
    notes: list[dict] = []
    lines = [_clean(l) for l in (raw_text or "").splitlines()]
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if _is_separator(line):
            continue
        if _followed_by_separator(lines, index):  # כותרת מעל קו מפריד
            continue

        bullet = _BULLET_RE.match(line)
        indented = line[:1].isspace() and not bullet

        if indented and notes:
            notes[-1]["text"] = f"{notes[-1]['text']} {line.strip()}".strip()
            if notes[-1].get("amount") is None:
                notes[-1]["amount"] = find_amount_in_text(line)
            continue

        text = line[bullet.end():] if bullet else line.strip()
        text, topic = _extract_topic(text)
        text, severity = _extract_severity(text)
        text = text.strip(" .;")
        if not text:
            continue

        notes.append(
            {
                "text": text,
                "topic": topic or default_topic,
                "severity": severity,
                "impact": "",
                "recommendation": "",
                "reference": "",
                "amount": find_amount_in_text(text),
            }
        )
    return notes


def parse_notes_text(raw_text: str, default_topic: str = "") -> list[dict]:
    """הכניסה הראשית: מזהה לבד אם הודבקה טבלה או רשימת שורות."""
    table = parse_notes_table(raw_text)
    if table:
        return table
    return parse_notes_lines(raw_text, default_topic=default_topic)
