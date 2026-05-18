import re
from difflib import SequenceMatcher


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("972"):
        digits = "0" + digits[3:]
    return digits


def normalize_id(id_number: str) -> str:
    return re.sub(r"\D", "", id_number or "")


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def is_same_customer(submission, candidate, fuzzy_threshold: float = 0.85) -> bool:
    phone_match = (
        normalize_phone(submission.phone)
        and normalize_phone(submission.phone) == normalize_phone(getattr(candidate, "phone", ""))
    )
    id_match = (
        normalize_id(submission.id_number)
        and normalize_id(submission.id_number) == normalize_id(getattr(candidate, "id_number", ""))
    )
    if not (phone_match or id_match):
        return False
    return name_similarity(submission.full_name, candidate.full_name) >= fuzzy_threshold
