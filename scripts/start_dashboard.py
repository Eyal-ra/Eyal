"""הפעלת הדשבורד בפקודה אחת.

הסקריפט עושה את כל ההכנה שצריך פעם אחת, ואז מעלה את השרת:

* בודק שהספריות הדרושות מותקנות, ואם לא - אומר בדיוק מה להריץ.
* יוצר ``config.yaml`` אם אינו קיים, עם מפתח אקראי למערכת.
* מבקש שם משתמש וסיסמה, ושומר את הסיסמה כ-hash (לא בטקסט גלוי).
* מעלה את הדשבורד ומדפיס את הכתובת.

    python scripts/start_dashboard.py

הרצה חוזרת פשוט מעלה את השרת - ההגדרות כבר קיימות. ``--reset-user``
מאפשר להחליף סיסמה, ו-``--port`` להעלות על פורט אחר לפעם אחת.
"""

from __future__ import annotations

import argparse
import getpass
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"
EXAMPLE = ROOT / "config.example.yaml"

SECRET_PLACEHOLDER = "CHANGE_ME_TO_A_LONG_RANDOM_STRING"
HASH_PLACEHOLDER = "PASTE_HASH_HERE"


def fail(message: str) -> None:
    print(f"\n[X] {message}\n", file=sys.stderr)
    raise SystemExit(1)


def check_dependencies() -> None:
    missing = []
    for module, package in (("flask", "Flask"), ("yaml", "PyYAML"), ("werkzeug", "Werkzeug")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        fail(
            "חסרות ספריות: " + ", ".join(missing) + "\n"
            "    הריצו:  pip install -r requirements.txt"
        )


def ask_password() -> str:
    """מבקש סיסמה פעמיים ומחזיר את ה-hash שלה."""
    from werkzeug.security import generate_password_hash

    while True:
        password = getpass.getpass("    סיסמה חדשה: ")
        if len(password) < 4:
            print("    הסיסמה קצרה מדי (לפחות 4 תווים).")
            continue
        if password != getpass.getpass("    שוב לאימות: "):
            print("    הסיסמאות אינן תואמות. שוב.")
            continue
        return generate_password_hash(password)


def create_config() -> None:
    """יוצר config.yaml מתוך הדוגמה, עם מפתח אקראי ומשתמש אמיתי."""
    if not EXAMPLE.exists():
        fail(f"קובץ הדוגמה {EXAMPLE.name} חסר. משכו מחדש את הפרויקט.")

    print("\n  הגדרה ראשונית של הדשבורד")
    print("  " + "-" * 40)
    username = input("    שם משתמש [eyal]: ").strip() or "eyal"
    display_name = input("    שם לתצוגה [אייל רייטר]: ").strip() or "אייל רייטר"
    password_hash = ask_password()

    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace(SECRET_PLACEHOLDER, secrets.token_hex(32))
    text = text.replace(HASH_PLACEHOLDER, password_hash)
    text = text.replace('- username: "eyal"', f'- username: "{username}"')
    text = text.replace(
        'display_name: "אייל רייטר"', f'display_name: "{display_name}"'
    )
    CONFIG.write_text(text, encoding="utf-8")
    print(f"\n  [V] נוצר {CONFIG.name} עם המשתמש '{username}'.")


def reset_user() -> None:
    """מחליף את הסיסמה של המשתמש הראשון בקובץ קיים."""
    text = CONFIG.read_text(encoding="utf-8")
    password_hash = ask_password()
    updated, count = re.subn(
        r'(password_hash:\s*)"[^"]*"', rf'\1"{password_hash}"', text, count=1
    )
    if not count:
        fail("לא נמצא שדה password_hash ב-config.yaml. ערכו אותו ידנית.")
    CONFIG.write_text(updated, encoding="utf-8")
    print("\n  [V] הסיסמה עודכנה.")


def check_config_is_usable() -> None:
    """מוודא שקובץ קיים אינו נשאר עם ערכי ברירת המחדל של הדוגמה."""
    text = CONFIG.read_text(encoding="utf-8")
    if HASH_PLACEHOLDER in text:
        print("\n  ב-config.yaml עדיין אין סיסמה. נגדיר אחת עכשיו.")
        reset_user()
        text = CONFIG.read_text(encoding="utf-8")
    if SECRET_PLACEHOLDER in text:
        CONFIG.write_text(
            text.replace(SECRET_PLACEHOLDER, secrets.token_hex(32)), encoding="utf-8"
        )
        print("  [V] נוצר מפתח אבטחה קבוע.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="הפעלת דשבורד הצוות")
    parser.add_argument("--port", type=int, help="פורט חלופי להפעלה זו")
    parser.add_argument(
        "--reset-user", action="store_true", help="החלפת הסיסמה של המשתמש"
    )
    args = parser.parse_args(argv)

    check_dependencies()
    sys.path.insert(0, str(ROOT))

    if not CONFIG.exists():
        create_config()
    elif args.reset_user:
        reset_user()
    else:
        check_config_is_usable()

    from src.dashboard import create_app, load_config

    cfg = load_config(CONFIG)
    dash = cfg.get("dashboard", {}) or {}
    host = dash.get("host", "0.0.0.0")
    port = args.port or int(dash.get("port", 9999))

    app = create_app(cfg)

    print()
    print("=" * 58)
    print("  הדשבורד פועל. פתחו בדפדפן:")
    print(f"      http://localhost:{port}")
    print("  סקירת וסגירת דוחות כספיים:")
    print(f"      http://localhost:{port}/reports")
    if host == "0.0.0.0":
        print(f"  ממחשב אחר במשרד: http://<שם-המחשב-הזה>:{port}")
    print()
    print("  לעצירה: Ctrl+C")
    print("=" * 58)
    print()

    try:
        app.run(host=host, port=port)
    except OSError as exc:
        fail(
            f"לא ניתן להאזין על פורט {port}: {exc}\n"
            f"    ייתכן שהפורט תפוס. נסו:  python scripts/start_dashboard.py --port 9998"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
