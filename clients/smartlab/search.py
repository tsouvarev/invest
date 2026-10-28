from collections.abc import Iterator
from itertools import count
from typing import Any

from httpxyz import AsyncClient

from utils import indicate_work, select_many_from_response

URL_SELECTOR = "main tr > td.trades-table__name > a"
CONFIG = {
    "corporate": {
        "url": "https://smart-lab.ru/q/bonds/order_by_year_yield/desc/page{}/",
        "pagination": True,
    },
    "federal": {
        "url": "https://smart-lab.ru/q/ofz/order_by_year_yield/desc/",
        "pagination": False,
    },
    "subfederal": {
        "url": "https://smart-lab.ru/q/subfed/order_by_year_yield/desc/",
        "pagination": False,
    },
}


async def search_isins(
    client: AsyncClient,
    *,
    min_rating: float,
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
) -> list[str]:
    isins = []
    params = {
        "paids_year": 12,
        "rating_gt": min_rating,
        "bonds_vdo": _to_smartlab_bool(with_vdo),
        "bonds_put_offer": _to_smartlab_bool(with_put_offer),
        "bonds_call_offer": _to_smartlab_bool(with_call_offer),
        "bonds_variable": _to_smartlab_bool(with_floaters),
        "bonds_structures": _to_smartlab_bool(with_structures),
        "bonds_mortage": _to_smartlab_bool(with_mortgage),
        "bonds_amortized": _to_smartlab_bool(with_amortized),
        "bonds_perpetual": _to_smartlab_bool(with_perpetual),
        "bonds_suborded": _to_smartlab_bool(with_subordered),
        "bonds_indexed": _to_smartlab_bool(with_indexed),
        "bonds_discount": _to_smartlab_bool(with_discount),
        "bonds_convertible": _to_smartlab_bool(with_convertible),
    }

    for name, conf in CONFIG.items():
        with indicate_work(f"Getting {name} bonds"):
            if conf["pagination"]:
                for page in count(1):
                    response = await client.get(conf["url"].format(page), params=params)

                    paged_tickers = list(_parse_search_page(response))
                    if not paged_tickers:
                        break

                    isins.extend(paged_tickers)
            else:
                response = await client.get(conf["url"], params=params)
                isins.extend(_parse_search_page(response))
    return isins


def _parse_search_page(response) -> Iterator[str]:
    search_infos = select_many_from_response(response, [URL_SELECTOR])
    for el in search_infos:
        yield el[0].attrib["href"].rsplit("/")[-2]


def _to_smartlab_bool(v: Any) -> int:
    return -1 if v else 0
