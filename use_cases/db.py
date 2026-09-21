import csv
import json
import re
from asyncio import Semaphore
from datetime import date, timedelta
from enum import StrEnum, auto
from functools import cached_property
from io import StringIO
from itertools import count
from typing import Annotated, NamedTuple

from asyncstdlib import zip as azip
from httpxyz import AsyncClient
from pydantic import BaseModel, Field, field_validator
from tqdm import tqdm
from whatever import that

from .utils import (
    Request,
    get_batch,
    get_text_from_node,
    has_prefixes,
    indicate_work,
    select_many_from_response,
    write_json,
)

type Db = dict[str, Ticker]

CONFIG = {
    "tinkoff": {
        "url": "https://www.tbank.ru/invest/bonds/{isin}/",
        "concurrency": 15,
        "selectors": {
            "isin": ".SecurityHeader__ticker_j7fZW",
            "name": ".SecurityHeader__showName_iw6qC",
        },
    },
    "cbr": {
        "url": "https://ratings.cbr.ru/bitrix/services/main/ajax.php",
        "concurrency": 15,
        "method": "POST",
    },
    "moex": {
        "url": (
            "https://web.moex.com/moex-web-icdb-api/api/v2/export/ru_securities-list"
        ),
        "concurrency": 15,
    },
}


class Grade(StrEnum):
    AAA = "AAA"
    AA_PLUS = "AA+"
    AA = "AA"
    AA_MINUS = "AA-"
    A_PLUS = "A+"
    A = "A"
    A_MINUS = "A-"
    BBB_PLUS = "BBB+"
    BBB = "BBB"
    BBB_MINUS = "BBB-"
    BB_PLUS = "BB+"
    BB = "BB"
    BB_MINUS = "BB-"
    B_PLUS = "B+"
    B = "B"
    B_MINUS = "B-"


class GradeQuality(StrEnum):
    HIGH = auto()
    MEDIUM_HIGH = auto()
    AVERAGE = auto()
    MEDIUM_LOW = auto()
    LOW = auto()

    @classmethod
    def humanize(cls, v):
        match v:
            case cls.HIGH:
                return "Высокий"
            case cls.MEDIUM_HIGH:
                return "Умеренно высокий"
            case cls.AVERAGE:
                return "Средний"
            case cls.MEDIUM_LOW:
                return "Умеренно низкий"
            case cls.LOW:
                return "Низкий"
            case _:
                raise ValueError(v)

    def from_grade(self, v: Grade) -> GradeQuality:
        match v:
            case self.AAA | self.AA_PLUS | self.AA:
                return GradeQuality.HIGH
            case self.AA_MINUS | self.A_PLUS | self.A:
                return GradeQuality.MEDIUM_HIGH
            case self.A_MINUS | self.BBB_PLUS | self.BBB | self.BBB_MINUS:
                return GradeQuality.AVERAGE
            case self.BB_PLUS | self.BB | self.BB_MINUS:
                return GradeQuality.MEDIUM_LOW
            case self.B_PLUS | self.B:
                return GradeQuality.LOW
            case _:
                raise ValueError(v)


class Prediction(StrEnum):
    STABLE = auto()
    UNKNOWN = auto()
    NEGATIVE = auto()
    POSITIVE = auto()
    WITHDRAWN = auto()

    @classmethod
    def humanize(cls, v):
        match v:
            case cls.STABLE:
                return "Стабильный"
            case cls.UNKNOWN:
                return "Неопределенный"
            case cls.NEGATIVE:
                return "Негативный"
            case cls.POSITIVE:
                return "Позитивный"
            case cls.WITHDRAWN | None:
                return "Отозван"
            case _:
                raise ValueError(v)


class Sector(StrEnum):
    BANKING = "Банки"
    GOV = "Гос"
    FOOD = "Еда"
    LEASING = "Лизинг"
    INDUSTRY = "Производство"
    OTHER = "Прочее"
    RESOURCES = "Ресурсы"
    DEVELOPMENT = "Строительство"
    TRADING = "Торговля"
    TRANSPORT = "Транспорт"
    SERVICES = "Услуги"
    FARMA = "Фармацевтика"


class Ticker(BaseModel):
    isin: str
    company: str
    series: str
    coupon: float | None = None
    is_used: bool = False
    inn: str | None = None
    prediction: Prediction | None = None
    prediction_date: date | None = None

    @field_validator("prediction_date", mode="before")
    @classmethod
    def parse_prediction_date(cls, v):
        if v is None:
            return v

        try:
            return date.strptime(v, "%d.%m.%Y")
        except ValueError:
            return date.strptime(v, "%Y-%m-%d")

    @property
    def full_name(self):
        return f"{self.company} {self.series}"

    @property
    def url(self):
        return CONFIG["tinkoff"]["url"].format(isin=self.isin)

    @cached_property
    def _company(self):
        return self.company.lower()

    @cached_property
    def _isin(self):
        return self.isin.lower()

    @property
    def has_outdated_prediction(self):
        cutoff = date.today() - timedelta(days=200)
        return self.prediction_date < cutoff


class ParsedName(NamedTuple):
    company: str
    series: str


class CbrData(BaseModel):
    item_list: Annotated[list[CbrItem], Field(alias="itemList")]
    page_count: Annotated[int, Field(alias="pageCount")]


class CbrItem(BaseModel):
    isin: str
    kra_name: Annotated[str, Field(alias="kraName")]
    object_id: Annotated[str, Field(alias="objectId")]
    object_type: Annotated[str, Field(alias="objectType")]
    object_name: Annotated[str, Field(alias="objectName")]
    prediction: str
    rating_action: Annotated[str, Field(alias="ratingAction")]
    release_date: Annotated[date | None, Field(alias="releaseDate")]

    @field_validator("release_date", mode="before")
    @classmethod
    def parse_release_date(cls, v):
        if v is None:
            return v

        return date.strptime(v, "%d.%m.%Y")


async def load_from_db(
    client: AsyncClient,
    *,
    isins: list[str],
    update_predictions: bool = False,
    skip_predictions: bool = True,
) -> Db:
    db = _load_db()

    await _set_base_info(client, db, isins)
    await _set_inns(client, db)

    if not skip_predictions:
        await _set_predictions(
            client, db, isins=isins, update_predictions=update_predictions
        )

    _write_db(db)

    return db


async def _set_base_info(client, db, isins):
    config = CONFIG["tinkoff"]
    uncached_isins = [isin for isin in isins if isin not in db]

    caption = "Loading base info from tinkoff"
    sem = Semaphore(config["concurrency"])
    reqs = [
        Request(sem=sem, url=config["url"].format(isin=isin)) for isin in uncached_isins
    ]

    async for isin, response in azip(uncached_isins, get_batch(caption, client, reqs)):
        info = _parse_info_page(response)
        db[isin] = info


async def _set_inns(client, db):
    config = CONFIG["moex"]
    sem = Semaphore(config["concurrency"])
    isins = [isin for isin, ticker in db.items() if ticker and not ticker.inn]

    reqs = [
        Request(
            sem=sem,
            url=config["url"],
            params={
                "Format.Type": "csv",
                "Format.Delimiter": "comma",
                "Data.Filter": f"query={isin}",
            },
        )
        for isin in isins
    ]
    caption = "Loading INNs from MOEX"

    async for isin, response in azip(isins, get_batch(caption, client, reqs)):
        with StringIO(response.text) as f:
            reader = csv.DictReader(f)
            db[isin].inn = next(reader)["INN"]


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


async def _set_predictions(
    client: AsyncClient,
    db: Db,
    *,
    isins: list[str],
    update_predictions: bool,
) -> dict:
    config = CONFIG["cbr"]

    if update_predictions:
        new_and_outdated_isins = isins
    else:
        new_and_outdated_isins = [
            isin
            for isin in isins
            if db[isin]
            and (not db[isin].prediction or db[isin].has_outdated_prediction)
        ]

    csrf = await _get_cbr_csrf(client)

    caption = "Loading ratings from CBR"
    for isin in tqdm(new_and_outdated_isins, caption):
        predictions = []
        ticker = db[isin]

        if not ticker:
            continue

        for page in count(1):
            data = {"fields[pageNumber]": page, "fields[inn]": ticker.inn}

            if page > 1:
                del data["fields[inn]"]
                action = "searchRatingNavigation"
            else:
                action = "searchRating"

            response = await client.request(
                method=config["method"],
                url=config["url"],
                headers={"X-Bitrix-Csrf-Token": csrf},
                params={"mode": "ajax", "c": "prr.form", "action": action},
                data=data,
            )

            if not response.json()["data"]:
                break

            cbr_data = CbrData(**response.json()["data"])
            predictions.extend(cbr_data.item_list)

            if cbr_data.page_count == page:
                break

        ticker = db[isin]
        predictions = sorted(
            predictions,
            key=that.release_date,
            reverse=True,
        )

        company_predictions = [
            p for p in predictions if not has_prefixes(p.object_type, ("TBND", "TMNB"))
        ]
        isin_predictions = [p for p in predictions if p.isin == isin]

        data = _get_last_prediction(company_predictions or isin_predictions)
        ticker.prediction = data[0]
        ticker.prediction_date = data[1]

    return db


def _get_last_prediction(predictions: list[CbrItem]) -> tuple[Prediction, date]:
    withdrawn_kra = []
    withdrawn_date = None

    if not predictions:
        return (Prediction.STABLE, date.today())

    for data in predictions:
        kra = data.kra_name
        if kra in withdrawn_kra:
            continue

        if data.rating_action.startswith("WD"):
            withdrawn_kra.append(kra)
            withdrawn_date = data.release_date
        else:
            return (_parse_prediction(data.prediction), data.release_date)

    return (Prediction.WITHDRAWN, withdrawn_date or date.today())


def _parse_prediction(s: str) -> Prediction:
    if has_prefixes(s, ("STA", "NA")):
        return Prediction.STABLE
    if has_prefixes(s, ("UN", "DEV", "UNW")):
        return Prediction.UNKNOWN
    if has_prefixes(s, ("NEG", "OP")):
        return Prediction.NEGATIVE
    if has_prefixes(s, ("POS",)):
        return Prediction.POSITIVE
    raise ValueError(s)


def _load_db() -> dict:
    with indicate_work("Loading DB"), open("db.json", encoding="utf-8") as f:
        return {k: v and Ticker(**v) for k, v in json.load(f).items()}


def _write_db(data: dict):
    write_json("db.json", data)


async def _get_cbr_csrf(client):
    with indicate_work("Getting CSRF token for CBR"):
        response = await client.post(
            CONFIG["cbr"]["url"],
            params={"mode": "ajax", "c": "prr.form", "action": "searchRating"},
            data={"fields[ratingName]": "RU000A10B2D2"},
        )
        return response.json()["errors"][0]["customData"]["csrf"]
