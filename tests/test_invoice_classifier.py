"""Unit tests for the incoming-invoice classifier."""

from src.invoice_classifier import (
    AUTO,
    REVIEW,
    ClassifierConfig,
    IncomingInvoice,
    classify,
)

COMPANY = "516879236@expense.co.il"
SPRAWL = "maven6405816@invoice-maven.com"
ZAKI = "517143814@expense.co.il"

CFG = ClassifierConfig(
    mapping={
        'ספרול מדיה בע"מ': SPRAWL,
        'זקי דיאב חברת עו"ד': ZAKI,
    },
    company_address=COMPANY,
    id_map={"517143814": ZAKI},
)

# Ardani invoice addressed to Eyal's own firm (a company expense).
ARDANI_BODY = (
    "דו\"ח זה הופק באמצעות תוכנת 'ארדני' לכבוד: אייל רייטר רואה חשבון בע\"מ "
    "האורנים 12, הוד השרון מספר עוסק: 632978651"
)
# TML invoice for the client Sprawl.
TML_SPRAWL_BODY = "חשבונית מס/קבלה לכבוד: ספרול מדיה בע``מ eyal@cpateam.co.il"


def test_own_company_routes_to_company_address():
    d = classify(IncomingInvoice(subject="FW", body=ARDANI_BODY), CFG)
    assert d.status == AUTO
    assert d.destination == COMPANY
    assert "own company" in d.reason


def test_known_client_routes_via_map():
    d = classify(IncomingInvoice(subject="1", body=TML_SPRAWL_BODY), CFG)
    assert d.status == AUTO
    assert d.destination == SPRAWL
    assert d.client == 'ספרול מדיה בע"מ'


def test_client_found_in_attachment_text():
    # Body is just a link; the client name lives in the PDF text.
    inv = IncomingInvoice(subject="חשבונית", body="לצפייה בחשבונית לחץ כאן", attachments_text=TML_SPRAWL_BODY)
    d = classify(inv, CFG)
    assert d.status == AUTO
    assert d.destination == SPRAWL


def test_unknown_client_goes_to_review():
    inv = IncomingInvoice(subject="חשבונית", body="לכבוד: חברה כלשהי בע\"מ")
    d = classify(inv, CFG)
    assert d.status == REVIEW
    assert "not in routing map" in d.reason


def test_unidentifiable_goes_to_review():
    d = classify(IncomingInvoice(subject="scan", body="just a link, no name"), CFG)
    assert d.status == REVIEW
    assert d.client is None


def test_company_id_fallback():
    # No usable "לכבוד" name, but the company id is present and mapped.
    inv = IncomingInvoice(subject="x", body="חשבונית עבור ח.פ 517143814 בלבד")
    d = classify(inv, CFG)
    assert d.status == AUTO
    assert d.destination == ZAKI
    assert "company id" in d.reason
