from functools import reduce
from operator import or_

from funcy import concat
from pydantic import BaseModel


def keys_dict(d: dict, keys: list[str], *, cast_to: BaseModel) -> dict:
    res = {}
    for key in keys:
        value = d.get(key)
        res[key] = value and cast_to(**dict(value))
    return res


def merge_as_dicts(
    one: dict[str, BaseModel], two: dict[str, BaseModel]
) -> dict[str, dict]:
    keys = set(concat(one, two))

    res = {}
    for key in keys:
        res[key] = merge_dicts(one.get(key) or {}, two.get(key) or {})

    return res


def merge_dicts(*dicts: dict) -> dict:
    return reduce(or_, map(dict, dicts), {})
