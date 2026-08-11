"""
Does the last message actually want an answer?

"The last message is theirs" is not the same as "they are waiting for me".
A conversation that ends with "צודק" or "מזל טוב!" is closed, not open, and a
report full of those is a report nobody reads.

Nothing is ever hidden on this basis - a chat that looks closed is still listed,
just under a separate heading. Missing a real question costs far more than one
extra line.
"""

import re

# A question mark, or an ask, means it is open regardless of how short it is.
ASKING = (
    "?", "מתי", "אפשר", "תוכל", "תוכלי", "האם", "כמה", "איפה", "למה", "איך",
    "צריך", "צריכה", "אשמח", "בבקשה", "תשלח", "תשלחי", "תעביר", "תעבירי",
    "תעדכן", "תעדכני", "נא ", "דחוף", "חוזר אליי", "מחכה", "ממתין", "תחזור אליי",
    "נדבר", "מה קורה", "מה נשמע", "תגיד לי", "תבדוק", "תבדקי",
)

# Short closings: the conversation ended, nobody is waiting.
CLOSING = (
    "תודה", "אחלה", "מעולה", "סבבה", "אוקיי", "אוקי", "ok", "אוקייי", "בסדר",
    "מצוין", "מצויין", "נהדר", "יופי", "מזל טוב", "משמח", "צודק", "צודקת",
    "בהחלט", "נכון", "בטח", "סגור", "מקובל", "הבנתי", "קיבלתי", "אין בעיה",
    "נתראה", "להתראות", "שבת שלום", "כל טוב", "בשמחה", "סבבה גמור", "מסכים",
    "ברור", "אמן", "יאללה", "טוב", "כן", "לא",
)

MAX_CLOSING_WORDS = 6


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def needs_reply(text: str) -> bool:
    """True when the message reads like something still waiting for an answer."""
    normalized = _normalize(text)
    if not normalized:
        return True                       # media or a voice note - look at it yourself

    if any(marker in normalized for marker in ASKING):
        return True

    words = normalized.split()
    if len(words) <= MAX_CLOSING_WORDS:
        stripped = re.sub(r"[^\w\s]", " ", normalized)
        if any(closing in stripped for closing in CLOSING):
            return False
        if not re.search(r"[א-תa-z0-9]", normalized):
            return False                  # emoji or punctuation only: a reaction

    return True                           # when unsure, show it
