import ssl
import sys
from asyncio import Semaphore, TaskGroup
from collections.abc import AsyncIterator

from httpx2 import AsyncClient, AsyncHTTPTransport, Response
from pydantic import BaseModel, ConfigDict
from tqdm import tqdm

from utils import get_env


class Request(BaseModel):
    sem: Semaphore
    method: str = "GET"
    url: str
    headers: dict | None = None
    params: dict | None = None
    data: dict | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


def get_async_client():
    russian_ca = get_env("RUSSIAN_CA")
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(cadata=russian_ca)

    # RetryTransport requires alias for checks against imports from httpx;
    # see https://github.com/will-ockmore/httpx-retries/issues/73
    sys.modules["httpx"] = sys.modules["httpx2"]
    from httpx_retries import RetryTransport

    retry = RetryTransport(AsyncHTTPTransport(verify=ssl_context))
    return AsyncClient(
        transport=retry,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64; rv:154.0) Gecko/20100101 Firefox/154.0"
            )
        },
    )


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


async_client = get_async_client()
