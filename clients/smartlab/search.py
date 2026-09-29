from collections.abc import Iterator
from itertools import count
from typing import Any

from httpxyz import AsyncClient

from utils import indicate_work, select_many_from_response

CONFIG = {
    "corporate": {
        "url": "https://smart-lab.ru/q/bonds/order_by_year_yield/desc/page{}/",
        "pagination": True,
        "selectors": {
            "url": "main tr > td.trades-table__name > a",
            "coupon": "main table tr td:nth-child(6)",
            "profitability": "main table tr td:nth-child(5)",
            "grade": "main table tr td:nth-child(8)",
        },
    },
    "federal": {
        "url": "https://smart-lab.ru/q/ofz/order_by_year_yield/desc/",
        "pagination": False,
        "selectors": {
            "url": "main tr > td.trades-table__name > a",
            "coupon": "main table tr td:nth-child(8)",
            "profitability": "main table tr td:nth-child(6)",
        },
    },
    "subfederal": {
        "url": "https://smart-lab.ru/q/subfed/order_by_year_yield/desc/page{}/",
        "pagination": False,
        "selectors": {
            "url": "main tr > td.trades-table__name > a",
            "coupon": "main table tr td:nth-child(7)",
            "profitability": "main table tr td:nth-child(6)",
        },
    },
}


async def search_isins(
    client: AsyncClient,
    *,
    years: int,
    min_rating: float,
    with_floaters: bool,
    with_structures: bool,
    with_mortgage: bool,
) -> list[str]:
    isins = []
    params = {
        "paids_year": 12,
        "mat_years_gt": years,
        "rating_gt": min_rating,
        "bonds_variable": _to_smartlab_bool(with_floaters),
        "bonds_structures": _to_smartlab_bool(with_structures),
        "bonds_mortage": _to_smartlab_bool(with_mortgage),
    }

    for name, conf in CONFIG.items():
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


def _to_smartlab_bool(v: Any) -> int:
    return -1 if v else 0
