"""בדיקות לשורת הפקודה של מערכת סגירת הדוחות."""

import pytest

from src.reports_closure.cli import main
from src.reports_closure.store import ClosureStore

NOTES = (
    "הערות סקירה\n"
    "==========\n"
    '1. [מאזן] יתרת לקוחות אינה מותאמת, הפרש 12,500 ₪\n'
    "! להשלים אישור יתרות מהבנק\n"
)


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "rc.json")


@pytest.fixture
def notes_file(tmp_path):
    file = tmp_path / "notes.txt"
    file.write_text(NOTES, encoding="utf-8")
    return str(file)


def run(*argv):
    return main(list(argv))


def test_import_with_create_opens_the_report(path, notes_file, capsys):
    assert run("--path", path, "--by", "אייל", "import", "--client", "אהבה",
               "--period", "2025", "--create", "--file", notes_file,
               "--source", "סשן סקירה") == 0
    out = capsys.readouterr().out
    assert "נקלטו 2 הערות" in out
    # הקריטית ראשונה, והסכום זוהה
    assert out.index("להשלים אישור יתרות") < out.index("יתרת לקוחות אינה מותאמת")
    assert "12,500 ₪" in out

    report = ClosureStore(path).list_reports()[0]
    assert report.client_name == "אהבה"
    assert report.open_count == 2
    assert {n.source for n in report.notes} == {"סשן סקירה"}


def test_import_reads_stdin(path, monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("- הערה מהצינור"))
    assert run("--path", path, "import", "--client", "אהבה", "--create", "--file", "-") == 0
    assert ClosureStore(path).list_reports()[0].open_notes[0].text == "הערה מהצינור"


def test_import_without_create_fails_on_unknown_client(path, notes_file, capsys):
    assert run("--path", path, "import", "--client", "אהבה", "--file", notes_file) == 1
    assert "לא נמצא דוח" in capsys.readouterr().err


def test_done_by_position_then_close(path, notes_file, capsys):
    run("--path", path, "import", "--client", "אהבה", "--create", "--file", notes_file)
    capsys.readouterr()

    assert run("--path", path, "--by", "אייל", "done", "--client", "אהבה",
               "--note", "1", "--comment", "התקבל אישור") == 0
    out = capsys.readouterr().out
    assert "נותרו 1 הערות פתוחות" in out

    assert run("--path", path, "close", "--client", "אהבה") == 1
    assert "נותרו 1 הערות פתוחות" in capsys.readouterr().err

    assert run("--path", path, "done", "--client", "אהבה", "--note", "1") == 0
    assert "מוכן לסגירה" in capsys.readouterr().out
    assert run("--path", path, "--by", "אייל", "close", "--client", "אהבה") == 0
    assert ClosureStore(path).list_reports()[0].is_closed


def test_done_by_note_id(path, notes_file):
    run("--path", path, "import", "--client", "אהבה", "--create", "--file", notes_file)
    note_id = ClosureStore(path).list_reports()[0].notes[0].id
    assert run("--path", path, "done", "--client", "אהבה", "--note", note_id) == 0
    assert ClosureStore(path).list_reports()[0].done_notes[0].id == note_id


def test_note_position_out_of_range(path, notes_file, capsys):
    run("--path", path, "import", "--client", "אהבה", "--create", "--file", notes_file)
    capsys.readouterr()
    assert run("--path", path, "done", "--client", "אהבה", "--note", "9") == 1
    assert "מחוץ לטווח" in capsys.readouterr().err


def test_ambiguous_client_lists_candidates_instead_of_guessing(path, capsys):
    store = ClosureStore(path)
    store.add_report("אהבה", period="2024")
    store.add_report("אהבה", period="2025")
    assert run("--path", path, "notes", "--client", "אהבה") == 1
    err = capsys.readouterr().err
    assert "נמצאו 2 דוחות תואמים" in err
    assert "2024" in err and "2025" in err


def test_period_disambiguates(path, capsys):
    store = ClosureStore(path)
    store.add_report("אהבה", period="2024")
    store.add_report("אהבה", period="2025")
    assert run("--path", path, "notes", "--client", "אהבה", "--period", "2025") == 0
    assert "2025" in capsys.readouterr().out


def test_target_requires_client_or_id(path, capsys):
    assert run("--path", path, "notes") == 1
    assert "--client" in capsys.readouterr().err


def test_missing_notes_file_reports_error(path, capsys):
    ClosureStore(path).add_report("אהבה")
    assert run("--path", path, "import", "--client", "אהבה", "--file", "אין-כזה.txt") == 1
    assert "שגיאת קובץ" in capsys.readouterr().err


def test_list_hides_closed_unless_asked(path, capsys):
    store = ClosureStore(path)
    report = store.add_report("אהבה", period="2025")
    store.close_report(report.id, by="אייל")
    run("--path", path, "list")
    assert "אין דוחות" in capsys.readouterr().out
    run("--path", path, "list", "--all")
    assert "אהבה" in capsys.readouterr().out


def test_guidelines_set_and_show(path, tmp_path, capsys):
    file = tmp_path / "g.txt"
    file.write_text("לבדוק התאמות בנק\n- לוודא תיעוד מעל 5,000 ₪\n", encoding="utf-8")
    assert run("--path", path, "guidelines", "--file", str(file)) == 0
    assert "נשמרו 2 הנחיות" in capsys.readouterr().out
    assert run("--path", path, "guidelines") == 0
    out = capsys.readouterr().out
    assert "1. לבדוק התאמות בנק" in out
    assert "2. לוודא תיעוד מעל 5,000 ₪" in out


def test_guidelines_empty_message(path, capsys):
    assert run("--path", path, "guidelines") == 0
    assert "טרם נרשמו הנחיות" in capsys.readouterr().out


def test_new_report(path, capsys):
    assert run("--path", path, "--by", "אייל", "new", "--client", "אהבה",
               "--period", "2025", "--client-id", "514000000") == 0
    assert "נפתח דוח" in capsys.readouterr().out
    report = ClosureStore(path).list_reports()[0]
    assert report.client_id == "514000000"
    assert report.created_by == "אייל"
