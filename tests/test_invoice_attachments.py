"""Unit tests for attachment text extraction (no real PDF lib needed)."""

import base64

from src.invoice_attachments import (
    extract_pdf_text,
    extract_text,
    gather_attachment_text,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_gather_uses_injected_extractor_and_joins():
    attachments = [
        {"name": "a.pdf", "contentBytes": _b64(b"AAA")},
        {"name": "b.pdf", "contentBytes": _b64(b"BBB")},
    ]
    fake = lambda name, data: f"{name}:{data.decode()}"
    out = gather_attachment_text(attachments, extractor=fake)
    assert out == "a.pdf:AAA\nb.pdf:BBB"


def test_gather_skips_missing_or_bad_content():
    attachments = [
        {"name": "x.pdf"},                       # no contentBytes
        {"name": "y.pdf", "contentBytes": "!!"},  # invalid base64
        {"name": "z.txt", "contentBytes": _b64(b"keep")},
    ]
    out = gather_attachment_text(attachments, extractor=lambda n, d: d.decode())
    assert out == "keep"


def test_extract_text_decodes_plain_text():
    assert extract_text("note.txt", "לכבוד: בדיקה".encode("utf-8")) == "לכבוד: בדיקה"


def test_extract_text_image_returns_empty():
    assert extract_text("scan.jpg", b"\xff\xd8\xff") == ""


def test_extract_pdf_text_soft_fails_on_garbage():
    # Whether or not a PDF backend is installed, garbage must not raise.
    assert extract_pdf_text(b"%PDF-1.4 not really") == ""
