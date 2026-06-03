import tempfile
import unittest
from pathlib import Path

from puzzle_tb_check.runner import (
    InputError,
    ResultWriter,
    expand_puzzle,
    pgn_snippet,
    read_rows,
)
from puzzle_tb_check.schema import Category
from puzzle_tb_check.verify import MalformedPuzzle, ReasonCode, Rejection


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


class PgnSnippetTest(unittest.TestCase):
    def test_fen_and_comment(self) -> None:
        snippet = pgn_snippet(
            "8/8/4k3/8/8/4K3/8/4Q3 b - - 0 1",
            ["e6d6", "e3e4"],
            [Rejection(ReasonCode.NOT_UNIQUE, Category.LOSS, 1)],
        )
        self.assertEqual(
            snippet,
            '[FEN "8/8/4k3/8/8/4K3/8/4Q3 b - - 0 1"] 1... Kd6 2. Ke4 { NOT_UNIQUE:loss@1 }',
        )

    def test_comment_on_later_move(self) -> None:
        snippet = pgn_snippet(
            "8/8/8/8/4k3/8/8/R3K3 b - - 0 1",
            ["e4e5", "e1e2", "e5e6", "e2e3"],
            [Rejection(ReasonCode.NOT_WINNING, Category.DRAW, 3)],
        )
        self.assertTrue(snippet.endswith("3. Ke3 { NOT_WINNING:draw@3 }"), snippet)


class ResultWriterTest(unittest.TestCase):
    def test_three_unquoted_columns_cut_friendly(self) -> None:
        path = _write("")
        pgn = '[FEN "8/8/4k3/8/8/4K3/8/4Q3 b - - 0 1"] 1... Kd6 { NOT_UNIQUE:loss@1 }'
        cli = "puzzle issue abc puzzle-tb-check:deadbeef:NOT_UNIQUE:loss@1"
        try:
            with ResultWriter(path) as writer:
                writer.write("abc", pgn, cli)
                writer.write("ok1", "", "")
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        finally:
            Path(path).unlink()
        self.assertEqual(lines[0], "PuzzleId,PGN,CliCommand")
        # No csv quoting added around the FEN's double-quotes; cut -f3 yields CliCommand.
        self.assertEqual(lines[1], f"abc,{pgn},{cli}")
        self.assertEqual(lines[1].split(",")[-1], cli)
        self.assertEqual(lines[2], "ok1,,")


if __name__ == "__main__":
    unittest.main()
