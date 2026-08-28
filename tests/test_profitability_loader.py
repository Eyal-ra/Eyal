from datetime import date

import pytest

from src.profitability.contracts import EXPENSE, INCOME
from src.profitability.loader import (
    build_column_map,
    load_billing,
    load_cashflow,
    parse_amount,
    parse_date,
    parse_direction,
)


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_parse_amount_handles_israeli_formatting():
    assert parse_amount("₪1,250.50") == 1250.50
    assert parse_amount("12,000") == 12000
    assert parse_amount("(500)") == -500
    assert parse_amount("") is None
    assert parse_amount("לא מספר") is None


def test_parse_date_accepts_common_formats():
    assert parse_date("31/08/2026") == date(2026, 8, 31)
    assert parse_date("31.08.2026") == date(2026, 8, 31)
    assert parse_date("2026-08-31") == date(2026, 8, 31)
    assert parse_date("2026-08-31T10:00:00") == date(2026, 8, 31)
    assert parse_date("") is None


def test_parse_direction_reads_hebrew_and_english():
    assert parse_direction("הכנסה") == INCOME
    assert parse_direction("תקבול") == INCOME
    assert parse_direction("הוצאה") == EXPENSE
    assert parse_direction("debit") == EXPENSE
    assert parse_direction("משהו אחר") is None


def test_build_column_map_matches_hebrew_headers_with_quotes():
    mapping = build_column_map(["תאריך", 'סכום כולל מע"מ', "שם לקוח", 'מע"מ'])
    assert mapping["date"] == "תאריך"
    assert mapping["client"] == "שם לקוח"
    assert mapping["vat"] == 'מע"מ'


def test_load_billing_derives_net_from_gross_minus_vat(tmp_path):
    path = write(
        tmp_path,
        "billing.csv",
        'תאריך,שם לקוח,סכום,מע"מ\n'
        "05/03/2026,לקוח א,1170,170\n"
        "10/03/2026,לקוח ב,2340,340\n",
    )
    records, problems = load_billing(path)
    assert problems == []
    assert [record.amount_net for record in records] == [1000, 2000]
    assert all(record.vat_is_known for record in records)


def test_load_billing_without_vat_column_flags_unverified_basis(tmp_path):
    path = write(tmp_path, "billing.csv", "תאריך,לקוח,סכום\n05/03/2026,לקוח א,1000\n")
    records, _ = load_billing(path)
    assert records[0].amount_net == 1000
    assert not records[0].vat_is_known


def test_load_billing_reports_unreadable_rows_instead_of_dropping_them(tmp_path):
    path = write(
        tmp_path,
        "billing.csv",
        "תאריך,לקוח,סכום\n05/03/2026,לקוח א,1000\nלא תאריך,לקוח ב,2000\n\n",
    )
    records, problems = load_billing(path)
    assert len(records) == 1
    assert len(problems) == 1
    assert problems[0].row_number == 3


def test_load_billing_rejects_file_without_required_columns(tmp_path):
    path = write(tmp_path, "billing.csv", "עמודה,אחרת\n1,2\n")
    with pytest.raises(ValueError, match="חסרות עמודות חובה"):
        load_billing(path)


def test_load_cashflow_infers_direction_from_sign_when_no_type_column(tmp_path):
    path = write(
        tmp_path,
        "cash.csv",
        "תאריך,סכום,קטגוריה\n01/02/2026,5000,גבייה\n02/02/2026,-1200,שכירות\n",
    )
    records, _ = load_cashflow(path)
    assert records[0].direction == INCOME
    assert records[1].direction == EXPENSE
    assert records[1].amount_net == 1200


def test_load_cashflow_prefers_explicit_type_column(tmp_path):
    path = write(
        tmp_path,
        "cash.csv",
        "תאריך,סוג,סכום\n01/02/2026,הוצאה,5000\n",
    )
    records, _ = load_cashflow(path)
    assert records[0].direction == EXPENSE


def test_column_map_tells_gross_and_net_headers_apart(tmp_path):
    mapping = build_column_map(['סכום כולל מע"מ', "סכום לפני מע\"מ", 'מע"מ', "תאריך"])
    assert mapping["amount"] == 'סכום כולל מע"מ'
    assert mapping["amount_net"] == "סכום לפני מע\"מ"
    assert mapping["vat"] == 'מע"מ'


def test_load_billing_reads_gross_header_with_vat_suffix(tmp_path):
    path = write(
        tmp_path,
        "billing.csv",
        'תאריך,שם לקוח,סכום כולל מע"מ,מע"מ\n05/03/2026,לקוח א,1180,180\n',
    )
    records, problems = load_billing(path)
    assert problems == []
    assert records[0].amount_net == 1000
    assert records[0].amount_gross == 1180
