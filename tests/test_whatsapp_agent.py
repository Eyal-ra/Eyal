from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.proposal_store import ProposalStore
from src.calendar_source import load_busy_intervals
from src.slots import Slot, build_slots, next_working_day
from src.templates import CONFIRMED, DECLINED, UNCLEAR, first_name, parse_answer, render_proposal
from src.reply_need import needs_reply
from src.unanswered import (
    ScanResult,
    strip_formatting_marks,
    count_trailing_inbound,
    evaluate_chat,
    last_inbound_without_reply,
    scan_pending,
)
from src.whatsapp_client import WhatsAppChat, WhatsAppError, parse_chat, parse_message, unwrap_list

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


def slots_at(*hours: int) -> list[Slot]:
    out = []
    for hour in hours:
        start = datetime(2026, 8, 11, hour, 0, tzinfo=TZ)
        out.append(Slot(start, start + timedelta(minutes=30)))
    return out


# --- normalization of bridge payloads -----------------------------------

def test_unwrap_list_handles_wrapped_payloads():
    assert unwrap_list([{"a": 1}]) == [{"a": 1}]
    assert unwrap_list({"response": [{"a": 1}]}) == [{"a": 1}]
    assert unwrap_list({"data": {"chats": [{"a": 1}]}}) == [{"a": 1}]
    assert unwrap_list({"error": "boom"}) == []


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


def test_parse_message_reads_nested_extended_text():
    parsed = parse_message({"id": "X", "message": {"extendedTextMessage": {"text": "היי"}}, "t": 1754827200})
    assert parsed.text == "היי"


def test_parse_message_tolerates_missing_fields():
    parsed = parse_message({})
    assert parsed.text == "" and parsed.sent_at is None and parsed.from_me is False


def test_parse_message_accepts_iso_timestamps():
    parsed = parse_message({"id": "1", "createdAt": "2026-08-10T09:00:00Z", "body": "היי"})
    assert parsed.sent_at == datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)


def test_parse_chat_detects_group_by_jid():
    assert parse_chat({"id": "123-456@g.us", "name": "קבוצה"}).is_group
    assert not parse_chat({"id": "972501234567@c.us", "name": "לקוח"}).is_group


def test_parse_chat_falls_back_to_phone_as_name():
    assert parse_chat({"id": {"_serialized": "972501234567@c.us"}}).name == "972501234567"


def test_chat_phone_strips_jid_suffix():
    assert chat().phone == "972501234567"


# --- who is still waiting for a reply -----------------------------------

def test_pending_when_last_message_is_theirs():
    messages = [msg(120, from_me=True), msg(90, from_me=False, text="אפשר לקבוע פגישה?")]
    assert last_inbound_without_reply(messages).text == "אפשר לקבוע פגישה?"


def test_not_pending_when_i_answered_after_them():
    assert last_inbound_without_reply([msg(90, from_me=False), msg(30, from_me=True)]) is None


def test_not_pending_when_only_my_messages():
    assert last_inbound_without_reply([msg(30, from_me=True)]) is None


def test_not_pending_for_empty_chat():
    assert last_inbound_without_reply([]) is None


def test_count_trailing_inbound_counts_the_streak():
    messages = [msg(200, from_me=True), msg(120, from_me=False), msg(90, from_me=False), msg(60, from_me=False)]
    assert count_trailing_inbound(messages) == 3
    assert count_trailing_inbound([msg(60, from_me=True)]) == 0


def test_evaluate_chat_respects_min_waiting_minutes():
    messages = [msg(10, from_me=False)]
    assert evaluate_chat(chat(), messages, NOW, min_waiting_minutes=30) is None
    assert evaluate_chat(chat(), messages, NOW, min_waiting_minutes=5) is not None


def test_evaluate_chat_ignores_old_messages():
    assert evaluate_chat(chat(), [msg(60 * 24 * 20, from_me=False)], NOW, max_age_days=14) is None


def test_pending_chat_waiting_label_and_preview():
    pending = evaluate_chat(chat(), [msg(180, from_me=False, text="  שלום   רב  ")], NOW)
    assert pending.waiting_label(NOW) == "3.0 שע'"
    assert pending.preview() == "שלום רב"
    assert pending.display_name == "ישראל ישראלי"


def test_pending_chat_preview_handles_media_only():
    assert evaluate_chat(chat(), [msg(180, from_me=False, text="")], NOW).preview().startswith("(ללא טקסט")


def test_waiting_label_switches_units():
    minutes = evaluate_chat(chat(), [msg(45, from_me=False)], NOW)
    days = evaluate_chat(chat(), [msg(60 * 24 * 3, from_me=False)], NOW)
    assert minutes.waiting_label(NOW) == "45 דק'"
    assert days.waiting_label(NOW) == "3.0 ימים"


# --- the scan loop ------------------------------------------------------

class FakeClient:
    """Stands in for WhatsAppClient: canned chats, canned messages, recorded sends."""

    def __init__(self, chats, messages, failing=()):
        self._chats = chats
        self._messages = messages
        self._failing = set(failing)
        self.sent = []

    def fetch_chats(self, limit=100):
        return self._chats[:limit]

    def fetch_messages(self, chat_id, limit=30):
        if chat_id in self._failing:
            raise WhatsAppError("timeout")
        return self._messages.get(chat_id, [])

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {"status": "ok"}


def test_scan_pending_filters_groups_and_answered_chats():
    chats = [
        WhatsAppChat("1@c.us", "ממתין", False, 2),
        WhatsAppChat("2@c.us", "כבר עניתי", False, 0),
        WhatsAppChat("3@g.us", "קבוצה", True, 5),
    ]
    messages = {
        "1@c.us": [msg(120, from_me=False)],
        "2@c.us": [msg(120, from_me=False), msg(60, from_me=True)],
        "3@g.us": [msg(120, from_me=False)],
    }
    result = scan_pending(FakeClient(chats, messages), {"scan": {}}, NOW)
    assert [p.display_name for p in result.pending] == ["ממתין"]
    assert result.scanned == 2


def test_scan_pending_reports_broken_chats_without_aborting():
    chats = [WhatsAppChat("1@c.us", "תקין", False, 0), WhatsAppChat("2@c.us", "שבור", False, 0)]
    client = FakeClient(chats, {"1@c.us": [msg(120, from_me=False)]}, failing={"2@c.us"})
    result = scan_pending(client, {"scan": {}}, NOW)
    assert [p.display_name for p in result.pending] == ["תקין"]
    assert result.errors == [("שבור", "timeout")]


def test_scan_pending_honors_skip_list_and_group_opt_in():
    chats = [WhatsAppChat("1@c.us", "מדולג", False, 0), WhatsAppChat("2@g.us", "קבוצה", True, 0)]
    messages = {"1@c.us": [msg(120, from_me=False)], "2@g.us": [msg(120, from_me=False)]}
    cfg = {"scan": {"skip_chat_ids": ["1@c.us"], "include_groups": True}}
    result = scan_pending(FakeClient(chats, messages), cfg, NOW)
    assert [p.display_name for p in result.pending] == ["קבוצה"]


def test_scan_pending_sorts_oldest_first():
    chats = [WhatsAppChat("1@c.us", "חדש", False, 0), WhatsAppChat("2@c.us", "ותיק", False, 0)]
    messages = {"1@c.us": [msg(30, from_me=False)], "2@c.us": [msg(600, from_me=False)]}
    result = scan_pending(FakeClient(chats, messages), {"scan": {}}, NOW)
    assert [p.display_name for p in result.pending] == ["ותיק", "חדש"]


# --- the two options ----------------------------------------------------

def test_next_working_day_skips_friday_and_saturday():
    assert next_working_day(date(2026, 8, 14), [4, 5]) == date(2026, 8, 16)  # Friday -> Sunday
    assert next_working_day(date(2026, 8, 11), [4, 5]) == date(2026, 8, 11)


def test_build_slots_returns_two_options_for_tomorrow():
    cfg = {"scheduling": {"option_times": ["10:00", "15:00"], "meeting_minutes": 30}}
    slots, target = build_slots(cfg, today=date(2026, 8, 10), now=datetime(2026, 8, 10, 9, 0, tzinfo=TZ))
    assert target == date(2026, 8, 11)
    assert [slot.time_range for slot in slots] == ["10:00–10:30", "15:00–15:30"]


def test_build_slots_skips_busy_times(tmp_path):
    busy = tmp_path / "busy.json"
    busy.write_text('[{"start": "2026-08-11T10:00", "end": "2026-08-11T11:00"}]', encoding="utf-8")
    cfg = {"scheduling": {
        "option_times": ["10:00", "15:00", "16:30"],
        "meeting_minutes": 30,
        "busy_file": str(busy),
    }}
    slots, _ = build_slots(cfg, today=date(2026, 8, 10), now=datetime(2026, 8, 10, 9, 0, tzinfo=TZ))
    assert [slot.time_range for slot in slots] == ["15:00–15:30", "16:30–17:00"]


def test_build_slots_rolls_to_next_day_when_tomorrow_is_full(tmp_path):
    busy = tmp_path / "busy.json"
    busy.write_text(
        '[{"start": "2026-08-11T09:00", "end": "2026-08-11T18:00"}]', encoding="utf-8"
    )
    cfg = {"scheduling": {"option_times": ["10:00", "15:00"], "meeting_minutes": 30, "busy_file": str(busy)}}
    slots, target = build_slots(cfg, today=date(2026, 8, 10), now=datetime(2026, 8, 10, 9, 0, tzinfo=TZ))
    assert target == date(2026, 8, 12)
    assert len(slots) == 2


def test_build_slots_rolls_over_the_weekend():
    cfg = {"scheduling": {"option_times": ["10:00", "15:00"]}}
    # 2026-08-13 is Thursday, so "tomorrow" is Friday and should land on Sunday.
    _, target = build_slots(cfg, today=date(2026, 8, 13), now=datetime(2026, 8, 13, 9, 0, tzinfo=TZ))
    assert target == date(2026, 8, 16)


def test_load_busy_intervals_tolerates_bad_file(tmp_path):
    bad = tmp_path / "busy.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_busy_intervals(str(bad), TZ) == []
    assert load_busy_intervals(None, TZ) == []
    assert load_busy_intervals(str(tmp_path / "missing.json"), TZ) == []


def test_slot_label_says_tomorrow():
    assert slots_at(10)[0].label(date(2026, 8, 10)) == "מחר (יום שלישי 11/08) בשעה 10:00–10:30"


def test_slot_label_names_the_day_when_not_tomorrow():
    assert slots_at(10)[0].label(date(2026, 8, 9)).startswith("יום שלישי")


# --- message text -------------------------------------------------------

def test_render_proposal_lists_both_options():
    text = render_proposal("ישראל ישראלי", slots_at(10, 15), date(2026, 8, 10), {"scheduling": {"signature": "אייל"}})
    assert text.startswith("היי ישראל,")
    assert "1. מחר" in text and "2. מחר" in text
    assert text.endswith("אייל")


def test_render_proposal_apologizes_only_when_late():
    cfg = {"scheduling": {"opening_line": "בוא נקבע.", "opening_line_late": "מצטער על העיכוב.",
                          "apology_after_hours": 12}}
    fresh = render_proposal("דנה", slots_at(10, 15), date(2026, 8, 10), cfg, waiting_hours=2)
    late = render_proposal("דנה", slots_at(10, 15), date(2026, 8, 10), cfg, waiting_hours=30)
    assert "בוא נקבע." in fresh and "מצטער" not in fresh
    assert "מצטער על העיכוב." in late


def test_first_name_handles_punctuation_and_empty():
    assert first_name("ישראל ישראלי") == "ישראל"
    assert first_name("🙂 דנה כהן") == "דנה"
    assert first_name("") == ""


# --- reading the answer -------------------------------------------------

@pytest.mark.parametrize("reply,expected", [
    ("1", 1),
    ("2", 2),
    ("2 בבקשה", 2),
    ("אפשרות 2", 2),
    ("ב", 2),
    ("א", 1),
    ("שנייה", 2),
])
def test_parse_answer_reads_explicit_choices(reply, expected):
    answer = parse_answer(reply, slots_at(10, 15))
    assert answer.kind == CONFIRMED and answer.option == expected


@pytest.mark.parametrize("reply,expected", [
    ("בעשר", 1),
    ("ב-15:00 מתאים", 2),
    ("בבוקר עדיף", 1),
    ("אחרי הצהריים", 2),
])
def test_parse_answer_reads_times_and_parts_of_day(reply, expected):
    answer = parse_answer(reply, slots_at(10, 15))
    assert answer.kind == CONFIRMED and answer.option == expected


@pytest.mark.parametrize("reply", ["שתיהן לא מתאימות", "לא מתאים לי מחר", "אף אחת מהאפשרויות"])
def test_parse_answer_detects_a_no(reply):
    assert parse_answer(reply, slots_at(10, 15)).kind == DECLINED


@pytest.mark.parametrize("reply", ["אחזור אליך", "", "תודה רבה על העדכון המפורט ששלחת לי אתמול בערב"])
def test_parse_answer_returns_unclear_when_it_cannot_tell(reply):
    assert parse_answer(reply, slots_at(10, 15)).kind == UNCLEAR


def test_parse_answer_is_unclear_when_a_time_matches_both_options():
    assert parse_answer("בעשר", slots_at(10, 10)).kind == UNCLEAR


def test_parse_answer_without_slots_still_reads_digits():
    assert parse_answer("2").option == 2


# --- proposal bookkeeping ----------------------------------------------

def test_store_skips_recent_and_booked_chats(tmp_path):
    store = ProposalStore(str(tmp_path / "proposals.json"))
    store.record("1@c.us", "דנה", ["2026-08-11T10:00:00+03:00", "2026-08-11T15:00:00+03:00"], NOW)

    assert store.should_skip("1@c.us", 48, NOW) == "כבר נשלחה הצעה לאחרונה"
    assert store.should_skip("1@c.us", 48, NOW + timedelta(hours=72)) is None

    store.record_answer("1@c.us", CONFIRMED, 2, "2", NOW)
    # Once a meeting is booked the chat is never offered new slots, however old.
    assert store.should_skip("1@c.us", 48, NOW + timedelta(days=30)) == "כבר נקבעה פגישה"


def test_store_skips_nothing_for_an_unknown_chat(tmp_path):
    store = ProposalStore(str(tmp_path / "proposals.json"))
    assert store.should_skip("nobody@c.us", 48, NOW) is None


def test_store_persists_between_runs(tmp_path):
    path = str(tmp_path / "proposals.json")
    ProposalStore(path).record("1@c.us", "דנה", ["2026-08-11T10:00:00+03:00"], NOW)
    assert ProposalStore(path).get("1@c.us")["display_name"] == "דנה"


def test_store_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "proposals.json"
    path.write_text("{ not json", encoding="utf-8")
    assert ProposalStore(str(path)).items() == []


def test_store_lists_awaiting_and_booked_for_a_day(tmp_path):
    store = ProposalStore(str(tmp_path / "proposals.json"))
    slots = ["2026-08-11T10:00:00+03:00", "2026-08-11T15:00:00+03:00"]
    store.record("1@c.us", "דנה", slots, NOW)
    store.record("2@c.us", "משה", slots, NOW)
    store.record_answer("1@c.us", CONFIRMED, 2, "2", NOW)

    assert [chat_id for chat_id, _ in store.awaiting_answer()] == ["2@c.us"]
    assert [chat_id for chat_id, _ in store.booked_for("2026-08-11")] == ["1@c.us"]
    assert store.booked_for("2026-08-12") == []


def test_declined_answer_is_not_a_booking(tmp_path):
    store = ProposalStore(str(tmp_path / "proposals.json"))
    store.record("1@c.us", "דנה", ["2026-08-11T10:00:00+03:00"], NOW)
    store.record_answer("1@c.us", DECLINED, None, "לא מתאים", NOW)
    assert not store.is_booked("1@c.us")
    assert store.booked_for("2026-08-11") == []


def test_scan_result_defaults_are_empty():
    result = ScanResult()
    assert result.pending == [] and result.errors == [] and result.scanned == 0


# --- text that WhatsApp wraps in invisible marks ------------------------

def test_bidi_marks_are_stripped_from_names_and_previews():
    # WhatsApp isolates Hebrew and numbers with U+2066..U+2069; the Windows
    # console cannot encode them and they add nothing to a report.
    marked = "\u2066רואת חשבון\u2069 מיטל אדלר"
    assert strip_formatting_marks(marked) == "רואת חשבון מיטל אדלר"
    assert strip_formatting_marks("") == ""


def test_pending_chat_is_built_without_invisible_marks():
    noisy = chat(name="\u2066מיטל אדלר\u2069")
    pending = evaluate_chat(noisy, [msg(180, from_me=False, text="\u2066משמח. מזל טוב!\u2069")], NOW)
    assert pending.display_name == "מיטל אדלר"
    assert pending.preview() == "משמח. מזל טוב!"
    assert all(ord(ch) < 0x2066 or ord(ch) > 0x2069 for ch in pending.display_name + pending.preview())


# --- does the last message actually want an answer ----------------------

def test_acknowledgements_do_not_count_as_waiting():
    for closing in ["צודק", "משמח. מזל טוב!!!", "תודה רבה", "אוקיי", "מעולה, נתראה", "👍"]:
        assert not needs_reply(closing), closing


def test_questions_and_requests_do_count():
    for asking in ["מתי אפשר להיפגש?", "תוכל לשלוח לי את הדוח", "אשמח לעדכון",
                   "מה קורה עם ההחזר", "צריך את החתימה שלך"]:
        assert needs_reply(asking), asking


def test_a_long_message_is_shown_even_without_a_question_mark():
    # When it is not clearly a closing, err towards showing it.
    assert needs_reply("שלחתי לך את כל המסמכים שביקשת אתמול בערב, כולל האישורים מהבנק")


def test_media_with_no_text_is_shown():
    assert needs_reply("")


def test_scan_result_splits_open_from_closed():
    chats = [WhatsAppChat("1@c.us", "שאלה", False, 0), WhatsAppChat("2@c.us", "סגירה", False, 0)]
    messages = {"1@c.us": [msg(120, from_me=False, text="מתי נוכל להיפגש?")],
                "2@c.us": [msg(120, from_me=False, text="צודק")]}
    result = scan_pending(FakeClient(chats, messages), {"scan": {}}, NOW)
    assert [c.display_name for c in result.open_chats] == ["שאלה"]
    assert [c.display_name for c in result.closed_chats] == ["סגירה"]
    assert len(result.pending) == 2      # nothing is dropped, only grouped
