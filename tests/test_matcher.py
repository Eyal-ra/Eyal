from dataclasses import dataclass

from src.matcher import (
    is_same_customer,
    name_similarity,
    normalize_id,
    normalize_name,
    normalize_phone,
)


@dataclass
class Sub:
    full_name: str
    phone: str
    id_number: str


def test_normalize_phone_strips_and_canonicalizes():
    assert normalize_phone("+972-50-123-4567") == "0501234567"
    assert normalize_phone("050 123 4567") == "0501234567"
    assert normalize_phone("") == ""


def test_normalize_id_strips_non_digits():
    assert normalize_id("123-456-789") == "123456789"


def test_normalize_name_collapses_whitespace():
    assert normalize_name("  ישראל   ישראלי  ") == "ישראל ישראלי"


def test_name_similarity_close_match():
    assert name_similarity("ישראל ישראלי", "ישראל ישראל") > 0.85


def test_is_same_customer_matches_on_phone_and_similar_name():
    a = Sub("ישראל ישראלי", "050-1234567", "")
    b = Sub("ישראל ישראל", "0501234567", "")
    assert is_same_customer(a, b)


def test_is_same_customer_rejects_when_no_phone_or_id_match():
    a = Sub("ישראל ישראלי", "0501234567", "111111111")
    b = Sub("ישראל ישראלי", "0509999999", "222222222")
    assert not is_same_customer(a, b)
