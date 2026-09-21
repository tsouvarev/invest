import locale
from asyncio import Semaphore
from collections.abc import AsyncIterator, Callable
from datetime import date
from enum import StrEnum, auto
from functools import wraps

from asyncstdlib import zip as azip
from funcy import group_by, lcat
from httpxyz import AsyncClient
from pydantic import BaseModel, field_validator

from .db import Prediction, Sector, load_from_db
from .utils import Request, get_batch, remap_values, select_one_from_response


class ShowField(StrEnum):
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


class ParseInfo(BaseModel):
    short_name: str
    isin: str
    coupon: float
    grade: str


class Info(BaseModel):
    name: str
    isin: str
    grade: str
    coupon: float
    quote: float
    nominal: str
    maturity_date: date
    sector: Sector
    prediction: Prediction | None
    prediction_date: date | None

    @field_validator("prediction_date", mode="before")
    @classmethod
    def parse_prediction_date(cls, v):
        if isinstance(v, date | None):
            return v

        try:
            return date.strptime(v, "%d.%m.%Y")
        except ValueError:
            return date.strptime(v, "%Y-%m-%d")


SHOW_CONFIG = {
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
    }
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
    "current_coupon": localize_percents,
    ShowField.QUOTE: localize_percents,
    ShowField.NOMINAL: localize_digits,
    ShowField.MATURITY_DATE: localize_date,
    ShowField.PREDICTION: Prediction.humanize,
    ShowField.PREDICTION_DATE: localize_date,
}


async def get_infos(
    client: AsyncClient,
    *,
    isins: list[str],
    update_predictions: bool = False,
    skip_predictions: bool = True,
) -> AsyncIterator[Info]:
    db = await load_from_db(
        client,
        isins=isins,
        update_predictions=update_predictions,
        skip_predictions=skip_predictions,
    )

    config = SHOW_CONFIG["smartlab"]
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

        yield Info(name=ticker.full_name, isin=isin, **values)


async def find_duplicates(
    client: AsyncClient, *, isins: list[str]
) -> AsyncIterator[Info]:
    db = await load_from_db(client, isins=isins)
    isins_by_company = group_by(lambda isin: db[isin] and db[isin].company, isins)
    isins_with_duplicates = lcat(
        isins_in_company
        for isins_in_company in isins_by_company.values()
        if len(isins_in_company) > 1
    )

    async for info in get_infos(client, isins=isins_with_duplicates):
        yield info
