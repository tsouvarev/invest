from enum import StrEnum, auto, nonmember

from funcy import compact, project
from httpxyz import AsyncClient

from clients import (
    InnsUpdateMode,
    PredictionsUpdateMode,
    TinkoffInfo,
    get_cbr_info,
    get_moex_info,
    get_smartlab_info,
    get_tinkoff_info,
)
from utils import (
    indicate_work,
    keys_dict,
    merge_as_dicts,
    merge_dicts,
    now,
    read_json,
    write_json,
)

from .base import Db, Ticker

DB_PATH = "db.json"


class ShowField(StrEnum):
    NAME = auto()
    ISIN = auto()
    TYPE = auto()
    GRADE = auto()
    PROFITABILITY = auto()
    COUPON = auto()
    QUOTE = auto()
    NOMINAL = auto()
    MATURITY_DATE = auto()
    SECTOR = auto()
    PREDICTION = auto()
    PREDICTION_DATE = auto()

    default = nonmember(
        [
            NAME,
            ISIN,
            TYPE,
            GRADE,
            COUPON,
            QUOTE,
            NOMINAL,
            MATURITY_DATE,
            SECTOR,
            PREDICTION,
            PREDICTION_DATE,
        ]
    )
    base = nonmember([NAME])


async def load_base_db(client: AsyncClient, *, isins: list[str] | None = None) -> Db:
    if isins is None:
        isins = []

    with indicate_work("Loading DB"):
        db = read_json(DB_PATH, cast_to=Db, initial={})

    if isins:
        infos = await get_tinkoff_info(client, db, isins)
        db = keys_dict(merge_as_dicts(db, infos), isins, cast_to=TinkoffInfo)

    return project(compact(db), isins) if isins else db


async def load_from_db(
    client: AsyncClient,
    *,
    isins: list[str] | None = None,
    update_predictions: PredictionsUpdateMode = PredictionsUpdateMode.OUTDATED,
    update_inns: InnsUpdateMode = InnsUpdateMode.MISSING,
    skip_empty: bool = False,
) -> Db:
    if isins is None:
        isins = []

    with indicate_work("Loading DB"):
        db = read_json(DB_PATH, cast_to=Db, initial={})

    tinkoff_info = await get_tinkoff_info(client, db, isins)
    moex_info = await get_moex_info(client, db, isins, update_inns=update_inns)
    cbr_info = await get_cbr_info(
        client, db, moex_info, isins, update_predictions=update_predictions
    )
    smartlab_info = await get_smartlab_info(client, db, isins)

    for isin in isins:
        infos = [
            tinkoff_info[isin],
            moex_info[isin],
            cbr_info[isin],
            smartlab_info[isin],
        ]
        if all(infos):
            db[isin] = Ticker(ts=now(), isin=isin, **merge_dicts(*infos))
        else:
            db[isin] = None

    _write_db_to_file(DB_PATH, db)

    if skip_empty:
        db = compact(db)

    return project(db, isins) if isins else db


def _write_db_to_file(path: str, data: Db) -> None:
    write_json(path, data)
