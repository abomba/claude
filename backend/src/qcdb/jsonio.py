"""Exact JSON I/O: numbers with a fraction or exponent become ``Decimal`` (never ``float``),
duplicate keys and NaN/Infinity are rejected, and serialisation writes Decimals verbatim."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any


class JsonFormatError(ValueError):
    """The bytes are not a strict UTF-8 JSON document."""


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonFormatError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise JsonFormatError(f"non-standard JSON constant {name}")


def loads_exact(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JsonFormatError(f"not valid UTF-8 ({exc.reason} at byte {exc.start})") from None
    if text.startswith("﻿"):
        text = text[1:]
    try:
        return json.loads(
            text,
            parse_float=Decimal,
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise JsonFormatError(
            f"invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from None


def loads_db(text: str | bytes) -> Any:
    """Deserializer for JSONB values read from PostgreSQL (keeps numbers exact)."""
    return json.loads(text, parse_float=Decimal)


def dumps_exact(value: Any) -> str:
    """Serialise to JSON, writing ``Decimal`` values exactly as they are."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("cannot serialise non-finite Decimal")
        return str(value)
    if isinstance(value, (int, float, str)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        items = (
            f"{json.dumps(str(k), ensure_ascii=False)}:{dumps_exact(v)}" for k, v in value.items()
        )
        return "{" + ",".join(items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(dumps_exact(v) for v in value) + "]"
    raise TypeError(f"cannot serialise {type(value).__name__}")


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
