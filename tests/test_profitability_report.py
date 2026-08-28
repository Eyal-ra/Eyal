from datetime import date

from src.profitability.analysis import compare
from src.profitability.cli import main, parse_until
from src.profitability.contracts import EXPENSE, INCOME, BillingRecord, CashflowRecord, RowProblem
from src.profitability.report import money, percent, render, signed_percent


def bill(day, month, year, amount, client="לקוח א"):
    return BillingRecord(date(year, month, day), client, amount, amount * 1.17, True)


def cash(day, month, year, amount, direction=INCOME, category="", known=True):
    return CashflowRecord(date(year, month, day), direction, amount, amount * 1.17, known, category)


def test_money_and_percent_formatting():
    assert money(1234.6) == "1,235 ₪"
    assert money(None) == "-"
    assert percent(0.1234) == "12.3%"
    assert signed_percent(0.05) == "+5.0%"
    assert signed_percent(-0.05) == "-5.0%"


def test_render_includes_verdict_period_and_metrics():
    comparison = compare(
        [bill(15, 8, 2026, 100_000), bill(15, 8, 2025, 90_000)],
        [cash(1, 5, 2026, 30_000, EXPENSE, "שכר"), cash(1, 5, 2025, 30_000, EXPENSE, "שכר")],
        2026,
    )
    output = render(comparison)
    assert "הרווחיות השתפרה" in output
    assert "1.1.2026-15.8.2026" in output
    assert "1.1.2025-15.8.2025" in output
    assert "רווח תפעולי" in output
    assert "לקוח א" in output


def test_render_warns_when_vat_basis_is_unverified():
    comparison = compare([bill(1, 5, 2026, 1000)], [cash(1, 5, 2026, 100, EXPENSE, "", False)], 2026)
    assert "לא נמצאה עמודת מעמ" in render(comparison)


def test_render_lists_unloaded_rows():
    comparison = compare([bill(1, 5, 2026, 1000)], [], 2026)
    comparison.problems = [RowProblem("billing", 7, "תאריך או סכום לא קריאים", "raw")]
    output = render(comparison)
    assert "1 שורות לא נטענו" in output
    assert "billing שורה 7" in output


def test_parse_until_accepts_dot_and_slash():
    assert parse_until("31/08").month == 8
    assert parse_until("31.08").day == 31


def test_cli_writes_a_report_end_to_end(tmp_path, capsys):
    billing = tmp_path / "billing.csv"
    billing.write_text(
        'תאריך,שם לקוח,סכום,מע"מ\n'
        "15/03/2026,לקוח א,117000,17000\n"
        "15/03/2025,לקוח א,58500,8500\n",
        encoding="utf-8",
    )
    cashflow = tmp_path / "cash.csv"
    cashflow.write_text(
        "תאריך,סוג,סכום,קטגוריה\n"
        "20/03/2026,הוצאה,10000,שכירות\n"
        "20/03/2025,הוצאה,10000,שכירות\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.txt"

    exit_code = main([
        "--billing", str(billing),
        "--cashflow", str(cashflow),
        "--year", "2026",
        "--out", str(out),
    ])

    assert exit_code == 0
    report = out.read_text(encoding="utf-8")
    assert "הרווחיות השתפרה" in report
    assert "100,000 ₪" in report


def test_cli_reports_a_bad_file_without_crashing(tmp_path, capsys):
    missing = str(tmp_path / "nope.csv")
    exit_code = main(["--billing", missing, "--cashflow", missing])
    assert exit_code == 1
    assert "שגיאה" in capsys.readouterr().err


def test_percentage_metrics_show_points_only_not_percent_of_percent():
    comparison = compare(
        [bill(1, 5, 2026, 100_000), bill(1, 5, 2025, 100_000)],
        [cash(1, 5, 2026, 60_000, EXPENSE), cash(1, 5, 2025, 40_000, EXPENSE)],
        2026,
    )
    margin_row = [line for line in render(comparison).splitlines() if "שיעור רווח" in line][0]
    assert "נק' אחוז" in margin_row
    assert margin_row.rstrip().endswith("נק' אחוז")
