"""Unit tests for the invoice processor (forward + tag flow, dry-run actions)."""

from src.invoice_classifier import ClassifierConfig
from src.invoice_processor import (
    ALREADY_DONE,
    FORWARDED,
    NEEDS_REVIEW,
    REVIEW_CATEGORY,
    SENT_CATEGORY,
    InvoiceProcessor,
    NoOpMailActions,
    ProcessableInvoice,
)

COMPANY = "516879236@expense.co.il"
SPRAWL = "maven6405816@invoice-maven.com"

CFG = ClassifierConfig(
    mapping={'ספרול מדיה בע"מ': SPRAWL},
    company_address=COMPANY,
)

ARDANI = ProcessableInvoice(
    message_id="m1",
    subject="FW",
    body='לכבוד: אייל רייטר רואה חשבון בע"מ',
)
SPRAWL_INV = ProcessableInvoice(
    message_id="m2",
    subject="1",
    body="לכבוד: ספרול מדיה בע``מ",
)
UNKNOWN = ProcessableInvoice(message_id="m3", subject="scan", body="just a link")


def _processor():
    return InvoiceProcessor(cfg=CFG, actions=NoOpMailActions())


def test_company_invoice_is_forwarded_and_tagged():
    p = _processor()
    result = p.process(ARDANI)
    assert result.action == FORWARDED
    assert result.destination == COMPANY
    assert p.actions.forwards == [("m1", [COMPANY], "")]
    assert ("m1", SENT_CATEGORY) in p.actions.categories


def test_client_invoice_routes_via_map():
    p = _processor()
    result = p.process(SPRAWL_INV)
    assert result.action == FORWARDED
    assert result.destination == SPRAWL


def test_unresolved_is_tagged_for_review_not_sent():
    p = _processor()
    result = p.process(UNKNOWN)
    assert result.action == NEEDS_REVIEW
    assert p.actions.forwards == []                       # nothing sent
    assert ("m3", REVIEW_CATEGORY) in p.actions.categories


def test_idempotent_does_not_reprocess():
    p = _processor()
    first = p.process(ARDANI)
    second = p.process(ARDANI)
    assert first.action == FORWARDED
    assert second.action == ALREADY_DONE
    assert len(p.actions.forwards) == 1                   # only forwarded once


def test_process_all_mixed_batch():
    p = _processor()
    results = p.process_all([ARDANI, SPRAWL_INV, UNKNOWN])
    actions = [r.action for r in results]
    assert actions == [FORWARDED, FORWARDED, NEEDS_REVIEW]
    assert len(p.actions.forwards) == 2
