import re
from asyncio import Semaphore
from functools import cached_property
from typing import TypedDict

from asyncstdlib import zip as azip
from funcy import lsplit
from httpxyz import AsyncClient
from pydantic import BaseModel, ConfigDict

from utils import (
    Request,
    get_batch,
    get_text_from_node,
    keys_dict,
    not_in,
    now,
    select_many_from_response,
)

CONFIG = {
    "tinkoff": {
        "url": "https://www.tbank.ru/invest/bonds/{isin}/",
        "concurrency": 15,
        "selectors": {
            "isin": ".SecurityHeader__ticker_j7fZW",
            "name": ".SecurityHeader__showName_iw6qC",
        },
    },
}


class TinkoffInfo(BaseModel):
    company: str
    series: str

    model_config = ConfigDict(extra="ignore")

    @cached_property
    def _company(self):
        return self.company.lower()


class ParsedName(TypedDict):
    company: str
    series: str


async def get_tinkoff_info(client: AsyncClient, db: dict, isins: list[str]) -> dict:
    missing_isins, cached_isins = lsplit(not_in(db), isins)
    pages = await _get_pages(client, missing_isins)
    missing_infos = {
        isin: _parse_info_page(response)
        async for isin, response in azip(missing_isins, pages)
    }
    return missing_infos | keys_dict(db, cached_isins, cast_to=TinkoffInfo)


async def _get_pages(client, isins):  # ruff: ignore[unused-async]
    config = CONFIG["tinkoff"]
    caption = "Loading base info from tinkoff"
    sem = Semaphore(config["concurrency"])

    reqs = [Request(sem=sem, url=config["url"].format(isin=isin)) for isin in isins]
    return get_batch(caption, client, reqs)


def _parse_info_page(response) -> TinkoffInfo:
    selectors = CONFIG["tinkoff"]["selectors"]

    if not response.is_success:
        return None

    nodes = select_many_from_response(response, [selectors["isin"], selectors["name"]])
    isin, name = map(get_text_from_node, nodes[0])
    return TinkoffInfo(ts=now(), isin=isin, **_parse_name(name))


def _parse_name(name: str) -> ParsedName:
    naive_company, *naive_series = name.rsplit(" ", 2)

    match len(naive_series):
        case 0:
            m = re.match(r"([A-Za-zА-Яа-я]+)-?([0-9\w]+)", name)
            company, series = m.groups()
        case 1:
            company, series = naive_company, naive_series[0]
        case 2:
            if naive_series[-1].isalpha() or naive_series[0] in {"БО", "АО"}:
                company, series = naive_company, " ".join(naive_series)
            else:
                company, series = name.rsplit(" ", 1)
        case _:
            raise ValueError(name)

    return ParsedName(company=company, series=series)
