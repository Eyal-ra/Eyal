"""
דשבורד web פנימי לצוות.

אפליקציית Flask קטנה שעוטפת את כלי סנכרון הלקוחות ומספקת:
  - מסך כניסה (login) פנימי
  - הצגת שם המשתמש המחובר בכל עמוד
  - כפתור יציאה (logout)

ההפעלה: ``python -m src.dashboard`` (קורא הגדרות מ-config.yaml).
"""

import os
import secrets
from pathlib import Path

import yaml
from flask import Flask


def load_config(path=None) -> dict:
    """טוען את config.yaml. אם אין קובץ - מחזיר מילון ריק (האפליקציה עדיין עולה)."""
    path = Path(path or os.environ.get("DASHBOARD_CONFIG", "config.yaml"))
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)

    cfg = config if config is not None else load_config()
    app.config["APP_CONFIG"] = cfg

    dash_cfg = cfg.get("dashboard", {}) or {}
    secret = dash_cfg.get("secret_key") or os.environ.get("DASHBOARD_SECRET_KEY")
    if not secret:
        # מפתח אקראי - מאפשר הרצה ללא הגדרה, אבל ה-sessions יתאפסו בכל הפעלה מחדש.
        secret = secrets.token_hex(32)
        app.logger.warning(
            "לא הוגדר dashboard.secret_key - נוצר מפתח אקראי זמני. "
            "הגדר secret_key קבוע ב-config.yaml כדי לשמור על חיבורי משתמשים בין הפעלות."
        )
    app.config["SECRET_KEY"] = secret

    # הקשחת עוגיית ה-session: לא נגישה ל-JavaScript ולא נשלחת בבקשות חוצות-אתר.
    # Secure נשאר כבוי כי הדשבורד מוגש פנימית מעל HTTP (בלי HTTPS).
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    from .views import bp

    app.register_blueprint(bp)
    return app
