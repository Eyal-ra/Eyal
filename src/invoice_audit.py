"""CLI: find invoices that were received but never forwarded to any book.

    python -m src.invoice_audit --config config.yaml --since 2026-08-01T00:00:00Z

Read-only (Mail.Read). Complements the office "sent but not confirmed"
monitor by catching the opposite blind spot — invoices that arrived and
were never sent onward at all. Writes ``state/missing_report.md``.
"""

import argparse
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from src.invoice_attachments import gather_attachment_text
from src.invoice_graph import GraphClient
from src.invoice_missing import (
    ReceivedInvoice,
    SentForward,
    find_missing,
    looks_like_invoice,
)

console = Console()

# Senders that are internal or are confirmations — never a received expense.
EXCLUDE_SENDER_SUBSTR = (
    "cpateam.co.il",
    "sumit.co.il",
    "paperless.tax",
    "invoice-maven.com",
    "biziboxcpa.com",
)


def _load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _excluded(sender: str) -> bool:
    s = (sender or "").lower()
    return any(sub in s for sub in EXCLUDE_SENDER_SUBSTR)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Find received-but-not-forwarded invoices")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--since", default=None, help="ISO date, e.g. 2026-08-01T00:00:00Z")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--no-pdf", action="store_true", help="skip reading attachment text")
    parser.add_argument("--out", default="state")
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    router_cfg = cfg.get("invoice_router", {})
    own = tuple(router_cfg.get("own_addresses", ["eyal@cpateam.co.il"]))
    client = GraphClient.from_config(router_cfg)

    console.print("[cyan]מושך Inbox (חשבוניות שהתקבלו) ו-Sent (מה שהועבר)…[/cyan]")
    received: list[ReceivedInvoice] = []
    for m in client.iter_inbox_messages(limit=args.limit, since=args.since):
        if _excluded(m["sender"]) or not looks_like_invoice(m["subject"], m["body"], m["hasAttachments"]):
            continue
        att = ""
        if not args.no_pdf and m.get("hasAttachments"):
            try:
                att = gather_attachment_text(client.get_attachments(m["id"]))
            except Exception:
                att = ""
        received.append(
            ReceivedInvoice(m["subject"], m["body"], m["sender"], m["hasAttachments"], att)
        )

    forwards = [
        SentForward(m.subject, m.body)
        for m in client.iter_sent_messages(limit=args.limit, since=args.since)
        if m.intake_recipients()
    ]

    missing = find_missing(received, forwards, own_addresses=own)
    console.print(
        f"חשבוניות שהתקבלו: {len(received)} · הועברו: {len(received) - len(missing)} · "
        f"[red]לא הועברו: {len(missing)}[/red]"
    )

    if missing:
        table = Table(title="⚠ התקבלו אך לא הועברו לאף ספר")
        table.add_column("שולח", overflow="fold")
        table.add_column("נושא", overflow="fold")
        for inv in missing:
            table.add_row(inv.sender, inv.subject or "(ללא נושא)")
        console.print(table)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# חשבוניות שהתקבלו אך לא הועברו",
        "",
        f"- התקבלו (זוהו כחשבונית): **{len(received)}**",
        f"- ⚠ לא הועברו לאף ספר: **{len(missing)}**",
        "",
    ]
    for inv in missing:
        lines.append(f"- **{inv.sender}** — `{inv.subject or '(ללא נושא)'}`")
    (out_dir / "missing_report.md").write_text("\n".join(lines), encoding="utf-8")
    console.print(f"[green]נשמר:[/green] {args.out}/missing_report.md")


if __name__ == "__main__":
    main()
