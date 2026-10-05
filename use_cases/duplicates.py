from datetime import datetime

from funcy import group_by, lcat, lmap, memoize
from httpxyz import AsyncClient
from humanize import naturaldate
from pydantic import BaseModel, Field, FieldSerializationInfo, field_serializer

from utils import indicate_work, now, print_model_list, read_json, write_json

from .base import Ticker
from .db import load_base_db

DB_PATH = "duplicates.json"

type Duplicates = dict[str, Duplicate]


class Duplicate(BaseModel):
    ts: datetime = Field(default_factory=now)
    name: str
    canonical: str

    @field_serializer("ts", mode="plain")
    @classmethod
    def serialize_ts(cls, v, info: FieldSerializationInfo):
        if info.mode_is_json():
            return v
        return naturaldate(v)


async def find_duplicates(client: AsyncClient, *, isins: list[str]) -> list[Ticker]:
    db = await load_base_db(client, isins=isins)

    isins_by_company = group_by(
        lambda isin: db[isin] and get_canonical_name(db[isin]._company), isins
    )
    isins_with_duplicates = lcat(
        isins_in_same_company
        for isins_in_same_company in isins_by_company.values()
        if len(isins_in_same_company) > 1
    )
    duplicated_tickers = lmap(db.get, isins_with_duplicates)
    return sorted(duplicated_tickers, key=lambda t: get_canonical_name(t._company))


def list_known_duplicates() -> None:
    duplicates = get_known_duplicates()

    if not duplicates:
        print("No data")
    else:
        print_model_list(list(duplicates.values()))


def add_to_known_duplicates(canonical: str, other_names: list[str]) -> None:
    duplicates = get_known_duplicates()

    for name in other_names:
        duplicates[name.lower()] = Duplicate(name=name, canonical=canonical)

    with indicate_work("Writing DB"):
        write_json(DB_PATH, duplicates)


def remove_from_known_duplicates(name: str) -> None:
    duplicates = get_known_duplicates()

    if name.lower() in duplicates:
        del duplicates[name.lower()]
    else:
        print("Not found")
        return

    with indicate_work("Writing DB"):
        write_json(DB_PATH, duplicates)


@memoize
def get_known_duplicates() -> Duplicates:
    with indicate_work("Reading DB"):
        return read_json(DB_PATH, cast_to=Duplicates, initial={})


def get_canonical_name(name: str) -> str:
    duplicates = get_known_duplicates()

    if duplicate := duplicates.get(name):
        return duplicate.canonical.lower()

    return name
