"""Unit tests for invoice_routing, using samples drawn from real mail."""

from src.invoice_routing import (
    SentMessage,
    extract_client_name,
    extract_company_ids,
    is_intake_address,
    learn_routes,
    normalize_client_name,
)

# --- real-world body samples (trimmed) ------------------------------------

# TML invoice issued for the client Sprawl, forwarded to Maven.
TML_SPRAWL_BODY = (
    'טמל מערכות מידע בע``מ 510986193 עוסק מורשה מספר 51260 בני ברק '
    'חשבונית מס/קבלה מספר הקצאה: לכבוד: ספרול מדיה בע``מ '
    'eyal@cpateam.co.il מסמך ממוחשב מקור'
)

# Rivhit fee invoice Eyal issued to Sprawl (greeting repeats the name).
RIVHIT_SPRAWL_BODY = (
    'שלום ספרול מדיה בע"מ ספרול מדיה בע"מ,\r\n\r\n'
    'מצורף לדואר אלקטרוני זה מסמך חשבונית מס מספר 23710\r\n'
)

RIVHIT_ZAKI_BODY = (
    'שלום זקי דיאב חברת עו"ד זקי דיאב חברת עו"ד,\r\n\r\n'
    'מצורף לדואר אלקטרוני זה מסמך חשבונית מס מספר 23809\r\n'
)


def test_is_intake_address():
    assert is_intake_address("517143814@expense.co.il")
    assert is_intake_address("maven6405816@invoice-maven.com")
    assert is_intake_address("517143814@biziboxcpa.com")
    assert is_intake_address("bk_x@mail.paperless.tax")
    assert not is_intake_address("eyal@cpateam.co.il")
    assert not is_intake_address("")


def test_normalize_unifies_quotes():
    assert normalize_client_name('ספרול מדיה בע``מ') == 'ספרול מדיה בע"מ'
    assert normalize_client_name('ספרול   מדיה בע"מ ') == 'ספרול מדיה בע"מ'


def test_extract_client_from_lekavod():
    # The TML body names the client after "לכבוד:" with trailers/email after it.
    assert extract_client_name(TML_SPRAWL_BODY) == 'ספרול מדיה בע"מ'


def test_extract_client_from_rivhit_greeting_dedupes():
    assert extract_client_name(RIVHIT_SPRAWL_BODY) == 'ספרול מדיה בע"מ'
    assert extract_client_name(RIVHIT_ZAKI_BODY) == 'זקי דיאב חברת עו"ד'


def test_extract_client_none_when_absent():
    assert extract_client_name("just some internal note") is None
    assert extract_client_name("") is None


def test_extract_company_ids():
    assert extract_company_ids(TML_SPRAWL_BODY) == ["510986193"]
    assert extract_company_ids("ח.פ: 517143814 sum 1234567890") == ["517143814"]


def test_learn_routes_basic():
    messages = [
        SentMessage("1", TML_SPRAWL_BODY, ["maven6405816@invoice-maven.com"]),
        SentMessage("חשבונית 23710", RIVHIT_SPRAWL_BODY, ["maven6405816@invoice-maven.com"]),
        SentMessage("חשבונית 23809", RIVHIT_ZAKI_BODY, ["517143814@expense.co.il"]),
        SentMessage("internal", "no client here", ["eyal@cpateam.co.il"]),
    ]
    result = learn_routes(messages)

    assert result.address_for('ספרול מדיה בע"מ') == "maven6405816@invoice-maven.com"
    assert result.address_for('זקי דיאב חברת עו"ד') == "517143814@expense.co.il"
    # The internal mail (no intake recipient) is ignored, not unresolved.
    assert messages[3] not in result.unresolved
    assert not result.conflicts


def test_learn_routes_detects_conflict():
    messages = [
        SentMessage("a", RIVHIT_ZAKI_BODY, ["517143814@expense.co.il"]),
        SentMessage("b", RIVHIT_ZAKI_BODY, ["517143814@biziboxcpa.com"]),
    ]
    result = learn_routes(messages)
    assert 'זקי דיאב חברת עו"ד' in result.conflicts


def test_learn_routes_unresolved_when_no_client():
    messages = [
        SentMessage("scan.pdf", "no recipient name in here", ["maven6405816@invoice-maven.com"]),
    ]
    result = learn_routes(messages)
    assert len(result.unresolved) == 1


def test_seed_overrides_learned_conflict():
    messages = [
        SentMessage("a", RIVHIT_ZAKI_BODY, ["517143814@expense.co.il"]),
        SentMessage("b", RIVHIT_ZAKI_BODY, ["517143814@biziboxcpa.com"]),
    ]
    seed = {'זקי דיאב חברת עו"ד': "517143814@expense.co.il"}
    result = learn_routes(messages, seed=seed)
    assert result.address_for('זקי דיאב חברת עו"ד') == "517143814@expense.co.il"
    assert 'זקי דיאב חברת עו"ד' not in result.conflicts
