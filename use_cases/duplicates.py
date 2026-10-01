from funcy import group_by, lcat, lmap
from httpxyz import AsyncClient
from whatever import that

from .base import Ticker
from .db import load_base_db


async def find_duplicates(client: AsyncClient, *, isins: list[str]) -> list[Ticker]:
    db = await load_base_db(client, isins=isins)

    isins_by_company = group_by(lambda isin: db[isin] and db[isin]._company, isins)
    isins_with_duplicates = lcat(
        isins_in_same_company
        for isins_in_same_company in isins_by_company.values()
        if len(isins_in_same_company) > 1
    )
    duplicated_tickers = lmap(db.get, isins_with_duplicates)
    return sorted(duplicated_tickers, key=that._company)
