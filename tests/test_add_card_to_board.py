"""בדיקות להשתלת כרטיס "סקירת דוחות כספיים" בלוח הבקרה."""

import pytest

from scripts.add_card_to_board import MARKER, find_card_bounds, main

BOARD = """<!doctype html><html lang="he" dir="rtl"><body>
<section class="category">
  <div class="category-header">🏦 חשבונאות ובנקים <span class="pill">8 מערכות</span></div>
  <div class="cards-grid">
    <div class="system-card" data-system="sumit">
      <h3 class="card-title">מאזני בוחן (Sumit)</h3>
      <div class="card-actions"><a href="http://eyal:9001/">פתח</a></div>
    </div>
  </div>
</section>
<section class="category">
  <div class="category-header">📄 מסמכים ואוטומציה <span class="pill">9 מערכות</span></div>
  <div class="cards-grid">
    <div class="system-card" data-system="invoices">
      <h3 class="card-title">מעקב חשבוניות</h3>
      <div class="card-actions"><a href="http://eyal:9002/">פתח דוח</a></div>
    </div>
  </div>
</section>
</body></html>"""


@pytest.fixture
def board(tmp_path):
    path = tmp_path / "index.html"
    path.write_text(BOARD, encoding="utf-8")
    return path


def counter_after(text: str, marker: str) -> int:
    """מחזיר את מונה המערכות של הקטגוריה שמכילה את הטקסט."""
    import re

    section = text[: text.index(marker)]
    return int(re.findall(r"(\d+)\s*מערכות", section)[-1])


def test_card_is_inserted_as_a_sibling_of_the_anchor_card(board):
    assert main(["--board", str(board)]) == 0
    html = board.read_text(encoding="utf-8")

    assert html.count(MARKER) == 1
    # הכרטיס נכנס אחרי כרטיס העוגן, בתוך אותו cards-grid
    anchor_at = html.index("מעקב חשבוניות")
    card_at = html.index(MARKER)
    assert anchor_at < card_at
    assert html.index("</section>", card_at) > card_at
    # ולפני פתיחת הקטגוריה הבאה (אין כזו כאן - נבדק שלא יצא מה-body)
    assert card_at < html.index("</body>")


def test_counter_of_the_right_category_is_bumped(board):
    main(["--board", str(board)])
    html = board.read_text(encoding="utf-8")
    assert counter_after(html, MARKER) == 10  # 9 -> 10
    assert "8 מערכות" in html  # הקטגוריה השנייה לא נגעה


def test_rerun_replaces_and_does_not_double_count(board):
    main(["--board", str(board)])
    main(["--board", str(board)])
    html = board.read_text(encoding="utf-8")
    assert html.count(MARKER) == 1
    assert counter_after(html, MARKER) == 10  # לא 11


def test_backup_is_written_and_undo_restores(board):
    original = board.read_text(encoding="utf-8")
    main(["--board", str(board)])
    backup = board.with_suffix(board.suffix + ".bak")
    assert backup.exists() and backup.read_text(encoding="utf-8") == original

    main(["--board", str(board), "--undo"])
    assert board.read_text(encoding="utf-8") == original


def test_dry_run_changes_nothing(board):
    original = board.read_text(encoding="utf-8")
    assert main(["--board", str(board), "--dry-run"]) == 0
    assert board.read_text(encoding="utf-8") == original
    assert not board.with_suffix(board.suffix + ".bak").exists()


def test_custom_anchor_places_the_card_in_that_category(board):
    main(["--board", str(board), "--anchor", "מאזני בוחן"])
    html = board.read_text(encoding="utf-8")
    assert counter_after(html, MARKER) == 9  # 8 -> 9, הקטגוריה הראשונה
    assert "9 מערכות" in html


def test_custom_url_is_used(board):
    main(["--board", str(board), "--url", "http://office-pc:7000/reports/"])
    html = board.read_text(encoding="utf-8")
    assert "http://office-pc:7000/reports/" in html
    assert "http://office-pc:7000/reports/guidelines" in html


def test_missing_anchor_fails_without_touching_the_file(board):
    original = board.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--board", str(board), "--anchor", "אין כזה כרטיס"])
    assert board.read_text(encoding="utf-8") == original


def test_missing_board_file_fails(tmp_path):
    with pytest.raises(SystemExit):
        main(["--board", str(tmp_path / "nope.html")])


def test_undo_without_backup_fails(board):
    with pytest.raises(SystemExit):
        main(["--board", str(board), "--undo"])


def test_find_card_bounds_picks_the_card_not_the_grid(board):
    html = board.read_text(encoding="utf-8")
    start, end = find_card_bounds(html, "מעקב חשבוניות")
    block = html[start:end]
    assert 'data-system="invoices"' in block
    assert "cards-grid" not in block  # לא תפס את המיכל של כל הקטגוריה
    assert "מאזני בוחן" not in block  # ולא כרטיס אחר
