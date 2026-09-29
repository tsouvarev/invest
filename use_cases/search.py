from funcy import group_by, walk_values
from whatever import that

from clients import search_isins

from .base import Db, Prediction, Ticker
from .blacklist import Blacklist, is_in_blacklist
from .db import PredictionsUpdateMode, load_base_db, load_from_db


async def search_tickers(
    client,
    *,
    used_isins: list[str],
    blacklist: Blacklist,
    min_yield: float,
    years: int,
    min_rating: int,
    exclude_duplicates: bool,
    show_better_duplicates: bool,
    with_floaters: bool,
    with_structures: bool,
    with_mortgage: bool,
) -> list[Ticker]:
    isins = await search_isins(
        client,
        years=years,
        min_rating=min_rating,
        with_floaters=with_floaters,
        with_structures=with_structures,
        with_mortgage=with_mortgage,
    )

    new_tickers = await load_from_db(
        client,
        isins=isins,
        skip_empty=True,
        update_predictions=PredictionsUpdateMode.SKIP,
    )

    if exclude_duplicates:
        _drop_duplicated_companies(new_tickers)

    _drop_blacklisted_companies_and_isins(new_tickers, blacklist)
    _drop_bad_predictions(new_tickers)
    _drop_bad_quotes(new_tickers)

    if show_better_duplicates:
        await _drop_worse_duplicates(client, new_tickers, used_isins)

    _drop_too_little_yield(new_tickers, min_yield)

    return sorted(new_tickers.values(), key=that.coupon, reverse=True)


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


async def _drop_worse_duplicates(
    client, new_tickers: Db, used_isins: list[str]
) -> None:
    used_db = await load_base_db(client, isins=used_isins)
    new_companies = {ticker._company for ticker in new_tickers.values()}
    conflict_used_isins = [
        isin for isin, ticker in used_db.items() if ticker._company in new_companies
    ]
    conflicted_used_tickers = await load_from_db(
        client,
        isins=conflict_used_isins,
        update_predictions=PredictionsUpdateMode.SKIP,
    )

    current_coupons = walk_values(
        lambda tickers: max(map(that.coupon, tickers)),
        group_by(that._company, conflicted_used_tickers.values()),
    )

    for isin, ticker in list(new_tickers.items()):
        if ticker.coupon <= current_coupons.get(ticker._company, 0):
            del new_tickers[isin]


def _drop_too_little_yield(db: Db, min_yield: float) -> None:
    for isin, ticker in list(db.items()):
        if ticker.coupon <= min_yield:
            del db[isin]


def _drop_blacklisted_companies_and_isins(db: Db, blacklist: Blacklist) -> None:
    for isin, ticker in list(db.items()):
        if is_in_blacklist(blacklist, ticker._company, ticker._isin):
            del db[isin]
