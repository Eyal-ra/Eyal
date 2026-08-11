"""
Timezone lookup with a usable error message.

Windows ships no IANA timezone database, so `ZoneInfo("Asia/Jerusalem")` fails
there unless the `tzdata` package is installed. The raw exception says nothing
about that, so it is translated into an instruction.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TimezoneMissing(RuntimeError):
    """The configured timezone cannot be resolved on this machine."""


def get_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise TimezoneMissing(
            f"אזור הזמן {name!r} לא נמצא במחשב הזה.\n"
            "ב-Windows חסר מסד אזורי הזמן של Python. התקן אותו:\n"
            "    python -m pip install tzdata\n"
            "(ואם השם שגוי - תקן את scheduling.timezone ב-config.yaml)"
        ) from exc
