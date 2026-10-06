import json
from collections.abc import Callable
from functools import cache

from funcy import lcat, lfilter
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import Resource, build
from pydantic import BaseModel

from utils import dump_with_order, indicate_work


class Cell(BaseModel):
    column: str
    row: int

    def __str__(self) -> str:
        return f"{self.column}{self.row}"


class Column(BaseModel):
    sheet: str
    index: str

    def as_range(self) -> str:
        return f"{self.sheet}!{self.index}:{self.index}"


class Range(BaseModel):
    sheet: str
    upper_left: Cell
    bottom_right: Cell

    def as_range(self):
        return f"{self.sheet}!{self.upper_left}:{self.bottom_right}"


def load_isins_from_sheet(token: str, sheet_id: str, tickers_column: str) -> list[str]:
    with indicate_work("Loading tickers from sheet"):
        col = _parse_column(tickers_column)
        cells = _get_cells(token, sheet_id, col.as_range())
        return lfilter(_is_ticker_cell, cells)


def write_info_to_sheet(
    token: str,
    sheet_id: str,
    tickers_column: str,
    data: list[BaseModel],
    fields: list[list],
) -> list[str]:
    with indicate_work("Writing tickers to sheet"):
        col = _parse_column(tickers_column)
        cells = _get_cells(token, sheet_id, col.as_range())

        values = dump_with_order(data, fields=fields)
        starting_row = _find_first_row(cells, _is_ticker_cell)
        ending_row = starting_row + len(values) - 1
        row = values[0]

        upper_left = Cell(column=_to_letter_col(1), row=starting_row)
        bottom_right = Cell(column=_to_letter_col(len(row)), row=ending_row)

        range_ = Range(
            sheet=col.sheet, upper_left=upper_left, bottom_right=bottom_right
        )
        _update_cells(token, sheet_id, range_.as_range(), values)


def _get_cells(token: str, sheet_id: str, range_: str) -> list[str]:
    sheets = _get_sheets_service(token)
    cells = sheets.values().get(spreadsheetId=sheet_id, range=range_).execute()
    return lcat(cells.get("values", []))


def _update_cells(token, sheet_id, range_: str, values: list[list]):
    sheets = _get_sheets_service(token)
    return (
        sheets.values()
        .update(
            spreadsheetId=sheet_id,
            range=range_,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        )
        .execute()
    )


def _find_first_row(cells: list, pred: Callable) -> str:
    for i, cell in enumerate(cells, start=1):
        if pred(cell):
            return i
    raise ValueError


@cache
def _get_sheets_service(token: str):
    creds = Credentials.from_service_account_info(
        json.loads(token), scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service: Resource = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()


def _is_ticker_cell(cell):
    return cell.startswith("RU")


def _parse_column(raw_column: str) -> Column:
    if "!" in raw_column:
        sheet, col = raw_column.split("!")
    else:
        sheet, col = "", raw_column

    return Column(sheet=sheet, index=col)


def _to_letter_col(i: int) -> str:
    if i > 20:
        raise ValueError
    return chr(ord("A") + i - 1)
