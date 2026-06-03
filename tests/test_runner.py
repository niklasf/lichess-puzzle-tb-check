import tempfile
import unittest
from pathlib import Path

from puzzle_tb.runner import InputError, expand_puzzle, format_rejection, read_rows
from puzzle_tb.schema import Category
from puzzle_tb.verify import MalformedPuzzle, ReasonCode, Rejection


def _write(text: str) -> str:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8", newline=""
    )
    handle.write(text)
    handle.close()
    return handle.name


class ReadRowsTest(unittest.TestCase):
    def test_extra_and_reordered_columns(self) -> None:
        # Columns reordered, with extra columns we don't use.
        path = _write(
            "Rating,Themes,PuzzleId,Extra,Moves,FEN,OpeningTags\n"
            "1500,mateIn2 endgame,abc,junk,e2e4 e7e5,8/8/8/8/8/8/8/8 w - - 0 1,\n"
        )
        try:
            rows = list(read_rows(path))
        finally:
            Path(path).unlink()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["PuzzleId"], "abc")
        self.assertEqual(row["Moves"], "e2e4 e7e5")
        self.assertEqual(row["Themes"], "mateIn2 endgame")
        self.assertEqual(row["FEN"], "8/8/8/8/8/8/8/8 w - - 0 1")

    def test_missing_required_column_raises(self) -> None:
        path = _write("PuzzleId,FEN,Themes\nabc,8/8/8/8/8/8/8/8 w - - 0 1,endgame\n")
        try:
            with self.assertRaises(InputError):
                list(read_rows(path))
        finally:
            Path(path).unlink()


class ExpandPuzzleTest(unittest.TestCase):
    def test_illegal_move_is_fatal(self) -> None:
        with self.assertRaises(MalformedPuzzle):
            expand_puzzle("8/8/4k3/8/8/4K3/8/4Q3 b - - 0 1", ["e6e6"])


class FormatRejectionTest(unittest.TestCase):
    def test_link_fen_and_comment(self) -> None:
        line = format_rejection(
            "xyz",
            "8/8/4k3/8/8/4K3/8/4Q3 b - - 0 1",
            ["e6d6", "e3e4"],
            [Rejection(ReasonCode.NOT_UNIQUE, Category.LOSS, 1)],
        )
        self.assertEqual(
            line,
            'https://lichess.org/training/xyz: '
            '[FEN "8/8/4k3/8/8/4K3/8/4Q3 b - - 0 1"] 1... Kd6 2. Ke4 { NOT_UNIQUE:loss@1 }',
        )

    def test_comment_on_later_move(self) -> None:
        line = format_rejection(
            "p",
            "8/8/8/8/4k3/8/8/R3K3 b - - 0 1",
            ["e4e5", "e1e2", "e5e6", "e2e3"],
            [Rejection(ReasonCode.NOT_WINNING, Category.DRAW, 3)],
        )
        self.assertTrue(line.endswith("3. Ke3 { NOT_WINNING:draw@3 }"), line)


if __name__ == "__main__":
    unittest.main()
