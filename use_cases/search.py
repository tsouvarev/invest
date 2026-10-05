from funcy import group_by, walk_values
from whatever import that

from clients import search_isins

from .base import Db, Prediction, Ticker
from .blacklist import Blacklist, is_in_blacklist
from .db import PredictionsUpdateMode, load_base_db, load_from_db
from .duplicates import get_canonical_name


async def search_tickers(
    client,
    *,
    used_isins: list[str],
    blacklist: Blacklist,
    min_yield: float,
    min_floater_yield: float,
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
    else:
        _drop_used(new_tickers, used_isins)

    _drop_too_little_yield(new_tickers, min_yield, min_floater_yield)

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
        canonical = get_canonical_name(ticker._company)
        if canonical in seen_companies:
            del db[isin]
        seen_companies.add(canonical)


async def _drop_worse_duplicates(
    client, new_tickers: Db, used_isins: list[str]
) -> None:
    used_db = await load_base_db(client, isins=used_isins)
    new_companies = {
        get_canonical_name(ticker._company) for ticker in new_tickers.values()
    }
    conflict_used_isins = [
        isin
        for isin, ticker in used_db.items()
        if get_canonical_name(ticker._company) in new_companies
    ]
    conflicted_used_tickers = await load_from_db(
        client,
        isins=conflict_used_isins,
        update_predictions=PredictionsUpdateMode.SKIP,
    )

    current_coupons = walk_values(
        lambda tickers: max(map(that.coupon, tickers)),
        group_by(
            lambda t: get_canonical_name(t._company), conflicted_used_tickers.values()
        ),
    )

    for isin, ticker in list(new_tickers.items()):
        canonical = get_canonical_name(ticker._company)
        if ticker.coupon <= current_coupons.get(canonical, 0):
            del new_tickers[isin]


def _drop_used(new_tickers: Db, used_isins: list[str]) -> None:
    for isin in used_isins:
        if isin in new_tickers:
            del new_tickers[isin]


def _drop_too_little_yield(db: Db, min_yield: float, min_floater_yield: float) -> None:
    for isin, ticker in list(db.items()):
        too_little_floater_yield = (
            ticker.is_floater and ticker.coupon <= min_floater_yield
        )
        too_little_yield = ticker.coupon <= min_yield

        if too_little_floater_yield or too_little_yield:
            del db[isin]


def _drop_blacklisted_companies_and_isins(db: Db, blacklist: Blacklist) -> None:
    for isin, ticker in list(db.items()):
        variants = [get_canonical_name(ticker._company), ticker._company, ticker._isin]
        if is_in_blacklist(blacklist, variants):
            del db[isin]
