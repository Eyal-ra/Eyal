"""Close the loop: verify that forwarded invoices were actually captured.

This is the automated version of the manual reconciliation: match every
invoice we forwarded to an intake mailbox against the confirmation it should
trigger, and flag anything sent-but-unconfirmed (the real "gap").

Confirmations:
  * Sumit       (support@sumit.co.il)      — "קיבלנו! המייל ששלחת התקבל…",
                 subject "Re: Fw: <original subject>"
  * Paperless   (notifications@paperless.tax) — "נקלטו בהצלחה…: <file>.pdf"

Matching uses two signals: a normalized subject key (after stripping
Re:/Fw: prefixes), and shared reference tokens (receipt ids like
#1234-5678-9012, or invoice numbers) — the latter catches Paperless, whose
confirmation names the attached file rather than the subject.
"""

import re
from dataclasses import dataclass, field

from src.invoice_routing import normalize_client_name

PROVIDER_SENDERS = {
    "support@sumit.co.il": "sumit",
    "notifications@paperless.tax": "paperless",
}
CONFIRMATION_PHRASES = (
    "קיבלנו",
    "המייל ששלחת התקבל",
    "נקלטו בהצלחה",
    "אישור קבלת",
)

_REPLY_PREFIX_RE = re.compile(
    r"^\s*(re|fw|fwd|תגובה|העברה)\s*:\s*", re.IGNORECASE
)
_RECEIPT_ID_RE = re.compile(r"#?\d{3,}(?:[-–]\d{3,})+")
_LONG_NUMBER_RE = re.compile(r"(?<!\d)\d{5,}(?!\d)")


def strip_reply_prefixes(subject: str) -> str:
    """Remove any stack of leading Re:/Fw:/Fwd:/תגובה:/העברה: tokens."""
    s = subject or ""
    while True:
        stripped = _REPLY_PREFIX_RE.sub("", s, count=1)
        if stripped == s:
            return s.strip()
        s = stripped


def subject_key(subject: str) -> str:
    """Normalized comparison key for a subject line."""
    return normalize_client_name(strip_reply_prefixes(subject)).lower()


def reference_tokens(text: str) -> set[str]:
    """Distinctive ids in *text*: receipt ids and long invoice numbers."""
    tokens: set[str] = set()
    for m in _RECEIPT_ID_RE.findall(text or ""):
        tokens.add(re.sub(r"[#–]", lambda x: "-" if x.group() == "–" else "", m))
    tokens.update(_LONG_NUMBER_RE.findall(text or ""))
    return tokens


def is_confirmation(sender: str, body: str) -> str | None:
    """Return the provider name if (sender, body) looks like a capture receipt."""
    provider = PROVIDER_SENDERS.get((sender or "").lower())
    if provider and any(p in (body or "") for p in CONFIRMATION_PHRASES):
        return provider
    return None


@dataclass
class ForwardRecord:
    subject: str
    destination: str = ""


@dataclass
class ConfirmationRecord:
    provider: str
    subject: str = ""
    body: str = ""

    def keys(self) -> tuple[str, set[str]]:
        return subject_key(self.subject), reference_tokens(
            f"{self.subject}\n{self.body}"
        )


@dataclass
class VerificationResult:
    confirmed: list[ForwardRecord] = field(default_factory=list)
    unconfirmed: list[ForwardRecord] = field(default_factory=list)
    orphan_confirmations: list[ConfirmationRecord] = field(default_factory=list)


def verify(
    forwards: list[ForwardRecord],
    confirmations: list[ConfirmationRecord],
) -> VerificationResult:
    """Match forwards to confirmations; report the ones with no match."""
    subj_index: dict[str, int] = {}
    token_index: dict[str, int] = {}
    conf_keys = []
    for i, conf in enumerate(confirmations):
        skey, tokens = conf.keys()
        conf_keys.append((skey, tokens))
        if skey:
            subj_index.setdefault(skey, i)
        for tok in tokens:
            token_index.setdefault(tok, i)

    result = VerificationResult()
    matched: set[int] = set()

    for fwd in forwards:
        fkey = subject_key(fwd.subject)
        ftokens = reference_tokens(fwd.subject)
        idx = subj_index.get(fkey) if fkey else None
        if idx is None:
            for tok in ftokens:
                if tok in token_index:
                    idx = token_index[tok]
                    break
        if idx is not None:
            matched.add(idx)
            result.confirmed.append(fwd)
        else:
            result.unconfirmed.append(fwd)

    for i, conf in enumerate(confirmations):
        if i not in matched:
            result.orphan_confirmations.append(conf)
    return result
