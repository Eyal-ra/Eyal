"""אימות משתמשים פנימי לדשבורד."""

import secrets
from functools import wraps

from flask import redirect, request, session, url_for
from werkzeug.security import check_password_hash


def get_users(app_config: dict) -> list[dict]:
    return (app_config.get("dashboard", {}) or {}).get("users", []) or []


def find_user(users: list[dict], username: str) -> dict | None:
    for user in users:
        if user.get("username") == username:
            return user
    return None


def verify_password(user: dict, password: str) -> bool:
    """בודק סיסמה מול המשתמש.

    עדיף password_hash (נוצר עם ``python -m src.dashboard.hash_password``).
    לנוחות, נתמכת גם סיסמה בטקסט גלוי בשדה ``password`` - לא מומלץ לפרודקשן.
    """
    pw_hash = user.get("password_hash")
    if pw_hash:
        return check_password_hash(pw_hash, password)
    plain = user.get("password")
    if plain is not None:
        return secrets.compare_digest(str(plain), password)
    return False


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("dashboard.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def get_csrf_token() -> str:
    """מחזיר טוקן CSRF לסשן הנוכחי, יוצר אחד אם אין."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf(submitted: str | None) -> bool:
    token = session.get("_csrf_token")
    return bool(token) and secrets.compare_digest(token, submitted or "")

