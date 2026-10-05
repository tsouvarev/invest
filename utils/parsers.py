import locale
from datetime import date


def parse_date(v: str, *formats: str) -> date:
    for format_ in formats:
        try:
            return date.strptime(v, format_)
        except ValueError:
            pass

    msg = f"{v=}"
    raise ValueError(msg)


def str_percent_to_float(v: str) -> float:
    return float(v.strip(" %") or "0")


def parse_human_date(v: str) -> date:
    locale.setlocale(category=locale.LC_ALL, locale="ru_RU")
    return date.strptime(v, "%d %B %Y")


def localize_date(v: date) -> str:
    return v and v.strftime("%d.%m.%Y")


def strip_ru(v: str) -> str:
    return v.removeprefix("ru")


def localize_digits(v: float) -> str:
    locale.setlocale(category=locale.LC_ALL, locale="nl_NL")
    return locale.localize(str(v))


def localize_percents(v: float) -> str:
    locale.setlocale(category=locale.LC_ALL, locale="nl_NL")
    return locale.localize(f"{v}%")
