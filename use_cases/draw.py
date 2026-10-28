from enum import StrEnum, auto

from uniplot import plot

from .snapshots import iter_snapshots


class DrawField(StrEnum):
    QUOTE = auto()
    NOMINAL = auto()
    COUPON = auto()


def draw_series(isin: str, field: DrawField) -> None:
    data = [
        (ts, getattr(snapshot.get(isin), field)) for ts, snapshot in iter_snapshots()
    ]

    dates, points = zip(*data)
    plot(xs=dates, ys=points, lines=True)
