"""
CLI: "למי טרם הגבתי, ומי מהם אפשר לתאם איתו פגישה למחר".

    python -m src.whatsapp_agent pending      # רק דוח - למי לא הגבת
    python -m src.whatsapp_agent schedule     # שולח הצעת שתי אפשרויות למחר (עם אישור לכל אחד)
    python -m src.whatsapp_agent replies      # מי ענה, ומה בחר
    python -m src.whatsapp_agent probe        # בדיקת ה-API של הבריג'
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .main import load_config
from .proposal_store import ProposalStore
from .slots import Slot, build_slots
from .templates import parse_choice, render_confirmation, render_proposal
from .unanswered import PendingChat, find_pending_chats
from .whatsapp_client import WhatsAppClient


def _prompt(question: str) -> str:
    while True:
        answer = input(f"  {question} [y]es / [n]o / [q]uit > ").strip().lower()
        if answer in {"y", "yes"}:
            return "yes"
        if answer in {"n", "no", "", "s", "skip"}:
            return "no"
        if answer in {"q", "quit"}:
            return "quit"
        print("  תשובה לא חוקית. נסה שוב.")


def _print_pending(pending: list[PendingChat], now: datetime) -> None:
    if not pending:
        print("אין שיחות שממתינות לתשובה. הכל עונה.")
        return
    print(f"\n{len(pending)} שיחות שטרם הגבת להן (הוותיקה קודם):\n")
    for index, chat in enumerate(pending, start=1):
        preview = chat.last_inbound_text.replace("\n", " ")[:70] or "(ללא טקסט - מדיה/הקלטה)"
        unread = f", {chat.unread} לא נקראו" if chat.unread else ""
        print(f"{index:>2}. {chat.display_name} ({chat.phone}) - ממתין {chat.waiting_label(now)}{unread}")
        print(f"    \"{preview}\"")


def cmd_pending(client: WhatsAppClient, cfg: dict, args) -> int:
    now = datetime.now(timezone.utc)
    _print_pending(find_pending_chats(client, cfg, now)[: args.limit], now)
    return 0


def cmd_schedule(client: WhatsAppClient, cfg: dict, args) -> int:
    scheduling = cfg.get("scheduling", {})
    tz = ZoneInfo(scheduling.get("timezone", "Asia/Jerusalem"))
    now_local = datetime.now(tz)
    now = datetime.now(timezone.utc)

    slots, target = build_slots(cfg, today=now_local.date(), now=now_local)
    if len(slots) < 2:
        print("לא נמצאו שתי אפשרויות פנויות למחר. עדכן option_times / busy_file ב-config.yaml.")
        return 1
    print(f"אפשרויות שיוצעו ל-{target:%d/%m}: " + " | ".join(slot.time_range for slot in slots))

    store = ProposalStore(cfg["whatsapp"]["proposals_path"])
    pending = find_pending_chats(client, cfg, now)
    _print_pending(pending, now)

    sent = skipped = 0
    for chat in pending[: args.limit]:
        if store.sent_recently(chat.chat_id, scheduling.get("resend_after_hours", 48), now):
            continue
        message = render_proposal(chat.display_name, slots, now_local.date(), cfg)
        print(f"\n--- {chat.display_name} ({chat.phone}) ---")
        print("\n".join(f"  | {line}" for line in message.splitlines()))

        if not args.yes:
            decision = _prompt("לשלוח?")
            if decision == "quit":
                break
            if decision == "no":
                skipped += 1
                continue

        if args.dry_run:
            print("  [dry-run] לא נשלח בפועל")
            sent += 1
            continue

        client.send_message(chat.chat_id, message)
        store.record(chat.chat_id, chat.display_name, [slot.to_iso() for slot in slots], now)
        print("  נשלח")
        sent += 1

    print(f"\nסיכום: נשלחו {sent} | דולגו {skipped}")
    return 0


def cmd_replies(client: WhatsAppClient, cfg: dict, args) -> int:
    tz = ZoneInfo(cfg.get("scheduling", {}).get("timezone", "Asia/Jerusalem"))
    store = ProposalStore(cfg["whatsapp"]["proposals_path"])
    records = [item for item in store.items() if item[1].get("answer") is None]
    if not records:
        print("אין הצעות שממתינות לתשובה.")
        return 0

    for chat_id, record in records:
        sent_at = datetime.fromisoformat(record["sent_at"])
        messages = client.fetch_messages(chat_id, limit=cfg.get("scan", {}).get("message_limit", 30))
        answers = [m for m in messages if not m.from_me and m.sent_at and m.sent_at > sent_at]
        name = record.get("display_name", chat_id)
        if not answers:
            print(f"{name}: טרם ענה")
            continue

        text = answers[0].text
        choice = parse_choice(text)
        if choice is None:
            print(f"{name}: ענה, אבל לא בחר אפשרות - \"{text[:70]}\"")
            store.record_answer(chat_id, None, text)
            continue

        chosen_iso = record["slots"][choice - 1]
        print(f"{name}: בחר אפשרות {choice} - {datetime.fromisoformat(chosen_iso):%d/%m %H:%M}")
        store.record_answer(chat_id, choice, text)

        if args.confirm and not args.dry_run:
            start = datetime.fromisoformat(chosen_iso)
            duration = timedelta(minutes=cfg.get("scheduling", {}).get("meeting_minutes", 30))
            slot = Slot(start=start, end=start + duration)
            client.send_message(chat_id, render_confirmation(slot, datetime.now(tz).date(), cfg))
            print("  נשלח אישור")
    return 0


def cmd_probe(client: WhatsAppClient, cfg: dict, args) -> int:
    print(f"בודק את {client.base_url} ...\n")
    for entry in client.probe():
        status = entry.get("status", entry.get("error", "?"))
        line = f"{entry['path']:<20} {status}"
        if "items" in entry:
            line += f"  פריטים: {entry['items']}"
        if entry.get("sample_keys"):
            line += f"  שדות: {', '.join(entry['sample_keys'])}"
        if entry.get("note"):
            line += f"  {entry['note']}"
        print(line)
    print("\nהעתק את הנתיב שעבד ואת שמות השדות אל whatsapp.endpoints ב-config.yaml.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="סוכן ווטסאפ - למי טרם הגבתי ותיאום פגישות למחר")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    sub = parser.add_subparsers(dest="command", required=True)

    pending = sub.add_parser("pending", help="דוח: למי טרם הגבת")
    pending.add_argument("--limit", type=int, default=20)
    pending.set_defaults(func=cmd_pending)

    schedule = sub.add_parser("schedule", help="שליחת הצעת שתי אפשרויות למחר")
    schedule.add_argument("--limit", type=int, default=10)
    schedule.add_argument("--dry-run", action="store_true", help="הצג את ההודעות בלי לשלוח")
    schedule.add_argument("--yes", action="store_true", help="שלח בלי לשאול על כל לקוח")
    schedule.set_defaults(func=cmd_schedule)

    replies = sub.add_parser("replies", help="מי ענה להצעה ומה בחר")
    replies.add_argument("--confirm", action="store_true", help="שלח הודעת אישור למי שבחר")
    replies.add_argument("--dry-run", action="store_true")
    replies.set_defaults(func=cmd_replies)

    probe = sub.add_parser("probe", help="בדיקת מבנה ה-API של הבריג'")
    probe.set_defaults(func=cmd_probe)

    args = parser.parse_args()
    cfg = load_config(args.config)
    if "whatsapp" not in cfg:
        sys.exit("חסר סעיף whatsapp ב-config.yaml. ראה config.example.yaml.")
    client = WhatsAppClient(cfg["whatsapp"])
    return args.func(client, cfg, args)


if __name__ == "__main__":
    sys.exit(main())
