"""Precise-category predicates from the puzzler's perspective.

A move's :class:`~puzzle_tb.schema.Category` describes the resulting position from
the *opponent's* perspective, so ``loss`` means the opponent is lost, i.e. *we*
win. We keep the precise category in rejection reasons and never collapse the
distinct ambiguous categories into a single notion.

Terminology and 50-move-rule handling (per project policy):

- ``maybe-win``/``syzygy-win`` and their losing variants ``maybe-loss``/
  ``syzygy-loss`` are treated as **unconditional** wins/losses (the WDL is known).
- ``cursed-win``/``blessed-loss`` are **frustrated** wins/losses: real wins/losses
  that the 50-move rule can turn into draws. A frustrated win is never an
  unconditional win for the *played* move. For *uniqueness*, a frustrated result
  still competes until the puzzler has seen a capture; afterwards it no longer
  refutes (see :func:`effective`).
"""

from __future__ import annotations

import enum

from .schema import Category

#: Move categories under which we win, unconditionally (no 50-move-rule caveat).
_UNCONDITIONAL_WIN = frozenset({Category.LOSS, Category.MAYBE_LOSS, Category.SYZYGY_LOSS})
#: Move categories under which we lose, unconditionally.
_UNCONDITIONAL_LOSS = frozenset({Category.WIN, Category.MAYBE_WIN, Category.SYZYGY_WIN})


class Outcome(enum.Enum):
    """Effective result for us from the puzzler's perspective (see :func:`effective`)."""

    WIN = enum.auto()
    DRAW = enum.auto()
    LOSS = enum.auto()
    UNKNOWN = enum.auto()


def is_known(category: Category) -> bool:
    """Whether the tablebase reported any information for this move."""
    return category is not Category.UNKNOWN


def is_unconditional_win(category: Category) -> bool:
    """Whether we win unconditionally -- required for the played move to count."""
    return category in _UNCONDITIONAL_WIN


def is_unconditional_draw(category: Category) -> bool:
    """Whether the position is an unconditional draw."""
    return category is Category.DRAW


def is_winning(category: Category) -> bool:
    """Whether we win at all (unconditional, or a frustrated/cursed win)."""
    return category in _UNCONDITIONAL_WIN or category is Category.BLESSED_LOSS


def effective(category: Category, capture_seen: bool) -> Outcome:
    """Our effective outcome from what the puzzler can see on the board.

    The 50-move counter is not visible on the board, so before the puzzler has
    seen a capture they cannot know it -- a frustrated win/loss can't be assumed
    frustrated and is taken at its raw win/loss value. Once a capture has reset
    the counter (a state the puzzler can account for), the frustration applies and
    the result is a draw.
    """
    if category in _UNCONDITIONAL_WIN:
        return Outcome.WIN
    if category in _UNCONDITIONAL_LOSS:
        return Outcome.LOSS
    if category is Category.DRAW:
        return Outcome.DRAW
    if category is Category.BLESSED_LOSS:  # we win, but frustrated
        return Outcome.DRAW if capture_seen else Outcome.WIN
    if category is Category.CURSED_WIN:  # we lose, but frustrated (saved by 50-move rule)
        return Outcome.DRAW if capture_seen else Outcome.LOSS
    return Outcome.UNKNOWN


def competes_for_win(category: Category, capture_seen: bool) -> bool:
    """Whether an alternative move is winning enough to spoil a unique win."""
    return effective(category, capture_seen) is Outcome.WIN


def holds_draw(category: Category, capture_seen: bool) -> bool:
    """Whether a move holds at least a draw (spoils a unique ``equality`` draw)."""
    return effective(category, capture_seen) in (Outcome.WIN, Outcome.DRAW)
