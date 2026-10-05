from functools import wraps


def has_prefixes(s: str, prefixes: list[str]) -> bool:
    return any(map(s.startswith, prefixes))


def not_in(seq):
    @wraps(not_in)
    def inner(el):
        return el not in seq

    return inner
