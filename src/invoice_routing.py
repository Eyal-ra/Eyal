"""Learn invoice-routing rules from previously forwarded ("Sent") emails.

Eyal forwards every supplier/client invoice he receives to a bookkeeping
"intake" mailbox, so it lands as an expense in the right set of books:

  * his company book          -> <id>@expense.co.il        (Sumit)
  * his sole-proprietor book  -> <token>@mail.paperless.tax (Paperless)
  * a client's book           -> <id>@expense.co.il / @invoice-maven.com /
                                 @biziboxcpa.com

Every one of those forwards is preserved in "Sent Items" with the exact
recipient address, and the invoice body names the client it is addressed to
(typically "לכבוד: <client>", or a Rivhit greeting "שלום <client> <client>,").

This module mines that history to learn a ``{client -> intake address}``
routing map, so future invoices can be routed automatically. It is pure
logic (no network) so it can be unit-tested against real message samples;
fetching the messages is the job of ``invoice_graph``.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

# Mail domains that represent a bookkeeping intake (where a forwarded
# invoice becomes an expense). An address in one of these domains marks a
# message as a "routing" forward we can learn from.
INTAKE_DOMAINS = (
    "expense.co.il",       # Sumit
    "mail.paperless.tax",  # Paperless (sole proprietor)
    "invoice-maven.com",   # Maven
    "biziboxcpa.com",      # Bizibox
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A run of Hebrew/ASCII quote-like marks, normalised to a single ".
_QUOTES_RE = re.compile(r"[\"'`׳״]+")
_WS_RE = re.compile(r"\s+")
# 9-digit Israeli company / dealer id (ח.פ / ע.מ), not glued to more digits.
_COMPANY_ID_RE = re.compile(r"(?<!\d)(\d{9})(?!\d)")

# Trailers that may follow the client name on the same line as "לכבוד:".
_CLIENT_TRAILERS = ("מסמך ממוחשב", "מסמך זה", "מספר הקצאה")


def address_domain(address: str) -> str:
    """Return the lower-cased domain part of an email address."""
    return address.split("@", 1)[1].lower() if "@" in (address or "") else ""


def is_intake_address(address: str) -> bool:
    """True if *address* belongs to a known bookkeeping-intake domain."""
    return address_domain(address) in INTAKE_DOMAINS


def normalize_client_name(name: str) -> str:
    """Canonical form of a client name for comparison / map keys.

    Collapses whitespace and unifies the various quote marks Hebrew company
    suffixes use (בע"מ / בע``מ / בע׳׳מ all become בע"מ).
    """
    if not name:
        return ""
    name = _QUOTES_RE.sub('"', name)
    name = _WS_RE.sub(" ", name).strip()
    return name.strip(" ,.-")


def _dedupe_doubled(name: str) -> str:
    """Rivhit greets with the client name twice ("X X"); keep one copy."""
    norm = normalize_client_name(name)
    if not norm:
        return norm
    words = norm.split(" ")
    if len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            return " ".join(words[:half])
    return norm


def extract_client_name(text: str) -> str | None:
    """Extract the client an invoice is addressed to, or ``None``.

    Tries the explicit "לכבוד:" label first (used by TML and most issuers),
    then falls back to the Rivhit greeting "שלום <client>,".
    """
    if not text:
        return None

    for line in text.splitlines():
        if "לכבוד" in line:
            tail = line.split("לכבוד", 1)[1].lstrip(": \t")
            tail = _EMAIL_RE.split(tail)[0]
            for trailer in _CLIENT_TRAILERS:
                tail = tail.split(trailer)[0]
            name = normalize_client_name(tail)
            if name:
                return name

    greeting = re.search(r"שלום\s+(.+?)[,\n\r]", text)
    if greeting:
        name = _dedupe_doubled(greeting.group(1))
        if name:
            return name
    return None


def extract_company_ids(text: str) -> list[str]:
    """All distinct 9-digit ids appearing in *text* (ח.פ / ע.מ candidates)."""
    seen: list[str] = []
    for match in _COMPANY_ID_RE.findall(text or ""):
        if match not in seen:
            seen.append(match)
    return seen


@dataclass
class SentMessage:
    """A message from the Sent Items folder."""

    subject: str = ""
    body: str = ""
    recipients: list[str] = field(default_factory=list)

    def intake_recipients(self) -> list[str]:
        return [r for r in self.recipients if is_intake_address(r)]


@dataclass
class RouteObservation:
    """One learned data point: this client was forwarded to this address."""

    client: str          # normalized client name
    display_name: str    # first-seen original spelling
    address: str
    subject: str


@dataclass
class RoutingResult:
    """Outcome of :func:`learn_routes`."""

    mapping: dict[str, str] = field(default_factory=dict)
    display_names: dict[str, str] = field(default_factory=dict)
    conflicts: dict[str, Counter] = field(default_factory=dict)
    observations: list[RouteObservation] = field(default_factory=list)
    unresolved: list[SentMessage] = field(default_factory=list)

    def address_for(self, client_name: str) -> str | None:
        """Look up the learned intake address for *client_name*."""
        return self.mapping.get(normalize_client_name(client_name))


def learn_routes(
    messages: list[SentMessage],
    seed: dict[str, str] | None = None,
) -> RoutingResult:
    """Build a ``{client -> intake address}`` map from sent forwards.

    For every message addressed to an intake mailbox we extract the client
    it concerns and record (client, address). The winning address per client
    is the most frequently used one; clients seen with more than one distinct
    address are also reported in :attr:`RoutingResult.conflicts` so a human
    can resolve them.

    *seed* is an optional ``{client -> address}`` map of hand-verified rules
    that override anything learned from history.
    """
    result = RoutingResult()
    per_client: dict[str, Counter] = {}

    for msg in messages:
        intake = msg.intake_recipients()
        if not intake:
            continue
        client = extract_client_name(msg.body) or extract_client_name(msg.subject)
        if not client:
            result.unresolved.append(msg)
            continue
        result.display_names.setdefault(client, client)
        for address in intake:
            result.observations.append(
                RouteObservation(client, result.display_names[client], address, msg.subject)
            )
            per_client.setdefault(client, Counter())[address] += 1

    for client, counter in per_client.items():
        result.mapping[client] = counter.most_common(1)[0][0]
        if len(counter) > 1:
            result.conflicts[client] = counter

    for client, address in (seed or {}).items():
        key = normalize_client_name(client)
        result.mapping[key] = address
        result.display_names.setdefault(key, client)
        result.conflicts.pop(key, None)

    return result
