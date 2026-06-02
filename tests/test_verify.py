import unittest
from collections.abc import Sequence

from puzzle_tb.schema import Category, Move, TablebaseResponse
from puzzle_tb.verify import PuzzleThemes, PuzzlerPosition, verify_puzzle


def mv(uci: str, category: Category, *, checkmate: bool = False) -> Move:
    return Move(
        uci=uci, san=uci, category=category, dtm=None, dtz=None, checkmate=checkmate, stalemate=False
    )


def position(
    move_index: int,
    played: str,
    moves: Sequence[Move],
    *,
    dtm: int | None = None,
    capture_seen: bool = False,
) -> PuzzlerPosition:
    response = TablebaseResponse(
        category=Category.UNKNOWN, dtm=dtm, dtz=None, checkmate=False, stalemate=False, moves=tuple(moves)
    )
    return PuzzlerPosition(
        move_index=move_index, played_uci=played, response=response, capture_seen=capture_seen
    )


def reasons(
    pos: PuzzlerPosition, *, equality: bool = False, mate_in: int | None = None
) -> list[str]:
    return verify_puzzle([pos], PuzzleThemes(equality=equality, mate_in=mate_in))


class ThemesParseTest(unittest.TestCase):
    def test_parse(self) -> None:
        themes = PuzzleThemes.parse("crushing mateIn3 long endgame")
        self.assertFalse(themes.equality)
        self.assertEqual(themes.mate_in, 3)

    def test_equality(self) -> None:
        themes = PuzzleThemes.parse("equality endgame")
        self.assertTrue(themes.equality)
        self.assertIsNone(themes.mate_in)


class NormalPuzzleTest(unittest.TestCase):
    def test_clean_unique_win_accepted(self) -> None:
        pos = position(1, "a1a8", [mv("a1a8", Category.LOSS), mv("a1a2", Category.DRAW)])
        self.assertEqual(reasons(pos), [])

    def test_two_known_winners_not_unique(self) -> None:
        pos = position(
            1, "a1a8", [mv("a1a8", Category.LOSS), mv("a1b8", Category.LOSS), mv("a1a2", Category.DRAW)]
        )
        self.assertEqual(reasons(pos), ["NOT_UNIQUE:loss@1"])

    def test_maybe_loss_is_clean_win(self) -> None:
        # maybe-win/maybe-loss now count as clean: accepted when unique.
        pos = position(1, "a1a8", [mv("a1a8", Category.MAYBE_LOSS), mv("a1a2", Category.DRAW)])
        self.assertEqual(reasons(pos), [])

    def test_syzygy_loss_is_clean_win(self) -> None:
        pos = position(1, "a1a8", [mv("a1a8", Category.SYZYGY_LOSS), mv("a1a2", Category.DRAW)])
        self.assertEqual(reasons(pos), [])

    def test_cursed_win_played_not_clean(self) -> None:
        # A cursed win (move category blessed-loss) is never clean for the played move.
        pos = position(1, "a1a8", [mv("a1a8", Category.BLESSED_LOSS), mv("a1a2", Category.DRAW)])
        self.assertEqual(reasons(pos), ["WIN_NOT_CLEAN:blessed-loss@1"])

    def test_wrong_move_when_played_draws(self) -> None:
        pos = position(1, "a1a2", [mv("a1a8", Category.LOSS), mv("a1a2", Category.DRAW)])
        self.assertEqual(reasons(pos), ["NOT_WINNING:draw@1", "WRONG_MOVE:loss@1"])

    def test_played_cursed_win_not_winning(self) -> None:
        pos = position(1, "a1a2", [mv("a1a2", Category.CURSED_WIN)])
        self.assertEqual(reasons(pos), ["NOT_WINNING:cursed-win@1"])

    def test_strongest_spoiler_reported(self) -> None:
        # Moves are best-first: the clean loss is the strongest winning alternative.
        pos = position(
            1,
            "a1a8",
            [mv("a1a8", Category.LOSS), mv("a1b8", Category.LOSS), mv("a1c8", Category.MAYBE_LOSS)],
        )
        self.assertEqual(reasons(pos), ["NOT_UNIQUE:loss@1"])


class CheckmateExceptionTest(unittest.TestCase):
    def test_immediate_mate_ok_despite_other_mates(self) -> None:
        pos = position(
            1,
            "a1a8",
            [mv("a1a8", Category.LOSS, checkmate=True), mv("a1b8", Category.LOSS, checkmate=True)],
        )
        self.assertEqual(reasons(pos), [])

    def test_immediate_mate_ok_despite_longer_wins(self) -> None:
        pos = position(
            1, "a1a8", [mv("a1a8", Category.LOSS, checkmate=True), mv("a1b8", Category.LOSS)]
        )
        self.assertEqual(reasons(pos), [])

    def test_non_mate_still_checked_for_uniqueness(self) -> None:
        pos = position(1, "a1a8", [mv("a1a8", Category.LOSS), mv("a1b8", Category.LOSS)])
        self.assertEqual(reasons(pos), ["NOT_UNIQUE:loss@1"])


class CaptureRuleTest(unittest.TestCase):
    def test_cursed_alternative_competes_before_capture(self) -> None:
        # Before a capture, a cursed-win alternative (blessed-loss) refutes uniqueness.
        pos = position(
            1, "a1a8", [mv("a1a8", Category.LOSS), mv("a1b8", Category.BLESSED_LOSS)], capture_seen=False
        )
        self.assertEqual(reasons(pos), ["NOT_UNIQUE:blessed-loss@1"])

    def test_cursed_alternative_ignored_after_capture(self) -> None:
        # After a capture, a cursed-win alternative no longer refutes -> unique, accepted.
        pos = position(
            1, "a1a8", [mv("a1a8", Category.LOSS), mv("a1b8", Category.BLESSED_LOSS)], capture_seen=True
        )
        self.assertEqual(reasons(pos), [])

    def test_clean_alternative_competes_after_capture(self) -> None:
        # A clean (maybe-loss) alternative still refutes after a capture.
        pos = position(
            1, "a1a8", [mv("a1a8", Category.LOSS), mv("a1b8", Category.MAYBE_LOSS)], capture_seen=True
        )
        self.assertEqual(reasons(pos), ["NOT_UNIQUE:maybe-loss@1"])

    def test_played_cursed_win_unique_after_capture(self) -> None:
        # Played cursed win is still flagged not-clean, but uniqueness holds post-capture.
        pos = position(
            1, "a1a8", [mv("a1a8", Category.BLESSED_LOSS), mv("a1b8", Category.DRAW)], capture_seen=True
        )
        self.assertEqual(reasons(pos), ["WIN_NOT_CLEAN:blessed-loss@1"])

    def test_equality_cursed_loss_holds_only_after_capture(self) -> None:
        # cursed-win (we cursed-lose) holds a draw only after a capture.
        before = position(
            1, "a1a2", [mv("a1a2", Category.DRAW), mv("a1b2", Category.CURSED_WIN)], capture_seen=False
        )
        self.assertEqual(reasons(before, equality=True), [])
        after = position(
            1, "a1a2", [mv("a1a2", Category.DRAW), mv("a1b2", Category.CURSED_WIN)], capture_seen=True
        )
        self.assertEqual(reasons(after, equality=True), ["NOT_UNIQUE:cursed-win@1"])


class UnknownHandlingTest(unittest.TestCase):
    def test_unknown_played_no_spoiler_accepted(self) -> None:
        pos = position(1, "a1a8", [mv("a1a8", Category.UNKNOWN), mv("a1a2", Category.DRAW)])
        self.assertEqual(reasons(pos), [])

    def test_unknown_moves_never_reject(self) -> None:
        pos = position(1, "a1a8", [mv("a1a8", Category.LOSS), mv("zzzz", Category.UNKNOWN)])
        self.assertEqual(reasons(pos), [])

    def test_known_winner_beside_unknown_played_rejects(self) -> None:
        pos = position(1, "zzzz", [mv("a1a8", Category.LOSS), mv("zzzz", Category.UNKNOWN)])
        self.assertEqual(reasons(pos), ["WRONG_MOVE:loss@1"])

    def test_played_move_not_listed_is_malformed(self) -> None:
        pos = position(1, "h1h8", [mv("a1a8", Category.LOSS)])
        self.assertEqual(reasons(pos), ["MALFORMED@1"])


class EqualityPuzzleTest(unittest.TestCase):
    def test_clean_unique_draw_accepted(self) -> None:
        pos = position(1, "a1a2", [mv("a1a2", Category.DRAW), mv("a1a8", Category.WIN)])
        self.assertEqual(reasons(pos, equality=True), [])

    def test_has_win(self) -> None:
        pos = position(1, "a1a2", [mv("a1a2", Category.DRAW), mv("a1a8", Category.LOSS)])
        self.assertIn("EQUALITY_HAS_WIN:loss@1", reasons(pos, equality=True))

    def test_not_unique_draw(self) -> None:
        pos = position(
            1, "a1a2", [mv("a1a2", Category.DRAW), mv("a1b2", Category.DRAW), mv("a1a8", Category.WIN)]
        )
        self.assertEqual(reasons(pos, equality=True), ["NOT_UNIQUE:draw@1"])

    def test_played_loses(self) -> None:
        pos = position(1, "a1a2", [mv("a1a2", Category.WIN), mv("a1b2", Category.WIN)])
        self.assertEqual(reasons(pos, equality=True), ["EQUALITY_NOT_DRAW:win@1"])


class MateTest(unittest.TestCase):
    def test_dtm_match(self) -> None:
        pos = position(1, "a1a8", [mv("a1a8", Category.LOSS)], dtm=3)
        self.assertEqual(reasons(pos, mate_in=2), [])

    def test_dtm_mismatch(self) -> None:
        pos = position(1, "a1a8", [mv("a1a8", Category.LOSS)], dtm=5)
        self.assertEqual(reasons(pos, mate_in=2), ["DTM_MISMATCH:5@1"])

    def test_dtm_countdown_on_tail(self) -> None:
        # Second puzzler move (index 3) of a mate-in-2: remaining 1 ply, dtm == 1.
        pos = position(3, "a1a8", [mv("a1a8", Category.LOSS)], dtm=1)
        self.assertEqual(reasons(pos, mate_in=2), [])

    def test_dtm_absent_skips_check(self) -> None:
        pos = position(1, "a1a8", [mv("a1a8", Category.LOSS)], dtm=None)
        self.assertEqual(reasons(pos, mate_in=2), [])


if __name__ == "__main__":
    unittest.main()
