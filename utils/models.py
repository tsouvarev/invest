from funcy import lmap
from pydantic import TypeAdapter
from tabulate import tabulate


def print_model_list[T](
    data: list[T], fields: list[str] | None = None, context: dict | None = None
) -> None:
    if not data:
        print("No data")
        return

    if fields:
        headers = fields
        dumped = dump_with_order(data, fields, context)
    else:
        headers = "keys"
        dumped = TypeAdapter(list[T]).dump_python(data, context=context)

    print(tabulate(dumped, headers=headers, tablefmt="tsv"))


def dump_with_order[T](
    data: list[T], fields: list[str], context: dict | None = None
) -> list[list]:
    return [
        lmap(obj.model_dump(include=fields, context=context).get, fields)
        for obj in data
    ]
