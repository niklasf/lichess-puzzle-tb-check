"""Typed model of the lila-tablebase ``/standard`` response.

This module is the single boundary where untyped JSON from the HTTP API is
turned into typed objects. :func:`parse_response` validates strictly and raises
:class:`MalformedResponse` on anything unexpected, so the rest of the code never
touches a raw ``dict``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Category(enum.Enum):
    """Position evaluation category, as reported by lila-tablebase.

    For a *move*, the category describes the resulting position from the
    perspective of the player to move *after* the move (i.e. the opponent).
    """

    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
    CURSED_WIN = "cursed-win"
    BLESSED_LOSS = "blessed-loss"
    MAYBE_WIN = "maybe-win"
    MAYBE_LOSS = "maybe-loss"
    SYZYGY_WIN = "syzygy-win"
    SYZYGY_LOSS = "syzygy-loss"
    UNKNOWN = "unknown"


class MalformedResponse(Exception):
    """Raised when the tablebase response does not match the expected schema."""


@dataclass(frozen=True, slots=True)
class Move:
    """A single legal move and the evaluation of the resulting position."""

    uci: str
    san: str
    category: Category
    dtm: int | None
    dtz: int | None
    checkmate: bool
    stalemate: bool


@dataclass(frozen=True, slots=True)
class TablebaseResponse:
    """Evaluation of a probed position and its legal moves (best first)."""

    category: Category
    dtm: int | None
    dtz: int | None
    checkmate: bool
    stalemate: bool
    moves: tuple[Move, ...]


def _as_mapping(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MalformedResponse(f"expected {what} to be an object, got {type(value).__name__}")
    # Keys in JSON objects are always strings.
    return {str(k): v for k, v in value.items()}


def _get_str(obj: dict[str, object], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise MalformedResponse(f"expected string field {key!r}, got {value!r}")
    return value


def _get_bool(obj: dict[str, object], key: str) -> bool:
    value = obj.get(key)
    if not isinstance(value, bool):
        raise MalformedResponse(f"expected boolean field {key!r}, got {value!r}")
    return value


def _get_opt_int(obj: dict[str, object], key: str) -> int | None:
    value = obj.get(key)
    if value is None:
        return None
    # bool is a subclass of int; reject it explicitly to catch schema drift.
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedResponse(f"expected integer or null field {key!r}, got {value!r}")
    return value


def _get_category(obj: dict[str, object], key: str) -> Category:
    raw = _get_str(obj, key)
    try:
        return Category(raw)
    except ValueError:
        raise MalformedResponse(f"unknown category {raw!r} in field {key!r}") from None


def _parse_move(value: object) -> Move:
    obj = _as_mapping(value, "move")
    return Move(
        uci=_get_str(obj, "uci"),
        san=_get_str(obj, "san"),
        category=_get_category(obj, "category"),
        dtm=_get_opt_int(obj, "dtm"),
        dtz=_get_opt_int(obj, "dtz"),
        checkmate=_get_bool(obj, "checkmate"),
        stalemate=_get_bool(obj, "stalemate"),
    )


def parse_response(payload: object) -> TablebaseResponse:
    """Parse and validate a ``/standard`` JSON payload into typed objects.

    Raises :class:`MalformedResponse` on any structural or value surprise
    (missing field, wrong type, or an unrecognized ``category``).
    """
    obj = _as_mapping(payload, "response")
    raw_moves = obj.get("moves")
    if not isinstance(raw_moves, list):
        raise MalformedResponse(f"expected list field 'moves', got {raw_moves!r}")
    return TablebaseResponse(
        category=_get_category(obj, "category"),
        dtm=_get_opt_int(obj, "dtm"),
        dtz=_get_opt_int(obj, "dtz"),
        checkmate=_get_bool(obj, "checkmate"),
        stalemate=_get_bool(obj, "stalemate"),
        moves=tuple(_parse_move(m) for m in raw_moves),
    )
