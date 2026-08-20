"""Detect invoices that were RECEIVED but never forwarded to any book.

The office monitor already reports "sent but not confirmed". This closes
the other blind spot: an invoice that landed in the Inbox and was never
forwarded to an intake mailbox at all — the true "missed" case, which
otherwise leaves no trace.

Approach: take the invoice-looking messages received in a window and the
forwards sent to intake addresses in the same window, and flag any received
invoice with no matching forward. Matching is deliberately *strict* — we
only treat a received invoice as handled on strong evidence (a shared
reference token, or a non-trivial subject match) — so the failure mode is a
harmless false alarm, never a hidden miss.
"""

from dataclasses import dataclass, field

from src.invoice_verifier import reference_tokens, subject_key

# Words that mark a message as an invoice/receipt worth tracking.
INVOICE_HINTS = (
    "חשבונית",
    "קבלה",
    "חשבון",
    "receipt",
    "invoice",
    "תשלום",
    "חיוב",
)
_MIN_SUBJECT_KEY = 6  # shorter/generic subjects ("1") never match on subject alone


@dataclass
class ReceivedInvoice:
    subject: str = ""
    body: str = ""
    sender: str = ""
    has_attachments: bool = False
    attachments_text: str = ""


@dataclass
class SentForward:
    subject: str = ""
    attachments_text: str = ""


def looks_like_invoice(subject: str, body: str = "", has_attachments: bool = False) -> bool:
    """Heuristic: does this message look like a supplier invoice/receipt?"""
    text = f"{subject}\n{body}"
    return any(hint in text for hint in INVOICE_HINTS)


def _forward_index(forwards: list[SentForward]) -> tuple[set[str], set[str]]:
    subjects: set[str] = set()
    tokens: set[str] = set()
    for fwd in forwards:
        key = subject_key(fwd.subject)
        if len(key) >= _MIN_SUBJECT_KEY:
            subjects.add(key)
        tokens |= reference_tokens(f"{fwd.subject}\n{fwd.attachments_text}")
    return subjects, tokens


def _is_forwarded(inv: ReceivedInvoice, subjects: set[str], tokens: set[str]) -> bool:
    inv_tokens = reference_tokens(f"{inv.subject}\n{inv.attachments_text}")
    if inv_tokens & tokens:
        return True
    key = subject_key(inv.subject)
    return len(key) >= _MIN_SUBJECT_KEY and key in subjects


def find_missing(
    received: list[ReceivedInvoice],
    forwards: list[SentForward],
    own_addresses: tuple[str, ...] = (),
) -> list[ReceivedInvoice]:
    """Return received invoices with no matching forward (i.e. never sent).

    *own_addresses* are excluded as senders — an invoice Eyal issued himself
    is income, not a received expense to forward.
    """
    subjects, tokens = _forward_index(forwards)
    own = {a.lower() for a in own_addresses}
    missing: list[ReceivedInvoice] = []
    for inv in received:
        if inv.sender and inv.sender.lower() in own:
            continue
        if not _is_forwarded(inv, subjects, tokens):
            missing.append(inv)
    return missing
