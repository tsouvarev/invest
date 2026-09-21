from datetime import datetime
from pathlib import Path
from typing import Annotated

from async_typer import AsyncTyper, Option
from asyncstdlib import list as alist
from tabulate import tabulate

from use_cases.db import Grade, load_from_db
from use_cases.search import search_tickers
from use_cases.sheets import load_tickers_from_sheet
from use_cases.show import (
    OUTPUT_VALUE_MAPPINGS as show_mappings,
)
from use_cases.show import (
    Info,
    ShowField,
    find_duplicates,
    get_infos,
)
from use_cases.snapshots import (
    Snapshot,
    get_last_snapshot,
    load_snapshot,
    print_diff,
    write_snapshot,
)
from use_cases.utils import (
    async_client,
    dump_model_list,
    project,
    read_file_or_none,
    remap_values,
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


@bonds_app.command()
async def show(
    file: Path | None = None,
    isin: list[str] | None = None,
    sheet: Annotated[str | None, Option(envvar="SHEET_ID")] = None,
    diff: bool = True,
    update_predictions: bool = False,
    # write: bool = False,
    field: list[ShowField] | None = None,
    token: Annotated[Path | None, Option(envvar="TOKEN_PATH")] = None,
    column: Annotated[str | None, Option(envvar="SHEET_COLUMN")] = None,
) -> None:
    if file:
        isins = read_file_or_none(file)
    elif isin:
        isins = isin
    elif sheet:
        isins = load_tickers_from_sheet(token, sheet, column)
    else:
        msg = "no source"
        raise ValueError(msg)

    async with async_client:
        data: list[Info] = await alist(
            get_infos(
                async_client,
                isins=isins,
                update_predictions=update_predictions,
                skip_predictions=False,
            )
        )

        if not data:
            print("No data")
            return

        output_data = [remap_values(v, show_mappings) for v in dump_model_list(data)]
        output_data = project(output_data, field) if field else output_data
        print(tabulate(output_data, headers="keys", tablefmt="tsv"))

        if diff:
            last_snapshot = get_last_snapshot()
            current_snapshot = Snapshot.from_info(data)
            await print_diff(async_client, last_snapshot, current_snapshot)
            write_snapshot(data)


@bonds_app.command()
async def duplicates(
    file: Path | None = None,
    isin: list[str] | None = None,
    sheet: Annotated[str | None, Option(envvar="SHEET_ID")] = None,
    token: Annotated[Path | None, Option(envvar="TOKEN_PATH")] = None,
    column: Annotated[str | None, Option(envvar="SHEET_COLUMN")] = None,
) -> None:
    if file:
        isins = read_file_or_none(file)
    elif isin:
        isins = isin
    elif sheet:
        isins = load_tickers_from_sheet(token, sheet, column)
    else:
        msg = "no source"
        raise ValueError(msg)

    async with async_client:
        data = await alist(find_duplicates(async_client, isins=isins))

        if not data:
            print("No data")
            return

        output_data = [remap_values(v, show_mappings) for v in dump_model_list(data)]
        print(tabulate(output_data, headers="keys", tablefmt="tsv"))


@bonds_app.command()
async def search(
    used: Path | None = None,
    sheet: Annotated[str | None, Option(envvar="SHEET_ID")] = None,
    blacklist_file: Path | None = None,
    blacklist: Annotated[str | None, Option(envvar="BLACKLIST")] = None,
    min_yield: float = 16,
    years: float = 1,
    min_rating: Grade = Grade.BB,
    exclude_duplicates: bool = True,
    show_better_duplicates: bool = True,
    token: Annotated[Path | None, Option(envvar="TOKEN_PATH")] = None,
    column: Annotated[str | None, Option(envvar="SHEET_COLUMN")] = None,
) -> None:
    if used:
        used_isins = read_file_or_none(used)
    elif sheet:
        used_isins = load_tickers_from_sheet(token, sheet, column)
    else:
        msg = "no source"
        raise ValueError(msg)

    if blacklist_file:
        blacklisted = read_file_or_none(blacklist)
    elif blacklist:
        blacklisted = blacklist.split(",")
    else:
        msg = "no source"
        raise ValueError(msg)

    async with async_client:
        data = await search_tickers(
            async_client,
            used_isins=used_isins,
            blacklist=[v.lower() for v in blacklisted],
            min_yield=min_yield,
            years=years,
            min_rating=min_rating,
            exclude_duplicates=exclude_duplicates,
            show_better_duplicates=show_better_duplicates,
        )

    if data:
        data = [remap_values(values, show_mappings) for values in dump_model_list(data)]
        print(tabulate(data, headers="keys", tablefmt="tsv"))
    else:
        print("No data")


@db_app.command()
async def update(
    file: Path | None = None,
    isin: list[str] | None = None,
    sheet: Annotated[str | None, Option(envvar="SHEET_ID")] = None,
    token: Annotated[Path | None, Option(envvar="TOKEN_PATH")] = None,
    column: Annotated[str | None, Option(envvar="SHEET_COLUMN")] = None,
) -> None:
    if file:
        isins = read_file_or_none(file)
    elif isin:
        isins = isin
    elif sheet:
        isins = load_tickers_from_sheet(token, sheet, column)
    else:
        msg = "no source"
        raise ValueError(msg)

    async with async_client:
        data = await load_from_db(
            async_client, isins=isins, update_predictions=True, skip_predictions=False
        )

    if data:
        print(tabulate([d for d in data.values() if d]))
    else:
        print("No data")


@snaps_app.command("load")
def load_snaps(date: datetime) -> None:
    data = load_snapshot(date)
    print(tabulate(data.values(), headers="keys"))


@snaps_app.command("diff")
async def diff_snaps(date: list[datetime]) -> None:
    async with async_client:
        await print_diff(async_client, *map(load_snapshot, date))


@sheets_app.command("read")
def read_sheets(
    token: Path = Option(), sheet: str = Option(), column: str = Option()
) -> None:
    print(load_tickers_from_sheet(token, sheet, column))


if __name__ == "__main__":
    app()
