from datetime import timedelta
from io import StringIO
from numbers import Number
from sys import stdout
from typing import IO, Any

from funcy import autocurry
from humanize import naturaldelta
from pydantic import BaseModel, TypeAdapter
from rich.box import MARKDOWN, SIMPLE
from rich.console import Console
from rich.table import Table

from .models import dump_with_order, get_model_fields


def format_with_sign(v: Number, precision: int = 2) -> str:
    return f"{v:+.{precision}f}"


def format_timedelta_with_sign(delta: timedelta) -> str:
    msg = naturaldelta(delta)
    sign = "-" if delta.days < 0 else "+"
    return f"{sign}{msg}"


def print_obj(obj: BaseModel) -> None:
    print_table(obj.model_dump().items(), fields=["Поле", "Значение"])


def print_model_list[T](
    data: list[T],
    *,
    fields: list[str] | None = None,
    context: dict | None = None,
    rich: bool = False,
) -> None:
    print(stringify_model_list(data, fields=fields, context=context, rich=rich))


def stringify_model_list[T](
    data: list[T],
    *,
    title: str = "",
    fields: list[str] | None = None,
    context: dict | None = None,
    rich: bool = False,
) -> str:
    if not data:
        return "No data"

    if fields:
        headers = fields
        dumped = dump_with_order(data, fields=fields, context=context)
    else:
        headers = get_model_fields(T)
        dumped = TypeAdapter(list[T]).dump_python(data, context=context)

    with StringIO() as buffer:
        print_table(dumped, fields=headers, title=title, rich=rich, buffer=buffer)
        return buffer.getvalue()


def print_table(
    data: list,
    *,
    fields: list[str] = [],
    title: str = "",
    rich: bool = False,
    buffer: IO = stdout,
) -> str | None:
    table = Table(title=title, box=MARKDOWN if rich else SIMPLE, show_header=False)

    for field in fields:
        table.add_column(field)

    for row in data:
        table.add_row(*map(_format_value, row))

    table.add_section()

    console = Console(file=buffer, force_terminal=not rich)
    console.print(table, soft_wrap=True, new_line_start=True)


def _format_value(v: Any) -> str:
    match v:
        case bool():
            return check if v else cross
        case _:
            f = str

    return f(v)


@autocurry
def colored(color, v):
    return f"[{color}]{v}[/{color}]"


better = colored("bright_green")
worse = colored("bright_red")
same = colored("bright_yellow")
check = better("v")
cross = worse("x")
