from datetime import datetime
from pathlib import Path
from typing import Annotated

from async_typer import AsyncTyper, Option
from tabulate import tabulate

from use_cases import (
    Db,
    EntryType,
    Grade,
    InnsUpdateMode,
    PredictionsUpdateMode,
    ShowField,
    add_to_blacklist,
    find_duplicates,
    get_blacklist,
    get_last_snapshot,
    load_base_db,
    load_from_db,
    load_isins_from_sheet,
    load_snapshot,
    print_blacklist,
    print_diff,
    print_ratings,
    remove_from_blacklist,
    search_tickers,
    write_snapshot,
)
from utils import (
    async_client,
    print_model_list,
    read_file_or_none,
)

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


@bonds_app.command()
async def show(
    file: Path | None = None,
    isin: list[str] | None = None,
    sheet: Annotated[str | None, Option(envvar="SHEET_ID")] = None,
    diff: bool = True,
    update: bool = False,
    update_predictions: PredictionsUpdateMode = PredictionsUpdateMode.OUTDATED,
    update_inns: InnsUpdateMode = InnsUpdateMode.MISSING,
    fields: list[ShowField] = ShowField.default,
    token: Annotated[str | None, Option(envvar="GOOGLE_SHEETS_TOKEN")] = None,
    column: Annotated[str | None, Option(envvar="SHEET_COLUMN")] = None,
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
        print_model_list(tickers, fields)

        if diff:
            last_snapshot = get_last_snapshot()
            print_diff(data, last_snapshot, data)
            write_snapshot(data)


@bonds_app.command()
async def ratings(isin: str, with_bond_actions: bool = False) -> None:
    async with async_client:
        await print_ratings(
            async_client, isin=isin, with_bond_actions=with_bond_actions
        )


@bonds_app.command()
async def duplicates(
    file: Path | None = None,
    isin: list[str] | None = None,
    sheet: Annotated[str | None, Option(envvar="SHEET_ID")] = None,
    fields: list[ShowField] = ShowField.base,
    token: Annotated[str | None, Option(envvar="GOOGLE_SHEETS_TOKEN")] = None,
    column: Annotated[str | None, Option(envvar="SHEET_COLUMN")] = None,
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

    async with async_client:
        data = await find_duplicates(async_client, isins=isins)
        print_model_list(data, fields)


@bonds_app.command()
async def search(
    used: Path | None = None,
    sheet: Annotated[str | None, Option(envvar="SHEET_ID")] = None,
    min_yield: float = 16,
    min_floater_yield: float = 20,
    years: float = 1,
    min_rating: Grade = Grade.BB,
    exclude_duplicates: bool = True,
    show_better_duplicates: bool = True,
    volatiles: bool = False,
    floaters: bool = False,
    structures: bool = False,
    mortgage: bool = False,
    fields: list[ShowField] = ShowField.default,
    token: Annotated[str | None, Option(envvar="GOOGLE_SHEETS_TOKEN")] = None,
    column: Annotated[str | None, Option(envvar="SHEET_COLUMN")] = None,
) -> None:
    if used:
        used_isins = read_file_or_none(used)
    elif sheet:
        used_isins = load_isins_from_sheet(token, sheet, column)
    else:
        msg = "no source"
        raise ValueError(msg)

    blacklisted = get_blacklist()

    async with async_client:
        data = await search_tickers(
            async_client,
            used_isins=used_isins,
            blacklist=blacklisted,
            min_yield=min_yield,
            min_floater_yield=min_floater_yield,
            years=years,
            min_rating=min_rating,
            exclude_duplicates=exclude_duplicates,
            show_better_duplicates=show_better_duplicates,
            with_floaters=volatiles or floaters,
            with_structures=volatiles or structures,
            with_mortgage=volatiles or mortgage,
        )
        print_model_list(data, fields)


@db_app.command()
async def update(
    file: Path | None = None,
    isin: list[str] | None = None,
    sheet: Annotated[str | None, Option(envvar="SHEET_ID")] = None,
    token: Annotated[str | None, Option(envvar="GOOGLE_SHEETS_TOKEN")] = None,
    column: Annotated[str | None, Option(envvar="SHEET_COLUMN")] = None,
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

    async with async_client:
        data = await load_from_db(
            async_client, isins=isins, update_predictions=PredictionsUpdateMode.ALL
        )
        print_model_list(data)


@snaps_app.command("load")
def load_snaps(date: datetime) -> None:
    data = load_snapshot(date)
    print(tabulate(data.values(), headers="keys"))


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
