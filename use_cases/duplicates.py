from funcy import group_by, lcat
from httpxyz import AsyncClient

from .base import Db
from .db import load_base_db


async def find_duplicates(client: AsyncClient, *, isins: list[str]) -> Db:
    db = await load_base_db(client, isins=isins)

    isins_by_company = group_by(lambda isin: db[isin] and db[isin].company, isins)
    isins_with_duplicates = lcat(
        isins_in_company
        for isins_in_company in isins_by_company.values()
        if len(isins_in_company) > 1
    )
    return [v for k, v in db.items() if k in isins_with_duplicates]
