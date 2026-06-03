"""Pure verdict logic: tablebase results + themes -> rejections.

No chess board, no network: a position is summarised as the played move's UCI
plus the typed :class:`~puzzle_tb.schema.TablebaseResponse`, so this is trivially
unit-testable. An empty rejection list means the puzzle was not rejected by any
known evidence.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Sequence
from dataclasses import dataclass

from .classify import (
    competes_for_win,
    holds_draw,
    is_known,
    is_unconditional_draw,
    is_unconditional_win,
    is_winning,
)
from .schema import Category, Move, TablebaseResponse

_MATE_IN_RE = re.compile(r"^mateIn(\d+)$")


class MalformedPuzzle(Exception):
    """A puzzle's data is unusable (illegal move, or a move the tablebase did not
    offer). Treated as fatal rather than a per-puzzle rejection."""


class ReasonCode(enum.Enum):
    """Why a puzzle position was rejected."""

    NOT_WINNING = "NOT_WINNING"
    WIN_FRUSTRATED = "WIN_FRUSTRATED"
    NOT_UNIQUE = "NOT_UNIQUE"
    WRONG_MOVE = "WRONG_MOVE"
    EQUALITY_HAS_WIN = "EQUALITY_HAS_WIN"
    EQUALITY_NOT_DRAW = "EQUALITY_NOT_DRAW"
    DTM_MISMATCH = "DTM_MISMATCH"


@dataclass(frozen=True, slots=True)
class Rejection:
    """One reason a puzzle position was rejected.

    ``detail`` is the exact category of the strongest relevant move, or the DTM
    value for :attr:`ReasonCode.DTM_MISMATCH`. ``move_index`` is the offending
    move's index in the puzzle's ``Moves`` list. ``str()`` renders ``CODE:detail@i``.
    """

    code: ReasonCode
    detail: Category | int
    move_index: int

    def __str__(self) -> str:
        detail = self.detail.value if isinstance(self.detail, Category) else self.detail
        return f"{self.code.value}:{detail}@{self.move_index}"


@dataclass(frozen=True, slots=True)
class PuzzlerPosition:
    """A single position where the puzzler is to move and must find the solution."""

    move_index: int  # index of the played move within the puzzle's Moves list
    played_uci: str
    response: TablebaseResponse
    capture_seen: bool  # whether a capture has occurred earlier in the puzzle line


@dataclass(frozen=True, slots=True)
class ExactMate:
    """A mate in exactly ``moves`` winning-side moves (Lichess mateIn1..mateIn4)."""

    moves: int


@dataclass(frozen=True, slots=True)
class AtLeastMate:
    """A mate in ``moves`` winning-side moves or more (Lichess mateIn5 = 5+)."""

    moves: int


# A mate requirement is either an exact count or a lower bound.
MateRequirement = ExactMate | AtLeastMate

# Lichess caps its mate themes at mateIn5, which therefore means "5 or more".
_LOWER_BOUND_MATE = 5


@dataclass(frozen=True, slots=True)
class PuzzleThemes:
    """The aspects of a puzzle's themes that affect verification."""

    equality: bool
    mate: MateRequirement | None  # for a mateInX puzzle, else None

    @classmethod
    def parse(cls, themes: str) -> PuzzleThemes:
        """Extract the relevant flags from the puzzle's space-separated themes."""
        tokens = themes.split()
        mate: MateRequirement | None = None
        for token in tokens:
            match = _MATE_IN_RE.match(token)
            if match is not None:
                x = int(match.group(1))
                mate = AtLeastMate(x) if x >= _LOWER_BOUND_MATE else ExactMate(x)
                break
        return cls(equality="equality" in tokens, mate=mate)


def verify_puzzle(
    positions: Sequence[PuzzlerPosition], themes: PuzzleThemes
) -> list[Rejection]:
    """Collect rejections across every verified position of a puzzle."""
    rejections: list[Rejection] = []
    for position in positions:
        rejections.extend(_verify_position(position, themes))
    return rejections


def _find_played(moves: Sequence[Move], uci: str) -> Move | None:
    return next((m for m in moves if m.uci == uci), None)


def _verify_position(position: PuzzlerPosition, themes: PuzzleThemes) -> list[Rejection]:
    i = position.move_index
    moves = position.response.moves
    played = _find_played(moves, position.played_uci)
    if played is None:
        raise MalformedPuzzle(
            f"played move {position.played_uci!r} not offered by the tablebase (move {i})"
        )

    if themes.equality:
        # Equality puzzles go through the full check even for a mating move: a mate
        # is a win, so it is rejected (EQUALITY_HAS_WIN), not accepted.
        rejections = _verify_equality(i, played, moves, position.capture_seen)
    elif played.checkmate:
        # For a winning/mate puzzle an immediate checkmate is always an acceptable
        # solution, regardless of other mating moves or longer winning alternatives
        # -- but it must still match the expected mate count (DTM check below).
        rejections = []
    else:
        rejections = _verify_winning(i, played, moves, position.capture_seen)

    if themes.mate is not None:
        rejections.extend(_verify_mate(i, position.response, themes.mate))
    return rejections


def _verify_winning(
    i: int, played: Move, moves: Sequence[Move], capture_seen: bool
) -> list[Rejection]:
    """Normal puzzle: the played move must be the unique unconditional winning move."""
    rejections: list[Rejection] = []
    pc = played.category
    if is_known(pc) and not is_winning(pc):
        rejections.append(Rejection(ReasonCode.NOT_WINNING, pc, i))
    elif is_winning(pc) and not is_unconditional_win(pc):  # a frustrated win
        rejections.append(Rejection(ReasonCode.WIN_FRUSTRATED, pc, i))

    spoiler = next(
        (
            m
            for m in moves
            if m.uci != played.uci and competes_for_win(m.category, capture_seen)
        ),
        None,
    )
    if spoiler is not None:
        code = ReasonCode.NOT_UNIQUE if is_unconditional_win(pc) else ReasonCode.WRONG_MOVE
        rejections.append(Rejection(code, spoiler.category, i))
    return rejections


def _verify_equality(
    i: int, played: Move, moves: Sequence[Move], capture_seen: bool
) -> list[Rejection]:
    """Equality puzzle: the played move must be the unique unconditional drawing move."""
    rejections: list[Rejection] = []
    pc = played.category

    winner = next((m for m in moves if is_unconditional_win(m.category)), None)
    if winner is not None:
        rejections.append(Rejection(ReasonCode.EQUALITY_HAS_WIN, winner.category, i))

    if is_known(pc) and not is_unconditional_draw(pc) and not is_unconditional_win(pc):
        rejections.append(Rejection(ReasonCode.EQUALITY_NOT_DRAW, pc, i))

    spoiler = next(
        (
            m
            for m in moves
            if m.uci != played.uci and holds_draw(m.category, capture_seen)
        ),
        None,
    )
    if spoiler is not None:
        code = ReasonCode.NOT_UNIQUE if holds_draw(pc, capture_seen) else ReasonCode.WRONG_MOVE
        rejections.append(Rejection(code, spoiler.category, i))
    return rejections


def _verify_mate(
    i: int, response: TablebaseResponse, mate: MateRequirement
) -> list[Rejection]:
    """For mateInX, when DTM is known, check the mate countdown at this ply.

    X counts winning-side moves from the start; at the j-th puzzler move the
    remaining count is ``X - j + 1`` and the position's DTM (in plies) is
    ``2 * remaining - 1``. For an :class:`ExactMate` the DTM must equal that
    value; for an :class:`AtLeastMate` (mateIn5 = "5 or more", and 4-or-more at
    the next move, etc.) it must be at least that value.
    """
    dtm = response.dtm
    if dtm is None:
        return []
    j = (i + 1) // 2  # puzzler-move ordinal: Moves[1]->1, Moves[3]->2, ...
    expected = 2 * (mate.moves - j + 1) - 1
    ok = dtm == expected if isinstance(mate, ExactMate) else dtm >= expected
    if not ok:
        return [Rejection(ReasonCode.DTM_MISMATCH, dtm, i)]
    return []
