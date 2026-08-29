"""בדיקות למנוע סגירת הדוחות: מודל, פרסור הערות ושמירה לדיסק."""

import json

import pytest

from src.reports_closure import ClosureError, ClosureStore, parse_notes_text
from src.reports_closure.models import (
    NOTE_CANCELLED,
    NOTE_DONE,
    NOTE_OPEN,
    REPORT_CLOSED,
    SEV_CRITICAL,
    SEV_INFO,
    find_amount_in_text,
    parse_amount,
)


@pytest.fixture
def store(tmp_path):
    return ClosureStore(tmp_path / "reports_closure.json")


@pytest.fixture
def report(store):
    return store.add_report("חברת דוגמה בע\"מ", period="2025", created_by="אייל")


# ----------------------------------------------------------------------
# פרסור סכומים
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234.56", 1234.56),
        ("₪1,000", 1000.0),
        ("(500)", -500.0),
        ("  12500 ", 12500.0),
        ("", None),
        ("לא מספר", None),
        (None, None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_amount_requires_currency_marker():
    """שנה או מספר חשבונית אינם סכום - רק מספר עם ₪ או ש\"ח."""
    assert find_amount_in_text("לבדוק את יתרת הפתיחה לשנת 2025") is None
    assert find_amount_in_text("חשבונית 1099 לא דווחה") is None
    assert find_amount_in_text("הפרש של 12,500 ₪") == 12500.0
    assert find_amount_in_text('שולם 3,200 ש"ח מראש') == 3200.0


# ----------------------------------------------------------------------
# פרסור טקסט ההערות
# ----------------------------------------------------------------------


def test_parse_notes_basic_shapes():
    notes = parse_notes_text(
        'הערות סקירה\n'
        '==========\n'
        '1. [מאזן] יתרת לקוחות לא מותאמת, הפרש 12,500 ₪\n'
        '- מע"מ: חסר דיווח על חשבונית 1099 (קריטי)\n'
        '! להשלים אישור יתרות מהבנק\n'
        'תזרים: לבדוק סיווג הלוואת בעלים (לבירור)\n'
    )
    assert [n["category"] for n in notes] == ["מאזן", 'מע"מ', "כללי", "תזרים"]
    assert notes[0]["amount"] == 12500.0
    assert notes[1]["severity"] == SEV_CRITICAL
    assert notes[2]["severity"] == SEV_CRITICAL
    assert notes[3]["severity"] == SEV_INFO
    # הכותרת שמעל קו מפריד אינה הערה
    assert all("הערות סקירה" != n["text"] for n in notes)


def test_parse_notes_joins_indented_continuation():
    notes = parse_notes_text("- חסר תיעוד לחשבונית\n    הספק לא נמצא במערכת\n")
    assert len(notes) == 1
    assert notes[0]["text"] == "חסר תיעוד לחשבונית הספק לא נמצא במערכת"


def test_parse_notes_keeps_unknown_prefix_as_text():
    """רק סיווג מוכר נחתך; ``הערה:`` נשאר חלק מהטקסט."""
    notes = parse_notes_text("הערה: לוודא שהמלאי נספר")
    assert notes[0]["text"] == "הערה: לוודא שהמלאי נספר"
    assert notes[0]["category"] == "כללי"


def test_parse_notes_ignores_blank_input():
    assert parse_notes_text("   \n\n---\n") == []


# ----------------------------------------------------------------------
# מחזור החיים של הערה
# ----------------------------------------------------------------------


def test_marking_done_removes_note_from_open_list(store, report):
    note = store.add_note(report.id, "יתרת לקוחות לא מותאמת", category="מאזן")
    store.add_note(report.id, "חסר אישור יתרות")

    assert store.get_report(report.id).open_count == 2

    store.mark_done(report.id, note.id, by="אייל", comment="הותאם מול הבנק")

    fresh = store.get_report(report.id)
    assert fresh.open_count == 1
    assert [n.id for n in fresh.open_notes] != [note.id]
    # ההערה לא נמחקה - היא עברה לרשימת המבוצעות עם תיעוד מלא
    done = fresh.done_notes[0]
    assert done.id == note.id
    assert done.status == NOTE_DONE
    assert done.done_by == "אייל"
    assert done.done_comment == "הותאם מול הבנק"
    assert done.done_at


def test_cancel_and_reopen_note(store, report):
    note = store.add_note(report.id, "לבדוק סיווג")

    store.cancel_note(report.id, note.id, by="אייל", comment="לא רלוונטי")
    assert store.get_report(report.id).open_count == 0
    assert store.get_report(report.id).cancelled_notes[0].status == NOTE_CANCELLED

    store.reopen_note(report.id, note.id, by="אייל")
    reopened = store.get_report(report.id).open_notes[0]
    assert reopened.status == NOTE_OPEN
    assert reopened.done_at is None and reopened.done_by == ""
    # ההיסטוריה שומרת את שני המעברים
    assert [h["to"] for h in reopened.history] == [NOTE_CANCELLED, NOTE_OPEN]


def test_double_marking_is_rejected(store, report):
    note = store.add_note(report.id, "הערה")
    store.mark_done(report.id, note.id, by="אייל")
    with pytest.raises(ClosureError, match="בוצע"):
        store.mark_done(report.id, note.id, by="אייל")


def test_empty_note_text_rejected(store, report):
    with pytest.raises(ClosureError):
        store.add_note(report.id, "   ")


def test_note_actions_on_missing_ids(store, report):
    with pytest.raises(ClosureError):
        store.mark_done(report.id, "לא-קיים", by="אייל")
    with pytest.raises(ClosureError):
        store.add_note("לא-קיים", "הערה")


# ----------------------------------------------------------------------
# סגירת דוח
# ----------------------------------------------------------------------


def test_report_closes_only_when_no_open_notes(store, report):
    first = store.add_note(report.id, "הערה ראשונה")
    second = store.add_note(report.id, "הערה שנייה")

    with pytest.raises(ClosureError, match="נותרו 2 הערות"):
        store.close_report(report.id, by="אייל")

    store.mark_done(report.id, first.id, by="אייל")
    with pytest.raises(ClosureError, match="נותרו 1 הערות"):
        store.close_report(report.id, by="אייל")

    store.mark_done(report.id, second.id, by="אייל")
    closed = store.close_report(report.id, by="אייל")
    assert closed.status == REPORT_CLOSED
    assert closed.closed_by == "אייל"
    assert closed.progress_pct == 100


def test_reopening_a_note_reopens_the_report(store, report):
    note = store.add_note(report.id, "הערה")
    store.mark_done(report.id, note.id, by="אייל")
    store.close_report(report.id, by="אייל")

    store.reopen_note(report.id, note.id, by="אייל")

    fresh = store.get_report(report.id)
    assert not fresh.is_closed
    assert fresh.closed_at is None
    assert fresh.open_count == 1


def test_adding_note_to_closed_report_reopens_it(store, report):
    store.close_report(report.id, by="אייל")  # דוח בלי הערות נסגר מיד
    store.add_note(report.id, "הערה שהתגלתה אחרי הסגירה")
    assert not store.get_report(report.id).is_closed


def test_report_without_notes_can_close(store, report):
    assert report.can_close
    assert store.close_report(report.id, by="אייל").is_closed
    with pytest.raises(ClosureError, match="כבר סגור"):
        store.close_report(report.id, by="אייל")


def test_progress_counts_cancelled_as_handled(store, report):
    a = store.add_note(report.id, "א")
    store.add_note(report.id, "ב")
    store.cancel_note(report.id, a.id, by="אייל")
    fresh = store.get_report(report.id)
    assert fresh.handled_count == 1
    assert fresh.progress_pct == 50


# ----------------------------------------------------------------------
# ייבוא, שאילתות והתמדה
# ----------------------------------------------------------------------


def test_import_notes_records_source(store, report):
    added = store.import_notes(
        report.id,
        "- [מאזן] יתרה לא מותאמת 12,500 ₪\n! להשלים אישור",
        source="סקירת דוחות 29/08",
        created_by="אייל",
    )
    assert len(added) == 2
    fresh = store.get_report(report.id)
    assert {n.source for n in fresh.notes} == {"סקירת דוחות 29/08"}
    assert fresh.notes[0].amount == 12500.0


def test_import_empty_text_rejected(store, report):
    with pytest.raises(ClosureError, match="לא נמצאו הערות"):
        store.import_notes(report.id, "\n\n")


def test_open_notes_sorted_critical_first(store, report):
    store.add_note(report.id, "רגילה")
    store.add_note(report.id, "קריטית", severity=SEV_CRITICAL)
    store.add_note(report.id, "לבירור", severity=SEV_INFO)
    order = [n.text for n in store.get_report(report.id).sorted_open_notes()]
    assert order == ["קריטית", "רגילה", "לבירור"]


def test_list_reports_filters(store):
    store.add_report("אלפא", period="2025")
    beta = store.add_report("בטא", period="2024", client_id="514000000")
    store.close_report(beta.id, by="אייל")

    assert [r.client_name for r in store.list_reports(status="open")] == ["אלפא"]
    assert [r.client_name for r in store.list_reports(status="closed")] == ["בטא"]
    assert [r.client_name for r in store.list_reports(query="514")] == ["בטא"]
    assert len(store.list_reports()) == 2


def test_report_requires_client_name(store):
    with pytest.raises(ClosureError, match="שם לקוח"):
        store.add_report("  ")


def test_state_survives_a_new_store_instance(tmp_path):
    path = tmp_path / "rc.json"
    first = ClosureStore(path)
    report = first.add_report("אלפא", period="2025")
    note = first.add_note(report.id, "הערה")
    first.mark_done(report.id, note.id, by="אייל", comment="טופל")

    second = ClosureStore(path)
    fresh = second.get_report(report.id)
    assert fresh.client_name == "אלפא"
    assert fresh.done_notes[0].done_comment == "טופל"


def test_corrupt_file_raises_instead_of_wiping_data(tmp_path):
    path = tmp_path / "rc.json"
    path.write_text("{ לא JSON תקין", encoding="utf-8")
    with pytest.raises(ClosureError, match="פגום"):
        ClosureStore(path).list_reports()


def test_guidelines_round_trip(store):
    saved = store.set_guidelines("לבדוק התאמות בנק\n\n- לוודא תיעוד מעל 5,000 ₪\n")
    assert saved == ["לבדוק התאמות בנק", "לוודא תיעוד מעל 5,000 ₪"]
    assert store.get_guidelines() == saved


def test_guidelines_survive_report_writes(store):
    store.set_guidelines(["הנחיה"])
    report = store.add_report("אלפא")
    store.add_note(report.id, "הערה")
    assert store.get_guidelines() == ["הנחיה"]


def test_summary_counts(store):
    ready = store.add_report("אלפא")
    note = store.add_note(ready.id, "הערה")
    store.mark_done(ready.id, note.id, by="אייל")
    busy = store.add_report("בטא")
    store.add_note(busy.id, "הערה פתוחה")

    summary = store.summary()
    assert summary["reports_open"] == 2
    assert summary["notes_open"] == 1
    assert summary["notes_done"] == 1
    assert summary["ready_to_close"] == 1


def test_written_file_is_readable_json(store, report):
    store.add_note(report.id, "הערה")
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["reports"][0]["notes"][0]["text"] == "הערה"


# ----------------------------------------------------------------------
# דוח שנפתח וטרם נרשמו בו הערות
# ----------------------------------------------------------------------


def test_untouched_report_is_not_shown_as_complete(store, report):
    """דוח שנפתח וטרם נסקר אינו '100% מטופל' - אחרת הוא נראה כמו דוח שהסתיים."""
    assert report.is_untouched
    assert report.progress_pct == 0
    # עדיין ניתן לסגירה: דוח בלי ממצאים הוא מקרה לגיטימי
    assert report.can_close


def test_report_stops_being_untouched_once_a_note_is_added(store, report):
    note = store.add_note(report.id, "הערה")
    assert not store.get_report(report.id).is_untouched
    store.mark_done(report.id, note.id, by="אייל")
    handled = store.get_report(report.id)
    assert not handled.is_untouched
    assert handled.progress_pct == 100


def test_summary_separates_untouched_from_ready_to_close(store):
    untouched = store.add_report("טרם נסקר")
    reviewed = store.add_report("נסקר")
    note = store.add_note(reviewed.id, "הערה")
    store.mark_done(reviewed.id, note.id, by="אייל")

    summary = store.summary()
    assert summary["awaiting_notes"] == 1
    assert summary["ready_to_close"] == 1
    assert store.get_report(untouched.id).is_untouched
