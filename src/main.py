import argparse
import sys
from pathlib import Path

import yaml

from .diff_display import prompt_decision, render_diff
from .jotform_client import JotformClient
from .matcher import normalize_name
from .powerlink_client import PowerlinkClient
from .ravgonit_gui import RavgonitGUI
from .state_store import StateStore


def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"קובץ קונפיגורציה לא נמצא: {path}. העתק את config.example.yaml ל-config.yaml.")
    # utf-8-sig, not utf-8: editors and PowerShell on Windows often save a BOM,
    # and the YAML parser refuses to start on one.
    return yaml.safe_load(path.read_text(encoding="utf-8-sig"))


def process_submission(submission, powerlink: PowerlinkClient, ravgonit: RavgonitGUI, dry_run: bool) -> str:
    new_name = normalize_name(submission.full_name)

    try:
        pl_customer = powerlink.find_customer(submission.phone, submission.id_number)
    except NotImplementedError:
        pl_customer = None
    pl_name = pl_customer.full_name if pl_customer else None

    try:
        rv_customer = ravgonit.find_customer(pl_customer.customer_number) if pl_customer else None
    except NotImplementedError:
        rv_customer = None
    rv_name = rv_customer.full_name if rv_customer else None

    if pl_name == new_name and rv_name == new_name:
        return "no-change"

    print(render_diff(submission, pl_name, rv_name))
    decision = prompt_decision()
    if decision != "yes":
        return decision

    if dry_run:
        print("  [dry-run] לא בוצע עדכון בפועל")
        return "dry-run"

    if pl_customer and pl_name != new_name:
        powerlink.update_full_name(pl_customer.customer_number, new_name)
        print("  Powerlink עודכן")
    if pl_customer and rv_name != new_name:
        ravgonit.update_full_name(pl_customer.customer_number, new_name)
        print("  רבגונית עודכן")
    return "updated"


def main() -> int:
    parser = argparse.ArgumentParser(description="סנכרון עדכוני לקוחות מ-Jotform ל-Powerlink ורבגונית")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="אל תבצע עדכונים בפועל, רק הצג מה היה קורה")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    cfg = load_config(args.config)

    jot = JotformClient(
        api_key=cfg["jotform"]["api_key"],
        form_id=cfg["jotform"]["form_id"],
        field_map=cfg["jotform"]["field_map"],
        base_url=cfg["jotform"].get("base_url", "https://api.jotform.com"),
    )
    powerlink = PowerlinkClient(
        api_url=cfg["powerlink"]["api_url"],
        api_token=cfg["powerlink"]["api_token"],
        fields=cfg["powerlink"],
    )
    ravgonit = RavgonitGUI(cfg["ravgonit"])
    state = StateStore(cfg["state"]["path"])

    total = updated = skipped = no_change = 0
    for submission in jot.fetch_submissions(limit=args.limit):
        if state.has_seen(submission.submission_id):
            continue
        total += 1
        result = process_submission(submission, powerlink, ravgonit, args.dry_run)
        if result == "updated" or result == "dry-run":
            updated += 1
        elif result == "no-change":
            no_change += 1
        else:
            skipped += 1
        if result != "no" and not args.dry_run:
            state.mark_seen(submission.submission_id)

    print(f"\nסיכום: {total} הגשות חדשות | עודכנו: {updated} | ללא שינוי: {no_change} | דולגו: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
