from dataclasses import dataclass
from typing import Optional


@dataclass
class FieldDiff:
    field: str
    jotform_value: str
    powerlink_value: Optional[str]
    ravgonit_value: Optional[str]

    def needs_update(self) -> bool:
        return self.jotform_value not in {self.powerlink_value, self.ravgonit_value} or (
            self.powerlink_value != self.ravgonit_value
        )


def render_diff(submission, powerlink_value: Optional[str], ravgonit_value: Optional[str]) -> str:
    lines = [
        f"לקוח: {submission.full_name}",
        f"  טלפון: {submission.phone}    ת.ז.: {submission.id_number}",
        f"  הוגש ב-Jotform: {submission.created_at}",
        "",
        "  שם מלא:",
        f"    Jotform   : {submission.full_name!r}",
        f"    Powerlink : {powerlink_value!r}",
        f"    רבגונית   : {ravgonit_value!r}",
    ]
    return "\n".join(lines)


def prompt_decision() -> str:
    while True:
        ans = input("  לעדכן את שתי המערכות לפי Jotform? [y]es / [n]o / [s]kip > ").strip().lower()
        if ans in {"y", "yes"}:
            return "yes"
        if ans in {"n", "no"}:
            return "no"
        if ans in {"s", "skip", ""}:
            return "skip"
        print("  תשובה לא חוקית. נסה שוב.")
