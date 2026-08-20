"""Decide where an *incoming* invoice should be forwarded.

Given an invoice that just arrived, work out which bookkeeping intake
mailbox it belongs to, using the routing map learned by
:mod:`src.invoice_routing` (plus a couple of rules):

* If the invoice is addressed to Eyal's own firm ("לכבוד: אייל רייטר…") it is
  a company expense -> the company intake address.
* If it is addressed to a known client -> that client's intake address.
* Otherwise it needs a human decision ("review").

This module only *decides*; actually forwarding/marking the mail is a later
step that needs Mail.Send / Mail.ReadWrite.
"""

from dataclasses import dataclass, field

from src.invoice_routing import (
    extract_client_name,
    extract_company_ids,
    normalize_client_name,
)

AUTO = "auto"
REVIEW = "review"


@dataclass
class IncomingInvoice:
    """An invoice email under consideration for routing."""

    subject: str = ""
    body: str = ""
    attachments_text: str = ""  # OCR'd / extracted text of attached PDFs

    @property
    def text(self) -> str:
        return "\n".join(p for p in (self.body, self.attachments_text) if p)


@dataclass
class RoutingDecision:
    """The outcome of :func:`classify`."""

    status: str            # AUTO (route it) or REVIEW (ask a human)
    destination: str | None = None
    client: str | None = None
    reason: str = ""


@dataclass
class ClassifierConfig:
    """Inputs that drive classification."""

    mapping: dict[str, str] = field(default_factory=dict)   # client name -> address
    company_address: str = ""                               # Eyal's own company book
    company_aliases: tuple[str, ...] = ("אייל רייטר",)      # substrings that mean "us"
    id_map: dict[str, str] = field(default_factory=dict)    # company id -> address


def _matches_company(client: str, aliases: tuple[str, ...]) -> bool:
    norm = normalize_client_name(client)
    return any(normalize_client_name(a) in norm for a in aliases if a)


def classify(invoice: IncomingInvoice, cfg: ClassifierConfig) -> RoutingDecision:
    """Return a routing decision for *invoice*.

    Looks for the addressed client in the body first, then attachment text,
    then the subject; matches it against the company aliases and the learned
    map; falls back to a company-id lookup; else asks for review.
    """
    text = invoice.text
    client = (
        extract_client_name(text)
        or extract_client_name(invoice.subject)
    )

    if client and _matches_company(client, cfg.company_aliases):
        if cfg.company_address:
            return RoutingDecision(AUTO, cfg.company_address, client, "own company expense")
        return RoutingDecision(REVIEW, None, client, "own company but no company_address configured")

    if client:
        address = cfg.mapping.get(normalize_client_name(client))
        if address:
            return RoutingDecision(AUTO, address, client, "matched client in routing map")

    for company_id in extract_company_ids(text):
        if company_id in cfg.id_map:
            return RoutingDecision(AUTO, cfg.id_map[company_id], client, f"matched company id {company_id}")

    if client:
        return RoutingDecision(REVIEW, None, client, f"client '{client}' not in routing map")
    return RoutingDecision(REVIEW, None, None, "could not identify the addressed client")
