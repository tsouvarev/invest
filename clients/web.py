import os
import ssl
from asyncio import Semaphore, TaskGroup
from collections.abc import AsyncIterator

from httpx_retries import RetryTransport
from httpxyz import AsyncClient, AsyncHTTPTransport, Response
from pydantic import BaseModel, ConfigDict
from tqdm import tqdm

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
