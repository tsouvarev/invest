from datetime import timedelta
from numbers import Number

from humanize import naturaldelta


def format_with_sign(v: Number) -> str:
    return f"{v:+}"


def format_timedelta_with_sign(delta: timedelta) -> str:
    msg = naturaldelta(delta)
    sign = "-" if delta.days < 0 else "+"
    return f"{sign}{msg}"
