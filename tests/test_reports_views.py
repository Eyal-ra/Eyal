"""בדיקות למסכי סקירת וסגירת הדוחות בדשבורד."""

import io
import json
import re

import pytest

from src.dashboard import create_app

NOTES_TABLE = (
    "חשיבות\tנושא\tהממצא / ההערה\tהשלכה כספית / מס\tהמלצה לפעולה\tהפניה\n"
    'גבוהה\tהכנסות מראש\tהביאור סותר את המאזן\tמס בעודף ~203K ש"ח\tלתקן את הביאור\tביאור 6\n'
    'בינונית\tפחת\tפער בין ביאור 5 לביאור 9\tפער 13,656 ש"ח\tלתאם\tביאור 5\n'
)


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "reports_closure.json"


@pytest.fixture
def app(state_path):
    app = create_app(
        {
            "dashboard": {
                "secret_key": "test-secret",
                "users": [
                    {"username": "eyal", "display_name": "אייל רייטר", "password": "1234"}
                ],
            },
            "reports_closure": {"path": str(state_path)},
        }
    )
    app.config.update(TESTING=True)
    return app


def csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


@pytest.fixture
def client(app):
    c = app.test_client()
    c.post(
        "/login",
        data={"username": "eyal", "password": "1234", "csrf_token": csrf(c)},
        follow_redirects=True,
    )
    return c


@pytest.fixture
def report_id(client, state_path):
    client.post(
        "/reports/new",
        data={
            "client_name": 'הקילומטר הנוסף בע"מ',
            "period": "2024",
            "client_id": "516823846",
            "report_type": "דוחות כספיים",
            "prepared_by": "לינוי",
            "csrf_token": csrf(client, "/reports/"),
        },
        follow_redirects=True,
    )
    return json.loads(state_path.read_text(encoding="utf-8"))["reports"][0]["id"]


def upload_draft(client, report_id, name="טיוטה 2024.pdf", data=b"%PDF-1.4"):
    return client.post(
        f"/reports/{report_id}/draft",
        data={
            "csrf_token": csrf(client, f"/reports/{report_id}"),
            "note": "טיוטה ראשונה",
            "draft": (io.BytesIO(data), name),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def notes_of(state_path, index=0):
    return json.loads(state_path.read_text(encoding="utf-8"))["reports"][index]["notes"]


# ----------------------------------------------------------------------
# הרשאות
# ----------------------------------------------------------------------


def test_anonymous_is_redirected_to_login(app):
    anon = app.test_client()
    for path in ("/reports/", "/reports/guidelines"):
        response = anon.get(path)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


def test_post_without_csrf_is_rejected(client, report_id):
    assert client.post(f"/reports/{report_id}/notes", data={"text": "הערה"}).status_code == 400


# ----------------------------------------------------------------------
# שלב 1: טיוטה
# ----------------------------------------------------------------------


def test_new_report_starts_awaiting_a_draft(client, report_id):
    html = client.get(f"/reports/{report_id}").get_data(as_text=True)
    assert "טרם נטענה טיוטה" in html
    assert "לינוי" in html  # מכין הטיוטה מוצג


def test_uploading_a_draft_advances_the_stage(client, report_id):
    html = upload_draft(client, report_id).get_data(as_text=True)
    assert "נטענה טיוטה (גרסה 1)" in html
    assert "ממתין להערות" in html
    assert "טיוטה 2024.pdf" in html


def test_draft_can_be_downloaded(client, report_id):
    upload_draft(client, report_id, data=b"%PDF-1.4 content")
    response = client.get(f"/reports/{report_id}/draft/1")
    assert response.status_code == 200
    assert response.data == b"%PDF-1.4 content"


def test_unknown_draft_version_is_404(client, report_id):
    upload_draft(client, report_id)
    assert client.get(f"/reports/{report_id}/draft/9").status_code == 404


def test_unsupported_file_type_is_refused(client, report_id):
    html = client.post(
        f"/reports/{report_id}/draft",
        data={
            "csrf_token": csrf(client, f"/reports/{report_id}"),
            "draft": (io.BytesIO(b"MZ"), "virus.exe"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "סוג קובץ לא נתמך" in html


def test_second_draft_becomes_a_new_version(client, report_id):
    upload_draft(client, report_id, name="v1.pdf")
    html = upload_draft(client, report_id, name="v2.pdf").get_data(as_text=True)
    assert "נטענה טיוטה (גרסה 2)" in html
    assert "v1.pdf" in html and "v2.pdf" in html


# ----------------------------------------------------------------------
# שלב 2: הערות
# ----------------------------------------------------------------------


def test_pasted_table_shows_all_its_columns(client, report_id):
    upload_draft(client, report_id)
    html = client.post(
        f"/reports/{report_id}/import",
        data={
            "raw_text": NOTES_TABLE,
            "source": "סקירת טיוטה 20/05",
            "csrf_token": csrf(client, f"/reports/{report_id}"),
        },
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "נקלטו 2 הערות" in html
    assert "הכנסות מראש" in html  # נושא
    assert "הביאור סותר את המאזן" in html  # ממצא
    assert "השלכה כספית / מס:" in html and "המלצה לפעולה:" in html
    assert "ביאור 6" in html  # הפניה
    assert "203,000 ₪" in html  # סכום שחולץ מההשלכה
    # החשובה קודם
    assert html.index("הכנסות מראש") < html.index("פער בין ביאור 5")


def test_single_note_form_accepts_every_field(client, state_path, report_id):
    upload_draft(client, report_id)
    client.post(
        f"/reports/{report_id}/notes",
        data={
            "topic": "מלאי",
            "text": "המלאי לא נספר",
            "severity": "high",
            "impact": 'חשיפה 50,000 ש"ח',
            "recommendation": "לבצע ספירה",
            "reference": "ביאור 4",
            "csrf_token": csrf(client, f"/reports/{report_id}"),
        },
        follow_redirects=True,
    )
    note = notes_of(state_path)[0]
    assert note["topic"] == "מלאי" and note["severity"] == "high"
    assert note["recommendation"] == "לבצע ספירה" and note["reference"] == "ביאור 4"


# ----------------------------------------------------------------------
# שלב 3: תשובה חובה, ואז סגירה
# ----------------------------------------------------------------------


def test_marking_done_without_an_answer_is_refused(client, state_path, report_id):
    upload_draft(client, report_id)
    client.post(
        f"/reports/{report_id}/notes",
        data={"text": "הערה", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]

    html = client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={"answer": "   ", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "חובה לרשום תשובה" in html
    assert "הערות הממתינות לתשובה (1)" in html  # נשארה פתוחה
    assert notes_of(state_path)[0]["status"] == "open"


def test_answering_moves_the_note_off_the_open_list(client, state_path, report_id):
    upload_draft(client, report_id)
    client.post(
        f"/reports/{report_id}/import",
        data={"raw_text": NOTES_TABLE, "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]

    html = client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={
            "answer": "תוקן בטיוטה השנייה",
            "csrf_token": csrf(client, f"/reports/{report_id}"),
        },
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "התשובה נרשמה" in html
    assert "הערות הממתינות לתשובה (1)" in html
    assert "נענו וירדו מהרשימה (1)" in html
    assert "תוקן בטיוטה השנייה" in html


def test_cancelling_requires_a_reason(client, state_path, report_id):
    upload_draft(client, report_id)
    client.post(
        f"/reports/{report_id}/notes",
        data={"text": "הערה", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]
    html = client.post(
        f"/reports/{report_id}/notes/{note_id}/cancel",
        data={"answer": "", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "לנמק" in html


def test_close_is_blocked_at_every_earlier_stage(client, state_path, report_id):
    def try_close():
        return client.post(
            f"/reports/{report_id}/close",
            data={"csrf_token": csrf(client, f"/reports/{report_id}")},
            follow_redirects=True,
        ).get_data(as_text=True)

    assert "טרם נטענה טיוטה" in try_close()

    upload_draft(client, report_id)
    assert "טרם נרשמו הערות" in try_close()

    client.post(
        f"/reports/{report_id}/import",
        data={"raw_text": NOTES_TABLE, "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    assert "2 הערות עדיין ממתינות לתשובה" in try_close()

    for note in notes_of(state_path):
        client.post(
            f"/reports/{report_id}/notes/{note['id']}/done",
            data={"answer": "תוקן", "csrf_token": csrf(client, f"/reports/{report_id}")},
            follow_redirects=True,
        )
    assert "הדוח נסגר סופית" in try_close()


def test_reopening_a_note_returns_it_and_reopens_the_report(client, state_path, report_id):
    upload_draft(client, report_id)
    client.post(
        f"/reports/{report_id}/notes",
        data={"text": "הערה", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]
    client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={"answer": "תוקן", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    client.post(
        f"/reports/{report_id}/close",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )

    html = client.post(
        f"/reports/{report_id}/notes/{note_id}/reopen",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "הוחזרה לרשימת הממתינות" in html
    assert "הערות הממתינות לתשובה (1)" in html
    assert "הדוח סגור" not in html


def test_unknown_note_action_is_404(client, state_path, report_id):
    upload_draft(client, report_id)
    client.post(
        f"/reports/{report_id}/notes",
        data={"text": "הערה", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]
    response = client.post(
        f"/reports/{report_id}/notes/{note_id}/delete",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
    )
    assert response.status_code == 404


def test_missing_report_shows_message_instead_of_crashing(client):
    html = client.get("/reports/לא-קיים", follow_redirects=True).get_data(as_text=True)
    assert "לא נמצא" in html


# ----------------------------------------------------------------------
# ייצוא, סינון והנחיות
# ----------------------------------------------------------------------


def test_export_lists_open_notes_with_an_answer_line(client, state_path, report_id):
    upload_draft(client, report_id)
    client.post(
        f"/reports/{report_id}/import",
        data={"raw_text": NOTES_TABLE, "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]
    client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={"answer": "תוקן", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )

    body = client.get(f"/reports/{report_id}/export.txt").get_data(as_text=True)
    assert "פער בין ביאור 5" in body  # שנותרה פתוחה
    assert "הביאור סותר את המאזן" not in body  # זו כבר נענתה
    assert "תשובה: ___" in body  # מקום לתשובה
    assert "המלצה:" in body


def test_status_filter(client, state_path, report_id):
    upload_draft(client, report_id)
    client.post(
        f"/reports/{report_id}/notes",
        data={"text": "הערה", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]
    client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={"answer": "תוקן", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    client.post(
        f"/reports/{report_id}/close",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    assert "הקילומטר" not in client.get("/reports/?status=open").get_data(as_text=True)
    assert "הקילומטר" in client.get("/reports/?status=closed").get_data(as_text=True)
    assert "הקילומטר" in client.get("/reports/?status=all").get_data(as_text=True)


def test_guidelines_are_saved_and_shown_on_report(client, report_id):
    html = client.post(
        "/reports/guidelines",
        data={
            "guidelines": "לבדוק התאמות בנק\n- לוודא תיעוד מעל 5,000 ₪",
            "csrf_token": csrf(client, "/reports/guidelines"),
        },
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "נשמרו 2 הנחיות" in html
    assert "לבדוק התאמות בנק" in client.get(f"/reports/{report_id}").get_data(as_text=True)


def test_guidelines_route_is_not_shadowed_by_report_id(client):
    assert "הנחיות סקירת דוחות" in client.get("/reports/guidelines").get_data(as_text=True)


def test_home_page_shows_closure_tiles(client, report_id):
    html = client.get("/").get_data(as_text=True)
    assert "סגירת דוחות כספיים" in html
