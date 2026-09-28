from datetime import datetime
from enum import StrEnum, auto

from funcy import remove
from pydantic import BaseModel, Field

from utils import indicate_work, now, print_model_list, read_json, write_json

DB_PATH = "blacklist.json"

type Blacklist = list[Entry]


class EntryType(StrEnum):
    ISIN = auto()
    COMPANY = auto()


class Entry(BaseModel):
    ts: datetime = Field(default_factory=now)
    type: EntryType
    value: str


def print_blacklist() -> None:
    blacklist = get_blacklist()
    if not blacklist:
        print("No data")
    else:
        print_model_list(blacklist)


def add_to_blacklist(value: str, entry_type: EntryType) -> None:
    blacklist = get_blacklist()
    blacklist.append(Entry(value=value, type=entry_type))

    with indicate_work("Writing DB"):
        write_json(DB_PATH, blacklist)


def remove_from_blacklist(value: str) -> None:
    blacklist = get_blacklist()
    blacklist = remove(lambda entry: entry.value == value, blacklist)

    with indicate_work("Writing DB"):
        write_json(DB_PATH, blacklist)


def get_blacklist() -> Blacklist:
    with indicate_work("Reading DB"):
        return read_json(DB_PATH, cast_to=Blacklist, initial=[])


def is_in_blacklist(blacklist: Blacklist, *values: str) -> bool:
    blacklisted = {entry.value.lower() for entry in blacklist}
    return bool(blacklisted.intersection(values))
