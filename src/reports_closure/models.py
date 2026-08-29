"""מבני הנתונים של מערכת סגירת הדוחות הכספיים.

התהליך שהמערכת מנהלת, בשלושה שלבים:

1. **טיוטה** - נטענת טיוטת הדוחות הכספיים.
2. **הערות** - נרשמות הערות הסקירה על הטיוטה.
3. **תשובות וסגירה** - לכל הערה חייבת להינתן תשובה. הערה שנענתה יורדת
   מרשימת הפתוחות, וכשכל ההערות נענו הדוח נסגר סופית.

הכלל המרכזי: **אי אפשר לסגור הערה בלי תשובה**, ואי אפשר לסגור דוח כל עוד
נותרה הערה פתוחה.
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
    NOTE_OPEN: "ממתין לתשובה",
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

# --- שלבי התהליך (נגזרים מהמצב, לא נשמרים - כדי שלא יצאו מסנכרון) ---
STAGE_NO_DRAFT = "no_draft"
STAGE_AWAITING_NOTES = "awaiting_notes"
STAGE_AWAITING_ANSWERS = "awaiting_answers"
STAGE_READY = "ready"
STAGE_CLOSED = "closed"

STAGE_LABELS = {
    STAGE_NO_DRAFT: "ממתין לטיוטה",
    STAGE_AWAITING_NOTES: "טיוטה נטענה — ממתין להערות",
    STAGE_AWAITING_ANSWERS: "ממתין לתשובות",
    STAGE_READY: "כל ההערות נענו — מוכן לסגירה",
    STAGE_CLOSED: "סגור",
}

# --- דירוג חשיבות, בשמות שבטבלאות ההערות ---
SEV_HIGH = "high"
SEV_MEDIUM = "medium"
SEV_LOW = "low"

SEVERITY_LABELS = {
    SEV_HIGH: "גבוהה",
    SEV_MEDIUM: "בינונית",
    SEV_LOW: "נמוכה",
}

SEVERITY_ORDER = {SEV_HIGH: 0, SEV_MEDIUM: 1, SEV_LOW: 2}

# זיהוי חשיבות מטקסט עברי, כולל הכינויים הישנים מגרסה קודמת
SEVERITY_ALIASES = {
    "גבוהה": SEV_HIGH,
    "גבוה": SEV_HIGH,
    "קריטי": SEV_HIGH,
    "דחוף": SEV_HIGH,
    "critical": SEV_HIGH,
    "high": SEV_HIGH,
    "בינונית": SEV_MEDIUM,
    "בינוני": SEV_MEDIUM,
    "רגיל": SEV_MEDIUM,
    "normal": SEV_MEDIUM,
    "medium": SEV_MEDIUM,
    "נמוכה": SEV_LOW,
    "נמוך": SEV_LOW,
    "בינונית-נמוכה": SEV_MEDIUM,
    "לבירור": SEV_LOW,
    "לבדיקה": SEV_LOW,
    "info": SEV_LOW,
    "low": SEV_LOW,
}


def normalize_severity(raw) -> str:
    """ממיר חשיבות שנכתבה בעברית או במפתח ישן למפתח הנוכחי."""
    if not raw:
        return SEV_MEDIUM
    return SEVERITY_ALIASES.get(str(raw).strip(), SEV_MEDIUM)


class ClosureError(Exception):
    """שגיאה עסקית של המערכת - ההודעה שלה מיועדת להצגה למשתמש."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


# סכום כספי מזוהה רק כשצמוד לו סימן מטבע - כדי ששנה (2025), ח.פ. או מספר
# ביאור לא ייקלטו בטעות כסכום.
_MONEY_RE = re.compile(
    r'(?:₪|ש"ח)\s*(-?[\d,]+(?:\.\d+)?)'
    r'|(-?[\d,]+(?:\.\d+)?)\s*(?:₪|ש"ח|שח)'
    r'|~?(-?[\d,]+(?:\.\d+)?)K\s*(?:ש"ח|₪)'
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
    text = text.replace("₪", "").replace('ש"ח', "").replace("שח", "").replace("~", "")
    multiplier = 1.0
    if text.strip().endswith(("K", "k")):
        multiplier = 1000.0
        text = text.strip()[:-1]
    text = text.replace(",", "").replace(" ", "").strip()
    if not text:
        return None
    try:
        value = float(text) * multiplier
    except ValueError:
        return None
    return -value if negative else value


def find_amount_in_text(text: str) -> float | None:
    """מחלץ סכום מטקסט חופשי, רק אם מופיע בו סימן מטבע."""
    match = _MONEY_RE.search(text or "")
    if not match:
        return None
    raw = match.group(1) or match.group(2) or match.group(3)
    if match.group(3):
        raw = f"{raw}K"
    return parse_amount(raw)


@dataclass
class Draft:
    """טיוטת דוחות שנטענה למערכת. כל טעינה היא גרסה חדשה."""

    filename: str  # השם המקורי, להצגה
    stored_name: str = ""  # השם על הדיסק
    version: int = 1
    uploaded_at: str = field(default_factory=now_iso)
    uploaded_by: str = ""
    note: str = ""  # הערת גרסה, למשל "טיוטה שנייה אחרי תיקוני לינוי"
    size: int = 0

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "stored_name": self.stored_name,
            "version": self.version,
            "uploaded_at": self.uploaded_at,
            "uploaded_by": self.uploaded_by,
            "note": self.note,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Draft":
        return cls(
            filename=data.get("filename", ""),
            stored_name=data.get("stored_name", ""),
            version=int(data.get("version") or 1),
            uploaded_at=data.get("uploaded_at") or now_iso(),
            uploaded_by=data.get("uploaded_by", ""),
            note=data.get("note", ""),
            size=int(data.get("size") or 0),
        )


@dataclass
class Note:
    """הערה בודדת מטבלת ההערות לטיוטה.

    השדות עוקבים אחר טבלת ההערות: חשיבות · נושא · הממצא · השלכה כספית/מס ·
    המלצה לפעולה · הפניה. ``answer`` היא התשובה שניתנה - **חובה** לפני סגירה.
    """

    text: str  # הממצא / ההערה
    id: str = field(default_factory=new_id)
    topic: str = ""  # נושא
    severity: str = SEV_MEDIUM  # חשיבות
    impact: str = ""  # השלכה כספית / מס
    recommendation: str = ""  # המלצה לפעולה
    reference: str = ""  # הפניה (ביאור / עמוד)
    amount: float | None = None
    assignee: str = ""
    source: str = ""
    status: str = NOTE_OPEN
    created_at: str = field(default_factory=now_iso)
    created_by: str = ""
    answer: str = ""  # התשובה / מה בוצע
    answered_at: str | None = None
    answered_by: str = ""
    history: list[dict] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.status == NOTE_OPEN

    @property
    def is_answered(self) -> bool:
        return bool(self.answer.strip())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "topic": self.topic,
            "severity": self.severity,
            "impact": self.impact,
            "recommendation": self.recommendation,
            "reference": self.reference,
            "amount": self.amount,
            "assignee": self.assignee,
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "answer": self.answer,
            "answered_at": self.answered_at,
            "answered_by": self.answered_by,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        # קריאה סלחנית, כולל שמות שדות מגרסה קודמת של הקובץ.
        return cls(
            id=data.get("id") or new_id(),
            text=data.get("text", ""),
            topic=data.get("topic") or data.get("category") or "",
            severity=normalize_severity(data.get("severity")),
            impact=data.get("impact", ""),
            recommendation=data.get("recommendation", ""),
            reference=data.get("reference", ""),
            amount=data.get("amount"),
            assignee=data.get("assignee", ""),
            source=data.get("source", ""),
            status=data.get("status") or NOTE_OPEN,
            created_at=data.get("created_at") or now_iso(),
            created_by=data.get("created_by", ""),
            answer=data.get("answer") or data.get("done_comment") or "",
            answered_at=data.get("answered_at") or data.get("done_at"),
            answered_by=data.get("answered_by") or data.get("done_by", ""),
            history=list(data.get("history") or []),
        )


@dataclass
class Report:
    """דוח כספי אחד של לקוח לתקופה מסוימת."""

    client_name: str
    id: str = field(default_factory=new_id)
    client_id: str = ""  # ח.פ. / ת.ז.
    period: str = ""  # למשל "2024"
    report_type: str = "דוחות כספיים"
    prepared_by: str = ""  # מי הכין את הטיוטה (למשל לינוי)
    status: str = REPORT_OPEN
    created_at: str = field(default_factory=now_iso)
    created_by: str = ""
    closed_at: str | None = None
    closed_by: str = ""
    drafts: list[Draft] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)

    # --- ספירה ותצוגה ---

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
        """כמה הערות ירדו מהרשימה - נענו או בוטלו."""
        return self.total_count - self.open_count

    @property
    def progress_pct(self) -> int:
        # דוח שטרם נרשמו בו הערות אינו "100% מטופל" - הוא לא נסקר עדיין.
        if not self.notes:
            return 0
        return round(self.handled_count * 100 / self.total_count)

    @property
    def has_draft(self) -> bool:
        return bool(self.drafts)

    @property
    def latest_draft(self) -> Draft | None:
        return self.drafts[-1] if self.drafts else None

    @property
    def is_untouched(self) -> bool:
        """טרם נרשמה בו אף הערה - להבדיל מדוח שכל הערותיו נענו."""
        return self.total_count == 0

    @property
    def is_closed(self) -> bool:
        return self.status == REPORT_CLOSED

    @property
    def stage(self) -> str:
        """שלב התהליך, נגזר מהמצב בפועל."""
        if self.is_closed:
            return STAGE_CLOSED
        if not self.has_draft:
            return STAGE_NO_DRAFT
        if self.is_untouched:
            return STAGE_AWAITING_NOTES
        if self.open_count:
            return STAGE_AWAITING_ANSWERS
        return STAGE_READY

    @property
    def stage_label(self) -> str:
        return STAGE_LABELS[self.stage]

    @property
    def can_close(self) -> bool:
        """סגירה אפשרית רק כשיש טיוטה, נרשמו הערות, וכולן נענו."""
        return self.stage == STAGE_READY

    @property
    def unanswered_count(self) -> int:
        return self.open_count

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
        """הערות פתוחות: החשובות קודם, ובתוך אותה רמה לפי סדר הרישום."""
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
            "prepared_by": self.prepared_by,
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "closed_at": self.closed_at,
            "closed_by": self.closed_by,
            "drafts": [d.to_dict() for d in self.drafts],
            "notes": [n.to_dict() for n in self.notes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Report":
        return cls(
            id=data.get("id") or new_id(),
            client_name=data.get("client_name", ""),
            client_id=data.get("client_id", ""),
            period=data.get("period", ""),
            report_type=data.get("report_type") or "דוחות כספיים",
            prepared_by=data.get("prepared_by", ""),
            status=data.get("status") or REPORT_OPEN,
            created_at=data.get("created_at") or now_iso(),
            created_by=data.get("created_by", ""),
            closed_at=data.get("closed_at"),
            closed_by=data.get("closed_by", ""),
            drafts=[Draft.from_dict(d) for d in data.get("drafts") or []],
            notes=[Note.from_dict(n) for n in data.get("notes") or []],
        )
