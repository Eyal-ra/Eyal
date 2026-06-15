"""CLI: process incoming invoices — forward to the right book and tag them.

    # dry run (default): decides + prints, sends NOTHING
    python -m src.invoice_process --config config.yaml

    # for real (needs Mail.Send + Mail.ReadWrite):
    python -m src.invoice_process --config config.yaml --apply

The routing map is loaded from ``state/routing_map.yaml`` (produced and
approved via ``invoice_learn``) merged with the ``seed`` in config; seed
wins. Unresolved invoices are tagged for review, never guessed.
"""

import argparse
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from src.invoice_classifier import ClassifierConfig
from src.invoice_graph import GraphClient
from src.invoice_processor import (
    ALREADY_DONE,
    FORWARDED,
    NEEDS_REVIEW,
    InMemorySeen,
    InvoiceProcessor,
    NoOpMailActions,
    ProcessableInvoice,
)
from src.invoice_routing import normalize_client_name
from src.state_store import StateStore

console = Console()

_ACTION_STYLE = {
    FORWARDED: "[green]נשלח[/green]",
    NEEDS_REVIEW: "[yellow]לבדיקה[/yellow]",
    ALREADY_DONE: "[dim]טופל כבר[/dim]",
}


def _load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _build_classifier_config(router_cfg: dict, map_path: Path) -> ClassifierConfig:
    raw: dict = {}
    if map_path.exists():
        raw.update(yaml.safe_load(map_path.read_text(encoding="utf-8")) or {})
    raw.update(router_cfg.get("seed") or {})
    mapping = {normalize_client_name(k): str(v) for k, v in raw.items()}
    return ClassifierConfig(
        mapping=mapping,
        company_address=str(router_cfg.get("company_address", "")),
        company_aliases=tuple(router_cfg.get("company_aliases", ["אייל רייטר"])),
        id_map={str(k): str(v) for k, v in (router_cfg.get("id_map") or {}).items()},
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Forward + tag incoming invoices")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--map", default="state/routing_map.yaml")
    parser.add_argument("--state", default="state/processed_invoices.json")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--since", default=None, help="ISO date, e.g. 2026-06-01T00:00:00Z")
    parser.add_argument("--apply", action="store_true", help="actually forward + tag (default: dry run)")
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    router_cfg = cfg.get("invoice_router", {})
    classifier_cfg = _build_classifier_config(router_cfg, Path(args.map))

    client = GraphClient.from_config(router_cfg)
    # Dry run must not touch the mailbox nor poison the persistent seen-store.
    actions = client if args.apply else NoOpMailActions()
    seen = StateStore(args.state) if args.apply else InMemorySeen()
    processor = InvoiceProcessor(
        cfg=classifier_cfg, actions=actions, seen=seen, comment=router_cfg.get("comment", "")
    )

    mode = "[red]APPLY[/red]" if args.apply else "[cyan]DRY-RUN[/cyan]"
    console.print(f"מצב: {mode} — מושך Inbox…")
    invoices = [
        ProcessableInvoice(m["id"], m["subject"], m["body"])
        for m in client.iter_inbox_messages(limit=args.limit, since=args.since)
    ]

    results = processor.process_all(invoices)
    by_subject = {inv.message_id: inv.subject for inv in invoices}

    table = Table(title=f"עיבוד חשבוניות ({mode})")
    table.add_column("נושא", overflow="fold", max_width=40)
    table.add_column("לקוח", overflow="fold")
    table.add_column("יעד")
    table.add_column("פעולה")
    forwarded = review = 0
    for r in results:
        if r.action == FORWARDED:
            forwarded += 1
        elif r.action == NEEDS_REVIEW:
            review += 1
        table.add_row(
            by_subject.get(r.message_id, ""),
            r.client or "—",
            r.destination or "—",
            _ACTION_STYLE.get(r.action, r.action),
        )
    console.print(table)
    console.print(f"[green]{forwarded} נשלחו[/green] · [yellow]{review} לבדיקה[/yellow]")
    if not args.apply:
        console.print("[dim]הרצה יבשה — לא נשלח כלום. הוסף --apply לשליחה אמיתית.[/dim]")


if __name__ == "__main__":
    main()
