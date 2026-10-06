from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from enum import IntEnum, auto
from itertools import pairwise
from pathlib import Path

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
    isin: str
    field: str
    from_: Value
    from_ts: datetime
    to_: Value
    to_ts: datetime


def print_diff(db: Db, *snapshots: Db) -> None:
    changes: list[Change] = diff_snapshots(*snapshots)

    if not changes:
        print("Nothing to report")
        return

    grouped_by_severity = group_by(that.severity, changes)

    print()
    for severity, changes in grouped_by_severity.items():
        print(Severity.humanize(severity), "\n")
        table = []
        for field, field_changes in group_by(that.field, changes).items():
            for change in field_changes:
                ticker = db[change.isin]

                name = ticker.name
                if ticker.is_floater and field == "coupon":
                    name = f"{name} (флоатер)"

                table.append(
                    {
                        "name": name,
                        "field": field,
                        "from": change.from_,
                        "to": change.to_,
                        "ts": change.to_ts.date(),
                    }
                )
        print(tabulate(table, headers="keys"), "\n")


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
            severity = _get_severity_for_quote(former, latter)
        elif field == "coupon":
            severity = _get_severity_for_coupon(former, latter)
        else:
            severity = Severity.for_field(field)

        if severity == Severity.IGNORE:
            continue

        yield Change(
            severity=severity,
            isin=isin,
            field=field,
            from_ts=snap_former.ts.date(),
            from_=former,
            to_ts=snap_latter.ts.date(),
            to_=latter,
        )


def _get_severity_for_quote(former, latter):
    if former < 70 or latter < 70:
        return Severity.HIGH

    if former < 80 or latter < 80:
        return Severity.MEDIUM

    delta = abs(former - latter)
    if delta > 5:
        return Severity.HIGH
    if delta > 2:
        return Severity.LOW

    return Severity.IGNORE


def _get_severity_for_coupon(former, latter):
    if former < 15 or latter < 15:
        return Severity.HIGH

    delta = abs(former - latter)
    if delta < 3:
        return Severity.IGNORE

    if delta > 5:
        return Severity.HIGH

    return Severity.LOW
