import locale
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from datetime import date
from enum import StrEnum, auto
from itertools import count

from asyncstdlib import list as alist
from funcy.seqs import concat
from httpxyz import AsyncClient
from pydantic import BaseModel
from whatever import that

from .db import Db, Prediction, Ticker, load_from_db
from .show import get_infos
from .utils import indicate_work, select_many_from_response


class SearchField(StrEnum):
    NAME = auto()
    ISIN = auto()
    GRADE = auto()
    URL = auto()
    COUPON = auto()
    CURRENT_COUPON = auto()
    PROFITABILITY = auto()
    QUOTE = auto()
    NOMINAL = auto()
    MATURITY_DATE = auto()
    SECTOR = auto()


class Info(BaseModel):
    isin: str
    grade: str
    coupon: float
    quote: str
    nominal: str
    maturity_date: str
    sector: str


SEARCH_CONFIG = {
    "corporate": {
        "url": "https://smart-lab.ru/q/bonds/order_by_year_yield/desc/page{}/",
        "pagination": True,
        "selectors": {
            SearchField.URL: "main tr > td.trades-table__name > a",
            SearchField.COUPON: "main table tr td:nth-child(6)",
            SearchField.PROFITABILITY: "main table tr td:nth-child(5)",
            SearchField.GRADE: "main table tr td:nth-child(8)",
        },
    },
    "federal": {
        "url": "https://smart-lab.ru/q/ofz/order_by_year_yield/desc/",
        "pagination": False,
        "selectors": {
            SearchField.URL: "main tr > td.trades-table__name > a",
            SearchField.COUPON: "main table tr td:nth-child(8)",
            SearchField.PROFITABILITY: "main table tr td:nth-child(6)",
        },
    },
    "subfederal": {
        "url": "https://smart-lab.ru/q/subfed/order_by_year_yield/desc/page{}/",
        "pagination": False,
        "selectors": {
            SearchField.URL: "main tr > td.trades-table__name > a",
            SearchField.COUPON: "main table tr td:nth-child(7)",
            SearchField.PROFITABILITY: "main table tr td:nth-child(6)",
        },
    },
}


SECTOR_MAPPING = {
    "Машиностроение": "Производство",
    "МФО": "Услуги",
    "Другие услуг": "Услуги",
    "Электроэнергетика": "Производство",
    "Нефтегазовая отрасль": "Ресурсы",
    "Горнодобывающие": "Ресурсы",
    "Ломбарды": "Услуги",
    "Недвижимость": "Услуги",
    "Хим.пром": "Производство",
    "Пищевая пром.": "Еда",
    "Сельское хозяйство": "Еда",
    "Черная металлургия": "Производство",
    "Оборонная промышленность": "Производство",
    "Потреб.услуги": "Услуги",
    "Телекомы": "Услуги",
    "IT компании": "Прочее",
    "Другая промышленность": "Производство",
    "Финансы прочие": "Банки",
    "Цветная Металлургия": "Производство",
    "Холдинг": "Прочее",
    "Субфедеральные": "Гос",
    "Медицина": "Фармацевтика",
}


def noop(v: str) -> str:
    return v


def parse_date(v: str) -> date:
    return date.strptime(v, "%d-%m-%Y")


def localize_date(v: date) -> str:
    return v.strftime("%d.%m.%Y")


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
    SearchField.PROFITABILITY: str_percent_to_float,
    SearchField.COUPON: str_percent_to_float,
    SearchField.QUOTE: str_percent_to_float,
    SearchField.NOMINAL: localize_digits,
    SearchField.MATURITY_DATE: parse_date,
}

OUTPUT_VALUE_MAPPINGS = {
    SearchField.PROFITABILITY: locale.localize,
    SearchField.COUPON: localize_percents,
    SearchField.CURRENT_COUPON: localize_percents,
    SearchField.QUOTE: localize_percents,
    SearchField.NOMINAL: localize_digits,
    SearchField.MATURITY_DATE: localize_date,
    SearchField.SECTOR: map_sector,
}


async def search_tickers(
    client,
    *,
    used_isins: list[str],
    blacklist: list[str],
    min_yield: float,
    years: int,
    min_rating: int,
    exclude_duplicates: bool,
    show_better_duplicates: bool,
) -> list[Info]:
    isins = await _collect_isins(client, years, min_rating)
    db = await load_from_db(client, isins=concat(isins, used_isins))

    isins = list(_drop_used_tickers(db, isins, used_isins))

    if exclude_duplicates:
        isins = list(_drop_duplicated_companies(db, isins))

    infos = await alist(get_infos(client, isins=list(isins)))
    infos = list(_drop_bad_predictions(infos))
    infos = list(_drop_bad_quotes(infos))

    if show_better_duplicates:
        infos = await alist(_drop_worse_duplicates(client, db, infos, used_isins))

    infos = list(_drop_too_little_yield(infos, min_yield))
    infos = list(_drop_blacklisted_companies_and_isins(infos, db, blacklist))

    return sorted(infos, key=that.coupon, reverse=True)


async def _collect_isins(
    client: AsyncClient, years: int, min_rating: float
) -> list[str]:
    isins = []
    params = {
        "paids_year": 12,
        "mat_years_gt": years,
        "rating_gt": min_rating,
        "bonds_variable": -1,
        "bonds_structures": -1,
        "bonds_mortage": -1,
    }

    for name, conf in SEARCH_CONFIG.items():
        with indicate_work(f"Getting {name} bonds"):
            if conf["pagination"]:
                for page in count(1):
                    response = await client.get(conf["url"].format(page), params=params)

                    paged_tickers = list(
                        _parse_search_page(response, conf["selectors"])
                    )
                    if not paged_tickers:
                        break

                    isins.extend(paged_tickers)
            else:
                response = await client.get(conf["url"], params=params)
                isins.extend(_parse_search_page(response, conf["selectors"]))
    return isins


def _parse_search_page(response, selectors) -> Iterator[Info]:
    search_infos = select_many_from_response(response, [selectors["url"]])
    for el in search_infos:
        yield el[0].attrib["href"].rsplit("/")[-2]


def _drop_used_tickers(
    db: Db, isins: list[str], used_isins: list[str]
) -> Iterator[str]:
    for isin in isins:
        if isin in used_isins or not db.get(isin):
            continue
        yield isin


def _drop_bad_predictions(infos: list[Info]) -> Iterator[Info]:
    for info in infos:
        if info.prediction and info.prediction != Prediction.WITHDRAWN:
            yield info


def _drop_bad_quotes(infos: list[Info]) -> Iterator[Info]:
    for info in infos:
        if info.quote > 70:
            yield info


def _drop_duplicated_companies(db: Db, isins: list[str]) -> Iterator[str]:
    seen_companies = set()
    for isin in isins:
        ticker = db[isin]

        if ticker._company in seen_companies:
            continue

        seen_companies.add(ticker._company)
        yield isin


async def _drop_worse_duplicates(
    client: AsyncClient, db: Db, infos: list[Info], used_isins: list[str]
) -> AsyncIterator[Info]:
    used_infos = await alist(get_infos(client, isins=used_isins))

    current_coupons = defaultdict(int)
    for info in used_infos:
        ticker = db[info.isin]
        current_coupons[ticker._company] = max(
            current_coupons[ticker._company], info.coupon or 0
        )

    for info in infos:
        ticker = db[info.isin]
        if info.coupon > current_coupons.get(ticker._company, 0):
            yield info


def _drop_too_little_yield(infos: list[Info], min_yield: float) -> Iterator[Info]:
    for info in infos:
        if info.coupon > min_yield:
            yield info


def _drop_blacklisted_companies_and_isins(
    infos: list[Info], db: dict[str, Ticker], blacklist: list[str]
) -> Iterator[Info]:
    for info in infos:
        ticker = db.get(info.isin)

        if not ticker:
            continue

        if ticker._company in blacklist or ticker._isin in blacklist:
            continue

        yield info
