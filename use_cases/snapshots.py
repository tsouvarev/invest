import json
from collections.abc import Iterator
from datetime import date, datetime
from enum import IntEnum, auto
from itertools import pairwise
from pathlib import Path

from funcy import concat, group_by
from pydantic import BaseModel
from tabulate import tabulate
from whatever import that

from .tickers import Db, Grade, Prediction, Sector, Ticker
from .utils import now, write_json

type Value = int | float | str


class Snapshot(BaseModel):
    ts: datetime
    isin: str
    grade: Grade
    coupon: float
    quote: float
    nominal: float
    maturity_date: date
    sector: Sector
    prediction: Prediction
    prediction_date: date

    @classmethod
    def from_ticker(cls, tickers: list[Ticker]) -> dict[str, Snapshot]:
        return {
            ticker.isin: Snapshot(
                ts=now(),
                isin=ticker.isin,
                grade=ticker.grade,
                coupon=ticker.coupon,
                quote=ticker.quote,
                nominal=ticker.nominal,
                maturity_date=ticker.maturity_date,
                sector=ticker.sector,
                prediction=ticker.prediction,
                prediction_date=ticker.prediction_date,
            )
            for ticker in tickers
        }

    @classmethod
    def from_json(cls, data: dict[str, dict]) -> dict[str, Snapshot]:
        return {isin: Snapshot(**info) for isin, info in data.items()}


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


def print_diff(db: Db, *snapshots: Snapshot) -> None:
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
                table.append(
                    {
                        "name": ticker.name,
                        "field": field,
                        "from": change.from_,
                        "to": change.to_,
                        "ts": change.to_ts.date(),
                    }
                )
        print(tabulate(table, headers="keys"), "\n")


def write_snapshot(infos: list[Ticker]) -> None:
    snapshot = Snapshot.from_ticker(infos)

    dt = now()
    day = dt.date().isoformat()
    ts = dt.time().isoformat()

    path = Path("snapshots") / day
    path.mkdir(exist_ok=True, parents=True)

    write_json(path / f"{ts}.json", snapshot)


def load_snapshot(dt: datetime) -> dict[str, Snapshot]:
    snapshot = {}

    path = Path("snapshots") / dt.date().isoformat()
    for filepath in path.iterdir():
        with filepath.open() as f:
            snapshot |= Snapshot.from_json(json.load(f))

    return snapshot


def get_last_snapshot() -> Snapshot:
    path = Path("snapshots")

    for day_path in sorted(path.iterdir(), reverse=True):
        day = datetime.fromisoformat(day_path.name)
        if day.date() == now().date():
            continue

        return load_snapshot(day)
    return None


def diff_snapshots(*snapshots: Snapshot) -> list[Change]:
    diff = []
    snapshots = [s for s in snapshots if s is not None]

    for isin in sorted(set(concat(*snapshots))):
        isin_snapshots = [s.get(isin) for s in snapshots if isin in s]
        if not isin_snapshots:
            continue

        diff.extend(_diff_for_isin(isin, *isin_snapshots))

    return sorted(diff, key=that.severity)


def _diff_for_isin(isin: str, *snapshots: Snapshot) -> list[Change]:
    diff = []

    for field in type(snapshots[0]).model_fields:
        if field in {"isin", "ts"}:
            continue

        diff.extend(_diff_for_field(isin, field, snapshots))

    return diff


def _diff_for_field(
    isin: str, field: str, snapshots: list[Snapshot]
) -> Iterator[Change]:
    for snap_a, snap_b in pairwise(snapshots):
        a, b = getattr(snap_a, field), getattr(snap_b, field)
        if a == b:
            continue

        if field == "quote":
            severity = _get_severity_for_quote(a, b)
        elif field == "coupon":
            severity = _get_severity_for_coupon(a, b)
        else:
            severity = Severity.for_field(field)

        if severity == Severity.IGNORE:
            continue

        yield Change(
            severity=severity,
            isin=isin,
            field=field,
            from_ts=snap_a.ts.date(),
            from_=getattr(snap_a, field),
            to_ts=snap_b.ts.date(),
            to_=getattr(snap_b, field),
        )


def _get_severity_for_quote(a, b):
    if a < 80 or b < 80:
        return Severity.HIGH

    if a < 90 or b < 90:
        return Severity.MEDIUM

    delta = abs(a - b)
    if delta > 5:
        return Severity.HIGH
    if delta > 2:
        return Severity.LOW

    return Severity.IGNORE


def _get_severity_for_coupon(a, b):
    if a < 15 or b < 15:
        return Severity.HIGH

    delta = abs(a - b)
    if delta < 3:
        return Severity.IGNORE

    if delta > 5:
        return Severity.HIGH

    return Severity.LOW
