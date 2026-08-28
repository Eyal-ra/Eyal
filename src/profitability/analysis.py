from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

from src.profitability.contracts import BillingRecord, CashflowRecord, is_expense, is_income


@dataclass(frozen=True)
class Window:
    """חלון השוואה - אותם יום וחודש בשתי השנים, כדי שלא נשווה שנה מלאה מול חלקית."""

    month: int
    day: int

    def bounds(self, year: int) -> tuple:
        return date(year, 1, 1), date(year, self.month, _clamp_day(year, self.month, self.day))

    def contains(self, when: date, year: int) -> bool:
        start, end = self.bounds(year)
        return start <= when <= end

    def label(self, year: int) -> str:
        _, end = self.bounds(year)
        return f"1.1.{year}-{end.day}.{end.month}.{year}"


@dataclass
class PeriodMetrics:
    year: int
    billed_net: float = 0.0
    billed_gross: float = 0.0
    collected_gross: float = 0.0
    expenses_net: float = 0.0
    active_clients: int = 0
    expenses_by_category: dict = field(default_factory=dict)
    revenue_by_client: dict = field(default_factory=dict)
    vat_basis_verified: bool = True

    @property
    def operating_profit(self) -> float:
        return self.billed_net - self.expenses_net

    @property
    def margin(self) -> Optional[float]:
        return self.operating_profit / self.billed_net if self.billed_net else None

    @property
    def collection_rate(self) -> Optional[float]:
        return self.collected_gross / self.billed_gross if self.billed_gross else None

    @property
    def revenue_per_client(self) -> Optional[float]:
        return self.billed_net / self.active_clients if self.active_clients else None


@dataclass(frozen=True)
class Change:
    label: str
    current: Optional[float]
    prior: Optional[float]

    @property
    def delta(self) -> Optional[float]:
        if self.current is None or self.prior is None:
            return None
        return self.current - self.prior

    @property
    def pct(self) -> Optional[float]:
        """שיעור השינוי. None כשאין בסיס להשוואה - עדיף חור בדוח מאשר מספר מומצא."""
        if self.current is None or self.prior is None or self.prior == 0:
            return None
        return (self.current - self.prior) / abs(self.prior)


@dataclass
class Comparison:
    window: Window
    current: PeriodMetrics
    prior: PeriodMetrics
    changes: list = field(default_factory=list)
    faster_growing_expenses: list = field(default_factory=list)
    new_clients: list = field(default_factory=list)
    lost_clients: list = field(default_factory=list)
    problems: list = field(default_factory=list)

    @property
    def verdict(self) -> str:
        current_margin, prior_margin = self.current.margin, self.prior.margin
        if current_margin is None or prior_margin is None:
            return "לא ניתן לקבוע - אין הכנסות באחת התקופות"
        gap = current_margin - prior_margin
        if abs(gap) < 0.005:
            return "הרווחיות כמעט זהה לשנה שעברה"
        return "הרווחיות השתפרה" if gap > 0 else "הרווחיות נשחקה"


def _clamp_day(year: int, month: int, day: int) -> int:
    """29.2 בשנה מעוברת מול שנה רגילה - מקצרים ליום האחרון הקיים."""
    if month == 2 and day == 29 and not _is_leap(year):
        return 28
    return day


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def latest_date(billing: Iterable[BillingRecord], cashflow: Iterable[CashflowRecord]) -> Optional[date]:
    dates = [record.date for record in billing] + [record.date for record in cashflow]
    return max(dates) if dates else None


def infer_window(billing, cashflow, year: int) -> Window:
    """חלון ההשוואה נגזר מהתאריך האחרון שיש עליו נתונים בשנה הנוכחית."""
    dates = [record.date for record in billing if record.date.year == year]
    dates += [record.date for record in cashflow if record.date.year == year]
    if not dates:
        return Window(12, 31)
    cutoff = max(dates)
    return Window(cutoff.month, cutoff.day)


def collect_metrics(billing, cashflow, year: int, window: Window) -> PeriodMetrics:
    metrics = PeriodMetrics(year=year)
    clients = set()

    for record in billing:
        if record.date.year != year or not window.contains(record.date, year):
            continue
        metrics.billed_net += record.amount_net
        metrics.billed_gross += record.amount_gross
        if not record.vat_is_known:
            metrics.vat_basis_verified = False
        if record.client:
            clients.add(record.client)
            metrics.revenue_by_client[record.client] = (
                metrics.revenue_by_client.get(record.client, 0.0) + record.amount_net
            )

    for record in cashflow:
        if record.date.year != year or not window.contains(record.date, year):
            continue
        if is_income(record):
            metrics.collected_gross += record.amount_gross
        elif is_expense(record):
            metrics.expenses_net += record.amount_net
            if not record.vat_is_known:
                metrics.vat_basis_verified = False
            category = record.category or "ללא סיווג"
            metrics.expenses_by_category[category] = (
                metrics.expenses_by_category.get(category, 0.0) + record.amount_net
            )

    metrics.active_clients = len(clients)
    return metrics


def compare(billing, cashflow, year: int, prior_year: Optional[int] = None,
            window: Optional[Window] = None) -> Comparison:
    prior_year = prior_year if prior_year is not None else year - 1
    window = window or infer_window(billing, cashflow, year)

    current = collect_metrics(billing, cashflow, year, window)
    prior = collect_metrics(billing, cashflow, prior_year, window)

    changes = [
        Change("הכנסות (מחויב, ללא מעמ)", current.billed_net, prior.billed_net),
        Change("הוצאות (ללא מעמ)", current.expenses_net, prior.expenses_net),
        Change("רווח תפעולי", current.operating_profit, prior.operating_profit),
        Change("שיעור רווח תפעולי", current.margin, prior.margin),
        Change("שיעור גבייה", current.collection_rate, prior.collection_rate),
        Change("לקוחות פעילים", float(current.active_clients), float(prior.active_clients)),
        Change("הכנסה ממוצעת ללקוח", current.revenue_per_client, prior.revenue_per_client),
    ]

    return Comparison(
        window=window,
        current=current,
        prior=prior,
        changes=changes,
        faster_growing_expenses=find_faster_growing_expenses(current, prior),
        new_clients=sorted(set(current.revenue_by_client) - set(prior.revenue_by_client)),
        lost_clients=sorted(set(prior.revenue_by_client) - set(current.revenue_by_client)),
    )


def find_faster_growing_expenses(current: PeriodMetrics, prior: PeriodMetrics) -> list:
    """סעיפי הוצאה שגדלו מהר יותר מההכנסות - שם נשחקת הרווחיות בפועל."""
    revenue_growth = Change("", current.billed_net, prior.billed_net).pct
    if revenue_growth is None:
        return []

    flagged = []
    for category, amount in current.expenses_by_category.items():
        prior_amount = prior.expenses_by_category.get(category, 0.0)
        change = Change(category, amount, prior_amount)
        if change.pct is not None and change.pct > revenue_growth:
            flagged.append(change)
    return sorted(flagged, key=lambda change: change.delta or 0, reverse=True)
