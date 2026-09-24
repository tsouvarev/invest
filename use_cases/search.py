from collections.abc import Iterator
from enum import StrEnum, auto
from itertools import count

from funcy import group_by, walk_values
from httpxyz import AsyncClient
from whatever import that

from .tickers import (
    Db,
    Prediction,
    PredictionsUpdateMode,
    Ticker,
    load_base_db,
    load_from_db,
)
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
) -> list[Ticker]:
    isins = await _collect_isins(client, years, min_rating)

    new_tickers = await load_base_db(client, isins=isins)

    if exclude_duplicates:
        _drop_duplicated_companies(new_tickers)

    _drop_blacklisted_companies_and_isins(new_tickers, blacklist)

    new_tickers = await load_from_db(client, isins=new_tickers, skip_empty=True)

    _drop_bad_predictions(new_tickers)
    _drop_bad_quotes(new_tickers)

    if show_better_duplicates:
        used_db = await load_base_db(client, isins=used_isins)
        conflict_companies = {ticker._company for ticker in new_tickers.values()}
        conflict_used_tickers = [
            isin
            for isin, ticker in used_db.items()
            if ticker._company in conflict_companies
        ]
        used_tickers = await load_from_db(
            client,
            isins=conflict_used_tickers,
            update_predictions=PredictionsUpdateMode.SKIP,
        )
        _drop_worse_duplicates(new_tickers, used_tickers)

    _drop_too_little_yield(new_tickers, min_yield)

    return sorted(new_tickers.values(), key=that.coupon, reverse=True)


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


def _parse_search_page(response, selectors) -> Iterator[str]:
    search_infos = select_many_from_response(response, [selectors["url"]])
    for el in search_infos:
        yield el[0].attrib["href"].rsplit("/")[-2]


def _drop_bad_predictions(db: Db) -> None:
    for isin, ticker in list(db.items()):
        if not ticker.prediction or ticker.prediction == Prediction.WITHDRAWN:
            del db[isin]


def _drop_bad_quotes(db: Db) -> None:
    for isin, ticker in list(db.items()):
        if not ticker.quote or ticker.quote < 70:
            del db[isin]


def _drop_duplicated_companies(db: Db) -> None:
    seen_companies = set()
    for isin, ticker in list(db.items()):
        if ticker._company in seen_companies:
            del db[isin]
        seen_companies.add(ticker._company)


def _drop_worse_duplicates(new_db: Db, used_db: Db) -> None:
    current_coupons = walk_values(
        lambda tickers: max(map(that.coupon, tickers)),
        group_by(that._company, used_db.values()),
    )

    for isin, ticker in list(new_db.items()):
        if ticker.coupon <= current_coupons.get(ticker._company, 0):
            del new_db[isin]


def _drop_too_little_yield(db: Db, min_yield: float) -> None:
    for isin, ticker in list(db.items()):
        if ticker.coupon <= min_yield:
            del db[isin]


def _drop_blacklisted_companies_and_isins(db: Db, blacklist: list[str]) -> None:
    for isin, ticker in list(db.items()):
        if ticker._company in blacklist or ticker._isin in blacklist:
            del db[isin]
