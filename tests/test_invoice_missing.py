"""Unit tests for received-but-never-forwarded detection."""

from src.invoice_missing import (
    ReceivedInvoice,
    SentForward,
    find_missing,
    looks_like_invoice,
)

EYAL = "eyal@cpateam.co.il"


def test_looks_like_invoice():
    assert looks_like_invoice("חשבונית מס קבלה 40402")
    assert looks_like_invoice("Your receipt from Anthropic")
    assert not looks_like_invoice("סיכום פגישה שבועית")


def test_received_not_forwarded_is_missing():
    received = [ReceivedInvoice(subject="חשבונית מס קבלה 40402", sender="billing@aor.co.il")]
    forwards: list[SentForward] = []
    missing = find_missing(received, forwards)
    assert len(missing) == 1


def test_forwarded_by_subject_is_not_missing():
    received = [ReceivedInvoice(subject="חשבונית חשמל סופרפאוור 55966414", sender="x@electra.co.il")]
    forwards = [SentForward(subject="Fw: חשבונית חשמל סופרפאוור 55966414")]
    assert find_missing(received, forwards) == []


def test_forwarded_by_reference_token_is_not_missing():
    # Generic subject, but the invoice number ties them together.
    received = [ReceivedInvoice(subject="1", sender="s@tml.co.il", attachments_text="חשבונית 8618994")]
    forwards = [SentForward(subject="1", attachments_text="758405_320_8618994.pdf")]
    assert find_missing(received, forwards) == []


def test_generic_subject_does_not_false_match():
    # Two unrelated "1" subjects must NOT be treated as the same → still missing.
    received = [ReceivedInvoice(subject="1", sender="s@supplier.co.il", attachments_text="חשבונית 40402")]
    forwards = [SentForward(subject="1", attachments_text="unrelated 99999.pdf")]
    assert len(find_missing(received, forwards)) == 1


def test_own_issued_invoice_is_excluded():
    received = [ReceivedInvoice(subject="אייל רייטר, רואה חשבון - חשבונית מס מספר 24092", sender=EYAL)]
    missing = find_missing(received, [], own_addresses=(EYAL,))
    assert missing == []
