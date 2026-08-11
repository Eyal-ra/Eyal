"""
End-to-end tests against a real HTTP server that imitates a WhatsApp bridge.

These cover the wiring the unit tests cannot: the client's URL building, retry
behaviour, pacing, and the full CLI flow of pending -> schedule -> replies.
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote, urlparse

import pytest
import yaml

from src.whatsapp_agent import main
from src.whatsapp_client import WhatsAppClient, WhatsAppError

NOW = int(time.time())


class BridgeState:
    def __init__(self):
        self.chats = [
            {"id": "972501111111@c.us", "name": "דנה כהן", "unreadCount": 2},
            {"id": "972502222222@c.us", "name": "משה לוי", "unreadCount": 0},
            {"id": "123-456@g.us", "name": "קבוצת משרד", "unreadCount": 9},
        ]
        self.messages = {
            "972501111111@c.us": [
                {"id": "a1", "fromMe": True, "timestamp": NOW - 7200, "body": "בטח"},
                {"id": "a2", "fromMe": False, "timestamp": NOW - 5400, "body": "אפשר לקבוע פגישה?"},
            ],
            "972502222222@c.us": [
                {"id": "b1", "fromMe": False, "timestamp": NOW - 9000, "body": "היי"},
                {"id": "b2", "fromMe": True, "timestamp": NOW - 600, "body": "עונה לך"},
            ],
        }
        self.sent = []
        self.fail_times = 0   # how many requests should fail before succeeding
        self.calls = 0


def _make_handler(state: BridgeState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            state.calls += 1
            if state.fail_times > 0:
                state.fail_times -= 1
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            path = unquote(urlparse(self.path).path)
            if path == "/health":
                return self._send_json({"server": "fake-bridge", "version": "1.0"})
            if path == "/chats":
                return self._send_json({"response": state.chats})
            if path.startswith("/chats/") and path.endswith("/messages"):
                chat_id = path[len("/chats/"):-len("/messages")]
                return self._send_json(state.messages.get(chat_id, []))
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            state.sent.append(payload)
            chat_id = payload.get("chatId") or payload.get("phone", "")
            state.messages.setdefault(chat_id, []).append(
                {"id": f"out{len(state.sent)}", "fromMe": True, "timestamp": int(time.time()),
                 "body": payload.get("message") or payload.get("text", "")}
            )
            return self._send_json({"status": "ok"})

    return Handler


@pytest.fixture
def bridge():
    state = BridgeState()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.base_url = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    server.server_close()


@pytest.fixture
def config_file(bridge, tmp_path):
    cfg = {
        "whatsapp": {
            "base_url": bridge.base_url,
            "send_delay_seconds": 0,
            "retries": 1,
            "proposals_path": str(tmp_path / "proposals.json"),
            "log_path": str(tmp_path / "sent.log"),
        },
        "scan": {"min_waiting_minutes": 1},
        "scheduling": {"option_times": ["10:00", "15:00"], "signature": "אייל"},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def run(config_file, *argv) -> int:
    return main(["--config", str(config_file), *argv])


def reply(bridge, text, minutes_ago=0, chat_id="972501111111@c.us"):
    """Append an incoming message from the customer."""
    bridge.messages.setdefault(chat_id, []).append(
        {"id": f"in{len(bridge.messages[chat_id])}", "fromMe": False,
         "timestamp": int(time.time()) - minutes_ago * 60, "body": text}
    )


def advance_time(bridge, config_file, minutes):
    """Simulate `minutes` passing: everything already said or sent moves that far
    into the past, so a reply appended afterwards genuinely lands after it."""
    for messages in bridge.messages.values():
        for message in messages:
            message["timestamp"] -= minutes * 60

    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    path = cfg["whatsapp"]["proposals_path"]
    with open(path, encoding="utf-8") as handle:
        items = json.load(handle)
    for record in items.values():
        record["sent_at"] = (datetime.fromisoformat(record["sent_at"]) - timedelta(minutes=minutes)).isoformat()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False)


# --- client level -------------------------------------------------------

def test_client_reads_chats_and_messages(bridge):
    client = WhatsAppClient({"base_url": bridge.base_url})
    chats = client.fetch_chats()
    assert [chat.name for chat in chats] == ["דנה כהן", "משה לוי", "קבוצת משרד"]

    messages = client.fetch_messages("972501111111@c.us")
    assert [m.from_me for m in messages] == [True, False]     # sorted oldest first
    assert messages[-1].text == "אפשר לקבוע פגישה?"


def test_client_retries_transient_failures(bridge):
    bridge.fail_times = 2
    slept = []
    client = WhatsAppClient({"base_url": bridge.base_url, "retries": 3}, sleeper=slept.append)
    assert len(client.fetch_chats()) == 3
    assert slept == [1, 2]   # exponential backoff between attempts


def test_client_gives_up_after_the_retry_budget(bridge):
    bridge.fail_times = 99
    client = WhatsAppClient({"base_url": bridge.base_url, "retries": 1}, sleeper=lambda _: None)
    with pytest.raises(WhatsAppError):
        client.fetch_chats()


def test_client_raises_a_clear_error_on_a_bad_path(bridge):
    client = WhatsAppClient({"base_url": bridge.base_url, "endpoints": {"chats": "/nope"}})
    with pytest.raises(WhatsAppError) as excinfo:
        client.fetch_chats()
    assert "404" in str(excinfo.value)


def test_client_paces_outgoing_messages(bridge):
    slept = []
    client = WhatsAppClient({"base_url": bridge.base_url, "send_delay_seconds": 10}, sleeper=slept.append)
    client.send_message("972501111111@c.us", "אחת")
    client.send_message("972501111111@c.us", "שתיים")
    assert len(slept) == 1 and 6 <= slept[0] <= 13   # ~10s with jitter, only between sends


def test_probe_reports_the_working_paths(bridge):
    report = WhatsAppClient({"base_url": bridge.base_url}).probe()
    assert report["suggested"]["chats"] == "/chats"
    assert report["suggested"]["messages"] == "/chats/{chat_id}/messages"
    assert report["sample_chat_id"] == "972501111111@c.us"


def test_extra_send_fields_are_added_to_the_payload(bridge):
    client = WhatsAppClient({
        "base_url": bridge.base_url,
        "session": "office",
        "send_delay_seconds": 0,
        "send_text_field": "text",
        "send_extra": {"session": "{session}", "linkPreview": False},
    })
    client.send_message("972501111111@c.us", "היי")
    assert bridge.sent[-1] == {"chatId": "972501111111@c.us", "text": "היי",
                               "session": "office", "linkPreview": False}


def test_chat_id_can_be_sent_as_a_bare_phone_number(bridge):
    client = WhatsAppClient({
        "base_url": bridge.base_url, "send_delay_seconds": 0,
        "send_chat_field": "phone", "send_chat_format": "phone",
    })
    assert client.format_chat_id("972501111111@c.us") == "972501111111"
    assert client.format_chat_id("972501111111") == "972501111111"


def test_probe_reports_what_the_server_says_about_itself(bridge):
    report = WhatsAppClient({"base_url": bridge.base_url}).probe()
    bodies = " ".join(entry.get("body", "") for entry in report["discovery"])
    assert "fake-bridge" in bodies      # served from /health


def test_session_name_is_filled_into_the_paths(bridge):
    client = WhatsAppClient({
        "base_url": bridge.base_url,
        "session": "office",
        "endpoints": {"chats": "/api/{session}/all-chats",
                      "messages": "/api/{session}/chat-messages/{chat_id}"},
    })
    assert client._path(client.endpoints["chats"]) == "/api/office/all-chats"
    assert client._path(client.endpoints["messages"], chat_id="1@c.us") == "/api/office/chat-messages/1@c.us"


# --- CLI level ----------------------------------------------------------

def test_pending_json_lists_only_the_unanswered_private_chat(bridge, config_file, capsys):
    assert run(config_file, "pending", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert [entry["name"] for entry in payload] == ["דנה כהן"]
    assert payload[0]["phone"] == "972501111111"
    assert payload[0]["waiting_hours"] == pytest.approx(1.5, abs=0.1)


def test_pending_only_filter_narrows_the_list(bridge, config_file, capsys):
    assert run(config_file, "pending", "--only", "משה", "--json") == 0
    assert json.loads(capsys.readouterr().out) == []


def test_dry_run_schedule_sends_nothing(bridge, config_file, capsys):
    assert run(config_file, "schedule", "--yes", "--dry-run") == 0
    assert bridge.sent == []
    assert "dry-run" in capsys.readouterr().out


def test_full_flow_proposal_answer_and_confirmation(bridge, config_file, capsys):
    assert run(config_file, "schedule", "--yes") == 0
    assert len(bridge.sent) == 1
    proposal = bridge.sent[0]["message"]
    assert proposal.startswith("היי דנה,")
    assert "1. מחר" in proposal and "2. מחר" in proposal

    # Sending made the chat answered, so she drops off the pending list entirely.
    capsys.readouterr()
    assert run(config_file, "pending", "--json") == 0
    assert json.loads(capsys.readouterr().out) == []

    # She writes back, which makes the chat pending again - and that is exactly
    # when a second run must not fire off another pair of slots.
    advance_time(bridge, config_file, minutes=10)
    reply(bridge, "2 בבקשה", minutes_ago=5)
    assert run(config_file, "schedule", "--yes") == 0
    assert len(bridge.sent) == 1
    assert "כבר נשלחה הצעה" in capsys.readouterr().out

    # Reading the answer books the slot and sends the confirmation.
    assert run(config_file, "replies", "--confirm") == 0
    assert "בחר אפשרות 2" in capsys.readouterr().out
    assert "מעולה, קבענו" in bridge.sent[-1]["message"]

    # It shows up in tomorrow's agenda...
    assert run(config_file, "agenda") == 0
    assert "דנה כהן" in capsys.readouterr().out

    # ...and even if she keeps writing, a booked customer is never re-offered.
    advance_time(bridge, config_file, minutes=5)
    reply(bridge, "מעולה, נתראה", minutes_ago=2)
    assert run(config_file, "schedule", "--yes") == 0
    assert len(bridge.sent) == 2
    assert "כבר נקבעה פגישה" in capsys.readouterr().out


def test_declined_answer_asks_for_another_time(bridge, config_file, capsys):
    run(config_file, "schedule", "--yes")
    bridge.messages["972501111111@c.us"].append(
        {"id": "reply", "fromMe": False, "timestamp": int(time.time()) + 5, "body": "שתיהן לא מתאימות"}
    )
    assert run(config_file, "replies", "--confirm") == 0
    assert "השעות לא מתאימות" in capsys.readouterr().out
    assert "מתי נוח לך" in bridge.sent[-1]["message"]


def test_unclear_answer_is_left_for_manual_handling(bridge, config_file, capsys):
    run(config_file, "schedule", "--yes")
    before = len(bridge.sent)
    bridge.messages["972501111111@c.us"].append(
        {"id": "reply", "fromMe": False, "timestamp": int(time.time()) + 5,
         "body": "אני צריך לבדוק מול השותף שלי ואחזור אליך בהמשך השבוע"}
    )
    assert run(config_file, "replies", "--confirm") == 0
    assert "טפל ידנית" in capsys.readouterr().out
    assert len(bridge.sent) == before      # nothing auto-sent when the answer is unclear

    # The proposal stays open, so a clear answer that arrives later is still caught.
    reply(bridge, "בסוף כן, 1", minutes_ago=-1)   # a minute after the vague one
    assert run(config_file, "replies", "--confirm") == 0
    assert "בחר אפשרות 1" in capsys.readouterr().out
    assert "מעולה, קבענו" in bridge.sent[-1]["message"]


def test_sent_messages_are_written_to_the_audit_log(bridge, config_file, tmp_path):
    run(config_file, "schedule", "--yes")
    entries = [json.loads(line) for line in (tmp_path / "sent.log").read_text(encoding="utf-8").splitlines()]
    assert entries[0]["action"] == "proposal"
    assert entries[0]["name"] == "דנה כהן"
    assert len(entries[0]["slots"]) == 2


def test_answering_them_myself_removes_them_from_the_pending_list(bridge, config_file, capsys):
    bridge.messages["972501111111@c.us"].append(
        {"id": "mine", "fromMe": True, "timestamp": int(time.time()), "body": "עניתי מהנייד"}
    )
    assert run(config_file, "pending", "--json") == 0
    assert json.loads(capsys.readouterr().out) == []


def test_bridge_failure_is_reported_with_a_hint(bridge, config_file, capsys):
    bridge.fail_times = 99
    assert run(config_file, "pending") == 1
    assert "probe" in capsys.readouterr().out


def test_calendar_command_explains_that_no_calendar_is_configured(bridge, config_file, capsys):
    assert run(config_file, "calendar") == 0
    out = capsys.readouterr().out
    assert "מקור היומן: none" in out
    assert "google" in out          # tells you how to turn one on


def test_calendar_command_shows_busy_blocks_and_the_resulting_offer(bridge, config_file, tmp_path, capsys):
    tomorrow = (datetime.now(ZoneInfo("Asia/Jerusalem")) + timedelta(days=1)).date()
    busy_file = tmp_path / "busy.json"
    busy_file.write_text(
        json.dumps([{"start": f"{tomorrow}T10:00", "end": f"{tomorrow}T11:00"}]), encoding="utf-8"
    )
    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    cfg["scheduling"]["option_times"] = ["10:00", "15:00", "16:30"]
    cfg["scheduling"]["calendar"] = {"provider": "file", "busy_file": str(busy_file)}
    config_file.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    assert run(config_file, "calendar") == 0
    out = capsys.readouterr().out
    assert "מקור היומן: file" in out
    assert "10:00 - 11:00" in out
    assert "15:00–15:30 | 16:30–17:00" in out   # the busy hour is not offered


def test_agenda_is_empty_before_anything_is_booked(bridge, config_file, capsys):
    assert run(config_file, "agenda") == 0
    assert "אין פגישות" in capsys.readouterr().out


def test_slots_are_always_in_the_future(bridge, config_file, capsys):
    run(config_file, "schedule", "--yes")
    proposal = bridge.sent[0]["message"]
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%d/%m")
    assert tomorrow in proposal or "מחר" in proposal
