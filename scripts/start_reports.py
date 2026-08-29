"""הפעלת מערכת סקירת וסגירת הדוחות הכספיים - כשרת עצמאי על פורט משלה.

הלוח הראשי (9999) הוא מערכת נפרדת; המערכת הזו עולה לצידו על פורט משלה,
וכרטיס בלוח מפנה אליה. הכתובת הבסיסית מובילה ישר למסך הדוחות.

    python scripts/start_reports.py              # http://localhost:9998
    python scripts/start_reports.py --port 9997

בהרצה ראשונה, אם אין עדיין config.yaml, הסקריפט מבקש שם משתמש וסיסמה
בדיוק כמו start_dashboard.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DEFAULT_PORT = 9998


def main(argv=None) -> int:
    from start_dashboard import (  # noqa: E402 - נטען אחרי עדכון sys.path
        CONFIG,
        check_config_is_usable,
        check_dependencies,
        create_config,
        fail,
        reset_user,
    )

    parser = argparse.ArgumentParser(description="מערכת סקירת וסגירת דוחות כספיים")
    parser.add_argument("--port", type=int, help=f"פורט (ברירת מחדל {DEFAULT_PORT})")
    parser.add_argument("--host", help="כתובת האזנה")
    parser.add_argument("--reset-user", action="store_true", help="החלפת סיסמה")
    args = parser.parse_args(argv)

    check_dependencies()

    if not CONFIG.exists():
        create_config()
    elif args.reset_user:
        reset_user()
    else:
        check_config_is_usable()

    from flask import redirect, url_for

    from src.dashboard import create_app, load_config

    cfg = load_config(CONFIG)
    closure_cfg = cfg.get("reports_closure", {}) or {}
    host = args.host or closure_cfg.get("host", "0.0.0.0")
    port = args.port or int(closure_cfg.get("port", DEFAULT_PORT))

    app = create_app(cfg)

    # השורש של השרת הזה הוא מערכת הדוחות, לא עמוד הבית של הדשבורד הכללי.
    app.add_url_rule(
        "/",
        endpoint="reports_root",
        view_func=lambda: redirect(url_for("reports.index")),
    )

    print()
    print("=" * 60)
    print("  מערכת סקירת וסגירת דוחות כספיים")
    print(f"      http://localhost:{port}")
    if host == "0.0.0.0":
        print(f"  ממחשב אחר במשרד:  http://<שם-המחשב-הזה>:{port}")
    print()
    print("  לעצירה: Ctrl+C")
    print("=" * 60)
    print()

    try:
        app.run(host=host, port=port)
    except OSError as exc:
        fail(
            f"לא ניתן להאזין על פורט {port}: {exc}\n"
            f"    ייתכן שהפורט תפוס. נסו:  python scripts/start_reports.py --port 9997"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
