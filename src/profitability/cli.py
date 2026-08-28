import argparse
import sys
from datetime import date

from src.profitability.analysis import Window, compare
from src.profitability.loader import load_billing, load_cashflow
from src.profitability.report import render


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.profitability",
        description="השוואת רווחיות בין שנה נוכחית לשנה קודמת, מקבצי חיובים ותזרים",
    )
    parser.add_argument("--billing", required=True, help="קובץ חיובים (CSV/TSV/XLSX)")
    parser.add_argument("--cashflow", required=True, help="קובץ תזרים (CSV/TSV/XLSX)")
    parser.add_argument("--year", type=int, default=date.today().year, help="השנה הנבדקת")
    parser.add_argument("--prior-year", type=int, default=None, help="שנת ההשוואה (ברירת מחדל: שנה אחורה)")
    parser.add_argument(
        "--until",
        default=None,
        help="סוף חלון ההשוואה בפורמט DD/MM. ברירת מחדל: התאריך האחרון שיש עליו נתונים",
    )
    parser.add_argument("--out", default=None, help="כתיבת הדוח לקובץ במקום למסך")
    return parser


def parse_until(value: str) -> Window:
    parts = value.replace(".", "/").split("/")
    if len(parts) != 2:
        raise ValueError("--until חייב להיות בפורמט DD/MM, למשל 31/08")
    day, month = int(parts[0]), int(parts[1])
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        raise ValueError(f"תאריך לא תקין: {value}")
    return Window(month, day)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        billing, billing_problems = load_billing(args.billing)
        cashflow, cashflow_problems = load_cashflow(args.cashflow)
        window = parse_until(args.until) if args.until else None
    except (OSError, ValueError, RuntimeError) as error:
        print(f"שגיאה: {error}", file=sys.stderr)
        return 1

    comparison = compare(billing, cashflow, args.year, args.prior_year, window)
    comparison.problems = billing_problems + cashflow_problems
    report = render(comparison)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(report + "\n")
        print(f"הדוח נכתב אל {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
