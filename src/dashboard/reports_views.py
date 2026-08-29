"""מסלולי מערכת סקירת וסגירת הדוחות הכספיים.

כתובת הבסיס: ``/reports``. כל המסלולים דורשים משתמש מחובר, וכל פעולה
שמשנה נתונים היא POST עם טוקן CSRF - כדי שקישור חיצוני לא יוכל לסמן
הערה כבוצעה בשם המשתמש המחובר.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from ..reports_closure import (
    KNOWN_TOPICS,
    NOTE_STATUS_LABELS,
    REPORT_CLOSED,
    REPORT_OPEN,
    REPORT_STATUS_LABELS,
    SEVERITY_LABELS,
    STAGE_LABELS,
    ClosureError,
)
from .auth import login_required, validate_csrf

try:  # אזור זמן ישראל להצגת תאריכים; אם חסר tzdata - נופלים ל-UTC
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo("Asia/Jerusalem")
except Exception:  # pragma: no cover - תלוי בסביבת ההרצה
    _TZ = timezone.utc

bp = Blueprint("reports", __name__, url_prefix="/reports")

REPORT_TYPES = ["דוחות כספיים", "דוח רבעוני", "מאזן בוחן", "דוח למוסדות", "אחר"]

# סוגי קבצים מותרים לטיוטה. רשימה סגורה - לא מעלים לשרת מה שלא צריך.
ALLOWED_DRAFT_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv",
    ".png", ".jpg", ".jpeg", ".txt",
}


def store():
    return current_app.config["CLOSURE_STORE"]


def _actor() -> str:
    return (g.user or {}).get("display_name") or (g.user or {}).get("username", "")


def _require_csrf() -> None:
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400, "טוקן אבטחה לא תקין. רעננו את העמוד ונסו שוב.")


@bp.app_template_filter("dt")
def format_dt(value: str | None) -> str:
    """מציג חותמת זמן ISO בשעון ישראל, בפורמט קריא."""
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_TZ).strftime("%d/%m/%Y %H:%M")


@bp.app_template_filter("ils")
def format_ils(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):,.0f} ₪"
    except (TypeError, ValueError):
        return str(value)


@bp.app_template_filter("filesize")
def format_filesize(value) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size:,.0f} {unit}" if unit == "B" else f"{size:,.1f} {unit}"
        size /= 1024
    return ""


@bp.app_context_processor
def inject_labels():
    return {
        "SEVERITY_LABELS": SEVERITY_LABELS,
        "NOTE_STATUS_LABELS": NOTE_STATUS_LABELS,
        "REPORT_STATUS_LABELS": REPORT_STATUS_LABELS,
        "STAGE_LABELS": STAGE_LABELS,
        "KNOWN_TOPICS": KNOWN_TOPICS,
        "REPORT_TYPES": REPORT_TYPES,
    }


# ----------------------------------------------------------------------
# רשימת הדוחות
# ----------------------------------------------------------------------


@bp.route("/")
@login_required
def index():
    status = request.args.get("status", REPORT_OPEN)
    if status not in (REPORT_OPEN, REPORT_CLOSED, "all"):
        status = REPORT_OPEN
    query = request.args.get("q", "").strip()
    reports = store().list_reports(
        status=None if status == "all" else status, query=query
    )
    return render_template(
        "reports/index.html",
        reports=reports,
        summary=store().summary(),
        status=status,
        query=query,
    )


@bp.route("/new", methods=["POST"])
@login_required
def new_report():
    _require_csrf()
    try:
        report = store().add_report(
            client_name=request.form.get("client_name", ""),
            period=request.form.get("period", ""),
            client_id=request.form.get("client_id", ""),
            report_type=request.form.get("report_type", "דוחות כספיים"),
            prepared_by=request.form.get("prepared_by", ""),
            created_by=_actor(),
        )
    except ClosureError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports.index"))
    flash(f"נפתח דוח חדש: {report.title}. השלב הבא — טעינת הטיוטה.", "success")
    return redirect(url_for("reports.detail", report_id=report.id))


# ----------------------------------------------------------------------
# דוח בודד
# ----------------------------------------------------------------------


@bp.route("/<report_id>")
@login_required
def detail(report_id: str):
    try:
        report = store().get_report(report_id)
    except ClosureError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports.index"))
    return render_template(
        "reports/detail.html",
        report=report,
        guidelines=store().get_guidelines(),
    )


# --- שלב 1: טעינת הטיוטה ---


@bp.route("/<report_id>/draft", methods=["POST"])
@login_required
def upload_draft(report_id: str):
    _require_csrf()
    uploaded = request.files.get("draft")
    if uploaded is None or not uploaded.filename:
        flash("לא נבחר קובץ טיוטה.", "error")
        return redirect(url_for("reports.detail", report_id=report_id))

    suffix = Path(uploaded.filename).suffix.lower()
    if suffix not in ALLOWED_DRAFT_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_DRAFT_SUFFIXES))
        flash(f"סוג קובץ לא נתמך ({suffix or 'ללא סיומת'}). מותר: {allowed}", "error")
        return redirect(url_for("reports.detail", report_id=report_id))

    try:
        draft = store().add_draft(
            report_id,
            filename=uploaded.filename,
            content=uploaded.read(),
            uploaded_by=_actor(),
            note=request.form.get("note", ""),
        )
        flash(f"נטענה טיוטה (גרסה {draft.version}). השלב הבא — רישום ההערות.", "success")
    except ClosureError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reports.detail", report_id=report_id))


@bp.route("/<report_id>/draft/<int:version>")
@login_required
def download_draft(report_id: str, version: int):
    try:
        report = store().get_report(report_id)
    except ClosureError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports.index"))

    draft = next((d for d in report.drafts if d.version == version), None)
    if draft is None:
        abort(404)
    path = store().draft_path(report_id, draft.stored_name)
    if not path.exists():
        flash("קובץ הטיוטה חסר מהדיסק.", "error")
        return redirect(url_for("reports.detail", report_id=report_id))
    return send_file(path, as_attachment=True, download_name=draft.filename)


# --- שלב 2: רישום ההערות ---


@bp.route("/<report_id>/notes", methods=["POST"])
@login_required
def add_note(report_id: str):
    _require_csrf()
    try:
        store().add_note(
            report_id,
            text=request.form.get("text", ""),
            topic=request.form.get("topic", ""),
            severity=request.form.get("severity", "medium"),
            impact=request.form.get("impact", ""),
            recommendation=request.form.get("recommendation", ""),
            reference=request.form.get("reference", ""),
            assignee=request.form.get("assignee", ""),
            amount=request.form.get("amount", ""),
            source=request.form.get("source", ""),
            created_by=_actor(),
        )
        flash("ההערה נוספה.", "success")
    except ClosureError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reports.detail", report_id=report_id))


@bp.route("/<report_id>/import", methods=["POST"])
@login_required
def import_notes(report_id: str):
    _require_csrf()
    try:
        added = store().import_notes(
            report_id,
            raw_text=request.form.get("raw_text", ""),
            source=request.form.get("source", "").strip() or "טבלת הערות סקירה",
            created_by=_actor(),
        )
        flash(f"נקלטו {len(added)} הערות.", "success")
    except ClosureError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reports.detail", report_id=report_id))


# --- שלב 3: תשובות וסגירה ---


@bp.route("/<report_id>/notes/<note_id>/<action>", methods=["POST"])
@login_required
def note_action(report_id: str, note_id: str, action: str):
    """מענה להערה (בוצע), ביטולה, או החזרתה לרשימת הממתינות."""
    _require_csrf()
    answer = request.form.get("answer", "")
    actions = {
        "done": lambda: store().mark_done(report_id, note_id, _actor(), answer),
        "cancel": lambda: store().cancel_note(report_id, note_id, _actor(), answer),
        "reopen": lambda: store().reopen_note(report_id, note_id, _actor()),
    }
    if action not in actions:
        abort(404)
    messages = {
        "done": "התשובה נרשמה. ההערה סומנה כבוצעה וירדה מהרשימה.",
        "cancel": "ההערה בוטלה עם נימוק וירדה מהרשימה.",
        "reopen": "ההערה הוחזרה לרשימת הממתינות לתשובה.",
    }
    try:
        actions[action]()
        flash(messages[action], "success")
    except ClosureError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reports.detail", report_id=report_id))


@bp.route("/<report_id>/close", methods=["POST"])
@login_required
def close_report(report_id: str):
    _require_csrf()
    try:
        store().close_report(report_id, by=_actor())
        flash("הדוח נסגר סופית. כל ההערות נענו.", "success")
    except ClosureError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reports.detail", report_id=report_id))


@bp.route("/<report_id>/reopen", methods=["POST"])
@login_required
def reopen_report(report_id: str):
    _require_csrf()
    try:
        store().reopen_report(report_id, by=_actor())
        flash("הדוח הוחזר לטיפול.", "success")
    except ClosureError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reports.detail", report_id=report_id))


@bp.route("/<report_id>/export.txt")
@login_required
def export_open_notes(report_id: str):
    """מייצא את ההערות שממתינות לתשובה - להעברה למי שמכין את הטיוטה."""
    try:
        report = store().get_report(report_id)
    except ClosureError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports.index"))

    lines = [
        f"הערות הממתינות לתשובה - {report.title} ({report.report_type})",
        f"שלב: {report.stage_label}",
        "=" * 60,
    ]
    if not report.open_notes:
        lines.append("אין הערות פתוחות. כל ההערות נענו.")
    for index, note in enumerate(report.sorted_open_notes(), start=1):
        severity = SEVERITY_LABELS.get(note.severity, note.severity)
        header = f"{index}. [{severity}]"
        if note.topic:
            header += f" {note.topic}"
        lines.append(header)
        lines.append(f"   הממצא: {note.text}")
        if note.impact:
            lines.append(f"   השלכה: {note.impact}")
        if note.recommendation:
            lines.append(f"   המלצה: {note.recommendation}")
        if note.reference:
            lines.append(f"   הפניה: {note.reference}")
        lines.append("   תשובה: ______________________________")
        lines.append("")
    body = "\n".join(lines) + "\n"
    return Response(
        body,
        mimetype="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="open-notes-{report.id}.txt"'
        },
    )


# ----------------------------------------------------------------------
# הנחיות סקירה קבועות
# ----------------------------------------------------------------------


@bp.route("/guidelines", methods=["GET", "POST"])
@login_required
def guidelines():
    if request.method == "POST":
        _require_csrf()
        lines = store().set_guidelines(request.form.get("guidelines", ""))
        flash(f"נשמרו {len(lines)} הנחיות.", "success")
        return redirect(url_for("reports.guidelines"))
    return render_template("reports/guidelines.html", guidelines=store().get_guidelines())
