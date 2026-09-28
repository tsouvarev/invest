from datetime import datetime
from enum import StrEnum, auto

from funcy import remove
from httpxyz import AsyncClient
from humanize import naturaldate
from pydantic import (
    BaseModel,
    Field,
    FieldSerializationInfo,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from utils import indicate_work, now, print_model_list, read_json, write_json

from .db import load_base_db

DB_PATH = "blacklist.json"

type Blacklist = list[Entry]


class EntryType(StrEnum):
    ISIN = auto()
    COMPANY = auto()


class Entry(BaseModel):
    ts: datetime = Field(default_factory=now)
    type: EntryType
    value: str
    extra: str = Field(default="", exclude=True)

    @model_serializer(mode="wrap")
    def serialize(
        self, handler: SerializerFunctionWrapHandler, info: FieldSerializationInfo
    ) -> dict:
        res = handler(self)

        if self.is_isin and info.context:
            ticker = info.context["db"].get(self.value)
            if ticker:
                res["extra"] = ticker.name

        return res | {"ts": naturaldate(self.ts)}

    @property
    def is_isin(self) -> bool:
        return self.type == EntryType.ISIN


async def print_blacklist(client: AsyncClient) -> None:
    blacklist = get_blacklist()
    db = await load_base_db(client, isins=[e.value for e in blacklist if e.is_isin])

    if not blacklist:
        print("No data")
    else:
        print_model_list(blacklist, context={"db": db})


def add_to_blacklist(entry_type: EntryType, *values: str) -> None:
    blacklist = get_blacklist()
    for value in values:
        blacklist.append(Entry(value=value, type=entry_type))

    with indicate_work("Writing DB"):
        write_json(DB_PATH, blacklist)


def remove_from_blacklist(*values: str) -> None:
    blacklist = get_blacklist()
    blacklist = remove(lambda entry: entry.value in values, blacklist)

    with indicate_work("Writing DB"):
        write_json(DB_PATH, blacklist)


def get_blacklist() -> Blacklist:
    with indicate_work("Reading DB"):
        return read_json(DB_PATH, cast_to=Blacklist, initial=[])


def is_in_blacklist(blacklist: Blacklist, *values: str) -> bool:
    blacklisted = {entry.value.lower() for entry in blacklist}
    return bool(blacklisted.intersection(values))
