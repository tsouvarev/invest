from datetime import datetime

import pytz


def now():
    return datetime.now(tz=pytz.timezone("Europe/Moscow"))


def today():
    return now().date()
