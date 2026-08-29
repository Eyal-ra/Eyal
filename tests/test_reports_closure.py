"""בדיקות למנוע סגירת הדוחות: מודל, פרסור, ושמירה לדיסק."""

import json

import pytest

from src.reports_closure import ClosureError, ClosureStore, parse_notes_text
from src.reports_closure.models import (
    NOTE_DONE,
    NOTE_OPEN,
    REPORT_CLOSED,
    SEV_HIGH,
    SEV_LOW,
    SEV_MEDIUM,
    STAGE_AWAITING_ANSWERS,
    STAGE_AWAITING_NOTES,
    STAGE_CLOSED,
    STAGE_NO_DRAFT,
    STAGE_READY,
    find_amount_in_text,
    normalize_severity,
    parse_amount,
)

NOTES_TABLE = """\
| # | חשיבות | נושא | הממצא / ההערה | השלכה כספית / מס (משוערת) | המלצה לפעולה | הפניה |
| :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| 1 | גבוהה | הכנסות מראש — סתירה בהצגה | הביאור קובע שההכנסות כוללות 881,523 ש"ח הכנסות מראש. | מס בעודף ~203K ש"ח. | לתקן את הביאור. | ביאור 6 |
| 2 | בינונית | אי-התאמה בהוצאות הפחת | פחת בביאור 9 שונה מביאור 5. | פער 13,656 ש"ח. | לתאם בין הביאורים. | ביאור 5, 9 |
| 3 | נמוכה | שגיאת ניסוח | שם החברה כפול. | עריכה בלבד. | לתקן את הניסוח. | ביאור 1ג |
"""


@pytest.fixture
def store(tmp_path):
    return ClosureStore(tmp_path / "reports_closure.json")


@pytest.fixture
def report(store):
    return store.add_report(
        'חברת דוגמה בע"מ', period="2024", prepared_by="לינוי", created_by="אייל"
    )


@pytest.fixture
def with_draft(store, report):
    store.add_draft(report.id, "draft.pdf", b"%PDF-1.4", uploaded_by="לינוי")
    return report


# ----------------------------------------------------------------------
# סכומים וחשיבות
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [("1,234.56", 1234.56), ("₪1,000", 1000.0), ("(500)", -500.0), ("~203K", 203000.0),
     ("", None), ("לא מספר", None), (None, None)],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_amount_requires_currency_marker():
    """שנה, ח.פ. או מספר ביאור אינם סכום - רק מספר עם ₪ או ש\"ח."""
    assert find_amount_in_text("יתרת הפתיחה לשנת 2025") is None
    assert find_amount_in_text("ח.פ 516823846") is None
    assert find_amount_in_text("הפרש של 12,500 ₪") == 12500.0
    assert find_amount_in_text('מס בעודף ~203K ש"ח') == 203000.0


@pytest.mark.parametrize(
    "raw,expected",
    [("גבוהה", SEV_HIGH), ("בינונית", SEV_MEDIUM), ("נמוכה", SEV_LOW),
     ("בינונית-נמוכה", SEV_MEDIUM), ("קריטי", SEV_HIGH), ("normal", SEV_MEDIUM),
     ("", SEV_MEDIUM), (None, SEV_MEDIUM)],
)
def test_normalize_severity(raw, expected):
    assert normalize_severity(raw) == expected


# ----------------------------------------------------------------------
# פרסור טבלת ההערות
# ----------------------------------------------------------------------


def test_parse_notes_table_maps_every_column():
    notes = parse_notes_text(NOTES_TABLE)
    assert len(notes) == 3
    first = notes[0]
    assert first["topic"] == "הכנסות מראש — סתירה בהצגה"
    assert first["severity"] == SEV_HIGH
    assert "881,523" in first["text"]
    assert first["impact"] == 'מס בעודף ~203K ש"ח.'
    assert first["recommendation"] == "לתקן את הביאור."
    assert first["reference"] == "ביאור 6"
    # הסכום נלקח מעמודת ההשלכה הכספית
    assert first["amount"] == 203000.0
    assert [n["severity"] for n in notes] == [SEV_HIGH, SEV_MEDIUM, SEV_LOW]


def test_parse_notes_table_accepts_tab_separated():
    """הדבקה ישירה מגיליון מגיעה מופרדת טאבים, בלי קווי markdown."""
    tsv = (
        "חשיבות\tנושא\tהממצא / ההערה\tהמלצה לפעולה\n"
        "גבוהה\tמלאי\tהמלאי לא נספר\tלבצע ספירה\n"
    )
    notes = parse_notes_text(tsv)
    assert len(notes) == 1
    assert notes[0]["topic"] == "מלאי"
    assert notes[0]["recommendation"] == "לבצע ספירה"


def test_parse_notes_table_ignores_column_order():
    reordered = (
        "נושא\tהפניה\tחשיבות\tהממצא\n"
        "פחת\tביאור 5\tנמוכה\tפער בפחת\n"
    )
    note = parse_notes_text(reordered)[0]
    assert note["topic"] == "פחת" and note["reference"] == "ביאור 5"
    assert note["severity"] == SEV_LOW


def test_plain_list_still_parsed_when_not_a_table():
    notes = parse_notes_text(
        "הערות סקירה\n==========\n"
        "1. [מאזן] יתרת לקוחות לא מותאמת, הפרש 12,500 ₪\n"
        "! להשלים אישור יתרות מהבנק\n"
        'מע"מ: חסר דיווח (קריטי)\n'
    )
    assert [n["topic"] for n in notes] == ["מאזן", "", 'מע"מ']
    assert notes[0]["amount"] == 12500.0
    assert notes[1]["severity"] == SEV_HIGH and notes[2]["severity"] == SEV_HIGH


def test_indented_line_continues_previous_note():
    notes = parse_notes_text("- חסר תיעוד לחשבונית\n    הספק לא נמצא במערכת\n")
    assert len(notes) == 1
    assert notes[0]["text"] == "חסר תיעוד לחשבונית הספק לא נמצא במערכת"


def test_unknown_prefix_stays_in_the_text():
    note = parse_notes_text("הערה: לוודא שהמלאי נספר")[0]
    assert note["text"] == "הערה: לוודא שהמלאי נספר"


def test_blank_input_yields_nothing():
    assert parse_notes_text("   \n\n---\n") == []


# ----------------------------------------------------------------------
# שלבי התהליך
# ----------------------------------------------------------------------


def test_stage_progresses_through_the_three_steps(store, report):
    assert report.stage == STAGE_NO_DRAFT

    store.add_draft(report.id, "draft.pdf", b"%PDF", uploaded_by="לינוי")
    assert store.get_report(report.id).stage == STAGE_AWAITING_NOTES

    store.import_notes(report.id, NOTES_TABLE, created_by="אייל")
    assert store.get_report(report.id).stage == STAGE_AWAITING_ANSWERS

    for note in store.get_report(report.id).open_notes:
        store.mark_done(report.id, note.id, by="לינוי", answer="תוקן")
    assert store.get_report(report.id).stage == STAGE_READY

    store.close_report(report.id, by="אייל")
    assert store.get_report(report.id).stage == STAGE_CLOSED


def test_draft_versions_accumulate(store, report):
    first = store.add_draft(report.id, "v1.pdf", b"one", uploaded_by="לינוי")
    second = store.add_draft(report.id, "v2.pdf", b"two", uploaded_by="לינוי")
    assert (first.version, second.version) == (1, 2)
    fresh = store.get_report(report.id)
    assert len(fresh.drafts) == 2
    assert fresh.latest_draft.filename == "v2.pdf"
    # הקובץ נשמר בפועל וניתן לקריאה
    assert store.draft_path(report.id, first.stored_name).read_bytes() == b"one"


def test_empty_draft_rejected(store, report):
    with pytest.raises(ClosureError, match="ריק"):
        store.add_draft(report.id, "empty.pdf", b"")
    with pytest.raises(ClosureError, match="לא נבחר"):
        store.add_draft(report.id, "", b"data")


# ----------------------------------------------------------------------
# הכלל המרכזי: אין סגירה בלי תשובה
# ----------------------------------------------------------------------


def test_note_cannot_be_closed_without_an_answer(store, with_draft):
    note = store.add_note(with_draft.id, "יתרת לקוחות לא מותאמת", topic="מאזן")

    with pytest.raises(ClosureError, match="חובה לרשום תשובה"):
        store.mark_done(with_draft.id, note.id, by="לינוי")
    with pytest.raises(ClosureError, match="חובה לרשום תשובה"):
        store.mark_done(with_draft.id, note.id, by="לינוי", answer="   ")

    # ההערה נשארה פתוחה - הדחייה לא שינתה דבר
    assert store.get_report(with_draft.id).open_count == 1


def test_cancelling_a_note_also_requires_a_reason(store, with_draft):
    note = store.add_note(with_draft.id, "הערה")
    with pytest.raises(ClosureError, match="לנמק"):
        store.cancel_note(with_draft.id, note.id, by="אייל")
    store.cancel_note(with_draft.id, note.id, by="אייל", answer="לא רלוונטי השנה")
    assert store.get_report(with_draft.id).cancelled_notes[0].answer == "לא רלוונטי השנה"


def test_answer_is_stored_with_author_and_time(store, with_draft):
    note = store.add_note(with_draft.id, "יתרת לקוחות לא מותאמת")
    store.mark_done(with_draft.id, note.id, by="לינוי", answer="הותאם מול הבנק")

    fresh = store.get_report(with_draft.id)
    assert fresh.open_count == 0
    answered = fresh.done_notes[0]
    assert answered.status == NOTE_DONE
    assert answered.answer == "הותאם מול הבנק"
    assert answered.answered_by == "לינוי"
    assert answered.answered_at and answered.is_answered


def test_reopening_a_note_clears_its_answer_but_keeps_history(store, with_draft):
    note = store.add_note(with_draft.id, "הערה")
    store.mark_done(with_draft.id, note.id, by="לינוי", answer="תוקן")
    store.reopen_note(with_draft.id, note.id, by="אייל")

    reopened = store.get_report(with_draft.id).open_notes[0]
    assert reopened.status == NOTE_OPEN
    assert reopened.answer == "" and reopened.answered_at is None
    assert [h["to"] for h in reopened.history] == [NOTE_DONE, NOTE_OPEN]
    assert reopened.history[0]["answer"] == "תוקן"  # התשובה שניתנה נשמרה


def test_double_answering_is_rejected(store, with_draft):
    note = store.add_note(with_draft.id, "הערה")
    store.mark_done(with_draft.id, note.id, by="לינוי", answer="תוקן")
    with pytest.raises(ClosureError, match="בוצע"):
        store.mark_done(with_draft.id, note.id, by="לינוי", answer="שוב")


# ----------------------------------------------------------------------
# סגירת הדוח
# ----------------------------------------------------------------------


def test_report_cannot_close_before_a_draft_is_loaded(store, report):
    with pytest.raises(ClosureError, match="טרם נטענה טיוטה"):
        store.close_report(report.id, by="אייל")


def test_report_cannot_close_before_notes_are_recorded(store, with_draft):
    with pytest.raises(ClosureError, match="טרם נרשמו הערות"):
        store.close_report(with_draft.id, by="אייל")


def test_report_closes_only_after_every_note_is_answered(store, with_draft):
    added = store.import_notes(with_draft.id, NOTES_TABLE, created_by="אייל")

    with pytest.raises(ClosureError, match="3 הערות עדיין ממתינות"):
        store.close_report(with_draft.id, by="אייל")

    for note in added[:-1]:
        store.mark_done(with_draft.id, note.id, by="לינוי", answer="תוקן")
    with pytest.raises(ClosureError, match="1 הערות עדיין ממתינות"):
        store.close_report(with_draft.id, by="אייל")

    store.mark_done(with_draft.id, added[-1].id, by="לינוי", answer="תוקן")
    closed = store.close_report(with_draft.id, by="אייל")
    assert closed.status == REPORT_CLOSED and closed.progress_pct == 100


def test_reopening_a_note_reopens_the_closed_report(store, with_draft):
    note = store.add_note(with_draft.id, "הערה")
    store.mark_done(with_draft.id, note.id, by="לינוי", answer="תוקן")
    store.close_report(with_draft.id, by="אייל")

    store.reopen_note(with_draft.id, note.id, by="אייל")

    fresh = store.get_report(with_draft.id)
    assert not fresh.is_closed and fresh.closed_at is None
    assert fresh.open_count == 1


def test_adding_a_note_to_a_closed_report_reopens_it(store, with_draft):
    note = store.add_note(with_draft.id, "הערה")
    store.mark_done(with_draft.id, note.id, by="לינוי", answer="תוקן")
    store.close_report(with_draft.id, by="אייל")

    store.add_note(with_draft.id, "הערה שהתגלתה אחרי הסגירה")
    assert not store.get_report(with_draft.id).is_closed


def test_untouched_report_is_not_ready_to_close(store, with_draft):
    assert with_draft.is_untouched
    assert with_draft.progress_pct == 0
    assert not with_draft.can_close


def test_progress_counts_cancelled_as_handled(store, with_draft):
    first = store.add_note(with_draft.id, "א")
    store.add_note(with_draft.id, "ב")
    store.cancel_note(with_draft.id, first.id, by="אייל", answer="לא רלוונטי")
    fresh = store.get_report(with_draft.id)
    assert fresh.handled_count == 1 and fresh.progress_pct == 50


# ----------------------------------------------------------------------
# ייבוא, שאילתות והתמדה
# ----------------------------------------------------------------------


def test_import_records_source_on_every_note(store, with_draft):
    added = store.import_notes(
        with_draft.id, NOTES_TABLE, source="סקירת טיוטה 20/05", created_by="אייל"
    )
    assert len(added) == 3
    assert {n.source for n in store.get_report(with_draft.id).notes} == {"סקירת טיוטה 20/05"}


def test_import_empty_text_rejected(store, report):
    with pytest.raises(ClosureError, match="לא נמצאו הערות"):
        store.import_notes(report.id, "\n\n")


def test_open_notes_sorted_by_severity(store, with_draft):
    store.add_note(with_draft.id, "בינונית", severity="בינונית")
    store.add_note(with_draft.id, "גבוהה", severity="גבוהה")
    store.add_note(with_draft.id, "נמוכה", severity="נמוכה")
    order = [n.text for n in store.get_report(with_draft.id).sorted_open_notes()]
    assert order == ["גבוהה", "בינונית", "נמוכה"]


def test_missing_ids_raise(store, report):
    with pytest.raises(ClosureError):
        store.mark_done(report.id, "לא-קיים", by="אייל", answer="תשובה")
    with pytest.raises(ClosureError):
        store.add_note("לא-קיים", "הערה")


def test_empty_note_text_rejected(store, report):
    with pytest.raises(ClosureError):
        store.add_note(report.id, "   ")


def test_report_requires_client_name(store):
    with pytest.raises(ClosureError, match="שם לקוח"):
        store.add_report("  ")


def test_list_reports_filters(store):
    store.add_report("אלפא", period="2024")
    beta = store.add_report("בטא", period="2023", client_id="514000000")
    store.add_draft(beta.id, "d.pdf", b"x")
    store.add_note(beta.id, "הערה")
    for note in store.get_report(beta.id).open_notes:
        store.mark_done(beta.id, note.id, by="לינוי", answer="תוקן")
    store.close_report(beta.id, by="אייל")

    assert [r.client_name for r in store.list_reports(status="open")] == ["אלפא"]
    assert [r.client_name for r in store.list_reports(status="closed")] == ["בטא"]
    assert [r.client_name for r in store.list_reports(query="514")] == ["בטא"]


def test_state_survives_a_new_store_instance(tmp_path):
    path = tmp_path / "rc.json"
    first = ClosureStore(path)
    report = first.add_report("אלפא", period="2024")
    first.add_draft(report.id, "d.pdf", b"%PDF")
    note = first.add_note(report.id, "הערה", topic="מאזן", impact="פער 100 ₪")
    first.mark_done(report.id, note.id, by="לינוי", answer="טופל")

    fresh = ClosureStore(path).get_report(report.id)
    assert fresh.client_name == "אלפא"
    assert fresh.done_notes[0].answer == "טופל"
    assert fresh.done_notes[0].topic == "מאזן"
    assert fresh.drafts[0].filename == "d.pdf"


def test_legacy_file_is_still_readable(tmp_path):
    """קובץ מהגרסה הקודמת (category / done_comment / severity ישן) עדיין נטען."""
    path = tmp_path / "rc.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "reports": [
                    {
                        "id": "abc",
                        "client_name": "ישן",
                        "notes": [
                            {
                                "id": "n1",
                                "text": "הערה ישנה",
                                "category": "מאזן",
                                "severity": "critical",
                                "status": "done",
                                "done_comment": "טופל",
                                "done_by": "אייל",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    note = ClosureStore(path).get_report("abc").done_notes[0]
    assert note.topic == "מאזן"  # category הפך ל-topic
    assert note.severity == SEV_HIGH  # critical הפך לגבוהה
    assert note.answer == "טופל" and note.answered_by == "אייל"


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


def test_summary_counts_each_stage(store):
    no_draft = store.add_report("ללא טיוטה")
    awaiting_notes = store.add_report("ממתין להערות")
    store.add_draft(awaiting_notes.id, "d.pdf", b"x")
    ready = store.add_report("מוכן")
    store.add_draft(ready.id, "d.pdf", b"x")
    note = store.add_note(ready.id, "הערה")
    store.mark_done(ready.id, note.id, by="לינוי", answer="תוקן")

    summary = store.summary()
    assert summary["awaiting_draft"] == 1
    assert summary["awaiting_notes"] == 1
    assert summary["ready_to_close"] == 1
    assert summary["notes_open"] == 0
    assert store.get_report(no_draft.id).stage == STAGE_NO_DRAFT


def test_written_file_is_readable_json(store, with_draft):
    store.add_note(with_draft.id, "הערה")
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert data["reports"][0]["notes"][0]["text"] == "הערה"
    assert data["reports"][0]["drafts"][0]["filename"] == "draft.pdf"
