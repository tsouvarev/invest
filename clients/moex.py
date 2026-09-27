import csv
from asyncio import Semaphore
from io import StringIO

from asyncstdlib import zip as azip
from funcy import autocurry, lsplit
from pydantic import BaseModel, ConfigDict

from utils import Request, get_batch

CONFIG = {
    "moex": {
        "url": (
            "https://web.moex.com/moex-web-icdb-api/api/v2/export/ru_securities-list"
        ),
        "concurrency": 15,
    },
}


class MoexInfo(BaseModel):
    inn: str

    model_config = ConfigDict(extra="ignore")


async def get_moex_info(client, db, isins) -> dict[str, MoexInfo]:
    cached_isins, missing_inns = lsplit(_get_inn(db), isins)
    pages = await _get_pages(client, missing_inns)
    missing_infos = {
        isin: _parse_page(response)
        async for isin, response in azip(missing_inns, pages)
    }
    cached_infos = {isin: _get_inn(db, isin) for isin in cached_isins}
    return missing_infos | cached_infos


async def _get_pages(client, isins):
    config = CONFIG["moex"]
    sem = Semaphore(config["concurrency"])

    reqs = [
        Request(
            sem=sem,
            url=config["url"],
            params={
                "Format.Type": "csv",
                "Format.Delimiter": "comma",
                "Data.Filter": f"query={isin}",
            },
        )
        for isin in isins
    ]

    caption = "Loading INNs from MOEX"
    return get_batch(caption, client, reqs)


def _parse_page(response) -> MoexInfo:
    with StringIO(response.text) as f:
        reader = csv.DictReader(f)
        return MoexInfo(inn=next(reader)["INN"])


@autocurry
def _get_inn(db, isin):
    ticker = db.get(isin)
    return ticker and MoexInfo(inn=ticker.inn)
