from datetime import date

from src.profitability.analysis import (
    Change,
    Window,
    collect_metrics,
    compare,
    infer_window,
)
from src.profitability.contracts import EXPENSE, INCOME, BillingRecord, CashflowRecord


def bill(day, month, year, amount, client="לקוח א"):
    return BillingRecord(date(year, month, day), client, amount, amount * 1.17, True)


def cash(day, month, year, amount, direction=INCOME, category=""):
    return CashflowRecord(date(year, month, day), direction, amount, amount * 1.17, True, category)


def test_window_clamps_leap_day_in_a_non_leap_year():
    window = Window(2, 29)
    assert window.bounds(2024)[1] == date(2024, 2, 29)
    assert window.bounds(2025)[1] == date(2025, 2, 28)


def test_infer_window_uses_latest_date_of_the_examined_year():
    billing = [bill(15, 8, 2026, 1000), bill(31, 12, 2025, 9999)]
    assert infer_window(billing, [], 2026) == Window(8, 15)


def test_window_excludes_records_after_the_cutoff():
    billing = [bill(1, 3, 2025, 1000), bill(1, 11, 2025, 5000)]
    metrics = collect_metrics(billing, [], 2025, Window(8, 31))
    assert metrics.billed_net == 1000


def test_compare_aligns_both_years_to_the_same_window():
    billing = [
        bill(1, 3, 2026, 100_000),
        bill(1, 3, 2025, 80_000),
        bill(1, 11, 2025, 500_000),  # מחוץ לחלון - אסור שייכנס להשוואה
    ]
    comparison = compare(billing, [], 2026)
    assert comparison.current.billed_net == 100_000
    assert comparison.prior.billed_net == 80_000


def test_operating_profit_and_margin():
    billing = [bill(1, 5, 2026, 200_000)]
    cashflow = [cash(1, 5, 2026, 50_000, EXPENSE, "שכר")]
    metrics = collect_metrics(billing, cashflow, 2026, Window(12, 31))
    assert metrics.operating_profit == 150_000
    assert metrics.margin == 0.75


def test_collection_rate_compares_gross_to_gross():
    billing = [bill(1, 5, 2026, 100_000)]  # ברוטו 117,000
    cashflow = [cash(1, 5, 2026, 50_000, INCOME)]  # נגבה ברוטו 58,500
    metrics = collect_metrics(billing, cashflow, 2026, Window(12, 31))
    assert round(metrics.collection_rate, 4) == 0.5


def test_margin_is_none_without_revenue():
    metrics = collect_metrics([], [cash(1, 5, 2026, 1000, EXPENSE)], 2026, Window(12, 31))
    assert metrics.margin is None


def test_change_pct_is_none_when_there_is_no_prior_base():
    assert Change("x", 100.0, 0.0).pct is None
    assert Change("x", 100.0, None).pct is None
    assert Change("x", 150.0, 100.0).pct == 0.5


def test_verdict_reflects_margin_direction():
    improving = compare(
        [bill(1, 5, 2026, 100_000), bill(1, 5, 2025, 100_000)],
        [cash(1, 5, 2026, 20_000, EXPENSE), cash(1, 5, 2025, 40_000, EXPENSE)],
        2026,
    )
    assert improving.verdict == "הרווחיות השתפרה"

    eroding = compare(
        [bill(1, 5, 2026, 100_000), bill(1, 5, 2025, 100_000)],
        [cash(1, 5, 2026, 60_000, EXPENSE), cash(1, 5, 2025, 40_000, EXPENSE)],
        2026,
    )
    assert eroding.verdict == "הרווחיות נשחקה"


def test_verdict_calls_a_flat_margin_unchanged():
    comparison = compare(
        [bill(1, 5, 2026, 100_000), bill(1, 5, 2025, 100_000)],
        [cash(1, 5, 2026, 40_100, EXPENSE), cash(1, 5, 2025, 40_000, EXPENSE)],
        2026,
    )
    assert comparison.verdict == "הרווחיות כמעט זהה לשנה שעברה"


def test_flags_only_expenses_growing_faster_than_revenue():
    billing = [bill(1, 5, 2026, 110_000), bill(1, 5, 2025, 100_000)]  # הכנסות +10%
    cashflow = [
        cash(1, 5, 2026, 30_000, EXPENSE, "שכר"),      # +50% - מהיר מההכנסות
        cash(1, 5, 2025, 20_000, EXPENSE, "שכר"),
        cash(1, 5, 2026, 10_500, EXPENSE, "שכירות"),   # +5% - איטי מההכנסות
        cash(1, 5, 2025, 10_000, EXPENSE, "שכירות"),
    ]
    comparison = compare(billing, cashflow, 2026)
    assert [change.label for change in comparison.faster_growing_expenses] == ["שכר"]


def test_identifies_new_and_lost_clients():
    billing = [
        bill(1, 5, 2026, 1000, "לקוח ותיק"),
        bill(1, 5, 2026, 1000, "לקוח חדש"),
        bill(1, 5, 2025, 1000, "לקוח ותיק"),
        bill(1, 5, 2025, 1000, "לקוח שעזב"),
    ]
    comparison = compare(billing, [], 2026)
    assert comparison.new_clients == ["לקוח חדש"]
    assert comparison.lost_clients == ["לקוח שעזב"]


def test_uncategorized_expenses_get_a_bucket():
    metrics = collect_metrics([], [cash(1, 5, 2026, 500, EXPENSE, "")], 2026, Window(12, 31))
    assert metrics.expenses_by_category == {"ללא סיווג": 500}
