from asyncio import Semaphore
from datetime import date
from enum import StrEnum, auto

from asyncstdlib import zip as azip
from funcy import autocurry, lsplit
from httpxyz import AsyncClient
from pydantic import BaseModel, ConfigDict, field_validator

from utils import (
    Request,
    get_batch,
    keys_dict,
    parse_date,
    select_one_from_response,
    str_percent_to_float,
)

CONFIG = {
    "smartlab": {
        "url": "https://smart-lab.ru/q/bonds/{isin}/",
        "concurrency": 15,
        "selectors": {
            "grade": ".linear-progress-bar__text",
            "type": (
                "article.quotes-info-list__item:nth-child(2) > div:nth-child(1) > "
                "div:nth-child(1) > div:nth-child(2)"
            ),
            "profitability": (
                "article.quotes-info-list__item:nth-child(1) > div:nth-child(1) > "
                "div:nth-child(2) > div:nth-child(2)"
            ),
            "coupon": (
                "article.quotes-info-list__item:nth-child(2) > div:nth-child(1) > "
                "div:nth-child(13) > div:nth-child(2)"
            ),
            "quote": (
                "article.quotes-info-list__item:nth-child(1) > div:nth-child(1) > "
                "div:nth-child(1) > div:nth-child(2)"
            ),
            "nominal": (
                "div.quotes-simple-table__row:nth-child(12) > div:nth-child(2)"
            ),
            "maturity_date": (
                "article.quotes-info-list__item:nth-child(1) > div:nth-child(1) > "
                "div:nth-child(8) > div:nth-child(2)"
            ),
            "sector": (
                "article.quotes-info-list__item:nth-child(5) > div:nth-child(1) > "
                "div:nth-child(3) > div:nth-child(2)"
            ),
        },
    },
}


class BondType(StrEnum):
    AMORTIZED = auto()
    FIX_KNOWN = auto()
    FIX_UNKNOWN = auto()
    FLOATER = auto()
    LINKER = auto()
    CONVERTIBLE = auto()

    @classmethod
    def from_value(cls, v) -> BondType:
        return {
            "Амортизируемая облигация": BondType.AMORTIZED,
            "Облигация с фиксированным (известным) купоном": BondType.FIX_KNOWN,
            "Облигация с фиксированным (неизвестным) купоном": BondType.FIX_UNKNOWN,
            "Линкер/облигация с индексируемым номиналом": BondType.LINKER,
            "Облигация с плавающим купоном": BondType.FLOATER,
            "Конвертируемая облигация": BondType.CONVERTIBLE,
        }[v]


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

    @classmethod
    def from_value(cls, v: str) -> Sector:
        return {
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
            "Структурные продукты": Sector.OTHER,
            "Ипотечные агенты": Sector.BANKING,
        }.get(v, v)


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
    CCC_PLUS = "CCC+"
    CCC = "CCC"
    CCC_MINUS = "CCC-"
    CC_PLUS = "CC+"
    CC = "CC"
    CC_MINUS = "CC-"
    C_PLUS = "C+"
    C = "C"
    C_MINUS = "C-"
    D_PLUS = "D+"
    D = "D"


class SmartlabInfo(BaseModel):
    grade: Grade
    type: BondType
    coupon: float
    quote: float
    nominal: float
    maturity_date: date
    sector: Sector

    model_config = ConfigDict(extra="ignore")

    @field_validator("maturity_date", mode="before")
    @classmethod
    def parse_dt(cls, v):
        if isinstance(v, date):
            return v
        return parse_date(v, "%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d")

    @field_validator("sector", mode="before")
    @classmethod
    def parse_sector(cls, v):
        if v in Sector:
            return v
        return Sector.from_value(v)

    @field_validator("type", mode="before")
    @classmethod
    def parse_type(cls, v):
        if v in BondType:
            return v
        return BondType.from_value(v)

    @field_validator("coupon", "quote", mode="before")
    @classmethod
    def parse_percents(cls, v):
        if isinstance(v, float):
            return v
        return str_percent_to_float(v)


async def get_smartlab_info(
    client: AsyncClient, db: dict, isins: list[str]
) -> dict[str, SmartlabInfo]:
    outdated_isins, cached_isins = lsplit(_is_outdated(db), isins)
    pages = await _get_pages(client, outdated_isins)
    infos = {
        isin: SmartlabInfo(**_parse_page(response))
        async for isin, response in azip(outdated_isins, pages)
    }
    return infos | keys_dict(db, cached_isins, cast_to=SmartlabInfo)


async def _get_pages(client, isins):  # ruff: ignore[unused-async]
    config = CONFIG["smartlab"]

    sem = Semaphore(config["concurrency"])
    reqs = [Request(sem=sem, url=config["url"].format(isin=isin)) for isin in isins]

    caption = "Getting full info from smartlab"
    return get_batch(caption, client, reqs)


def _parse_page(response):
    selectors = CONFIG["smartlab"]["selectors"]
    values = {
        str(sel): select_one_from_response(response, path)
        for sel, path in selectors.items()
    }
    values["coupon"] = values["coupon"] or values["profitability"]
    del values["profitability"]

    return values


@autocurry
def _is_outdated(db: dict, isin: list[str]) -> bool:
    ticker = db.get(isin)
    return not ticker or ticker.is_outdated
