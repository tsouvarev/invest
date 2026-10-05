import json
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter


def encoder_fallback(o):
    if is_dataclass(o):
        return asdict(o)

    if isinstance(o, date):
        return o.isoformat()

    raise ValueError(o)


def read_file_or_none(
    f: Path | None, transform: Callable | None = None
) -> list[str] | None:
    return read_file(f, transform) if f else []


def read_file(f: Path, transform: Callable | None = None) -> list[str]:
    if transform:
        return sorted(
            transform(line.strip())
            for line in f.read_text("utf-8").splitlines()
            if line
        )
    return sorted(line.strip() for line in f.read_text("utf-8").splitlines() if line)


def write_json[T](path: str, data: T) -> None:
    serialized = TypeAdapter(T).dump_json(
        data, indent=2, ensure_ascii=False, fallback=encoder_fallback
    )
    Path(path).write_bytes(serialized)


def read_json(path: str, cast_to: type, initial: Any = None) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        with path.open(encoding='utf-8') as f:
            return TypeAdapter(cast_to).validate_python(json.load(f))

    if initial is not None:
        path.write_text(json.dumps(initial))

    return initial
