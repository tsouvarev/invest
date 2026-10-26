from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Annotated

from async_typer import AsyncTyper, Option

from clients import async_client, send_message
from use_cases import (
    Db,
    EntryType,
    Grade,
    InnsUpdateMode,
    PredictionsUpdateMode,
    ShowField,
    add_to_blacklist,
    add_to_known_duplicates,
    find_duplicates,
    get_blacklist,
    get_last_snapshot,
    list_known_duplicates,
    load_base_db,
    load_from_db,
    load_isins_from_sheet,
    load_snapshot,
    print_blacklist,
    print_diff,
    print_info,
    print_ratings,
    remove_from_blacklist,
    remove_from_known_duplicates,
    search_tickers,
    stringify_diff,
    write_info_to_sheet,
    write_snapshot,
)
from utils import env_option, print_model_list, read_file_or_none

COMMON_ENVS = {
    "<FIELDS>": "FIELDS",
    "<FILE>": "FILE",
    "<SHEET>": "GOOGLE_SHEETS_ID",
    "<TOKEN>": "GOOGLE_SHEETS_TOKEN",
    "<COLUMN>": "GOOGLE_TICKERS_COLUMN",
    "<CHAT>": "TELEGRAM_CHAT_ID",
    "<BOT>": "TELEGRAM_BOT_TOKEN",
}


app = AsyncTyper()

db_app = AsyncTyper()
app.add_typer(db_app, name="db")

bonds_app = AsyncTyper()
app.add_typer(bonds_app, name="bonds")

snaps_app = AsyncTyper()
app.add_typer(snaps_app, name="snaps")

sheets_app = AsyncTyper()
app.add_typer(sheets_app, name="sheets")

blacklist_app = AsyncTyper()
app.add_typer(blacklist_app, name="blacklist")

duplicates_app = AsyncTyper()
app.add_typer(duplicates_app, name="duplicates")


show_opt = partial(env_option, common_envs=COMMON_ENVS, prefix="SHOW")
find_opt = partial(env_option, common_envs=COMMON_ENVS, prefix="FIND")
search_opt = partial(env_option, common_envs=COMMON_ENVS, prefix="SEARCH")


@bonds_app.command()
async def show(
    diff: Annotated[bool, show_opt(env="DIFF")],
    write: Annotated[bool, show_opt(env="WRITE")],
    tg: Annotated[bool, show_opt(env="TG")],
    update: Annotated[bool, show_opt(env="UPDATE")] = False,
    update_inns: Annotated[
        InnsUpdateMode, show_opt(env="UPDATE_INNS")
    ] = InnsUpdateMode.MISSING,
    update_predictions: Annotated[
        PredictionsUpdateMode, show_opt(env="UPDATE_PREDICTIONS")
    ] = PredictionsUpdateMode.OUTDATED,
    fields: Annotated[list[ShowField], show_opt(env="<FIELDS>")] = ShowField.default,
    isin: list[str] | None = None,
    file: Annotated[Path | None, show_opt(env="<FILE>")] = None,
    sheet: Annotated[str | None, show_opt(env="<SHEET>")] = None,
    token: Annotated[str | None, show_opt(env="<TOKEN>")] = None,
    column: Annotated[str | None, show_opt(env="<COLUMN>")] = None,
    chat: Annotated[str | None, show_opt(env="<CHAT>")] = None,
    bot: Annotated[str | None, show_opt(env="<BOT>")] = None,
) -> None:
    if file:
        isins = read_file_or_none(file)
    elif isin:
        isins = isin
    elif sheet:
        isins = load_isins_from_sheet(token, sheet, column)
    else:
        msg = "no source"
        raise ValueError(msg)

    if update:
        update_predictions = PredictionsUpdateMode.ALL
        update_inns = InnsUpdateMode.ALL

    async with async_client:
        data: Db = await load_from_db(
            async_client,
            isins=isins,
            update_predictions=update_predictions,
            update_inns=update_inns,
        )

    tickers = list(data.values())

    if write:
        write_info_to_sheet(token, sheet, column, tickers, fields)
    else:
        print_model_list(tickers, fields=fields)

    if diff:
        last_snapshot = get_last_snapshot()
        diff_str = stringify_diff(data, last_snapshot, data, rich=tg)

        if tg:
            if not chat or not bot:
                raise NotImplementedError
            await send_message(bot, chat, diff_str)
        else:
            print(diff_str)

        write_snapshot(data)


@bonds_app.command()
async def ratings(
    isin: str, with_bond_actions: Annotated[bool, Option("--all")] = False
) -> None:
    async with async_client:
        db = await load_base_db(async_client, isins=[isin])
        ticker = db[isin]
        print("\n", ticker.name, "\n")
        await print_ratings(
            async_client, isin=isin, with_bond_actions=with_bond_actions
        )


@bonds_app.command()
async def info(isin: str) -> None:
    async with async_client:
        await print_info(async_client, isin=isin)


@duplicates_app.command("find")
async def find_dupes(
    fields: Annotated[list[ShowField], find_opt(env="<FIELDS>")] = ShowField.base,
    sheet: Annotated[str | None, find_opt(env="<SHEET>")] = None,
    token: Annotated[str | None, find_opt(env="<TOKEN>")] = None,
    column: Annotated[str | None, find_opt(env="<COLUMN>")] = None,
) -> None:
    if sheet:
        isins = load_isins_from_sheet(token, sheet, column)
    else:
        msg = "no source"
        raise ValueError(msg)

    async with async_client:
        data = await find_duplicates(async_client, isins=isins)
        print_model_list(data, fields=fields)


@duplicates_app.command("get")
def list_dupes() -> None:
    list_known_duplicates()


@duplicates_app.command("add")
def add_dupe(canonical: str, other_name: str) -> None:
    add_to_known_duplicates(canonical, [other_name])


@duplicates_app.command("del")
def remove_dupe(name: str) -> None:
    remove_from_known_duplicates(name)


@bonds_app.command()
async def search(
    min_rating: Annotated[Grade, search_opt(env="MIN_RATING")],
    min_yield: Annotated[float, search_opt(env="MIN_YIELD")],
    min_floater_yield: Annotated[float, search_opt(env="MIN_FLOATER_YIELD")],
    profitable_months: Annotated[float, search_opt(env="PROFITABLE_MONTHS")],
    exclude_duplicates: Annotated[bool, search_opt(env="EXCLUDE_DUPLICATES")] = True,
    show_better_duplicates: Annotated[
        bool, search_opt(env="SHOW_BETTER_DUPLICATES")
    ] = True,
    volatiles: Annotated[bool, search_opt(env="VOLATILES")] = False,
    vdo: Annotated[bool, search_opt(env="VDO")] = False,
    put_offer: Annotated[bool, search_opt(env="PUT_OFFER")] = False,
    call_offer: Annotated[bool, search_opt(env="CALL_OFFER")] = False,
    floaters: Annotated[bool, search_opt(env="FLOATERS")] = False,
    structures: Annotated[bool, search_opt(env="STRUCTURES")] = False,
    mortgage: Annotated[bool, search_opt(env="MORTGAGE")] = False,
    amortized: Annotated[bool, search_opt(env="AMORTIZED")] = False,
    perpetual: Annotated[bool, search_opt(env="PERPETUAL")] = False,
    subordered: Annotated[bool, search_opt(env="SUBORDERED")] = False,
    indexed: Annotated[bool, search_opt(env="INDEXED")] = False,
    discount: Annotated[bool, search_opt(env="DISCOUNT")] = False,
    convertible: Annotated[bool, search_opt(env="CONVERTIBLE")] = False,
    fields: Annotated[list[ShowField], search_opt(env="<FIELDS>")] = ShowField.default,
    sheet: Annotated[str | None, search_opt(env="<SHEET>")] = None,
    token: Annotated[str | None, search_opt(env="<TOKEN>")] = None,
    column: Annotated[str | None, search_opt(env="<COLUMN>")] = None,
) -> None:
    used_isins = load_isins_from_sheet(token, sheet, column) if sheet else []

    blacklisted = get_blacklist()

    async with async_client:
        data = await search_tickers(
            async_client,
            used_isins=used_isins,
            blacklist=blacklisted,
            min_yield=min_yield,
            min_floater_yield=min_floater_yield,
            min_rating=min_rating,
            profitable_months=profitable_months,
            exclude_duplicates=exclude_duplicates,
            show_better_duplicates=show_better_duplicates,
            with_vdo=volatiles or vdo,
            with_put_offer=volatiles or put_offer,
            with_call_offer=volatiles or call_offer,
            with_floaters=volatiles or floaters,
            with_structures=volatiles or structures,
            with_mortgage=volatiles or mortgage,
            with_amortized=volatiles or amortized,
            with_perpetual=volatiles or perpetual,
            with_subordered=volatiles or subordered,
            with_indexed=volatiles or indexed,
            with_discount=volatiles or discount,
            with_convertible=volatiles or convertible,
        )
        print_model_list(data, fields=fields)


@snaps_app.command("diff")
async def diff_snaps(date: list[datetime]) -> None:
    async with async_client:
        db = await load_base_db(async_client)
        print_diff(db, *map(load_snapshot, date))


@blacklist_app.command("get")
async def print_bl() -> None:
    async with async_client:
        await print_blacklist(async_client)


@blacklist_app.command("add")
def add_to_bl(type: EntryType, value: list[str]) -> None:
    values = value if type == EntryType.ISIN else [" ".join(value)]

    add_to_blacklist(type, *values)


@blacklist_app.command("del")
def del_from_bl(type: EntryType, value: list[str]) -> None:
    values = value if type == EntryType.ISIN else [" ".join(value)]
    remove_from_blacklist(*values)


if __name__ == "__main__":
    app()
