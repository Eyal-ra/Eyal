"""יצירת hash לסיסמה עבור config.yaml.

שימוש:
    python -m src.dashboard.hash_password
ואז הדביקו את הפלט לשדה password_hash של המשתמש ב-config.yaml.
"""

import getpass
import sys

from werkzeug.security import generate_password_hash


def main() -> None:
    if sys.stdin.isatty():
        pw = getpass.getpass("הקלד סיסמה: ")
        pw2 = getpass.getpass("הקלד שוב לאימות: ")
        if pw != pw2:
            sys.exit("הסיסמאות אינן תואמות.")
    else:
        pw = sys.stdin.readline().rstrip("\n")
    if not pw:
        sys.exit("סיסמה ריקה.")
    print(generate_password_hash(pw))


if __name__ == "__main__":
    main()
