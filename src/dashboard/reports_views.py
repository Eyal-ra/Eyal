"""מסלולי מערכת סגירת הדוחות הכספיים בדשבורד.

כתובת הבסיס: ``/reports``. כל המסלולים דורשים משתמש מחובר, וכל פעולה
שמשנה נתונים היא POST עם טוקן CSRF - כדי שקישור חיצוני לא יוכל לסמן
הערה כבוצעה בשם המשתמש המחובר.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
    url_for,
)

from ..reports_closure import (
    CATEGORIES,
    NOTE_STATUS_LABELS,
    REPORT_CLOSED,
    REPORT_OPEN,
    REPORT_STATUS_LABELS,
    SEVERITY_LABELS,
    ClosureError,
)
from .auth import login_required, validate_csrf

try:  # אזור זמן ישראל להצגת תאריכים; אם חסר tzdata - נופלים ל-UTC
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo("Asia/Jerusalem")
except Exception:  # pragma: no cover - תלוי בסביבת ההרצה
    _TZ = timezone.utc

bp = Blueprint("reports", __name__, url_prefix="/reports")

REPORT_TYPES = ["דוח שנתי", "דוח רבעוני", "מאזן בוחן", "דוח למוסדות", "אחר"]


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
    """סכום בשקלים עם מפריד אלפים. ריק כשאין סכום."""
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):,.0f} ₪"
    except (TypeError, ValueError):
        return str(value)


@bp.app_context_processor
def inject_labels():
    return {
        "SEVERITY_LABELS": SEVERITY_LABELS,
        "NOTE_STATUS_LABELS": NOTE_STATUS_LABELS,
        "REPORT_STATUS_LABELS": REPORT_STATUS_LABELS,
        "CATEGORIES": CATEGORIES,
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
            report_type=request.form.get("report_type", "דוח שנתי"),
            created_by=_actor(),
        )
    except ClosureError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports.index"))
    flash(f"נפתח דוח חדש: {report.title}", "success")
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


@bp.route("/<report_id>/notes", methods=["POST"])
@login_required
def add_note(report_id: str):
    _require_csrf()
    try:
        store().add_note(
            report_id,
            text=request.form.get("text", ""),
            category=request.form.get("category", "כללי"),
            severity=request.form.get("severity", "normal"),
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
            source=request.form.get("source", "").strip() or "ייבוא הערות סקירה",
            created_by=_actor(),
        )
        flash(f"נקלטו {len(added)} הערות.", "success")
    except ClosureError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reports.detail", report_id=report_id))


@bp.route("/<report_id>/notes/<note_id>/<action>", methods=["POST"])
@login_required
def note_action(report_id: str, note_id: str, action: str):
    """סימון הערה כבוצעה / ביטולה / החזרתה לפתוחות."""
    _require_csrf()
    comment = request.form.get("comment", "")
    actions = {
        "done": lambda: store().mark_done(report_id, note_id, _actor(), comment),
        "cancel": lambda: store().cancel_note(report_id, note_id, _actor(), comment),
        "reopen": lambda: store().reopen_note(report_id, note_id, _actor()),
    }
    if action not in actions:
        abort(404)
    messages = {
        "done": "ההערה סומנה כבוצעה וירדה מהרשימה.",
        "cancel": "ההערה בוטלה וירדה מהרשימה.",
        "reopen": "ההערה הוחזרה לרשימת הפתוחות.",
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
        flash("הדוח נסגר. כל ההערות טופלו.", "success")
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
    """מייצא את ההערות הפתוחות כטקסט - להעברה ללקוח או לעובד."""
    try:
        report = store().get_report(report_id)
    except ClosureError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports.index"))

    lines = [f"הערות פתוחות - {report.title} ({report.report_type})", "=" * 50]
    if not report.open_notes:
        lines.append("אין הערות פתוחות. הדוח מוכן לסגירה.")
    for index, note in enumerate(report.sorted_open_notes(), start=1):
        amount = f" [{format_ils(note.amount)}]" if note.amount is not None else ""
        marker = "!" if note.severity == "critical" else ""
        lines.append(f"{index}. {marker}[{note.category}] {note.text}{amount}")
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
