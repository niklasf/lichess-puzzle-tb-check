"""Precise-category predicates from the puzzler's perspective.

A move's :class:`~puzzle_tb.schema.Category` describes the resulting position from
the *opponent's* perspective, so ``loss`` means the opponent is lost, i.e. *we*
win. We keep the precise category in rejection reasons and never collapse the
distinct ambiguous categories into a single "fuzzy" notion.

Cleanness and 50-move-rule handling (per project policy):

- ``maybe-win``/``syzygy-win`` and their losing variants ``maybe-loss``/
  ``syzygy-loss`` are treated as **clean** wins/losses (the WDL is known).
- ``cursed-win``/``blessed-loss`` are the genuinely 50-move-rule-distorted
  results. A cursed win is never "clean" for the *played* move. For
  *uniqueness*, a cursed result still competes until the puzzler has seen a
  capture; afterwards it collapses to a draw and no longer refutes.
"""

from __future__ import annotations

import enum

from .schema import Category

#: Move categories under which we win, unambiguously (no 50-move-rule caveat).
_CLEAN_WIN = frozenset({Category.LOSS, Category.MAYBE_LOSS, Category.SYZYGY_LOSS})
#: Move categories under which we lose, unambiguously.
_CLEAN_LOSS = frozenset({Category.WIN, Category.MAYBE_WIN, Category.SYZYGY_WIN})


class Outcome(enum.Enum):
    """Effective result for us once the 50-move rule is applied (see :func:`effective`)."""

    WIN = enum.auto()
    DRAW = enum.auto()
    LOSS = enum.auto()
    UNKNOWN = enum.auto()


def is_known(category: Category) -> bool:
    """Whether the tablebase reported any information for this move."""
    return category is not Category.UNKNOWN


def is_clean_win(category: Category) -> bool:
    """Whether we win unambiguously -- required for the played move to count."""
    return category in _CLEAN_WIN


def is_clean_draw(category: Category) -> bool:
    """Whether the position is unambiguously a draw."""
    return category is Category.DRAW


def is_winning(category: Category) -> bool:
    """Whether we win ignoring the 50-move rule (clean win or a cursed win)."""
    return category in _CLEAN_WIN or category is Category.BLESSED_LOSS


def effective(category: Category, capture_seen: bool) -> Outcome:
    """Our effective outcome, collapsing cursed results to draws after a capture.

    Before a capture has been seen, a cursed result keeps its raw win/loss value;
    after a capture the 50-move rule has had a chance to take effect, so a cursed
    win/loss becomes a draw.
    """
    if category in _CLEAN_WIN:
        return Outcome.WIN
    if category in _CLEAN_LOSS:
        return Outcome.LOSS
    if category is Category.DRAW:
        return Outcome.DRAW
    if category is Category.BLESSED_LOSS:  # we win, but cursed
        return Outcome.DRAW if capture_seen else Outcome.WIN
    if category is Category.CURSED_WIN:  # we lose, but cursed (saved by 50-move rule)
        return Outcome.DRAW if capture_seen else Outcome.LOSS
    return Outcome.UNKNOWN


def competes_for_win(category: Category, capture_seen: bool) -> bool:
    """Whether an alternative move is winning enough to spoil a unique win."""
    return effective(category, capture_seen) is Outcome.WIN


def holds_draw(category: Category, capture_seen: bool) -> bool:
    """Whether a move holds at least a draw (spoils a unique ``equality`` draw)."""
    return effective(category, capture_seen) in (Outcome.WIN, Outcome.DRAW)
