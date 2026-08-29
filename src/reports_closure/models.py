"""מבני הנתונים של מערכת סגירת הדוחות הכספיים.

הרעיון: לכל **דוח** (לקוח + תקופה) יש רשימת **הערות** שנרשמו בסקירה.
כשהערה מבוצעת היא מסומנת "בוצע" ויורדת מרשימת ההערות הפתוחות - אבל
נשמרת בהיסטוריה, כדי שתמיד יהיה תיעוד מה תוקן, על ידי מי ומתי.
דוח נסגר רק כשלא נותרה בו אף הערה פתוחה.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- סטטוסים של הערה ---
NOTE_OPEN = "open"
NOTE_DONE = "done"
NOTE_CANCELLED = "cancelled"

NOTE_STATUS_LABELS = {
    NOTE_OPEN: "פתוח",
    NOTE_DONE: "בוצע",
    NOTE_CANCELLED: "בוטל",
}

# --- סטטוסים של דוח ---
REPORT_OPEN = "open"
REPORT_CLOSED = "closed"

REPORT_STATUS_LABELS = {
    REPORT_OPEN: "בטיפול",
    REPORT_CLOSED: "סגור",
}

# --- דירוג חשיבות ---
SEV_CRITICAL = "critical"
SEV_NORMAL = "normal"
SEV_INFO = "info"

SEVERITY_LABELS = {
    SEV_CRITICAL: "קריטי",
    SEV_NORMAL: "רגיל",
    SEV_INFO: "לבירור",
}

# סדר להצגה: הקריטי קודם
SEVERITY_ORDER = {SEV_CRITICAL: 0, SEV_NORMAL: 1, SEV_INFO: 2}

# סיווגי הערות נפוצים בסקירת דוחות כספיים
CATEGORIES = [
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


class ClosureError(Exception):
    """שגיאה עסקית של המערכת - ההודעה שלה מיועדת להצגה למשתמש."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


# סכום כספי מזוהה רק כשצמוד לו סימן מטבע - כדי ששנה (2025) או מספר סעיף
# לא ייקלטו בטעות כסכום.
_MONEY_RE = re.compile(
    r'(?:₪|ש"ח|שח)\s*(-?[\d,]+(?:\.\d+)?)'
    r'|(-?[\d,]+(?:\.\d+)?)\s*(?:₪|ש"ח|שח)'
)


def parse_amount(raw) -> float | None:
    """ממיר סכום שהוקלד לפורמט מספרי. מחזיר None כשאין סכום תקין.

    תומך בפורמט הישראלי: ``1,234.56``, ``₪1,000``, ``(500)`` כמינוס.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace("₪", "").replace('ש"ח', "").replace("שח", "")
    text = text.replace(",", "").replace(" ", "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def find_amount_in_text(text: str) -> float | None:
    """מחלץ סכום מתוך שורת הערה חופשית, רק אם מופיע בה סימן מטבע."""
    match = _MONEY_RE.search(text or "")
    if not match:
        return None
    return parse_amount(match.group(1) or match.group(2))


@dataclass
class Note:
    """הערה בודדת שנרשמה בסקירת הדוח."""

    text: str
    id: str = field(default_factory=new_id)
    category: str = "כללי"
    severity: str = SEV_NORMAL
    assignee: str = ""
    amount: float | None = None
    source: str = ""  # מאיפה הגיעה ההערה (סשן סקירה, קובץ, שם הסוקר)
    status: str = NOTE_OPEN
    created_at: str = field(default_factory=now_iso)
    created_by: str = ""
    done_at: str | None = None
    done_by: str = ""
    done_comment: str = ""
    history: list[dict] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.status == NOTE_OPEN

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "category": self.category,
            "severity": self.severity,
            "assignee": self.assignee,
            "amount": self.amount,
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "done_at": self.done_at,
            "done_by": self.done_by,
            "done_comment": self.done_comment,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        # קריאה סלחנית: קובץ ישן בלי שדה חדש עדיין נטען.
        return cls(
            id=data.get("id") or new_id(),
            text=data.get("text", ""),
            category=data.get("category") or "כללי",
            severity=data.get("severity") or SEV_NORMAL,
            assignee=data.get("assignee", ""),
            amount=data.get("amount"),
            source=data.get("source", ""),
            status=data.get("status") or NOTE_OPEN,
            created_at=data.get("created_at") or now_iso(),
            created_by=data.get("created_by", ""),
            done_at=data.get("done_at"),
            done_by=data.get("done_by", ""),
            done_comment=data.get("done_comment", ""),
            history=list(data.get("history") or []),
        )


@dataclass
class Report:
    """דוח כספי אחד של לקוח לתקופה מסוימת."""

    client_name: str
    id: str = field(default_factory=new_id)
    client_id: str = ""  # ח.פ. / ת.ז.
    period: str = ""  # למשל "2025" או "רבעון 2/2026"
    report_type: str = "דוח שנתי"
    status: str = REPORT_OPEN
    created_at: str = field(default_factory=now_iso)
    created_by: str = ""
    closed_at: str | None = None
    closed_by: str = ""
    notes: list[Note] = field(default_factory=list)

    # --- תצוגה וספירה ---

    @property
    def open_notes(self) -> list[Note]:
        return [n for n in self.notes if n.status == NOTE_OPEN]

    @property
    def done_notes(self) -> list[Note]:
        return [n for n in self.notes if n.status == NOTE_DONE]

    @property
    def cancelled_notes(self) -> list[Note]:
        return [n for n in self.notes if n.status == NOTE_CANCELLED]

    @property
    def open_count(self) -> int:
        return len(self.open_notes)

    @property
    def total_count(self) -> int:
        return len(self.notes)

    @property
    def handled_count(self) -> int:
        """כמה הערות ירדו מהרשימה - בוצעו או בוטלו."""
        return self.total_count - self.open_count

    @property
    def progress_pct(self) -> int:
        # דוח שטרם נרשמו בו הערות אינו "100% מטופל" - הוא בכלל לא נסקר עדיין.
        if not self.notes:
            return 0
        return round(self.handled_count * 100 / self.total_count)

    @property
    def is_untouched(self) -> bool:
        """נפתח אך טרם נרשמה בו אף הערה - להבדיל מדוח שכל הערותיו טופלו."""
        return self.total_count == 0

    @property
    def is_closed(self) -> bool:
        return self.status == REPORT_CLOSED

    @property
    def can_close(self) -> bool:
        """דוח בלי הערות פתוחות ניתן לסגירה - גם דוח שלא היו בו ממצאים כלל.

        ההבחנה בין "כל ההערות טופלו" ל"טרם נרשמו הערות" נעשית ב-``is_untouched``,
        כדי שדוח שטרם נסקר לא יוצג כדוח שסיימת.
        """
        return self.status == REPORT_OPEN and self.open_count == 0

    @property
    def title(self) -> str:
        parts = [self.client_name]
        if self.period:
            parts.append(self.period)
        return " - ".join(parts)

    def find_note(self, note_id: str) -> Note | None:
        for note in self.notes:
            if note.id == note_id:
                return note
        return None

    def sorted_open_notes(self) -> list[Note]:
        """הערות פתוחות: קריטי קודם, ובתוך אותה רמה לפי סדר הרישום."""
        return sorted(
            self.open_notes,
            key=lambda n: (SEVERITY_ORDER.get(n.severity, 1), n.created_at),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "client_name": self.client_name,
            "client_id": self.client_id,
            "period": self.period,
            "report_type": self.report_type,
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "closed_at": self.closed_at,
            "closed_by": self.closed_by,
            "notes": [n.to_dict() for n in self.notes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Report":
        return cls(
            id=data.get("id") or new_id(),
            client_name=data.get("client_name", ""),
            client_id=data.get("client_id", ""),
            period=data.get("period", ""),
            report_type=data.get("report_type") or "דוח שנתי",
            status=data.get("status") or REPORT_OPEN,
            created_at=data.get("created_at") or now_iso(),
            created_by=data.get("created_by", ""),
            closed_at=data.get("closed_at"),
            closed_by=data.get("closed_by", ""),
            notes=[Note.from_dict(n) for n in data.get("notes") or []],
        )
