"""Act on incoming invoices: forward to the right book and mark the original.

This is step 3 of the automation. For each invoice the classifier resolves
to a destination, the processor:

  1. forwards the original email (with its attachment) to that intake mailbox,
  2. tags the original with a category so you have certainty it was handled
     ("✓ נשלח לסאמיט"),
  3. records it so it is never processed twice.

Invoices the classifier can't resolve are tagged for review and left for you.

The mail side is injected (:class:`MailActions`) so the decision/▶action flow
is fully unit-testable, and so the default is a safe **dry run** that sends
nothing until you opt in.
"""

from dataclasses import dataclass, field
from typing import Protocol

from src.invoice_classifier import AUTO, ClassifierConfig, IncomingInvoice, classify

SENT_CATEGORY = "✓ נשלח לסאמיט"
REVIEW_CATEGORY = "⚠ לבדיקה - ניתוב"

FORWARDED = "forwarded"
NEEDS_REVIEW = "needs_review"
ALREADY_DONE = "already_done"


class MailActions(Protocol):
    """The two mailbox writes the processor needs (Graph implements these)."""

    def forward(self, message_id: str, to: list[str], comment: str = "") -> None: ...

    def add_category(self, message_id: str, category: str) -> None: ...


class NoOpMailActions:
    """Dry-run actions: record what *would* happen, touch nothing."""

    def __init__(self) -> None:
        self.forwards: list[tuple[str, list[str], str]] = []
        self.categories: list[tuple[str, str]] = []

    def forward(self, message_id: str, to: list[str], comment: str = "") -> None:
        self.forwards.append((message_id, to, comment))

    def add_category(self, message_id: str, category: str) -> None:
        self.categories.append((message_id, category))


class InMemorySeen:
    """Default seen-store; swap for StateStore to persist across runs."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def has_seen(self, key: str) -> bool:
        return key in self._seen

    def mark_seen(self, key: str) -> None:
        self._seen.add(key)


@dataclass
class ProcessableInvoice:
    """An incoming invoice email together with its Graph message id."""

    message_id: str
    subject: str = ""
    body: str = ""
    attachments_text: str = ""

    def as_incoming(self) -> IncomingInvoice:
        return IncomingInvoice(self.subject, self.body, self.attachments_text)


@dataclass
class ProcessResult:
    message_id: str
    action: str                       # FORWARDED / NEEDS_REVIEW / ALREADY_DONE
    destination: str | None = None
    client: str | None = None
    reason: str = ""


@dataclass
class InvoiceProcessor:
    """Forward + tag incoming invoices according to the routing config."""

    cfg: ClassifierConfig
    actions: MailActions = field(default_factory=NoOpMailActions)
    seen: object = field(default_factory=InMemorySeen)
    comment: str = ""

    def process(self, invoice: ProcessableInvoice) -> ProcessResult:
        if self.seen.has_seen(invoice.message_id):
            return ProcessResult(invoice.message_id, ALREADY_DONE)

        decision = classify(invoice.as_incoming(), self.cfg)

        if decision.status == AUTO and decision.destination:
            self.actions.forward(invoice.message_id, [decision.destination], self.comment)
            self.actions.add_category(invoice.message_id, SENT_CATEGORY)
            self.seen.mark_seen(invoice.message_id)
            return ProcessResult(
                invoice.message_id, FORWARDED, decision.destination, decision.client, decision.reason
            )

        # Unresolved: surface it in the mailbox, leave the rest to a human.
        self.actions.add_category(invoice.message_id, REVIEW_CATEGORY)
        self.seen.mark_seen(invoice.message_id)
        return ProcessResult(
            invoice.message_id, NEEDS_REVIEW, None, decision.client, decision.reason
        )

    def process_all(self, invoices: list[ProcessableInvoice]) -> list[ProcessResult]:
        return [self.process(inv) for inv in invoices]
