"""
CLI: "למי טרם הגבתי, ומי מהם אפשר לתאם איתו פגישה למחר".

    python -m src.whatsapp_agent probe                 # בדיקת ה-API של הבריג'
    python -m src.whatsapp_agent pending               # דוח: למי טרם הגבת
    python -m src.whatsapp_agent schedule --dry-run    # להציג את ההודעות בלי לשלוח
    python -m src.whatsapp_agent schedule              # שליחה, עם אישור לכל לקוח
    python -m src.whatsapp_agent replies --confirm     # מי ענה, מה בחר, ושליחת אישור
    python -m src.whatsapp_agent agenda                # מה נסגר למחר
"""

import argparse
import json
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from .audit_log import AuditLog
from .calendar_outlook import working_hours_gaps
from .calendar_source import CalendarError, calendar_backend, load_busy, resolve_provider
from .main import load_config
from .proposal_store import ProposalStore
from .slots import Slot, build_slots
from .templates import (
    CONFIRMED,
    DECLINED,
    UNCLEAR,
    parse_answer,
    render_confirmation,
    render_no_fit,
    render_proposal,
)
from .tz import TimezoneMissing, get_timezone
from .unanswered import PendingChat, ScanResult, scan_pending
from .whatsapp_client import WhatsAppClient, WhatsAppError


class Agent:
    """Everything the sub-commands share: config, client, store and audit log."""

    def __init__(self, cfg: dict, client: WhatsAppClient):
        self.cfg = cfg
        self.client = client
        self.scheduling = cfg.get("scheduling", {})
        self.tz = get_timezone(self.scheduling.get("timezone", "Asia/Jerusalem"))
        self.store = ProposalStore(cfg["whatsapp"]["proposals_path"])
        self.audit = AuditLog(cfg["whatsapp"].get("log_path"))

    @property
    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    @property
    def now_local(self) -> datetime:
        return datetime.now(self.tz)

    def meeting_duration(self) -> timedelta:
        return timedelta(minutes=self.scheduling.get("meeting_minutes", 30))

    def slot_from_iso(self, slot_iso: str) -> Slot:
        start = datetime.fromisoformat(slot_iso)
        return Slot(start=start, end=start + self.meeting_duration())

    def book_in_calendar(self, name: str, phone: str, slot: Slot) -> Optional[str]:
        """Write the agreed meeting into Google Calendar, when that is turned on."""
        calendar = calendar_backend(self.cfg)
        if calendar is None or not getattr(calendar, "create_events", False):
            return None
        summary = self.scheduling.get("event_title", "פגישה - {name}").format(name=name)
        return calendar.create_event(summary, slot.start, slot.end, description=f"תואם בווטסאפ. טלפון: {phone}")


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


def _matches_filter(chat: PendingChat, needle: str) -> bool:
    needle = needle.strip().lower()
    return needle in chat.display_name.lower() or needle in chat.phone or needle in chat.chat_id.lower()


def _print_scan(result: ScanResult, now: datetime) -> None:
    for name, error in result.errors:
        print(f"אזהרה: לא ניתן לקרוא את השיחה עם {name} - {error}")
    if not result.pending:
        print(f"נסרקו {result.scanned} שיחות. אין שיחות שממתינות לתשובה.")
        return
    print(f"\n{len(result.pending)} שיחות שטרם הגבת להן, מתוך {result.scanned} שנסרקו (הוותיקה קודם):\n")
    for index, chat in enumerate(result.pending, start=1):
        badges = []
        if chat.unread:
            badges.append(f"{chat.unread} לא נקראו")
        if chat.inbound_streak > 1:
            badges.append(f"{chat.inbound_streak} הודעות ברצף")
        suffix = f" [{', '.join(badges)}]" if badges else ""
        print(f"{index:>2}. {chat.display_name} ({chat.phone}) - ממתין {chat.waiting_label(now)}{suffix}")
        print(f"    \"{chat.preview()}\"")


def _scan(agent: Agent, args) -> ScanResult:
    verbose = not getattr(args, "json", False)

    def progress(done: int, total: int) -> None:
        if verbose:
            print(f"\rסורק שיחות... {done}/{total}", end="", flush=True)
            if done == total:
                print("\r" + " " * 40 + "\r", end="")

    result = scan_pending(agent.client, agent.cfg, agent.now_utc, on_progress=progress)
    if getattr(args, "only", None):
        result.pending = [chat for chat in result.pending if _matches_filter(chat, args.only)]
    return result


# --- commands -----------------------------------------------------------


def cmd_pending(agent: Agent, args) -> int:
    now = agent.now_utc
    result = _scan(agent, args)
    pending = result.pending[: args.limit]
    if args.json:
        print(json.dumps([chat.to_dict(now) for chat in pending], ensure_ascii=False, indent=2))
        return 0
    _print_scan(ScanResult(pending, result.scanned, result.errors), now)
    return 0


def cmd_schedule(agent: Agent, args) -> int:
    now, now_local = agent.now_utc, agent.now_local
    slots, target = build_slots(agent.cfg, today=now_local.date(), now=now_local)
    if len(slots) < 2:
        print("לא נמצאו שתי אפשרויות פנויות. עדכן option_times / busy_file ב-config.yaml.")
        return 1
    if target != now_local.date() + timedelta(days=1):
        print(f"מחר אינו יום עבודה או שאין בו שתי אפשרויות פנויות - ההצעות יהיו ל-{target:%d/%m}.")
    print(f"אפשרויות שיוצעו ל-{target:%d/%m}: " + " | ".join(slot.time_range for slot in slots))

    result = _scan(agent, args)
    _print_scan(result, now)

    resend_after = agent.scheduling.get("resend_after_hours", 48)
    sent = skipped = declined = 0
    for chat in result.pending[: args.limit]:
        reason = agent.store.should_skip(chat.chat_id, resend_after, now)
        if reason:
            print(f"\n--- {chat.display_name}: דילוג ({reason})")
            skipped += 1
            continue

        message = render_proposal(chat.display_name, slots, now_local.date(), agent.cfg, chat.waiting_hours(now))
        print(f"\n--- {chat.display_name} ({chat.phone}) - ממתין {chat.waiting_label(now)} ---")
        print("\n".join(f"  | {line}" for line in message.splitlines()))

        if not args.yes:
            decision = _prompt("לשלוח?")
            if decision == "quit":
                print("\nהופסק לבקשתך.")
                break
            if decision == "no":
                declined += 1
                continue

        if args.dry_run:
            print("  [dry-run] לא נשלח בפועל")
            sent += 1
            continue

        try:
            agent.client.send_message(chat.chat_id, message)
        except WhatsAppError as exc:
            print(f"  שגיאה בשליחה: {exc}")
            agent.audit.write("send_failed", chat.chat_id, chat.display_name, message, error=str(exc))
            continue

        agent.store.record(chat.chat_id, chat.display_name, [slot.to_iso() for slot in slots], now)
        agent.audit.write("proposal", chat.chat_id, chat.display_name, message,
                          slots=[slot.to_iso() for slot in slots])
        print("  נשלח")
        sent += 1

    verb = "היו נשלחות" if args.dry_run else "נשלחו"
    print(f"\nסיכום: {verb} {sent} | לא אישרת {declined} | דולגו אוטומטית {skipped}")
    if sent and not args.dry_run:
        print("לבדיקת התשובות מאוחר יותר: python -m src.whatsapp_agent replies --confirm")
    return 0


def cmd_replies(agent: Agent, args) -> int:
    awaiting = agent.store.awaiting_answer()
    if not awaiting:
        print("אין הצעות שממתינות לתשובה.")
        return 0

    message_limit = agent.cfg.get("scan", {}).get("message_limit", 30)
    answered = waiting = unclear = 0
    for chat_id, record in awaiting:
        name = record.get("display_name", chat_id)
        sent_at = datetime.fromisoformat(record["sent_at"])
        slots = [agent.slot_from_iso(slot_iso) for slot_iso in record.get("slots", [])]
        try:
            messages = agent.client.fetch_messages(chat_id, limit=message_limit)
        except WhatsAppError as exc:
            print(f"{name}: שגיאה בקריאת השיחה - {exc}")
            continue

        replies = [m for m in messages if not m.from_me and m.sent_at and m.sent_at > sent_at]
        if not replies:
            print(f"{name}: טרם ענה")
            waiting += 1
            continue

        answer = _read_answer(replies, slots)
        if answer.kind != UNCLEAR:
            # An unclear reply stays open on purpose: if they write "2" an hour
            # later, the next run should still pick it up.
            agent.store.record_answer(chat_id, answer.kind, answer.option, answer.text, replies[-1].sent_at)

        if answer.kind == CONFIRMED:
            slot = slots[answer.option - 1]
            print(f"{name}: בחר אפשרות {answer.option} - {slot.start:%d/%m %H:%M}")
            answered += 1
            if not args.dry_run:
                try:
                    link = agent.book_in_calendar(name, chat_id.split("@")[0], slot)
                except CalendarError as exc:
                    print(f"  לא נוצר אירוע ביומן: {exc}")
                else:
                    if link:
                        print("  נוצר אירוע ביומן")
                        agent.audit.write("calendar_event", chat_id, name, slot.to_iso(), link=link)
            _maybe_reply(agent, args, chat_id, name,
                         render_confirmation(slot, agent.now_local.date(), agent.cfg), "confirmation")
            if not args.dry_run and args.confirm:
                agent.store.mark_confirmation_sent(chat_id)
        elif answer.kind == DECLINED:
            print(f"{name}: השעות לא מתאימות - \"{answer.text[:60]}\"")
            unclear += 1
            _maybe_reply(agent, args, chat_id, name, render_no_fit(agent.cfg), "no_fit")
        else:
            print(f"{name}: ענה, אבל לא ברור מה נבחר - \"{answer.text[:60]}\"  (טפל ידנית)")
            unclear += 1

    print(f"\nסיכום: נקבעו {answered} | ממתינים {waiting} | דורשים טיפול ידני {unclear}")
    return 0


def _read_answer(replies, slots):
    """Newest message wins - "אחזור אליך" followed by "1" is a yes to option 1.
    If no single message decides it, try them joined: an answer is often split
    across two short messages ("שתיים" then "בבקשה")."""
    for message in reversed(replies):
        answer = parse_answer(message.text, slots)
        if answer.kind != UNCLEAR:
            return answer
    return parse_answer(" ".join(m.text for m in replies if m.text), slots)


def _maybe_reply(agent: Agent, args, chat_id: str, name: str, text: str, action: str) -> None:
    if not args.confirm:
        return
    if args.dry_run:
        print(f"  [dry-run] היה נשלח: {text.splitlines()[0]}")
        return
    try:
        agent.client.send_message(chat_id, text)
    except WhatsAppError as exc:
        print(f"  שגיאה בשליחת התשובה: {exc}")
        return
    agent.audit.write(action, chat_id, name, text)
    print("  נשלחה תשובה")


def cmd_agenda(agent: Agent, args) -> int:
    day = agent.now_local.date() + timedelta(days=args.days)
    booked = agent.store.booked_for(day.isoformat())
    if not booked:
        print(f"אין פגישות שנקבעו דרך הסוכן ל-{day:%d/%m}.")
        return 0
    print(f"פגישות שנקבעו דרך הסוכן ל-{day:%d/%m}:\n")
    rows = []
    for chat_id, record in booked:
        slot = agent.slot_from_iso(record["slots"][record["answer"]["choice"] - 1])
        rows.append((slot.start, record.get("display_name", chat_id), chat_id.split("@")[0], slot.time_range))
    for start, name, phone, time_range in sorted(rows):
        print(f"  {time_range}  {name} ({phone})")
    return 0


def cmd_calendar(agent: Agent, args) -> int:
    """Check calendar access the same way `probe` checks the bridge."""
    provider = resolve_provider(agent.cfg)
    print(f"מקור היומן: {provider}")
    if provider == "none":
        print("לא הוגדר יומן - כל השעות ב-option_times נחשבות פנויות.")
        print("להפעלה, ב-config.yaml תחת scheduling.calendar:")
        print('    provider: "outlook"   # האאוטלוק שמותקן במחשב הזה')
        print("    (או graph / google / file - ראה README)")
        return 0

    today = agent.now_local.date()
    start = datetime.combine(today + timedelta(days=1), time(0, 0), tzinfo=agent.tz)
    end = start + timedelta(days=args.days)
    try:
        busy = load_busy(agent.cfg, agent.tz, start, end)
    except CalendarError as exc:
        print(f"שגיאה: {exc}")
        return 1

    print(f"תפוס בין {start:%d/%m} ל-{end:%d/%m}:")
    if not busy:
        print("  (לא נמצאו אירועים)")
    for busy_start, busy_end in sorted(busy):
        print(f"  {busy_start:%d/%m %H:%M} - {busy_end:%H:%M}")

    work = agent.scheduling
    day_start = datetime.combine(today + timedelta(days=1), time(8, 0), tzinfo=agent.tz)
    day_end = datetime.combine(today + timedelta(days=1), time(19, 0), tzinfo=agent.tz)
    gaps = working_hours_gaps(busy, day_start, day_end, agent.meeting_duration())
    if gaps:
        print(f"\nחלונות פנויים מחר ({day_start:%d/%m}, {work.get('meeting_minutes', 30)} דק' ומעלה):")
        for gap_start, gap_end in gaps:
            print(f"  {gap_start:%H:%M} - {gap_end:%H:%M}")

    slots, target = build_slots(agent.cfg, today=today, now=agent.now_local, busy=busy)
    if slots:
        print(f"\nמה שיוצע ללקוחות ({target:%d/%m}): " + " | ".join(slot.time_range for slot in slots))
    else:
        print("\nלא נמצאו שתי אפשרויות פנויות - הרחב את option_times או את lookahead_days.")

    calendar = calendar_backend(agent.cfg)
    if calendar and getattr(calendar, "create_events", False):
        print("יצירת אירועים ביומן: פעילה (אירוע ייווצר כשלקוח מאשר שעה)")
    elif calendar:
        print("יצירת אירועים ביומן: כבויה (calendar.create_events: true כדי להפעיל)")
    return 0


def cmd_probe(agent: Agent, args) -> int:
    print(f"בודק את {agent.client.base_url} ...\n")
    report = agent.client.probe()

    def show(title: str, entries: list[dict]) -> None:
        print(title)
        if not entries:
            print("  (לא נבדק - לא נמצאה שיחה לדוגמה)")
            return
        for entry in entries:
            status = entry.get("status", entry.get("error", "?"))
            line = f"  {entry['path']:<38} {status}"
            if "items" in entry:
                line += f"  פריטים: {entry['items']}"
            if entry.get("sample_keys"):
                line += f"  שדות: {', '.join(entry['sample_keys'])}"
            if entry.get("note"):
                line += f"  {entry['note']}"
            print(line)

    discovery = report.get("discovery") or []
    if discovery:
        print("מה השרת מספר על עצמו:")
        for entry in discovery:
            print(f"  {entry['path']:<28} {entry.get('status', entry.get('error', '?'))}")
            if entry.get("body"):
                print(f"      {entry['body']}")
        print()

    show("שיחות:", report["chats"])
    print()
    show("הודעות:", report["messages"])

    suggested = report.get("suggested") or {}
    if suggested:
        print("\nהוסף ל-config.yaml:\n")
        print("whatsapp:")
        print("  endpoints:")
        for key in ("chats", "messages"):
            if key in suggested:
                print(f"    {key}: \"{suggested[key]}\"")
        print("    send: \"/send-message\"   # יש לאמת מול תיעוד הבריג'")
    else:
        print("\nאף נתיב לא החזיר רשימה של שיחות.")
        statuses = {entry.get("status") for entry in report["chats"]} | \
                   {entry.get("status") for entry in report.get("discovery", [])}
        if statuses & {401, 403}:
            # 401 means the paths are right and the credentials are not - saying
            # "check the paths" here sends you looking in the wrong place.
            print("השרת מחזיר 401 - כלומר הנתיבים נכונים, אבל ההרשאה נדחית.")
            print("ודא שב-config.yaml, תחת whatsapp, יש בדיוק:")
            print("  headers:")
            print('    X-Api-Key: "המפתח שהגדרת ב-docker run"')
            print("(שתי רמות הזחה, והמפתח זהה בדיוק לזה שב-WHATSAPP_API_KEY)")
        elif any(entry.get("status") for entry in report["chats"]):
            print("השרת עונה, אבל הנתיבים שלו שונים מהמוכרים. שתי אפשרויות:")
            print("  1. אם הבריג' דורש שם session בנתיב - הגדר whatsapp.session ב-config.yaml והרץ שוב.")
            print("  2. חפש בתיעוד של הבריג' את הנתיב לרשימת שיחות, והגדר אותו ב-whatsapp.endpoints.")
        else:
            print("השרת לא ענה בכלל. ודא שהבריג' רץ ושהכתובת ב-base_url נכונה.")
    print("\nשים לב: נתיב השליחה לא נבדק כאן כדי לא לשלוח הודעה אמיתית.")
    return 0


# --- entry point --------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="סוכן ווטסאפ - למי טרם הגבתי ותיאום פגישות למחר")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    sub = parser.add_subparsers(dest="command", required=True)

    pending = sub.add_parser("pending", help="דוח: למי טרם הגבת")
    pending.add_argument("--limit", type=int, default=20)
    pending.add_argument("--only", help="סנן לפי שם / טלפון")
    pending.add_argument("--json", action="store_true", help="פלט JSON")
    pending.set_defaults(func=cmd_pending)

    schedule = sub.add_parser("schedule", help="שליחת הצעת שתי אפשרויות למחר")
    schedule.add_argument("--limit", type=int, default=10)
    schedule.add_argument("--only", help="סנן לפי שם / טלפון")
    schedule.add_argument("--dry-run", action="store_true", help="הצג את ההודעות בלי לשלוח")
    schedule.add_argument("--yes", action="store_true", help="שלח בלי לשאול על כל לקוח")
    schedule.set_defaults(func=cmd_schedule)

    replies = sub.add_parser("replies", help="מי ענה להצעה ומה בחר")
    replies.add_argument("--confirm", action="store_true", help="שלח אישור למי שבחר, ותשובה למי שלא מתאים")
    replies.add_argument("--dry-run", action="store_true")
    replies.set_defaults(func=cmd_replies)

    agenda = sub.add_parser("agenda", help="מה נקבע דרך הסוכן")
    agenda.add_argument("--days", type=int, default=1, help="0=היום, 1=מחר (ברירת מחדל)")
    agenda.set_defaults(func=cmd_agenda)

    calendar = sub.add_parser("calendar", help="בדיקת גישה ליומן ומה פנוי")
    calendar.add_argument("--days", type=int, default=7, help="כמה ימים קדימה להציג")
    calendar.set_defaults(func=cmd_calendar)

    probe = sub.add_parser("probe", help="בדיקת מבנה ה-API של הבריג'")
    probe.set_defaults(func=cmd_probe)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    if "whatsapp" not in cfg:
        sys.exit("חסר סעיף whatsapp ב-config.yaml. ראה config.example.yaml.")
    try:
        agent = Agent(cfg, WhatsAppClient(cfg["whatsapp"]))
    except TimezoneMissing as exc:
        print(exc)
        return 1
    try:
        return args.func(agent, args)
    except WhatsAppError as exc:
        print(f"שגיאה מול הבריג': {exc}")
        print(f"ודא שהבריג' רץ ומחובר, והרץ: python -m src.whatsapp_agent --config {args.config} probe")
        return 1
    except KeyboardInterrupt:
        print("\nהופסק.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
