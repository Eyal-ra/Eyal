from typing import Optional

from src.profitability.analysis import Change, Comparison

PERCENT_METRICS = ("שיעור רווח תפעולי", "שיעור גבייה")
COUNT_METRICS = ("לקוחות פעילים",)


def money(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f} ₪"


def percent(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def signed_percent(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value * 100:+.1f}%"


def format_growth(change: Change) -> str:
    """אחוז שינוי של מדד שהוא עצמו אחוז הוא מספר מטעה - שם מוצגת רק תזוזת נקודות האחוז."""
    if change.label in PERCENT_METRICS:
        return ""
    return signed_percent(change.pct)


def format_value(change: Change, value: Optional[float]) -> str:
    if change.label in PERCENT_METRICS:
        return percent(value)
    if change.label in COUNT_METRICS:
        return "-" if value is None else f"{value:.0f}"
    return money(value)


def format_delta(change: Change) -> str:
    if change.label in PERCENT_METRICS:
        return "-" if change.delta is None else f"{change.delta * 100:+.1f} נק' אחוז"
    if change.label in COUNT_METRICS:
        return "-" if change.delta is None else f"{change.delta:+.0f}"
    return "-" if change.delta is None else f"{change.delta:+,.0f} ₪"


def render(comparison: Comparison) -> str:
    current, prior, window = comparison.current, comparison.prior, comparison.window
    lines = []

    lines.append("=" * 64)
    lines.append("השוואת רווחיות - שנה מול שנה")
    lines.append(f"תקופה: {window.label(current.year)} מול {window.label(prior.year)}")
    lines.append("=" * 64)
    lines.append("")
    lines.append(f"מסקנה: {comparison.verdict}")
    lines.append("")

    lines.append(f"{'מדד':<26}{'השנה':>14}{'אשתקד':>14}{'שינוי':>16}{'':>10}")
    lines.append("-" * 80)
    for change in comparison.changes:
        lines.append(
            f"{change.label:<26}"
            f"{format_value(change, change.current):>14}"
            f"{format_value(change, change.prior):>14}"
            f"{format_delta(change):>16}"
            f"{format_growth(change):>10}"
        )
    lines.append("")

    if comparison.faster_growing_expenses:
        lines.append("סעיפי הוצאה שגדלו מהר יותר מההכנסות:")
        for change in comparison.faster_growing_expenses:
            lines.append(
                f"  - {change.label}: {money(change.prior)} ← {money(change.current)} "
                f"({signed_percent(change.pct)})"
            )
        lines.append("")

    if comparison.new_clients:
        lines.append(f"לקוחות חדשים ({len(comparison.new_clients)}): {_join(comparison.new_clients)}")
    if comparison.lost_clients:
        lines.append(f"לקוחות שנשרו ({len(comparison.lost_clients)}): {_join(comparison.lost_clients)}")
    if comparison.new_clients or comparison.lost_clients:
        lines.append("")

    top = sorted(current.revenue_by_client.items(), key=lambda item: item[1], reverse=True)[:5]
    if top:
        lines.append("חמשת הלקוחות הגדולים השנה:")
        for name, amount in top:
            share = amount / current.billed_net if current.billed_net else None
            lines.append(f"  - {name}: {money(amount)} ({percent(share)} מההכנסות)")
        lines.append("")

    lines.extend(_caveats(comparison))
    return "\n".join(lines)


def _caveats(comparison: Comparison) -> list:
    lines = ["הערות לקריאת הדוח:"]
    lines.append("  - ההכנסות נמדדות לפי מועד החיוב (בסיס מצטבר), ההוצאות לפי תשלום בפועל.")
    if not (comparison.current.vat_basis_verified and comparison.prior.vat_basis_verified):
        lines.append("  - לא נמצאה עמודת מעמ בחלק מהשורות; הסכומים נלקחו כפי שהם.")
    if comparison.problems:
        lines.append(f"  - {len(comparison.problems)} שורות לא נטענו:")
        for problem in comparison.problems[:5]:
            lines.append(f"      {problem.source} שורה {problem.row_number}: {problem.reason}")
        if len(comparison.problems) > 5:
            lines.append(f"      ...ועוד {len(comparison.problems) - 5}")
    return lines


def _join(names: list, limit: int = 8) -> str:
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f", ...ועוד {len(names) - limit}"
