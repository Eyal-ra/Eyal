"""מסלולי (routes) הדשבורד: כניסה, יציאה ועמוד ראשי."""

from flask import (
    Blueprint,
    current_app,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .auth import (
    find_user,
    get_csrf_token,
    get_users,
    login_required,
    validate_csrf,
    verify_password,
)

bp = Blueprint("dashboard", __name__)


@bp.app_context_processor
def inject_csrf_token():
    """מאפשר לתבניות לקרוא ל-csrf_token() כדי להטמיע את הטוקן בטפסים."""
    return {"csrf_token": get_csrf_token}


@bp.before_app_request
def load_logged_in_user():
    """טוען את פרטי המשתמש המחובר ל-g.user כך שכל עמוד יוכל להציג מי מחובר."""
    username = session.get("username")
    g.user = None
    if username:
        user = find_user(get_users(current_app.config["APP_CONFIG"]), username)
        if user:
            g.user = {
                "username": user["username"],
                "display_name": user.get("display_name") or user["username"],
            }
        else:
            # המשתמש הוסר מההגדרות - מנתקים אותו.
            session.clear()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard.index"))

    error = None
    if request.method == "POST":
        if not validate_csrf(request.form.get("csrf_token")):
            error = "טוקן אבטחה לא תקין. רעננו את העמוד ונסו שוב."
            return render_template("login.html", error=error)
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users = get_users(current_app.config["APP_CONFIG"])
        user = find_user(users, username)
        if user and verify_password(user, password):
            session.clear()
            session["username"] = user["username"]
            nxt = request.args.get("next", "")
            # מגנים מפני open-redirect: מקבלים רק נתיב פנימי.
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("dashboard.index")
            return redirect(nxt)
        error = "שם משתמש או סיסמה שגויים"

    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("dashboard.login"))


@bp.route("/")
@login_required
def index():
    submissions, data_error = _load_recent_submissions(current_app.config["APP_CONFIG"])
    return render_template("index.html", submissions=submissions, data_error=data_error)


def _load_recent_submissions(app_config: dict, limit: int = 10):
    """מנסה למשוך הגשות אחרונות מ-Jotform. מחזיר (רשימה, הודעת_שגיאה_או_None).

    הפונקציה מתגוננת: אם Jotform לא מוגדר או שיש תקלת רשת - מחזירה רשימה ריקה
    והודעה ידידותית במקום להפיל את העמוד.
    """
    jot_cfg = app_config.get("jotform") or {}
    api_key = jot_cfg.get("api_key", "")
    if not api_key or api_key.startswith("YOUR_"):
        return [], "Jotform עדיין לא מוגדר ב-config.yaml - אין נתונים להצגה."

    try:
        from ..jotform_client import JotformClient

        client = JotformClient(
            api_key=api_key,
            form_id=jot_cfg["form_id"],
            field_map=jot_cfg["field_map"],
            base_url=jot_cfg.get("base_url", "https://api.jotform.com"),
        )
        return list(client.fetch_submissions(limit=limit)), None
    except Exception as exc:  # תקלת רשת / הגדרה - לא מפילים את הדשבורד
        return [], f"שגיאה בשליפת הגשות מ-Jotform: {exc}"
