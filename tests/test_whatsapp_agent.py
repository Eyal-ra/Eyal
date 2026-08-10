from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.slots import Slot, build_slots, next_working_day
from src.templates import first_name, parse_choice, render_proposal
from src.unanswered import evaluate_chat, last_inbound_without_reply
from src.whatsapp_client import parse_chat, parse_message, unwrap_list

TZ = ZoneInfo("Asia/Jerusalem")
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def msg(minutes_ago: int, from_me: bool, text: str = "שלום"):
    return parse_message({
        "id": f"m{minutes_ago}",
        "fromMe": from_me,
        "timestamp": int((NOW - timedelta(minutes=minutes_ago)).timestamp()),
        "body": text,
    }, "972501234567@c.us")


def chat(name="ישראל ישראלי", chat_id="972501234567@c.us", unread=1, **extra):
    return parse_chat({"id": chat_id, "name": name, "unreadCount": unread, **extra})


# --- normalization of bridge payloads ---

def test_unwrap_list_handles_wrapped_payloads():
    assert unwrap_list([{"a": 1}]) == [{"a": 1}]
    assert unwrap_list({"response": [{"a": 1}]}) == [{"a": 1}]
    assert unwrap_list({"data": {"chats": [{"a": 1}]}}) == [{"a": 1}]


def test_parse_message_reads_baileys_shape():
    parsed = parse_message({
        "key": {"id": "ABC", "fromMe": True, "remoteJid": "972501234567@c.us"},
        "messageTimestamp": 1754827200000,
        "message": {"conversation": "בסדר גמור"},
    })
    assert parsed.message_id == "ABC"
    assert parsed.from_me is True
    assert parsed.text == "בסדר גמור"
    assert parsed.sent_at.year == 2025


def test_parse_chat_detects_group_by_jid():
    assert parse_chat({"id": "123-456@g.us", "name": "קבוצה"}).is_group


def test_chat_phone_strips_jid_suffix():
    assert chat().phone == "972501234567"


# --- who is still waiting for a reply ---

def test_pending_when_last_message_is_theirs():
    messages = [msg(120, from_me=True), msg(90, from_me=False, text="אפשר לקבוע פגישה?")]
    assert last_inbound_without_reply(messages).text == "אפשר לקבוע פגישה?"


def test_not_pending_when_i_answered_after_them():
    messages = [msg(90, from_me=False), msg(30, from_me=True)]
    assert last_inbound_without_reply(messages) is None


def test_not_pending_when_only_my_messages():
    assert last_inbound_without_reply([msg(30, from_me=True)]) is None


def test_evaluate_chat_respects_min_waiting_minutes():
    messages = [msg(10, from_me=False)]
    assert evaluate_chat(chat(), messages, NOW, min_waiting_minutes=30) is None
    assert evaluate_chat(chat(), messages, NOW, min_waiting_minutes=5) is not None


def test_evaluate_chat_ignores_old_messages():
    assert evaluate_chat(chat(), [msg(60 * 24 * 20, from_me=False)], NOW, max_age_days=14) is None


def test_pending_chat_waiting_label():
    pending = evaluate_chat(chat(), [msg(180, from_me=False)], NOW)
    assert pending.waiting_label(NOW) == "3.0 שע'"
    assert pending.display_name == "ישראל ישראלי"


# --- the two options for tomorrow ---

def test_next_working_day_skips_friday_and_saturday():
    # 2026-08-13 is a Thursday, so "tomorrow" (Friday) rolls to Sunday the 16th.
    assert next_working_day(date(2026, 8, 14), [4, 5]) == date(2026, 8, 16)
    assert next_working_day(date(2026, 8, 11), [4, 5]) == date(2026, 8, 11)


def test_build_slots_returns_two_options_for_tomorrow():
    cfg = {"scheduling": {"option_times": ["10:00", "15:00"], "meeting_minutes": 30}}
    slots, target = build_slots(cfg, today=date(2026, 8, 10), now=datetime(2026, 8, 10, 9, 0, tzinfo=TZ))
    assert target == date(2026, 8, 11)
    assert [slot.time_range for slot in slots] == ["10:00–10:30", "15:00–15:30"]


def test_build_slots_skips_busy_and_past_times(tmp_path):
    busy = tmp_path / "busy.json"
    busy.write_text('[{"start": "2026-08-11T10:00", "end": "2026-08-11T11:00"}]', encoding="utf-8")
    cfg = {"scheduling": {
        "option_times": ["10:00", "15:00", "16:30"],
        "meeting_minutes": 30,
        "busy_file": str(busy),
    }}
    slots, _ = build_slots(cfg, today=date(2026, 8, 10), now=datetime(2026, 8, 10, 9, 0, tzinfo=TZ))
    assert [slot.time_range for slot in slots] == ["15:00–15:30", "16:30–17:00"]


def test_slot_label_says_tomorrow():
    start = datetime(2026, 8, 11, 10, 0, tzinfo=TZ)
    label = Slot(start, start + timedelta(minutes=30)).label(date(2026, 8, 10))
    assert label == "מחר (יום שלישי 11/08) בשעה 10:00–10:30"


# --- message text and the customer's answer ---

def test_render_proposal_lists_both_options():
    start = datetime(2026, 8, 11, 10, 0, tzinfo=TZ)
    slots = [Slot(start, start + timedelta(minutes=30)),
             Slot(start.replace(hour=15), start.replace(hour=15) + timedelta(minutes=30))]
    text = render_proposal("ישראל ישראלי", slots, date(2026, 8, 10), {"scheduling": {"signature": "אייל"}})
    assert text.startswith("היי ישראל,")
    assert "1. מחר" in text and "2. מחר" in text
    assert text.endswith("אייל")


def test_first_name_handles_emoji_and_empty():
    assert first_name("ישראל ישראלי") == "ישראל"
    assert first_name("") == ""


def test_parse_choice_reads_common_answers():
    assert parse_choice("1") == 1
    assert parse_choice("2 בבקשה") == 2
    assert parse_choice("אפשרות 2") == 2
    assert parse_choice("ב") == 2


def test_parse_choice_returns_none_when_unclear():
    assert parse_choice("שתיהן לא מתאימות") is None
    assert parse_choice("אחזור אליך") is None
    assert parse_choice("") is None
