from math import ceil

from funcy import group_by, walk_values
from tabulate import tabulate
from whatever import that

from clients import search_isins
from utils import now

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
    min_rating: int,
    profitable_months: int,
    exclude_duplicates: bool,
    show_better_duplicates: bool,
    with_vdo: bool,
    with_put_offer: bool,
    with_call_offer: bool,
    with_floaters: bool,
    with_structures: bool,
    with_mortgage: bool,
    with_amortized: bool,
    with_perpetual: bool,
    with_subordered: bool,
    with_indexed: bool,
    with_discount: bool,
    with_convertible: bool,
) -> list[Ticker]:
    search_conditions = [
        ("Число выплат в год", 12),
        ("Месяцев в плюс", profitable_months),
        ("Минимальный рейтинг", min_rating),
        ("Включить высокодоходные", with_vdo),
        ("Включить put-оферты", with_put_offer),
        ("Включить call-оферты", with_call_offer),
        ("Включить флоатеры", with_floaters),
        ("Включить структурные", with_structures),
        ("Включить ипотечные", with_mortgage),
        ("Включить амортизированные", with_amortized),
        ("Включить бессрочные", with_perpetual),
        ("Включить субординированные", with_subordered),
        ("Включить линкеры", with_indexed),
        ("Включить дисконтные", with_discount),
        ("Включить конвертируемые", with_convertible),
    ]
    print("\nУсловия поиска\n", tabulate(search_conditions))

    isins = await search_isins(
        client,
        min_rating=min_rating,
        with_vdo=with_vdo,
        with_put_offer=with_put_offer,
        with_call_offer=with_call_offer,
        with_floaters=with_floaters,
        with_structures=with_structures,
        with_mortgage=with_mortgage,
        with_amortized=with_amortized,
        with_perpetual=with_perpetual,
        with_subordered=with_subordered,
        with_indexed=with_indexed,
        with_discount=with_discount,
        with_convertible=with_convertible,
    )

    new_tickers = await load_from_db(
        client,
        isins=isins,
        skip_empty=True,
        update_predictions=PredictionsUpdateMode.SKIP,
    )

    if exclude_duplicates:
        _drop_duplicated_companies(new_tickers)

    _drop_too_little_profitable_months(new_tickers, profitable_months)

    _drop_blacklisted_companies_and_isins(new_tickers, blacklist)
    _drop_bad_predictions(new_tickers)
    _drop_bad_quotes(new_tickers)
    _drop_too_little_yield(new_tickers, min_yield, min_floater_yield)

    if show_better_duplicates:
        await _drop_worse_duplicates(client, new_tickers, used_isins)
    else:
        _drop_used(new_tickers, used_isins)

    return sorted(new_tickers.values(), key=that.coupon, reverse=True)


def _drop_bad_predictions(db: Db) -> None:
    for isin, ticker in list(db.items()):
        if not ticker.prediction or ticker.prediction == Prediction.WITHDRAWN:
            del db[isin]


def _drop_too_little_profitable_months(db: Db, profitable_months: int) -> None:
    today = now().date()

    for isin, ticker in list(db.items()):
        if ticker.quote < 95:
            continue

        days_until_mature = (ticker.maturity_date - today).days
        percents_per_day = ticker.coupon / 365
        days_until_profitable = ceil((ticker.quote - 100) / percents_per_day)

        if (days_until_mature - days_until_profitable) * 30 <= profitable_months:
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
        lambda tickers: max((t.coupon, t.maturity_date) for t in tickers),
        group_by(
            lambda t: get_canonical_name(t._company), conflicted_used_tickers.values()
        ),
    )

    for isin, ticker in list(new_tickers.items()):
        canonical = get_canonical_name(ticker._company)
        coupon, maturity_date = current_coupons.get(canonical, (0, now()))

        has_better_coupon = ticker.coupon > coupon
        has_same_coupon_but_better_maturity = (
            ticker.coupon == coupon and ticker.maturity_date > maturity_date
        )

        if has_better_coupon or has_same_coupon_but_better_maturity:
            continue

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
    has_blacklisted = is_in_blacklist(blacklist)
    for isin, ticker in list(db.items()):
        variants = [get_canonical_name(ticker._company), ticker._company, ticker._isin]
        if has_blacklisted(variants):
            del db[isin]
