"""שמירה וטעינה של דוחות והערות סגירה.

הנתונים נשמרים בקובץ JSON אחד (ברירת מחדל ``state/reports_closure.json``).
הכתיבה אטומית - קודם לקובץ זמני ואז ``os.replace`` - כדי שנפילה באמצע
כתיבה לא תשאיר קובץ חצי-כתוב ותאבד הערות.

כל שינוי במצב הערה נרשם ב-``history`` שלה. סימון "בוצע" אינו מוחק כלום:
ההערה יורדת מרשימת הפתוחות ועוברת לרשימת המבוצעות, עם מי סימן ומתי.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .models import (
    NOTE_CANCELLED,
    NOTE_STATUS_LABELS,
    NOTE_DONE,
    NOTE_OPEN,
    REPORT_CLOSED,
    REPORT_OPEN,
    SEV_NORMAL,
    ClosureError,
    Note,
    Report,
    now_iso,
    parse_amount,
)
from .parser import parse_notes_text

SCHEMA_VERSION = 1


class ClosureStore:
    """מאגר הדוחות. מופע אחד לאפליקציה; בטוח לשימוש ממספר בקשות במקביל."""

    def __init__(self, path: str | os.PathLike = "state/reports_closure.json"):
        self.path = Path(path)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # קריאה וכתיבה של הקובץ
    # ------------------------------------------------------------------

    def _read_raw(self) -> dict:
        if not self.path.exists():
            return {"version": SCHEMA_VERSION, "reports": [], "guidelines": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ClosureError(
                f"קובץ הנתונים {self.path} פגום ולא ניתן לקריאה: {exc}. "
                "שחזרו מגיבוי לפני שתמשיכו, אחרת הערות עלולות להימחק."
            ) from exc
        data.setdefault("reports", [])
        data.setdefault("guidelines", [])
        return data

    def _write_raw(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["version"] = SCHEMA_VERSION
        # כתיבה אטומית: קובץ זמני באותה תיקייה ואז החלפה.
        fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _load_reports(self, data: dict) -> list[Report]:
        return [Report.from_dict(r) for r in data.get("reports", [])]

    # ------------------------------------------------------------------
    # דוחות
    # ------------------------------------------------------------------

    def list_reports(self, status: str | None = None, query: str = "") -> list[Report]:
        """מחזיר דוחות, החדשים קודם. ``status`` מסנן פתוח/סגור, ``query`` מחפש בשם."""
        with self._lock:
            reports = self._load_reports(self._read_raw())
        if status:
            reports = [r for r in reports if r.status == status]
        if query:
            q = query.strip()
            reports = [
                r
                for r in reports
                if q in r.client_name or q in r.client_id or q in r.period
            ]
        return sorted(reports, key=lambda r: r.created_at, reverse=True)

    def get_report(self, report_id: str) -> Report:
        with self._lock:
            for report in self._load_reports(self._read_raw()):
                if report.id == report_id:
                    return report
        raise ClosureError("הדוח המבוקש לא נמצא.")

    def add_report(
        self,
        client_name: str,
        period: str = "",
        client_id: str = "",
        report_type: str = "דוח שנתי",
        created_by: str = "",
    ) -> Report:
        client_name = (client_name or "").strip()
        if not client_name:
            raise ClosureError("חובה להזין שם לקוח.")
        report = Report(
            client_name=client_name,
            period=(period or "").strip(),
            client_id=(client_id or "").strip(),
            report_type=(report_type or "דוח שנתי").strip(),
            created_by=created_by,
        )
        with self._lock:
            data = self._read_raw()
            data["reports"].append(report.to_dict())
            self._write_raw(data)
        return report

    def delete_report(self, report_id: str) -> None:
        with self._lock:
            data = self._read_raw()
            remaining = [r for r in data["reports"] if r.get("id") != report_id]
            if len(remaining) == len(data["reports"]):
                raise ClosureError("הדוח המבוקש לא נמצא.")
            data["reports"] = remaining
            self._write_raw(data)

    def close_report(self, report_id: str, by: str = "") -> Report:
        """סוגר דוח. נכשל כל עוד נותרה בו הערה פתוחה אחת."""

        def mutate(report: Report) -> None:
            if report.is_closed:
                raise ClosureError("הדוח כבר סגור.")
            if report.open_count:
                raise ClosureError(
                    f"לא ניתן לסגור: נותרו {report.open_count} הערות פתוחות."
                )
            report.status = REPORT_CLOSED
            report.closed_at = now_iso()
            report.closed_by = by

        return self._mutate_report(report_id, mutate)

    def reopen_report(self, report_id: str, by: str = "") -> Report:
        def mutate(report: Report) -> None:
            if not report.is_closed:
                raise ClosureError("הדוח פתוח ממילא.")
            report.status = REPORT_OPEN
            report.closed_at = None
            report.closed_by = ""

        return self._mutate_report(report_id, mutate)

    # ------------------------------------------------------------------
    # הערות
    # ------------------------------------------------------------------

    def add_note(
        self,
        report_id: str,
        text: str,
        category: str = "כללי",
        severity: str = SEV_NORMAL,
        assignee: str = "",
        amount=None,
        source: str = "",
        created_by: str = "",
    ) -> Note:
        text = (text or "").strip()
        if not text:
            raise ClosureError("חובה להזין תוכן להערה.")
        note = Note(
            text=text,
            category=(category or "כללי").strip(),
            severity=severity or SEV_NORMAL,
            assignee=(assignee or "").strip(),
            amount=parse_amount(amount),
            source=(source or "").strip(),
            created_by=created_by,
        )

        def mutate(report: Report) -> None:
            # הוספת הערה לדוח סגור פותחת אותו מחדש - אחרת ההערה הייתה
            # נבלעת בדוח שכבר "נסגר".
            if report.is_closed:
                report.status = REPORT_OPEN
                report.closed_at = None
                report.closed_by = ""
            report.notes.append(note)

        self._mutate_report(report_id, mutate)
        return note

    def import_notes(
        self,
        report_id: str,
        raw_text: str,
        source: str = "",
        created_by: str = "",
        default_category: str = "כללי",
    ) -> list[Note]:
        """קולט הערות שהודבקו כטקסט חופשי. מחזיר את ההערות שנוספו."""
        parsed = parse_notes_text(raw_text, default_category=default_category)
        if not parsed:
            raise ClosureError("לא נמצאו הערות בטקסט שהודבק.")
        added = [
            Note(
                text=item["text"],
                category=item["category"],
                severity=item["severity"],
                amount=item["amount"],
                source=source,
                created_by=created_by,
            )
            for item in parsed
        ]

        def mutate(report: Report) -> None:
            if report.is_closed:
                report.status = REPORT_OPEN
                report.closed_at = None
                report.closed_by = ""
            report.notes.extend(added)

        self._mutate_report(report_id, mutate)
        return added

    def mark_done(
        self, report_id: str, note_id: str, by: str = "", comment: str = ""
    ) -> Note:
        """מסמן הערה כבוצעה - היא יורדת מרשימת ההערות הפתוחות בדוח."""
        return self._set_note_status(report_id, note_id, NOTE_DONE, by, comment)

    def cancel_note(
        self, report_id: str, note_id: str, by: str = "", comment: str = ""
    ) -> Note:
        """מבטל הערה שאינה רלוונטית - יורדת מהרשימה בלי להיחשב כבוצעה."""
        return self._set_note_status(report_id, note_id, NOTE_CANCELLED, by, comment)

    def reopen_note(self, report_id: str, note_id: str, by: str = "") -> Note:
        """מחזיר הערה שסומנה בטעות חזרה לרשימת הפתוחות."""
        return self._set_note_status(report_id, note_id, NOTE_OPEN, by, "")

    def _set_note_status(
        self, report_id: str, note_id: str, status: str, by: str, comment: str
    ) -> Note:
        result: dict = {}

        def mutate(report: Report) -> None:
            note = report.find_note(note_id)
            if note is None:
                raise ClosureError("ההערה המבוקשת לא נמצאה.")
            if note.status == status:
                label = NOTE_STATUS_LABELS.get(status, status)
                raise ClosureError(f"ההערה כבר במצב '{label}'.")
            previous = note.status
            note.status = status
            if status == NOTE_OPEN:
                note.done_at = None
                note.done_by = ""
                note.done_comment = ""
            else:
                note.done_at = now_iso()
                note.done_by = by
                note.done_comment = (comment or "").strip()
            note.history.append(
                {
                    "at": now_iso(),
                    "by": by,
                    "from": previous,
                    "to": status,
                    "comment": (comment or "").strip(),
                }
            )
            # פתיחת הערה בדוח סגור מחזירה את הדוח לטיפול.
            if status == NOTE_OPEN and report.is_closed:
                report.status = REPORT_OPEN
                report.closed_at = None
                report.closed_by = ""
            result["note"] = note

        self._mutate_report(report_id, mutate)
        return result["note"]

    # ------------------------------------------------------------------
    # הנחיות סקירה קבועות
    # ------------------------------------------------------------------

    def get_guidelines(self) -> list[str]:
        """ההנחיות הקבועות לסקירת דוחות - נשמרות כאן כדי שלא יאבדו בין סשנים."""
        with self._lock:
            return list(self._read_raw().get("guidelines") or [])

    def set_guidelines(self, lines) -> list[str]:
        if isinstance(lines, str):
            lines = lines.splitlines()
        cleaned = [l.strip().lstrip("-*•").strip() for l in lines]
        cleaned = [l for l in cleaned if l]
        with self._lock:
            data = self._read_raw()
            data["guidelines"] = cleaned
            self._write_raw(data)
        return cleaned

    # ------------------------------------------------------------------
    # עזר
    # ------------------------------------------------------------------

    def _mutate_report(self, report_id: str, mutate) -> Report:
        """טוען, משנה דוח אחד ושומר - הכל תחת נעילה, כדי שלא יאבדו עדכונים."""
        with self._lock:
            data = self._read_raw()
            for index, raw in enumerate(data["reports"]):
                if raw.get("id") == report_id:
                    report = Report.from_dict(raw)
                    mutate(report)
                    data["reports"][index] = report.to_dict()
                    self._write_raw(data)
                    return report
        raise ClosureError("הדוח המבוקש לא נמצא.")

    def summary(self) -> dict:
        """מספרים לכותרת הדשבורד."""
        reports = self.list_reports()
        open_reports = [r for r in reports if not r.is_closed]
        return {
            "reports_total": len(reports),
            "reports_open": len(open_reports),
            "reports_closed": len(reports) - len(open_reports),
            "notes_open": sum(r.open_count for r in open_reports),
            "notes_done": sum(len(r.done_notes) for r in reports),
            "ready_to_close": sum(1 for r in open_reports if r.can_close),
        }
