"""שורת פקודה למערכת סגירת הדוחות.

נועדה לשימוש מתוך סשן סקירה או סקריפט: אפשר להזרים הערות ישירות לתוך
המערכת בלי לעבור דרך הדשבורד, ואז לראות אותן בדשבורד כרגיל.

    python -m src.reports_closure.cli new    --client "אהבה" --period 2025
    python -m src.reports_closure.cli import --client "אהבה" --file notes.txt
    cat notes.txt | python -m src.reports_closure.cli import --client "אהבה" -
    python -m src.reports_closure.cli notes  --client "אהבה"
    python -m src.reports_closure.cli done   --client "אהבה" --note 3 --comment "הותאם"
    python -m src.reports_closure.cli close  --client "אהבה"
    python -m src.reports_closure.cli guidelines --file guidelines.txt

דוח מזוהה ב-``--client`` (התאמה חלקית בשם) או ב-``--id`` המדויק. אם השם
מתאים ליותר מדוח אחד, הפקודה נעצרת ומציגה את המועמדים במקום לנחש.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import SEVERITY_LABELS, ClosureError
from .store import ClosureStore

DEFAULT_PATH = "state/reports_closure.json"


def _resolve_report(store: ClosureStore, args):
    """מאתר דוח לפי --id או לפי --client. לא מנחש כשיש יותר מהתאמה אחת."""
    if args.id:
        return store.get_report(args.id)
    if not args.client:
        raise ClosureError("ציינו --client (שם לקוח) או --id (מזהה דוח).")

    matches = [r for r in store.list_reports() if args.client in r.client_name]
    if args.period:
        matches = [r for r in matches if r.period == args.period]
    if not matches:
        raise ClosureError(f"לא נמצא דוח ללקוח '{args.client}'.")
    if len(matches) > 1:
        listing = "\n".join(
            f"  {r.id}  {r.client_name} · {r.period or 'ללא תקופה'}" for r in matches
        )
        raise ClosureError(
            f"נמצאו {len(matches)} דוחות תואמים. הריצו שוב עם --id:\n{listing}"
        )
    return matches[0]


def _read_text(source: str) -> str:
    """קורא טקסט מקובץ, או מהקלט הסטנדרטי כש-source הוא ``-``."""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def _print_notes(report) -> None:
    open_notes = report.sorted_open_notes()
    print(f"{report.title} ({report.report_type})")
    print(f"פתוחות: {report.open_count} · טופלו: {report.handled_count} · מזהה: {report.id}")
    if not open_notes:
        if report.is_untouched:
            print("טרם נרשמו הערות בדוח הזה.")
        else:
            print("אין הערות פתוחות — הדוח מוכן לסגירה.")
        return
    print("-" * 60)
    for index, note in enumerate(open_notes, start=1):
        amount = f" [{note.amount:,.0f} ₪]" if note.amount is not None else ""
        severity = SEVERITY_LABELS.get(note.severity, note.severity)
        print(f"{index}. [{note.category}/{severity}] {note.text}{amount}")


def _find_note(report, reference: str):
    """מאתר הערה לפי מספר סידורי ברשימת הפתוחות, או לפי מזהה מלא."""
    open_notes = report.sorted_open_notes()
    if reference.isdigit():
        position = int(reference)
        if not 1 <= position <= len(open_notes):
            raise ClosureError(
                f"מספר הערה {position} מחוץ לטווח (יש {len(open_notes)} הערות פתוחות)."
            )
        return open_notes[position - 1]
    note = report.find_note(reference)
    if note is None:
        raise ClosureError(f"לא נמצאה הערה במזהה '{reference}'.")
    return note


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.reports_closure.cli",
        description="מערכת סגירת דוחות כספיים - שורת פקודה",
    )
    parser.add_argument("--path", default=DEFAULT_PATH, help="קובץ הנתונים")
    parser.add_argument("--by", default="", help="מי מבצע את הפעולה (לתיעוד)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_target(p):
        p.add_argument("--client", help="שם הלקוח (התאמה חלקית)")
        p.add_argument("--id", help="מזהה הדוח המדויק")
        p.add_argument("--period", help="תקופה, לצמצום ההתאמה")

    p = sub.add_parser("list", help="רשימת הדוחות")
    p.add_argument("--all", action="store_true", help="כולל דוחות סגורים")

    p = sub.add_parser("new", help="פתיחת דוח חדש")
    p.add_argument("--client", required=True)
    p.add_argument("--period", default="")
    p.add_argument("--client-id", default="", dest="client_id")
    p.add_argument("--type", default="דוח שנתי", dest="report_type")

    p = sub.add_parser("import", help="קליטת הערות מקובץ או מהקלט הסטנדרטי")
    add_target(p)
    p.add_argument("--file", default="-", help="קובץ ההערות, או - לקלט סטנדרטי")
    p.add_argument("--source", default="", help="מקור ההערות, לתיעוד")
    p.add_argument(
        "--create", action="store_true", help="פתיחת הדוח אם אינו קיים"
    )

    p = sub.add_parser("notes", help="הצגת ההערות הפתוחות")
    add_target(p)

    p = sub.add_parser("done", help="סימון הערה כבוצעה")
    add_target(p)
    p.add_argument("--note", required=True, help="מספר ההערה ברשימה, או מזהה")
    p.add_argument("--comment", default="", help="מה בוצע")

    p = sub.add_parser("close", help="סגירת הדוח")
    add_target(p)

    p = sub.add_parser("guidelines", help="הצגת או עדכון הנחיות הסקירה")
    p.add_argument("--file", help="קובץ הנחיות (שורה להנחיה), או - לקלט סטנדרטי")

    return parser


def run(args) -> int:
    store = ClosureStore(args.path)

    if args.command == "list":
        reports = store.list_reports(status=None if args.all else "open")
        if not reports:
            print("אין דוחות.")
            return 0
        for report in reports:
            if report.is_closed:
                flag = "סגור"
            elif report.is_untouched:
                flag = "טרם נרשמו הערות"
            else:
                flag = f"{report.open_count} פתוחות"
            print(f"{report.id}  {report.client_name} · {report.period or '-'}  ({flag})")
        return 0

    if args.command == "new":
        report = store.add_report(
            client_name=args.client,
            period=args.period,
            client_id=args.client_id,
            report_type=args.report_type,
            created_by=args.by,
        )
        print(f"נפתח דוח {report.id}: {report.title}")
        return 0

    if args.command == "guidelines":
        if args.file:
            lines = store.set_guidelines(_read_text(args.file))
            print(f"נשמרו {len(lines)} הנחיות.")
        else:
            existing = store.get_guidelines()
            if not existing:
                print("טרם נרשמו הנחיות.")
            for index, line in enumerate(existing, start=1):
                print(f"{index}. {line}")
        return 0

    # מכאן ואילך - פקודות שפועלות על דוח מסוים
    if args.command == "import" and args.create and args.client and not args.id:
        if not any(args.client in r.client_name for r in store.list_reports()):
            store.add_report(
                client_name=args.client, period=args.period or "", created_by=args.by
            )

    report = _resolve_report(store, args)

    if args.command == "import":
        added = store.import_notes(
            report.id,
            _read_text(args.file),
            source=args.source or "ייבוא משורת פקודה",
            created_by=args.by,
        )
        print(f"נקלטו {len(added)} הערות לדוח {report.title}.")
        _print_notes(store.get_report(report.id))
        return 0

    if args.command == "notes":
        _print_notes(report)
        return 0

    if args.command == "done":
        note = _find_note(report, args.note)
        store.mark_done(report.id, note.id, by=args.by, comment=args.comment)
        fresh = store.get_report(report.id)
        print(f'סומן כבוצע: {note.text}')
        print(f"נותרו {fresh.open_count} הערות פתוחות.")
        if fresh.can_close:
            print("כל ההערות טופלו — הדוח מוכן לסגירה.")
        return 0

    if args.command == "close":
        store.close_report(report.id, by=args.by)
        print(f"הדוח {report.title} נסגר.")
        return 0

    raise ClosureError(f"פקודה לא מוכרת: {args.command}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ClosureError as exc:
        print(f"שגיאה: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"שגיאת קובץ: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
