"""Precise-category predicates from the puzzler's perspective.

A move's :class:`~puzzle_tb.schema.Category` describes the resulting position
from the *opponent's* perspective, so ``loss`` means the opponent is lost, i.e.
*we* win. We never collapse the ambiguous categories into a single "fuzzy"
bucket; rejection reasons record the exact category.
"""

from __future__ import annotations

from .schema import Category

#: Opponent categories under which we might be winning.
_WINNING = frozenset(
    {Category.LOSS, Category.BLESSED_LOSS, Category.MAYBE_LOSS, Category.SYZYGY_LOSS}
)


def is_known(category: Category) -> bool:
    """Whether the tablebase reported any information for this move."""
    return category is not Category.UNKNOWN


def is_clean_win(category: Category) -> bool:
    """Whether we win unambiguously (opponent cleanly lost)."""
    return category is Category.LOSS


def is_winning(category: Category) -> bool:
    """Whether we might win (clean or 50-move-rule ambiguous)."""
    return category in _WINNING


def is_clean_draw(category: Category) -> bool:
    """Whether the position is unambiguously a draw."""
    return category is Category.DRAW


def is_holding(category: Category) -> bool:
    """Whether we might hold at least a draw (spoils an ``equality`` puzzle).

    True for everything known except a clean loss for us (opponent ``win``).
    ``cursed-win``/``maybe-win``/``syzygy-win`` are losing for us but might still
    hold a draw under the 50-move rule, so they count.
    """
    return category is not Category.UNKNOWN and category is not Category.WIN
