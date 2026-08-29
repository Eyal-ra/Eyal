"""בדיקות לסקריפטי ההפעלה - בדגש על הרצה בלי טרמינל אינטראקטיבי."""

import pytest

from scripts import start_dashboard


@pytest.fixture
def project(tmp_path, monkeypatch):
    """מדמה תיקיית פרויקט עם config.example.yaml בלבד."""
    example = tmp_path / "config.example.yaml"
    example.write_text(
        "dashboard:\n"
        '  secret_key: "CHANGE_ME_TO_A_LONG_RANDOM_STRING"\n'
        "  users:\n"
        '    - username: "eyal"\n'
        '      display_name: "אייל רייטר"\n'
        '      password_hash: "PASTE_HASH_HERE"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(start_dashboard, "EXAMPLE", example)
    monkeypatch.setattr(start_dashboard, "CONFIG", tmp_path / "config.yaml")
    return tmp_path


def test_config_is_created_without_asking_when_password_is_given(project, capsys):
    start_dashboard.create_config(username="linoy", password="s3cret")
    text = (project / "config.yaml").read_text(encoding="utf-8")

    assert 'username: "linoy"' in text
    assert start_dashboard.HASH_PLACEHOLDER not in text
    assert start_dashboard.SECRET_PLACEHOLDER not in text  # מפתח אקראי נוצר


def test_created_password_actually_verifies(project):
    from werkzeug.security import check_password_hash

    start_dashboard.create_config(username="eyal", password="s3cret")
    text = (project / "config.yaml").read_text(encoding="utf-8")
    stored = text.split('password_hash: "')[1].split('"')[0]
    assert check_password_hash(stored, "s3cret")
    assert not check_password_hash(stored, "wrong")


def test_without_a_terminal_and_without_a_password_it_fails_clearly(
    project, monkeypatch, capsys
):
    """הכשל החשוב: סוכן שמריץ בלי טרמינל יקבל שגיאה, לא יתקע על input()."""
    monkeypatch.setattr(start_dashboard, "interactive", lambda: False)

    with pytest.raises(SystemExit):
        start_dashboard.create_config()

    assert "--password" in capsys.readouterr().err
    assert not (project / "config.yaml").exists()


def test_reset_user_without_a_terminal_fails_clearly(project, monkeypatch, capsys):
    start_dashboard.create_config(username="eyal", password="first")
    monkeypatch.setattr(start_dashboard, "interactive", lambda: False)

    with pytest.raises(SystemExit):
        start_dashboard.reset_user()
    assert "--password" in capsys.readouterr().err


def test_reset_user_replaces_the_hash(project):
    from werkzeug.security import check_password_hash

    start_dashboard.create_config(username="eyal", password="first")
    start_dashboard.reset_user(password="second")

    text = (project / "config.yaml").read_text(encoding="utf-8")
    stored = text.split('password_hash: "')[1].split('"')[0]
    assert check_password_hash(stored, "second")
    assert not check_password_hash(stored, "first")


def test_placeholder_secret_is_replaced_on_an_existing_config(project):
    config = project / "config.yaml"
    config.write_text(
        f'dashboard:\n  secret_key: "{start_dashboard.SECRET_PLACEHOLDER}"\n'
        '  users:\n    - username: "eyal"\n      password_hash: "x"\n',
        encoding="utf-8",
    )
    start_dashboard.check_config_is_usable()
    assert start_dashboard.SECRET_PLACEHOLDER not in config.read_text(encoding="utf-8")


def test_missing_example_file_fails(project, monkeypatch, capsys):
    monkeypatch.setattr(start_dashboard, "EXAMPLE", project / "nope.yaml")
    with pytest.raises(SystemExit):
        start_dashboard.create_config(username="eyal", password="x")
    assert "חסר" in capsys.readouterr().err
