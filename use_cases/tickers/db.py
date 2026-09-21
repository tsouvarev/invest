import json
import locale
import re
from asyncio import Semaphore
from collections.abc import AsyncIterator, Callable
from datetime import date
from enum import StrEnum, auto, nonmember
from functools import wraps
from typing import NamedTuple

from asyncstdlib import zip as azip
from funcy import compact, lfilter, project
from httpxyz import AsyncClient
from pydantic import TypeAdapter

from use_cases.utils import (
    Request,
    get_batch,
    get_text_from_node,
    indicate_work,
    not_in,
    remap_values,
    select_many_from_response,
    select_one_from_response,
    write_json,
)

from .base import Db, Prediction, PredictionsUpdateMode, Sector, Ticker
from .predictions import set_predictions


class ShowField(StrEnum):
    NAME = auto()
    ISIN = auto()
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


CONFIG = {
    "smartlab": {
        "url": "https://smart-lab.ru/q/bonds/{isin}/",
        "concurrency": 15,
        "selectors": {
            ShowField.GRADE: ".linear-progress-bar__text",
            ShowField.PROFITABILITY: (
                "article.quotes-info-list__item:nth-child(1) > div:nth-child(1) > "
                "div:nth-child(2) > div:nth-child(2)"
            ),
            ShowField.COUPON: (
                "article.quotes-info-list__item:nth-child(2) > div:nth-child(1) > "
                "div:nth-child(13) > div:nth-child(2)"
            ),
            ShowField.QUOTE: (
                "article.quotes-info-list__item:nth-child(1) > div:nth-child(1) > "
                "div:nth-child(1) > div:nth-child(2)"
            ),
            ShowField.NOMINAL: (
                "div.quotes-simple-table__row:nth-child(12) > div:nth-child(2)"
            ),
            ShowField.MATURITY_DATE: (
                "article.quotes-info-list__item:nth-child(1) > div:nth-child(1) > "
                "div:nth-child(8) > div:nth-child(2)"
            ),
            ShowField.SECTOR: (
                "article.quotes-info-list__item:nth-child(5) > div:nth-child(1) > "
                "div:nth-child(3) > div:nth-child(2)"
            ),
        },
    },
    "tinkoff": {
        "url": "https://www.tbank.ru/invest/bonds/{isin}/",
        "concurrency": 15,
        "selectors": {
            ShowField.ISIN: ".SecurityHeader__ticker_j7fZW",
            ShowField.NAME: ".SecurityHeader__showName_iw6qC",
        },
    },
}


SECTOR_MAPPING = {
    "Машиностроение": Sector.INDUSTRY,
    "МФО": Sector.SERVICES,
    "Другие услуг": Sector.SERVICES,
    "Электроэнергетика": Sector.INDUSTRY,
    "Нефтегазовая отрасль": Sector.RESOURCES,
    "Горнодобывающие": Sector.RESOURCES,
    "Ломбарды": Sector.SERVICES,
    "Недвижимость": Sector.SERVICES,
    "Хим.пром": Sector.INDUSTRY,
    "Пищевая пром.": Sector.FOOD,
    "Сельское хозяйство": Sector.FOOD,
    "Черная металлургия": Sector.INDUSTRY,
    "Оборонная промышленность": Sector.INDUSTRY,
    "Потреб.услуги": Sector.SERVICES,
    "Телекомы": Sector.SERVICES,
    "IT компании": Sector.OTHER,
    "Высокие технологии": Sector.OTHER,
    "Другая промышленность": Sector.INDUSTRY,
    "Финансы прочие": Sector.BANKING,
    "Цветная Металлургия": Sector.INDUSTRY,
    "Холдинг": Sector.OTHER,
    "Субфедеральные": Sector.GOV,
    "Медицина": Sector.FARMA,
}


class ParsedName(NamedTuple):
    company: str
    series: str


async def load_base_db(client: AsyncClient, *, isins: list[str] | None = None) -> Db:
    if isins is None:
        isins = []

    db = _read_db_from_file()

    if isins:
        await _set_base_info(client, db, isins)

    return project(compact(db), isins) if isins else db


async def load_from_db(
    client: AsyncClient,
    *,
    isins: list[str] | None = None,
    update_predictions: PredictionsUpdateMode = PredictionsUpdateMode.OUTDATED,
    skip_empty: bool = False,
) -> Db:
    if isins is None:
        isins = []

    db = _read_db_from_file()

    if isins:
        await _set_base_info(client, db, isins)

    await set_predictions(
        client, db, isins=isins, update_predictions=update_predictions
    )

    await set_infos(client, db, isins=isins)
    _write_db_to_file(db)

    if skip_empty:
        db = compact(db)

    return project(db, isins) if isins else db


async def _set_base_info(client, db, isins):
    config = CONFIG["tinkoff"]
    uncached_isins = lfilter(not_in(db), isins)

    caption = "Loading base info from tinkoff"
    sem = Semaphore(config["concurrency"])
    reqs = [
        Request(sem=sem, url=config["url"].format(isin=isin)) for isin in uncached_isins
    ]

    async for isin, response in azip(uncached_isins, get_batch(caption, client, reqs)):
        info = _parse_info_page(response)
        db[isin] = info


def _parse_info_page(response) -> Ticker:
    selectors = CONFIG["tinkoff"]["selectors"]

    if not response.is_success:
        return None

    nodes = select_many_from_response(response, [selectors["isin"], selectors["name"]])
    isin, name = map(get_text_from_node, nodes[0])
    return Ticker(isin=isin, **_parse_name(name)._asdict())


def _parse_name(name: str) -> ParsedName:
    naive_company, *naive_series = name.rsplit(" ", 2)

    match len(naive_series):
        case 0:
            m = re.match(r"([A-Za-zА-Яа-я]+)-?([0-9\w]+)", name)
            company, series = m.groups()
        case 1:
            company, series = naive_company, naive_series[0]
        case 2:
            if naive_series[-1].isalpha() or naive_series[0] in {"БО", "АО"}:
                company, series = naive_company, " ".join(naive_series)
            else:
                company, series = name.rsplit(" ", 1)
        case _:
            raise ValueError(name)

    return ParsedName(company, series)


def parse_date(*formats: str) -> Callable:
    @wraps(parse_date)
    def inner(v: str) -> date:
        for format_ in formats:
            try:
                return date.strptime(v, format_)
            except ValueError:
                pass

        raise ValueError(v)

    return inner


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


def map_sector(v: str) -> str:
    return SECTOR_MAPPING.get(v, v)


def str_percent_to_float(v: str) -> float:
    return float(v.strip(" %") or "0")


INPUT_VALUE_MAPPINGS = {
    ShowField.PROFITABILITY: str_percent_to_float,
    ShowField.COUPON: str_percent_to_float,
    ShowField.QUOTE: str_percent_to_float,
    ShowField.SECTOR: map_sector,
    ShowField.MATURITY_DATE: parse_date("%d-%m-%Y"),
}

OUTPUT_VALUE_MAPPINGS = {
    ShowField.PROFITABILITY: locale.localize,
    ShowField.COUPON: localize_percents,
    ShowField.QUOTE: localize_percents,
    ShowField.NOMINAL: localize_digits,
    ShowField.MATURITY_DATE: localize_date,
    ShowField.PREDICTION: Prediction.humanize,
    ShowField.PREDICTION_DATE: localize_date,
}


async def set_infos(
    client: AsyncClient, db: Db, *, isins: list[str]
) -> AsyncIterator[Ticker]:
    config = CONFIG["smartlab"]
    selectors = config["selectors"]

    sem = Semaphore(config["concurrency"])
    reqs = [Request(sem=sem, url=config["url"].format(isin=isin)) for isin in isins]

    caption = "Getting full info from smartlab"

    async for isin, response in azip(isins, get_batch(caption, client, reqs)):
        ticker = db[isin]
        if ticker is None:
            continue

        values = {
            str(sel): select_one_from_response(response, path)
            for sel, path in selectors.items()
        }
        values |= {
            "prediction": ticker.prediction,
            "prediction_date": ticker.prediction_date,
        }
        values = remap_values(values, INPUT_VALUE_MAPPINGS)
        values["coupon"] = values["coupon"] or values["profitability"]
        del values["profitability"]

        for k, v in values.items():
            setattr(ticker, k, v)


def _read_db_from_file() -> Db:
    with indicate_work("Loading DB"), open("db.json", encoding="utf-8") as f:
        return TypeAdapter(Db).validate_python(json.load(f))


def _write_db_to_file(data: Db) -> None:
    write_json("db.json", data)
