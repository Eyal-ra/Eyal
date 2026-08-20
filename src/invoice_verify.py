"""CLI: reconcile forwarded invoices against Sumit/Paperless confirmations.

    python -m src.invoice_verify --config config.yaml --since 2026-03-01T00:00:00Z

Read-only (Mail.Read). Lists every invoice that was forwarded to an intake
mailbox but has no matching "קיבלנו"/"אישור קבלת" confirmation — i.e. things
that may not have landed in the books. Writes ``state/verify_report.md``.
"""

import argparse
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from src.invoice_graph import GraphClient
from src.invoice_verifier import (
    ConfirmationRecord,
    ForwardRecord,
    is_confirmation,
    verify,
)

console = Console()


def _load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Verify forwarded invoices were captured")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--since", default=None, help="ISO date, e.g. 2026-03-01T00:00:00Z")
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--out", default="state")
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    client = GraphClient.from_config(cfg.get("invoice_router", {}))

    console.print("[cyan]מושך העברות (Sent) ואישורים (Inbox)…[/cyan]")
    forwards = [
        ForwardRecord(m.subject, m.intake_recipients()[0])
        for m in client.iter_sent_messages(limit=args.limit, since=args.since)
        if m.intake_recipients()
    ]
    confirmations = []
    for m in client.iter_inbox_messages(limit=args.limit, since=args.since):
        provider = is_confirmation(m["sender"], m["body"])
        if provider:
            confirmations.append(ConfirmationRecord(provider, m["subject"], m["body"]))

    result = verify(forwards, confirmations)
    total = len(forwards)
    console.print(
        f"הועברו: {total} · אושרו: [green]{len(result.confirmed)}[/green] · "
        f"ללא אישור: [red]{len(result.unconfirmed)}[/red] · "
        f"אישורים יתומים: {len(result.orphan_confirmations)}"
    )

    if result.unconfirmed:
        table = Table(title="⚠ הועברו אך לא אומתו (ייתכן שלא נקלטו)")
        table.add_column("נושא", overflow="fold")
        table.add_column("יעד")
        for f in result.unconfirmed:
            table.add_row(f.subject, f.destination)
        console.print(table)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# דוח אימות קליטה",
        "",
        f"- הועברו לכתובות קליטה: **{total}**",
        f"- אושרו ('קיבלנו'/'אישור קבלת'): **{len(result.confirmed)}**",
        f"- ⚠ ללא אישור: **{len(result.unconfirmed)}**",
        "",
    ]
    if result.unconfirmed:
        lines.append("## ⚠ הועברו אך לא אומתו")
        for f in result.unconfirmed:
            lines.append(f"- `{f.subject}` → {f.destination}")
        lines.append("")
    (out_dir / "verify_report.md").write_text("\n".join(lines), encoding="utf-8")
    console.print(f"[green]נשמר:[/green] {args.out}/verify_report.md")


if __name__ == "__main__":
    main()
