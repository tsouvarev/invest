from funcy import lmap
from pydantic import BaseModel


def dump_with_order[T](
    data: list[T], *, fields: list[str], context: dict | None = None
) -> list[list]:
    return [
        lmap(obj.model_dump(include=fields, context=context).get, fields)
        for obj in data
    ]


def get_model_fields(model: BaseModel) -> list[str]:
    return type(model).model_fields
