"""CLI: learn the invoice routing map from Sent Items and write it for review.

    python -m src.invoice_learn --config config.yaml

Reads the mailbox's sent forwards, builds a ``{client -> intake address}``
map (see :mod:`src.invoice_routing`), prints it for you to eyeball, and
writes ``state/routing_map.yaml`` + ``state/routing_report.md``. Nothing is
forwarded — this step only proposes the routing table.
"""

import argparse
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from src.invoice_graph import GraphClient
from src.invoice_routing import RoutingResult, learn_routes

console = Console()


def _load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _render_table(result: RoutingResult) -> None:
    table = Table(title="מפת ניתוב שנלמדה (לקוח ← כתובת הוצאות)")
    table.add_column("לקוח", overflow="fold")
    table.add_column("כתובת יעד")
    table.add_column("מקורות", justify="right")
    table.add_column("סטטוס")

    counts: dict[str, int] = {}
    for obs in result.observations:
        counts[obs.client] = counts.get(obs.client, 0) + 1

    for client in sorted(result.mapping):
        address = result.mapping[client]
        status = "[red]סתירה[/red]" if client in result.conflicts else "[green]ok[/green]"
        table.add_row(
            result.display_names.get(client, client),
            address,
            str(counts.get(client, 0)),
            status,
        )
    console.print(table)

    if result.conflicts:
        console.print(
            f"[red]⚠ {len(result.conflicts)} לקוחות עם יותר מכתובת אחת — דורש הכרעה ידנית.[/red]"
        )
    if result.unresolved:
        console.print(
            f"[yellow]• {len(result.unresolved)} העברות שלא זוהה בהן לקוח — יידרש ניתוב ידני.[/yellow]"
        )


def _write_outputs(result: RoutingResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    routing_map = {
        result.display_names.get(c, c): addr for c, addr in sorted(result.mapping.items())
    }
    (out_dir / "routing_map.yaml").write_text(
        yaml.safe_dump(routing_map, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )

    lines = ["# מפת ניתוב חשבוניות — לאישור", ""]
    lines.append(f"- לקוחות שמופו: **{len(result.mapping)}**")
    lines.append(f"- סתירות (כמה כתובות לאותו לקוח): **{len(result.conflicts)}**")
    lines.append(f"- העברות ללא זיהוי לקוח: **{len(result.unresolved)}**")
    lines.append("")
    if result.conflicts:
        lines.append("## ⚠ סתירות להכרעה")
        for client, counter in result.conflicts.items():
            opts = ", ".join(f"{a} ×{n}" for a, n in counter.most_common())
            lines.append(f"- **{result.display_names.get(client, client)}**: {opts}")
        lines.append("")
    if result.unresolved:
        lines.append("## • העברות ללא זיהוי לקוח")
        for msg in result.unresolved[:50]:
            lines.append(f"- `{msg.subject or '(ללא נושא)'}` → {', '.join(msg.intake_recipients())}")
        lines.append("")
    (out_dir / "routing_report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Learn invoice routing from Sent Items")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--limit", type=int, default=1000, help="max sent messages to scan")
    parser.add_argument("--since", default=None, help="ISO date, e.g. 2025-01-01T00:00:00Z")
    parser.add_argument("--out", default="state", help="output directory")
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    router_cfg = cfg.get("invoice_router", {})
    seed = {str(k): str(v) for k, v in (router_cfg.get("seed") or {}).items()}

    client = GraphClient.from_config(router_cfg)
    console.print("[cyan]מושך הודעות מ-Sent Items…[/cyan]")
    messages = list(client.iter_sent_messages(limit=args.limit, since=args.since))
    console.print(f"נסרקו {len(messages)} הודעות.")

    result = learn_routes(messages, seed=seed)
    _render_table(result)
    _write_outputs(result, Path(args.out))
    console.print(f"[green]נשמר:[/green] {args.out}/routing_map.yaml , {args.out}/routing_report.md")


if __name__ == "__main__":
    main()
