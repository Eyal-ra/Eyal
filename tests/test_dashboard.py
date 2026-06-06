"""בדיקות לדשבורד: כניסה, הצגת המשתמש המחובר, ויציאה (logout)."""

import re

import pytest
from werkzeug.security import generate_password_hash

from src.dashboard import create_app


@pytest.fixture
def app_config():
    return {
        "dashboard": {
            "secret_key": "test-secret",
            "users": [
                {
                    "username": "eyal",
                    "display_name": "אייל רייטר",
                    "password_hash": generate_password_hash("s3cret"),
                },
                {
                    "username": "office",
                    "display_name": "משרד",
                    "password": "1234",  # נתיב הסיסמה בטקסט גלוי
                },
            ],
        }
    }


@pytest.fixture
def client(app_config):
    app = create_app(app_config)
    app.config.update(TESTING=True)
    return app.test_client()


def get_csrf(client):
    html = client.get("/login").get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "טוקן CSRF לא נמצא בטופס הכניסה"
    return match.group(1)


def login(client, username, password):
    token = get_csrf(client)
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=True,
    )


def test_index_requires_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_with_hashed_password_shows_user(client):
    resp = login(client, "eyal", "s3cret")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # המשתמש המחובר מוצג בכל עמוד
    assert "אייל רייטר" in body
    assert "@eyal" in body
    # כפתור היציאה קיים
    assert "/logout" in body
    assert "יציאה" in body


def test_login_with_plaintext_password(client):
    resp = login(client, "office", "1234")
    assert resp.status_code == 200
    assert "משרד" in resp.get_data(as_text=True)


def test_login_wrong_password(client):
    resp = login(client, "eyal", "wrong")
    body = resp.get_data(as_text=True)
    assert "שם משתמש או סיסמה שגויים" in body
    assert "אייל רייטר" not in body


def test_logout_clears_session(client):
    login(client, "eyal", "s3cret")
    resp = client.get("/logout", follow_redirects=True)
    body = resp.get_data(as_text=True)
    # אחרי יציאה חוזרים למסך הכניסה ולא מוצג שם משתמש מחובר
    assert "כניסה לדשבורד" in body
    # ונחסמת הגישה לעמוד הראשי
    assert client.get("/").status_code == 302


def test_login_redirect_blocks_external_next(client):
    token = get_csrf(client)
    resp = client.post(
        "/login?next=https://evil.example.com",
        data={"username": "eyal", "password": "s3cret", "csrf_token": token},
    )
    assert resp.status_code == 302
    # ה-next החיצוני נדחה - מפנים לעמוד הראשי הפנימי
    assert "evil.example.com" not in resp.headers["Location"]


def test_login_rejects_missing_csrf(client):
    # POST ללא טוקן CSRF נדחה גם עם פרטים נכונים
    resp = client.post(
        "/login",
        data={"username": "eyal", "password": "s3cret"},
    )
    body = resp.get_data(as_text=True)
    assert "טוקן אבטחה לא תקין" in body
    # ולא בוצעה כניסה
    assert client.get("/").status_code == 302
