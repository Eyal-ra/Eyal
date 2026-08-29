"""הוספת כרטיס "סקירת דוחות כספיים" ללוח הבקרה, אוטומטית.

הלוח הוא קובץ HTML על המחשב המקומי. הסקריפט מאתר בו כרטיס קיים, מזהה את
גבולות אלמנט הכרטיס, ומשתיל את הכרטיס החדש מיד אחריו - כך שהוא יורש את
אותו מיכל ואותו עיצוב, בלי להניח דבר על מבנה הלוח.

    python scripts/add_card_to_board.py --board "C:\\dash\\index.html"
    python scripts/add_card_to_board.py --board index.html --dry-run
    python scripts/add_card_to_board.py --board index.html --undo

לפני כל שינוי נשמר גיבוי ``<שם הקובץ>.bak``. הרצה חוזרת מחליפה את הכרטיס
הקיים במקום להוסיף אותו שוב.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

MARKER = 'data-system="reports-closure"'
DEFAULT_ANCHOR = "מעקב חשבוניות"
DEFAULT_URL = "http://eyal:9998/reports/"

CARD_TEMPLATE = """
<!-- סקירת דוחות כספיים - נוסף אוטומטית -->
<div class="system-card" {marker}>
  <div class="card-status">
    <span class="status-dot"></span>
    <span class="status-text">פעיל</span>
  </div>
  <div class="card-icon">📑</div>
  <h3 class="card-title">סקירת דוחות כספיים</h3>
  <p class="card-desc">
    טיוטה ← הערות סקירה ← תשובה לכל הערה ← סגירה סופית.
    הערה נסגרת רק עם תשובה כתובה, ודוח נסגר רק כשכל ההערות נענו.
  </p>
  <div class="card-actions">
    <a class="card-btn card-btn-primary" href="{url}">▶ פתח מערכת</a>
    <a class="card-btn" href="{guidelines_url}">הנחיות סקירה</a>
  </div>
</div>
<!-- סוף סקירת דוחות כספיים -->
"""


def fail(message: str) -> None:
    print(f"\n[X] {message}\n", file=sys.stderr)
    raise SystemExit(1)


def build_card(url: str) -> str:
    base = url.rstrip("/")
    guidelines = base + "/guidelines" if base.endswith("/reports") else base
    return CARD_TEMPLATE.format(marker=MARKER, url=url, guidelines_url=guidelines)


def block_end(html: str, start: int) -> int | None:
    """מוצא את סוף האלמנט שנפתח ב-``start``, בספירת div פתוחים וסגורים."""
    depth = 0
    pos = start
    pattern = re.compile(r"<\s*(/?)div\b[^>]*?(/?)>", re.IGNORECASE)
    while True:
        match = pattern.search(html, pos)
        if not match:
            return None
        closing, self_closing = match.group(1), match.group(2)
        if self_closing:
            pass  # <div/> - נפתח ונסגר באותו תג
        elif closing:
            depth -= 1
            if depth == 0:
                return match.end()
        else:
            depth += 1
        pos = match.end()


def find_card_bounds(html: str, anchor: str) -> tuple[int, int] | None:
    """מאתר את גבולות הכרטיס שמכיל את הטקסט ``anchor``.

    נבחר האב הקטן ביותר שמכיל גם את הטקסט וגם קישור או כפתור אחריו -
    כלומר הכרטיס עצמו, ולא הכותרת שבתוכו ולא כל המיכל של הקטגוריה.
    """
    text_at = html.find(anchor)
    if text_at == -1:
        return None

    candidates = [m.start() for m in re.finditer(r"<\s*div\b", html[:text_at], re.I)]
    for start in reversed(candidates):  # מהפנימי לחיצוני
        end = block_end(html, start)
        if end is None or end <= text_at:
            continue
        block = html[start:end]
        if re.search(r"<\s*(a|button)\b", block, re.I):
            return start, end
    return None


def bump_counter(html: str, before: int) -> tuple[str, str | None]:
    """מעלה ב-1 את מונה המערכות של הקטגוריה שמעל נקודת ההשתלה."""
    matches = list(re.finditer(r"(\d+)(\s*מערכות)", html[:before]))
    if not matches:
        return html, None
    last = matches[-1]
    count = int(last.group(1))
    updated = html[: last.start()] + f"{count + 1}{last.group(2)}" + html[last.end():]
    return updated, f"{count} -> {count + 1}"


def remove_existing(html: str) -> tuple[str, bool]:
    """מסיר כרטיס שנוסף בהרצה קודמת, כדי שהרצה חוזרת לא תכפיל אותו."""
    at = html.find(MARKER)
    if at == -1:
        return html, False
    start = html.rfind("<div", 0, at)
    end = block_end(html, start)
    if end is None:
        return html, False
    # מסירים גם את הערות הפתיחה והסגירה שמסביב
    comment_start = html.rfind("<!-- סקירת דוחות כספיים", 0, start)
    if comment_start != -1 and start - comment_start < 200:
        start = comment_start
    tail = html[end:]
    closing = "<!-- סוף סקירת דוחות כספיים -->"
    if tail.lstrip().startswith(closing):
        end += tail.index(closing) + len(closing)
    return html[:start] + html[end:], True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="הוספת כרטיס ללוח הבקרה")
    parser.add_argument("--board", required=True, help="נתיב קובץ ה-HTML של הלוח")
    parser.add_argument(
        "--anchor", default=DEFAULT_ANCHOR,
        help=f"טקסט של כרטיס קיים שאחריו יושתל הכרטיס (ברירת מחדל: {DEFAULT_ANCHOR})",
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="כתובת המערכת")
    parser.add_argument("--dry-run", action="store_true", help="להציג בלי לשנות")
    parser.add_argument("--undo", action="store_true", help="שחזור מהגיבוי")
    args = parser.parse_args(argv)

    board = Path(args.board)
    if not board.exists():
        fail(f"הקובץ לא נמצא: {board}")
    backup = board.with_suffix(board.suffix + ".bak")

    if args.undo:
        if not backup.exists():
            fail(f"אין גיבוי לשחזור ({backup.name}).")
        shutil.copy2(backup, board)
        print(f"\n[V] הלוח שוחזר מהגיבוי {backup.name}.\n")
        return 0

    html = board.read_text(encoding="utf-8")

    html, replaced = remove_existing(html)
    if replaced:
        print("  נמצא כרטיס קיים מהרצה קודמת - יוחלף.")

    bounds = find_card_bounds(html, args.anchor)
    if bounds is None:
        fail(
            f"לא נמצא כרטיס שמכיל את הטקסט '{args.anchor}'.\n"
            "    העבירו --anchor עם טקסט שמופיע בכרטיס קיים בלוח,\n"
            "    למשל:  --anchor \"מאזני בוחן\""
        )
    _, insert_at = bounds
    card = build_card(args.url)
    updated = html[:insert_at] + "\n" + card + html[insert_at:]

    # המונה עולה רק בהוספה אמיתית. החלפת כרטיס קיים אינה מוסיפה מערכת.
    counter = None
    if not replaced:
        updated, counter = bump_counter(updated, insert_at)

    print(f"\n  לוח:      {board}")
    print(f"  אחרי:     הכרטיס שמכיל '{args.anchor}'")
    print(f"  מפנה אל:  {args.url}")
    if counter:
        print(f"  מונה הקטגוריה: {counter}")
    elif replaced:
        print("  מונה הקטגוריה: לא שונה (החלפת כרטיס קיים)")
    else:
        print("  מונה הקטגוריה: לא נמצא, לא שונה")

    if args.dry_run:
        print("\n  --dry-run: לא בוצע שינוי. הכרטיס שהיה מושתל:\n")
        print(card)
        return 0

    if not replaced:
        shutil.copy2(board, backup)
        print(f"  גיבוי:    {backup.name}")
    board.write_text(updated, encoding="utf-8")
    print("\n[V] הכרטיס נוסף. רעננו את הלוח בדפדפן (Ctrl+F5).")
    print(f"    לביטול:  python scripts/add_card_to_board.py --board \"{board}\" --undo\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
