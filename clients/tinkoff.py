import re
from asyncio import Semaphore
from typing import TypedDict

from asyncstdlib import zip as azip
from funcy import lsplit
from httpxyz import AsyncClient
from pydantic import BaseModel, ConfigDict, computed_field

from utils import (
    Request,
    get_batch,
    keys_dict,
    not_in,
    now,
    select_one_from_response,
)

CONFIG = {
    "tinkoff": {
        "url": "https://www.tbank.ru/invest/bonds/{isin}/",
        "concurrency": 15,
        "selectors": {
            "isin": "span[class^=SecurityHeader__ticker]",
            "name": "span[class^=SecurityHeader__showName]",
        },
    },
}


class TinkoffInfo(BaseModel):
    company: str
    series: str

    model_config = ConfigDict(extra="ignore")

    @property
    def _company(self):
        return self.company.lower()

    @computed_field
    def name(self) -> str:
        return f"{self.company} {self.series}"


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

    name = select_one_from_response(response, selectors["name"])
    return TinkoffInfo(**_parse_name(name))


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
