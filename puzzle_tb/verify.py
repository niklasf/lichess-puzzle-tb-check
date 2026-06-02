"""Pure verdict logic: tablebase results + themes -> rejection reason codes.

No chess board, no network: a position is summarised as the played move's UCI
plus the typed :class:`~puzzle_tb.schema.TablebaseResponse`, so this is trivially
unit-testable. An empty reason list means the puzzle was not rejected by any
known evidence.

Reasons are formatted ``CODE:detail@i`` where ``i`` is the index of the played
move in the puzzle's ``Moves`` list and ``detail`` is the exact lila category (or
dtm) of the strongest relevant move.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .classify import is_clean_draw, is_clean_win, is_holding, is_known, is_winning
from .schema import Move, TablebaseResponse

_MATE_IN_RE = re.compile(r"^mateIn(\d+)$")


@dataclass(frozen=True, slots=True)
class PuzzlerPosition:
    """A single position where the puzzler is to move and must find the solution."""

    move_index: int  # index of the played move within the puzzle's Moves list
    played_uci: str
    response: TablebaseResponse


@dataclass(frozen=True, slots=True)
class PuzzleThemes:
    """The aspects of a puzzle's themes that affect verification."""

    equality: bool
    mate_in: int | None  # X for a mateInX puzzle, else None

    @classmethod
    def parse(cls, themes: str) -> PuzzleThemes:
        """Extract the relevant flags from the puzzle's space-separated themes."""
        tokens = themes.split()
        mate_in: int | None = None
        for token in tokens:
            match = _MATE_IN_RE.match(token)
            if match is not None:
                mate_in = int(match.group(1))
                break
        return cls(equality="equality" in tokens, mate_in=mate_in)


def verify_puzzle(
    positions: Sequence[PuzzlerPosition], themes: PuzzleThemes
) -> list[str]:
    """Collect rejection reasons across every verified position of a puzzle."""
    reasons: list[str] = []
    for position in positions:
        reasons.extend(_verify_position(position, themes))
    return reasons


def _find_played(moves: Sequence[Move], uci: str) -> Move | None:
    return next((m for m in moves if m.uci == uci), None)


def _verify_position(position: PuzzlerPosition, themes: PuzzleThemes) -> list[str]:
    i = position.move_index
    moves = position.response.moves
    played = _find_played(moves, position.played_uci)
    if played is None:
        return [f"MALFORMED@{i}"]

    if themes.equality:
        reasons = _verify_equality(i, played, moves)
    else:
        reasons = _verify_winning(i, played, moves)

    if themes.mate_in is not None:
        reasons.extend(_verify_mate(i, position.response, themes.mate_in))
    return reasons


def _verify_winning(i: int, played: Move, moves: Sequence[Move]) -> list[str]:
    """Normal puzzle: the played move must be the unique clean winning move."""
    reasons: list[str] = []
    pc = played.category
    if is_known(pc) and not is_winning(pc):
        reasons.append(f"NOT_WINNING:{pc.value}@{i}")
    elif is_winning(pc) and not is_clean_win(pc):
        reasons.append(f"WIN_NOT_CLEAN:{pc.value}@{i}")

    spoiler = next(
        (m for m in moves if m.uci != played.uci and is_winning(m.category)), None
    )
    if spoiler is not None:
        code = "NOT_UNIQUE" if is_winning(pc) else "WRONG_MOVE"
        reasons.append(f"{code}:{spoiler.category.value}@{i}")
    return reasons


def _verify_equality(i: int, played: Move, moves: Sequence[Move]) -> list[str]:
    """Equality puzzle: the played move must be the unique clean drawing move."""
    reasons: list[str] = []
    pc = played.category

    winner = next((m for m in moves if is_winning(m.category)), None)
    if winner is not None:
        reasons.append(f"EQUALITY_HAS_WIN:{winner.category.value}@{i}")

    if is_known(pc) and not is_clean_draw(pc) and not is_winning(pc):
        reasons.append(f"EQUALITY_NOT_DRAW:{pc.value}@{i}")

    spoiler = next(
        (m for m in moves if m.uci != played.uci and is_holding(m.category)), None
    )
    if spoiler is not None:
        code = "NOT_UNIQUE" if is_holding(pc) else "WRONG_MOVE"
        reasons.append(f"{code}:{spoiler.category.value}@{i}")
    return reasons


def _verify_mate(i: int, response: TablebaseResponse, mate_in: int) -> list[str]:
    """For mateInX, when DTM is known, check the mate countdown at this ply.

    X counts winning-side moves from the start; at the j-th puzzler move the
    remaining count is ``X - j + 1`` and the position's DTM (in plies) must be
    ``2 * remaining - 1``.
    """
    dtm = response.dtm
    if dtm is None:
        return []
    j = (i + 1) // 2  # puzzler-move ordinal: Moves[1]->1, Moves[3]->2, ...
    expected = 2 * (mate_in - j + 1) - 1
    if dtm != expected:
        return [f"DTM_MISMATCH:{dtm}@{i}"]
    return []
