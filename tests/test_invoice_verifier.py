"""Unit tests for the verifier, using real confirmation/forward shapes."""

from src.invoice_verifier import (
    ConfirmationRecord,
    ForwardRecord,
    is_confirmation,
    reference_tokens,
    strip_reply_prefixes,
    subject_key,
    verify,
)

SUMIT_BODY = "קיבלנו!  המייל ששלחת התקבל יחד עם הקובץ המצורף. הקבצים מחכים לך במודול הוצאות."
PAPERLESS_BODY = "שלום, המסמכים הבאים נקלטו בהצלחה במערכת: 1_23824.pdf"


def test_strip_reply_prefixes_stacked():
    assert strip_reply_prefixes("Re: Fw: Your receipt #1") == "Your receipt #1"
    assert strip_reply_prefixes("FW: חשבונית") == "חשבונית"


def test_subject_key_matches_across_forward_and_reply():
    fwd = "Fw: Your receipt from Anthropic, PBC #2121-7983-8544"
    conf = "Re: Fw: Your receipt from Anthropic, PBC #2121-7983-8544"
    assert subject_key(fwd) == subject_key(conf)


def test_reference_tokens():
    assert "2121-7983-8544" in reference_tokens("receipt #2121-7983-8544")
    assert "261183" in reference_tokens("Fw: חשבונית מס מספר 261183")
    assert "2026" not in reference_tokens("date 2026")  # years excluded (4 digits)


def test_is_confirmation():
    assert is_confirmation("support@sumit.co.il", SUMIT_BODY) == "sumit"
    assert is_confirmation("notifications@paperless.tax", PAPERLESS_BODY) == "paperless"
    assert is_confirmation("billing@ardani.co.il", "חשבונית") is None


def test_verify_confirmed_by_subject():
    forwards = [ForwardRecord("Fw: Your receipt from Anthropic, PBC #2121-7983-8544")]
    confs = [ConfirmationRecord("sumit", "Re: Fw: Your receipt from Anthropic, PBC #2121-7983-8544", SUMIT_BODY)]
    result = verify(forwards, confs)
    assert result.confirmed == forwards
    assert not result.unconfirmed


def test_verify_gap_when_no_confirmation():
    forwards = [
        ForwardRecord("Fw: חשבונית מס מספר 261183"),
        ForwardRecord("Fw: חשבונית מס מספר 261184"),
    ]
    confs = [ConfirmationRecord("sumit", "Re: Fw: חשבונית מס מספר 261183", SUMIT_BODY)]
    result = verify(forwards, confs)
    assert [f.subject for f in result.unconfirmed] == ["Fw: חשבונית מס מספר 261184"]


def test_verify_paperless_matches_by_filename_token():
    # Paperless names the attached file, not the subject; match on "23824".
    forwards = [ForwardRecord('אייל רייטר, רואה חשבון - חשבונית מס מספר 23824')]
    confs = [ConfirmationRecord("paperless", "אישור קבלת 1 מסמכים בדואל", PAPERLESS_BODY)]
    result = verify(forwards, confs)
    assert result.confirmed == forwards


def test_verify_reports_orphan_confirmation():
    forwards: list[ForwardRecord] = []
    confs = [ConfirmationRecord("sumit", "Re: Fw: something", SUMIT_BODY)]
    result = verify(forwards, confs)
    assert len(result.orphan_confirmations) == 1
