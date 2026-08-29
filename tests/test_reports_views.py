"""בדיקות למסכי מערכת סגירת הדוחות בדשבורד."""

import json
import re

import pytest

from src.dashboard import create_app


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
                    {
                        "username": "eyal",
                        "display_name": "אייל רייטר",
                        "password": "1234",
                    }
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
            "client_name": 'חברת דוגמה בע"מ',
            "period": "2025",
            "client_id": "514000000",
            "report_type": "דוח שנתי",
            "csrf_token": csrf(client, "/reports/"),
        },
        follow_redirects=True,
    )
    return json.loads(state_path.read_text(encoding="utf-8"))["reports"][0]["id"]


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
    response = client.post(f"/reports/{report_id}/notes", data={"text": "הערה"})
    assert response.status_code == 400


# ----------------------------------------------------------------------
# מסלול העבודה המלא
# ----------------------------------------------------------------------


def test_report_appears_in_list(client, report_id):
    html = client.get("/reports/").get_data(as_text=True)
    assert "חברת דוגמה" in html
    assert report_id in html


def test_import_then_mark_done_removes_note_from_open_list(client, state_path, report_id):
    response = client.post(
        f"/reports/{report_id}/import",
        data={
            "raw_text": (
                "- [מאזן] יתרת לקוחות לא מותאמת 12,500 ₪\n"
                "! להשלים אישור יתרות מהבנק"
            ),
            "source": "סקירה 29/08",
            "csrf_token": csrf(client, f"/reports/{report_id}"),
        },
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert "נקלטו 2 הערות" in html
    assert "12,500 ₪" in html  # הסכום נקלט והוצג
    # הקריטית מוצגת ראשונה
    assert html.index("להשלים אישור יתרות") < html.index("יתרת לקוחות לא מותאמת")

    note_id = notes_of(state_path)[0]["id"]
    response = client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={
            "comment": "הותאם מול הבנק",
            "csrf_token": csrf(client, f"/reports/{report_id}"),
        },
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert "ההערה סומנה כבוצעה וירדה מהרשימה" in html
    assert "הערות פתוחות (1)" in html
    assert "ירדו מהרשימה (1)" in html
    assert "הותאם מול הבנק" in html


def test_close_is_blocked_until_all_notes_handled(client, state_path, report_id):
    client.post(
        f"/reports/{report_id}/notes",
        data={
            "text": "חסר אישור יתרות",
            "category": "מאזן",
            "severity": "normal",
            "csrf_token": csrf(client, f"/reports/{report_id}"),
        },
        follow_redirects=True,
    )
    blocked = client.post(
        f"/reports/{report_id}/close",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "נותרו 1 הערות פתוחות" in blocked

    note_id = notes_of(state_path)[0]["id"]
    client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    closed = client.post(
        f"/reports/{report_id}/close",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "הדוח נסגר" in closed


def test_reopen_note_returns_it_to_the_open_list(client, state_path, report_id):
    client.post(
        f"/reports/{report_id}/notes",
        data={"text": "הערה", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]
    client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    html = client.post(
        f"/reports/{report_id}/notes/{note_id}/reopen",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "ההערה הוחזרה לרשימת הפתוחות" in html
    assert "הערות פתוחות (1)" in html


def test_unknown_note_action_is_404(client, state_path, report_id):
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


def test_export_lists_only_open_notes(client, state_path, report_id):
    client.post(
        f"/reports/{report_id}/import",
        data={
            "raw_text": "- הערה ראשונה\n- הערה שנייה",
            "csrf_token": csrf(client, f"/reports/{report_id}"),
        },
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]
    client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    body = client.get(f"/reports/{report_id}/export.txt").get_data(as_text=True)
    assert "הערה שנייה" in body
    assert "הערה ראשונה" not in body


def test_status_filter(client, state_path, report_id):
    client.post(
        f"/reports/{report_id}/close",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    assert "חברת דוגמה" not in client.get("/reports/?status=open").get_data(as_text=True)
    assert "חברת דוגמה" in client.get("/reports/?status=closed").get_data(as_text=True)
    assert "חברת דוגמה" in client.get("/reports/?status=all").get_data(as_text=True)


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
    assert "לבדוק התאמות בנק" in html
    assert "לבדוק התאמות בנק" in client.get(f"/reports/{report_id}").get_data(as_text=True)


def test_guidelines_route_is_not_shadowed_by_report_id(client):
    """``/reports/guidelines`` חייב להגיע לעמוד ההנחיות ולא להיקרא כמזהה דוח."""
    assert "הנחיות סקירת דוחות" in client.get("/reports/guidelines").get_data(as_text=True)


def test_home_page_shows_closure_tiles(client, report_id):
    client.post(
        f"/reports/{report_id}/notes",
        data={"text": "הערה", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    html = client.get("/").get_data(as_text=True)
    assert "סגירת דוחות כספיים" in html
    assert "הערות פתוחות" in html


def test_untouched_report_is_labelled_not_ready(client, report_id):
    """דוח חדש בלי הערות מסומן 'טרם נרשמו הערות', לא 'מוכן לסגירה'."""
    detail = client.get(f"/reports/{report_id}").get_data(as_text=True)
    assert "טרם נרשמו הערות" in detail
    assert "מוכן לסגירה" not in detail

    listing = client.get("/reports/").get_data(as_text=True)
    assert "טרם נרשמו הערות" in listing


def test_report_reads_ready_only_after_notes_are_handled(client, state_path, report_id):
    client.post(
        f"/reports/{report_id}/notes",
        data={"text": "הערה", "csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    )
    note_id = notes_of(state_path)[0]["id"]
    html = client.post(
        f"/reports/{report_id}/notes/{note_id}/done",
        data={"csrf_token": csrf(client, f"/reports/{report_id}")},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "מוכן לסגירה" in html
    assert "טרם נרשמו הערות" not in html
