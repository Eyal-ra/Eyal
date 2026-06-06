"""הוספת כתובת ידידותית (למשל cpateam-dash) לקובץ ה-hosts.

מאחר שהכל פנימי, כדי שעובד יוכל לרשום בדפדפן כתובת פשוטה כמו
``http://cpateam-dash`` במקום מספר ID/IP ארוך - מוסיפים שורה לקובץ ה-hosts
שממפה את השם הידידותי לכתובת ה-IP של המחשב שמריץ את הדשבורד.

שימוש (דורש הרשאות מנהל):
    Windows (PowerShell כ-Administrator):
        python scripts/setup_hostname.py
        python scripts/setup_hostname.py --name cpateam-dash --ip 192.168.1.50
    Linux/Mac (sudo):
        sudo python scripts/setup_hostname.py

ברירת מחדל: ממפה את השם ל-127.0.0.1 (גישה מהמחשב המקומי בלבד).
כדי לאפשר גישה לעובדים אחרים ברשת - העבירו --ip עם כתובת ה-IP ברשת המקומית
של המחשב שמריץ את השרת.
"""

import argparse
import platform
from pathlib import Path

MARKER = "# added by cpateam dashboard setup_hostname.py"


def hosts_path() -> Path:
    if platform.system() == "Windows":
        return Path(r"C:\Windows\System32\drivers\etc\hosts")
    return Path("/etc/hosts")


def main() -> None:
    parser = argparse.ArgumentParser(description="הוספת כתובת ידידותית לקובץ ה-hosts")
    parser.add_argument("--name", default="cpateam-dash", help="השם הידידותי (ברירת מחדל: cpateam-dash)")
    parser.add_argument("--ip", default="127.0.0.1", help="כתובת ה-IP של מחשב השרת (ברירת מחדל: 127.0.0.1)")
    args = parser.parse_args()

    path = hosts_path()
    entry = f"{args.ip}\t{args.name}\t{MARKER}"

    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except PermissionError:
        raise SystemExit(
            f"אין הרשאת קריאה ל-{path}. הריצו כמנהל (Administrator / sudo)."
        )

    # הסרת שורות קודמות של אותו שם שיצרנו, כדי לאפשר עדכון IP.
    kept = [
        ln
        for ln in existing.splitlines()
        if not (MARKER in ln and f"\t{args.name}\t" in f"{ln}\t")
    ]
    kept.append(entry)
    new_content = "\n".join(kept).rstrip("\n") + "\n"

    try:
        path.write_text(new_content, encoding="utf-8")
    except PermissionError:
        raise SystemExit(
            f"אין הרשאת כתיבה ל-{path}. הריצו כמנהל (Administrator / sudo)."
        )

    print(f"נוסף/עודכן: {args.name} -> {args.ip}")
    print(f"כעת ניתן לגשת בדפדפן אל: http://{args.name}")


if __name__ == "__main__":
    main()
