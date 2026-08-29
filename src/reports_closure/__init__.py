"""מערכת סגירת דוחות כספיים.

מנהלת את ההערות שנרשמו בסקירת דוח: כל הערה שבוצעה מסומנת "בוצע", יורדת
מרשימת ההערות הפתוחות ונשמרת בהיסטוריה. דוח נסגר רק כשהרשימה התרוקנה.
"""

from .models import (
    CATEGORIES,
    NOTE_CANCELLED,
    NOTE_DONE,
    NOTE_OPEN,
    NOTE_STATUS_LABELS,
    REPORT_CLOSED,
    REPORT_OPEN,
    REPORT_STATUS_LABELS,
    SEV_CRITICAL,
    SEV_INFO,
    SEV_NORMAL,
    SEVERITY_LABELS,
    ClosureError,
    Note,
    Report,
)
from .parser import parse_notes_text
from .store import ClosureStore

__all__ = [
    "CATEGORIES",
    "ClosureError",
    "ClosureStore",
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
    "SEV_CRITICAL",
    "SEV_INFO",
    "SEV_NORMAL",
    "parse_notes_text",
]
