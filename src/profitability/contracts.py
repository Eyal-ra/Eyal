from dataclasses import dataclass
from datetime import date
from typing import Optional

INCOME = "in"
EXPENSE = "out"


@dataclass(frozen=True)
class BillingRecord:
    """חיוב שהוצא ללקוח (בסיס מצטבר - לפי מועד החיוב, לא לפי הגבייה)."""

    date: date
    client: str
    amount_net: float
    amount_gross: float
    vat_is_known: bool
    document: str = ""


@dataclass(frozen=True)
class CashflowRecord:
    """תנועת מזומן בפועל - כניסה או יציאה."""

    date: date
    direction: str
    amount_net: float
    amount_gross: float
    vat_is_known: bool
    category: str = ""
    client: str = ""


@dataclass(frozen=True)
class RowProblem:
    """שורה שלא נטענה - נשמרת כדי שאפשר יהיה להבין מה הושמט ולמה."""

    source: str
    row_number: int
    reason: str
    raw: str


def is_income(record: CashflowRecord) -> bool:
    return record.direction == INCOME


def is_expense(record: CashflowRecord) -> bool:
    return record.direction == EXPENSE
