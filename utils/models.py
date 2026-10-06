from funcy import lmap
from pydantic import TypeAdapter
from tabulate import tabulate


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
        headers = "keys"
        dumped = TypeAdapter(list[T]).dump_python(data, context=context)

    tablefmt = "tsv" if rich else "github"
    return tabulate(dumped, headers=headers, tablefmt=tablefmt)


def dump_with_order[T](
    data: list[T], *, fields: list[str], context: dict | None = None
) -> list[list]:
    return [
        lmap(obj.model_dump(include=fields, context=context).get, fields)
        for obj in data
    ]
