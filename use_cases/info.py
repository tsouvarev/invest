from httpxyz import AsyncClient

from utils import print_obj

from .db import load_from_db


async def print_info(client: AsyncClient, *, isin: str) -> None:
    db = await load_from_db(client, isins=[isin], update=True)

    ticker = db[isin]
    if ticker is None:
        print("No data")

    print_obj(ticker)
