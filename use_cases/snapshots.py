from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from enum import IntEnum, auto
from itertools import pairwise
from pathlib import Path
from textwrap import shorten
from typing import Any, NamedTuple

from funcy import concat, group_by
from pydantic import BaseModel
from tabulate import tabulate
from whatever import that

from utils import now, read_json, write_json

from .base import Db

type Value = int | Decimal | str


class Severity(IntEnum):
    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()
    IGNORE = auto()

    @classmethod
    def for_field(cls, field):
        match field:
            case "grade" | "prediction" | "sector":
                return cls.HIGH
            case "coupon":
                return cls.MEDIUM
            case "quote" | "maturity_date" | "nominal":
                return cls.LOW
            case "prediction_date":
                return cls.IGNORE
            case _:
                raise ValueError(field)

    @classmethod
    def humanize(cls, v):
        match v:
            case cls.HIGH:
                return "Важное!"
            case cls.MEDIUM:
                return "Текучка"
            case cls.LOW:
                return "Фоновое"


class Change(BaseModel):
    severity: Severity
    reason: str | None = None
    isin: str
    field: str
    from_: Value
    from_ts: datetime
    to_: Value
    to_ts: datetime


class Record(NamedTuple):
    name: str
    field: str
    from_: Any
    to_: Any


def print_diff(db: Db, *snapshots: Db, rich: bool = False) -> None:
    print(stringify_diff(db, *snapshots, rich))


def stringify_diff(db: Db, *snapshots: Db, rich: bool = False) -> None:
    all_changes: list[Change] = diff_snapshots(*snapshots)

    if not all_changes:
        return "Nothing to report"

    res = ""
    table = []

    for severity, changes in group_by(that.severity, all_changes).items():
        if rich:
            table += _stringify_rich_diff(db, severity, changes)
        else:
            res += _stringify_plain_diff(db, severity, changes)

    if rich:
        res = tabulate(
            table,
            colalign=[None, None, "right", "left", "left"],
            tablefmt="unsafehtml",
        )
    return res


def _stringify_plain_diff(db: Db, severity: Severity, changes: list[Change]) -> str:
    res = f"\n{Severity.humanize(severity)}\n\n"

    table = []
    for field, field_changes in group_by(that.field, changes).items():
        for change in field_changes:
            ticker = db[change.isin]

            name = ticker.name
            if ticker.is_floater and field == "coupon":
                name += " (флоатер)"

            table.append((name, field, change.from_, change.to_, change.reason))

    return res + tabulate(table, tablefmt="simple") + "\n"


def _stringify_rich_diff(
    db: Db, severity: Severity, changes: list[Change]
) -> list[tuple]:
    header = f"<i><b>--- {Severity.humanize(severity)} ---</b></i>"
    table = [(header,)]

    for field, field_changes in group_by(that.field, changes).items():
        for change in field_changes:
            ticker = db[change.isin]

            company = shorten(ticker.company, width=15, break_long_words=False)
            name = f"{company} <sup>{ticker.series}</sup>"
            if ticker.is_floater and field == "coupon":
                name = f"(ф) {name}"

            table.append((name, field, change.from_, change.to_, change.reason))

    return table


def write_snapshot(data: Db) -> None:
    dt = now()
    day = dt.date().isoformat()
    ts = dt.time().isoformat()

    path = Path("snapshots") / day
    path.mkdir(exist_ok=True, parents=True)

    write_json(path / f"{ts}.json", data)


def load_snapshot(dt: datetime) -> dict[str, Db]:
    snapshot = {}

    path = Path("snapshots") / dt.date().isoformat()
    for filepath in path.iterdir():
        snapshot |= read_json(filepath, cast_to=Db)

    return snapshot


def get_last_snapshot() -> Db:
    path = Path("snapshots")

    for day_path in sorted(path.iterdir(), reverse=True):
        day = datetime.fromisoformat(day_path.name)
        if day.date() == now().date():
            continue

        return load_snapshot(day)
    return None


def diff_snapshots(*snapshots: Db) -> list[Change]:
    diff = []
    snapshots = [s for s in snapshots if s is not None]

    for isin in sorted(set(concat(*snapshots))):
        isin_snapshots = [s.get(isin) for s in snapshots if isin in s]
        if not isin_snapshots:
            continue

        diff.extend(_diff_for_isin(isin, *isin_snapshots))

    return sorted(diff, key=that.severity)


def _diff_for_isin(isin: str, *snapshots: Db) -> list[Change]:
    diff = []

    for field in type(snapshots[0]).model_fields:
        if field in {"isin", "ts", "company", "series", "inn", "type"}:
            continue

        diff.extend(_diff_for_field(isin, field, snapshots))

    return diff


def _diff_for_field(isin: str, field: str, snapshots: list[Db]) -> Iterator[Change]:
    for snap_former, snap_latter in pairwise(snapshots):
        former, latter = getattr(snap_former, field), getattr(snap_latter, field)
        if former == latter:
            continue

        if field == "quote":
            severity, reason = _get_severity_for_quote(former, latter)
        elif field == "coupon":
            severity, reason = _get_severity_for_coupon(
                former, latter, snap_former.is_floater
            )
        else:
            severity, reason = Severity.for_field(field), None

        if severity == Severity.IGNORE:
            continue

        yield Change(
            severity=severity,
            reason=reason,
            isin=isin,
            field=field,
            from_ts=snap_former.ts.date(),
            from_=getattr(snap_former, field),
            to_ts=snap_latter.ts.date(),
            to_=getattr(snap_latter, field),
        )


def _get_severity_for_quote(former, latter) -> tuple[Severity, str]:
    if former < 70 or latter < 70:
        return Severity.HIGH, "<70"

    if former < 80 or latter < 80:
        return Severity.MEDIUM, "<80"

    delta = latter - former
    match abs(delta):
        case v if v > 5:
            severity = Severity.HIGH
        case v if v > 2:
            severity = Severity.LOW
        case _:
            severity = Severity.IGNORE

    return severity, f"{delta:+}"


def _get_severity_for_coupon(former, latter, is_floater) -> tuple[Severity, str]:
    if not is_floater and (former < 15 or latter < 15):
        return Severity.HIGH, "<15"

    delta = latter - former
    match abs(delta):
        case v if v < 3:
            severity = Severity.IGNORE
        case v if not is_floater and v > 5:
            severity = Severity.HIGH
        case _:
            severity = Severity.LOW

    return severity, f"{delta:+}"
