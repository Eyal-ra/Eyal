"""Extract text from invoice attachments.

Many invoices name the client they are for only inside the attached PDF
(or behind a link), not in the email body. This module pulls text out of
attachments so the classifier can read "לכבוד: <client>" from there too.

The PDF backend (pdfminer.six) is imported lazily and failures are soft:
if it isn't installed or a file can't be parsed we return "" and the
invoice simply falls through to manual review instead of crashing. That
also keeps the wiring unit-testable without any PDF library — tests inject
their own extractor.
"""

import base64
from typing import Callable

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp")


def extract_pdf_text(data: bytes) -> str:
    """Best-effort PDF → text. Returns "" if no backend or on any error."""
    try:
        from io import BytesIO

        from pdfminer.high_level import extract_text as _pdf_extract
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        # Backend missing or broken (e.g. native panic) → soft-fail to review.
        return ""
    try:
        return _pdf_extract(BytesIO(data)) or ""
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return ""


def extract_text(name: str, data: bytes) -> str:
    """Extract text from one attachment, dispatching on its file extension."""
    lname = (name or "").lower()
    if lname.endswith(".pdf"):
        return extract_pdf_text(data)
    if lname.endswith(_IMAGE_EXT):
        return ""  # image-only invoices need OCR (out of scope) → review
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def gather_attachment_text(
    attachments: list[dict],
    extractor: Callable[[str, bytes], str] = extract_text,
) -> str:
    """Decode Graph fileAttachment dicts and join their extracted text.

    Each attachment is ``{"name": str, "contentBytes": <base64 str>}``.
    """
    parts: list[str] = []
    for att in attachments or []:
        content = att.get("contentBytes")
        if not content:
            continue
        try:
            data = base64.b64decode(content)
        except Exception:
            continue
        text = extractor(att.get("name", ""), data)
        if text and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)
