"""מערכת סגירת דוחות כספיים.

מנהלת את התהליך מהטיוטה ועד הסגירה: טיוטה נטענת, נרשמות עליה הערות סקירה,
ולכל הערה ניתנת תשובה. הערה שנענתה יורדת מרשימת ההערות הפתוחות ונשמרת עם
התשובה שלה; הדוח נסגר רק כשכל ההערות נענו.
"""

from .models import (
    NOTE_CANCELLED,
    NOTE_DONE,
    NOTE_OPEN,
    NOTE_STATUS_LABELS,
    REPORT_CLOSED,
    REPORT_OPEN,
    REPORT_STATUS_LABELS,
    SEV_HIGH,
    SEV_LOW,
    SEV_MEDIUM,
    SEVERITY_LABELS,
    STAGE_AWAITING_ANSWERS,
    STAGE_AWAITING_NOTES,
    STAGE_CLOSED,
    STAGE_LABELS,
    STAGE_NO_DRAFT,
    STAGE_READY,
    ClosureError,
    Draft,
    Note,
    Report,
    normalize_severity,
)
from .parser import KNOWN_TOPICS, parse_notes_lines, parse_notes_table, parse_notes_text
from .store import ClosureStore

__all__ = [
    "ClosureError",
    "ClosureStore",
    "Draft",
    "KNOWN_TOPICS",
    "Note",
    "NOTE_CANCELLED",
    "NOTE_DONE",
    "NOTE_OPEN",
    "NOTE_STATUS_LABELS",
    "Report",
    "REPORT_CLOSED",
    "REPORT_OPEN",
    "REPORT_STATUS_LABELS",
    "SEVERITY_LABELS",
    "SEV_HIGH",
    "SEV_LOW",
    "SEV_MEDIUM",
    "STAGE_AWAITING_ANSWERS",
    "STAGE_AWAITING_NOTES",
    "STAGE_CLOSED",
    "STAGE_LABELS",
    "STAGE_NO_DRAFT",
    "STAGE_READY",
    "normalize_severity",
    "parse_notes_lines",
    "parse_notes_table",
    "parse_notes_text",
]
