import locale
import os
import ssl
from asyncio import Semaphore, TaskGroup
from collections.abc import AsyncIterator, Callable, Generator
from contextlib import contextmanager
from dataclasses import asdict, fields, is_dataclass
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from typing import Any

import pytz
from funcy import split
from httpx_retries import RetryTransport
from httpxyz import AsyncClient, AsyncHTTPTransport, Response
from lxml import etree
from pydantic import BaseModel, ConfigDict, TypeAdapter
from tabulate import tabulate
from tqdm import tqdm

parser = etree.XMLParser(recover=True)

russian_ca = os.getenv("RUSSIAN_CA")
ssl_context = ssl.create_default_context()
ssl_context.load_verify_locations(cadata=russian_ca)

retry = RetryTransport(AsyncHTTPTransport(verify=ssl_context))
async_client = AsyncClient(
    transport=retry,
    headers={
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:154.0) Gecko/20100101 Firefox/154.0"
        )
    },
)


class Request(BaseModel):
    sem: Semaphore
    method: str = "GET"
    url: str
    headers: dict | None = None
    params: dict | None = None
    data: dict | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


def encoder_fallback(o):
    if is_dataclass(o):
        return asdict(o)

    if isinstance(o, date):
        return o.isoformat()

    raise ValueError(o)


def read_file_or_none(
    f: Path | None, transform: Callable | None = None
) -> list[str] | None:
    return read_file(f, transform) if f else []


def read_file(f: Path, transform: Callable | None = None) -> list[str]:
    if transform:
        return sorted(
            transform(line.strip())
            for line in f.read_text("utf-8").splitlines()
            if line
        )
    return sorted(line.strip() for line in f.read_text("utf-8").splitlines() if line)


async def get_batch(
    caption: str, client: AsyncClient, reqs: list[Request]
) -> AsyncIterator:
    tasks = []

    for req in tqdm(reqs, caption):
        async with TaskGroup() as tg:
            task = _limited_download(
                client, req.sem, req.method, req.url, req.headers, req.params, req.data
            )
            tasks.append(tg.create_task(task))

    for task in tasks:
        yield task.result()


async def _limited_download(
    client: AsyncClient,
    sem: Semaphore,
    method: str,
    url: str,
    headers: dict | None,
    params: dict | None,
    data: dict | None,
) -> Response:
    async with sem:
        return await client.request(
            method, url, headers=headers, params=params, data=data
        )


def select_one_from_response(response: Response, css_selector: str) -> str:
    nodes = select_many_from_response(response, [css_selector])

    try:
        node = nodes[0][0]
    except IndexError:
        return "-"

    return get_text_from_node(node)


def select_many_from_response(
    response: Response, css_selectors: list[str]
) -> list[str]:
    tree = etree.fromstring(response.text, parser)
    return list(zip(*map(tree.cssselect, css_selectors)))


def get_text_from_node(n) -> str:
    return n.text.strip()


def project(data: list, fields: list[str]) -> list:
    return [{str(k): d[k] for k in fields} for d in data]


def has_prefixes(s: str, prefixes: list[str]) -> bool:
    return any(map(s.startswith, prefixes))


def get_dataclass_fields(obj: Any) -> list[str]:
    return [field.name for field in fields(obj)]


@contextmanager
def indicate_work(msg_enter: str, msg_exit: str = "Done") -> Generator:
    print(f"{msg_enter}... ", end="")
    yield
    print(msg_exit)


def write_json[T](path: str, data: T) -> None:
    serialized = TypeAdapter(T).dump_json(
        data, indent=2, ensure_ascii=True, fallback=encoder_fallback
    )
    Path(path).write_bytes(serialized)


def print_model_list[T](data: list[T], fields: list[str] | None = None) -> None:
    if not data:
        print("No data")
        return

    dumped = [map(obj.model_dump(include=fields).get, fields) for obj in data]
    print(tabulate(dumped, headers=fields, tablefmt="tsv"))


def get_model_fields(m: BaseModel) -> list[str]:
    return type(m).model_fields


def now():
    return datetime.now(tz=pytz.timezone("Europe/Moscow"))


def merge_dicts(one: dict, two: dict) -> dict:
    overlapping, missing = split(lambda k: k in one, two)

    for key in overlapping:
        one[key] |= two[key]

    return one | project(two, missing)


def is_in(seq):
    @wraps(is_in)
    def inner(el):
        return el in seq

    return inner


def not_in(seq):
    @wraps(not_in)
    def inner(el):
        return el not in seq

    return inner


def parse_date(*formats: str) -> Callable:
    @wraps(parse_date)
    def inner(v: str) -> date:
        for format_ in formats:
            try:
                return date.strptime(v, format_)
            except ValueError:
                pass

        raise ValueError(v)

    return inner


def str_percent_to_float(v: str) -> float:
    return float(v.strip(" %") or "0")


def parse_human_date(v: str) -> date:
    locale.setlocale(category=locale.LC_ALL, locale="ru_RU")
    return date.strptime(v, "%d %B %Y")


def localize_date(v: date) -> str:
    return v and v.strftime("%d.%m.%Y")


def strip_ru(v: str) -> str:
    return v.removeprefix("ru")


def localize_digits(v: float) -> str:
    locale.setlocale(category=locale.LC_ALL, locale="nl_NL")
    return locale.localize(str(v))


def localize_percents(v: float) -> str:
    locale.setlocale(category=locale.LC_ALL, locale="nl_NL")
    return locale.localize(f"{v}%")
