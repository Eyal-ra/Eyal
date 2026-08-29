"""שמירה וטעינה של דוחות, טיוטות והערות.

הנתונים נשמרים בקובץ JSON אחד (ברירת מחדל ``state/reports_closure.json``),
וקבצי הטיוטות לצידו בתיקיית ``drafts``. הכתיבה אטומית - קודם לקובץ זמני ואז
``os.replace`` - כדי שנפילה באמצע כתיבה לא תשאיר קובץ חצי-כתוב.

שני כללים שהמאגר אוכף ולא מאפשר לעקוף:

* **אין סגירת הערה בלי תשובה** - ``mark_done`` דורש טקסט תשובה.
* **אין סגירת דוח כל עוד נותרה הערה פתוחה**, ורק אחרי שנטענה טיוטה
  ונרשמו הערות.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from .models import (
    NOTE_CANCELLED,
    NOTE_DONE,
    NOTE_OPEN,
    NOTE_STATUS_LABELS,
    REPORT_CLOSED,
    REPORT_OPEN,
    SEV_MEDIUM,
    STAGE_AWAITING_NOTES,
    STAGE_NO_DRAFT,
    ClosureError,
    Draft,
    Note,
    Report,
    normalize_severity,
    now_iso,
    parse_amount,
)
from .parser import parse_notes_text

SCHEMA_VERSION = 2


class ClosureStore:
    """מאגר הדוחות. מופע אחד לאפליקציה; בטוח לשימוש ממספר בקשות במקביל."""

    def __init__(self, path: str | os.PathLike = "state/reports_closure.json"):
        self.path = Path(path)
        self.drafts_dir = self.path.parent / "drafts"
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
        report_type: str = "דוחות כספיים",
        prepared_by: str = "",
        created_by: str = "",
    ) -> Report:
        client_name = (client_name or "").strip()
        if not client_name:
            raise ClosureError("חובה להזין שם לקוח.")
        report = Report(
            client_name=client_name,
            period=(period or "").strip(),
            client_id=(client_id or "").strip(),
            report_type=(report_type or "דוחות כספיים").strip(),
            prepared_by=(prepared_by or "").strip(),
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
        shutil.rmtree(self.drafts_dir / report_id, ignore_errors=True)

    def close_report(self, report_id: str, by: str = "") -> Report:
        """סוגר דוח. נכשל כשאין טיוטה, כשלא נרשמו הערות, או כשנותרה הערה פתוחה."""

        def mutate(report: Report) -> None:
            if report.is_closed:
                raise ClosureError("הדוח כבר סגור.")
            if report.stage == STAGE_NO_DRAFT:
                raise ClosureError("לא ניתן לסגור: טרם נטענה טיוטה.")
            if report.stage == STAGE_AWAITING_NOTES:
                raise ClosureError("לא ניתן לסגור: טרם נרשמו הערות על הטיוטה.")
            if report.open_count:
                raise ClosureError(
                    f"לא ניתן לסגור: {report.open_count} הערות עדיין ממתינות לתשובה."
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
    # טיוטות
    # ------------------------------------------------------------------

    def draft_path(self, report_id: str, stored_name: str) -> Path:
        return self.drafts_dir / report_id / stored_name

    def add_draft(
        self,
        report_id: str,
        filename: str,
        content: bytes,
        uploaded_by: str = "",
        note: str = "",
        stored_name: str | None = None,
    ) -> Draft:
        """שומר טיוטה חדשה. כל טעינה היא גרסה נוספת - הקודמות נשמרות."""
        filename = (filename or "").strip()
        if not filename:
            raise ClosureError("לא נבחר קובץ טיוטה.")
        if not content:
            raise ClosureError("קובץ הטיוטה ריק.")

        report = self.get_report(report_id)
        version = len(report.drafts) + 1
        suffix = Path(filename).suffix.lower()[:10]
        stored = stored_name or f"v{version}-{now_iso()[:10]}{suffix}"

        target = self.draft_path(report_id, stored)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

        draft = Draft(
            filename=filename,
            stored_name=stored,
            version=version,
            uploaded_by=uploaded_by,
            note=(note or "").strip(),
            size=len(content),
        )

        def mutate(report: Report) -> None:
            report.drafts.append(draft)

        self._mutate_report(report_id, mutate)
        return draft

    # ------------------------------------------------------------------
    # הערות
    # ------------------------------------------------------------------

    def add_note(
        self,
        report_id: str,
        text: str,
        topic: str = "",
        severity: str = SEV_MEDIUM,
        impact: str = "",
        recommendation: str = "",
        reference: str = "",
        assignee: str = "",
        amount=None,
        source: str = "",
        created_by: str = "",
    ) -> Note:
        text = (text or "").strip()
        if not text:
            raise ClosureError("חובה להזין את תוכן ההערה.")
        note = Note(
            text=text,
            topic=(topic or "").strip(),
            severity=normalize_severity(severity),
            impact=(impact or "").strip(),
            recommendation=(recommendation or "").strip(),
            reference=(reference or "").strip(),
            assignee=(assignee or "").strip(),
            amount=parse_amount(amount),
            source=(source or "").strip(),
            created_by=created_by,
        )

        def mutate(report: Report) -> None:
            self._reopen_if_closed(report)
            report.notes.append(note)

        self._mutate_report(report_id, mutate)
        return note

    def import_notes(
        self,
        report_id: str,
        raw_text: str,
        source: str = "",
        created_by: str = "",
        default_topic: str = "",
    ) -> list[Note]:
        """קולט טבלת הערות או רשימת הערות שהודבקה. מחזיר את ההערות שנוספו."""
        parsed = parse_notes_text(raw_text, default_topic=default_topic)
        if not parsed:
            raise ClosureError("לא נמצאו הערות בטקסט שהודבק.")
        added = [
            Note(
                text=item["text"],
                topic=item.get("topic", ""),
                severity=normalize_severity(item.get("severity")),
                impact=item.get("impact", ""),
                recommendation=item.get("recommendation", ""),
                reference=item.get("reference", ""),
                amount=item.get("amount"),
                source=source,
                created_by=created_by,
            )
            for item in parsed
        ]

        def mutate(report: Report) -> None:
            self._reopen_if_closed(report)
            report.notes.extend(added)

        self._mutate_report(report_id, mutate)
        return added

    def mark_done(self, report_id: str, note_id: str, by: str = "", answer: str = "") -> Note:
        """מסמן הערה כבוצעה. **חובה תשובה** - בלעדיה הפעולה נדחית."""
        if not (answer or "").strip():
            raise ClosureError(
                "חובה לרשום תשובה להערה לפני סימונה כבוצעה. "
                "מה נבדק, מה תוקן, או מהי התשובה לשאלה?"
            )
        return self._set_note_status(report_id, note_id, NOTE_DONE, by, answer)

    def cancel_note(self, report_id: str, note_id: str, by: str = "", answer: str = "") -> Note:
        """מבטל הערה שאינה רלוונטית. גם כאן נדרש נימוק - למה ירדה בלי טיפול."""
        if not (answer or "").strip():
            raise ClosureError("חובה לנמק מדוע ההערה אינה רלוונטית.")
        return self._set_note_status(report_id, note_id, NOTE_CANCELLED, by, answer)

    def reopen_note(self, report_id: str, note_id: str, by: str = "") -> Note:
        """מחזיר הערה לרשימת הפתוחות. התשובה הקודמת נשמרת בהיסטוריה."""
        return self._set_note_status(report_id, note_id, NOTE_OPEN, by, "")

    def _set_note_status(
        self, report_id: str, note_id: str, status: str, by: str, answer: str
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
            previous_answer = note.answer
            note.status = status
            if status == NOTE_OPEN:
                note.answer = ""
                note.answered_at = None
                note.answered_by = ""
            else:
                note.answer = (answer or "").strip()
                note.answered_at = now_iso()
                note.answered_by = by
            note.history.append(
                {
                    "at": now_iso(),
                    "by": by,
                    "from": previous,
                    "to": status,
                    "answer": (answer or "").strip() or previous_answer,
                }
            )
            if status == NOTE_OPEN:
                self._reopen_if_closed(report)
            result["note"] = note

        self._mutate_report(report_id, mutate)
        return result["note"]

    # ------------------------------------------------------------------
    # הנחיות סקירה קבועות
    # ------------------------------------------------------------------

    def get_guidelines(self) -> list[str]:
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

    @staticmethod
    def _reopen_if_closed(report: Report) -> None:
        """הערה חדשה או הערה שנפתחה מחדש מחזירות דוח סגור לטיפול."""
        if report.is_closed:
            report.status = REPORT_OPEN
            report.closed_at = None
            report.closed_by = ""

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
            "awaiting_notes": sum(
                1 for r in open_reports if r.stage == STAGE_AWAITING_NOTES
            ),
            "awaiting_draft": sum(1 for r in open_reports if r.stage == STAGE_NO_DRAFT),
        }
