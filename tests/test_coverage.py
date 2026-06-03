import unittest

import chess

from puzzle_tb_check import coverage


class DirectlyCoveredTest(unittest.TestCase):
    def test_op1_rs_vectors(self) -> None:
        # Ported from lila-tablebase src/op1.rs test_use_op1.
        cases = [
            ("R7/8/8/8/7q/2K1B2p/7P/2Bk4 w - - 0 1", True),  # 8-piece op1
            ("QN4n1/6r1/3k4/8/b2K4/8/8/8 b - - 0 1", True),  # 7-piece syzygy
            ("4k3/4p3/8/8/8/8/3PPPPP/4K3 w - - 0 1", False),  # 8-piece, weak lone pawn
        ]
        for fen, expected in cases:
            with self.subTest(fen=fen):
                self.assertEqual(coverage.directly_covered(chess.Board(fen)), expected)

    def test_more_than_nine_not_covered(self) -> None:
        self.assertFalse(coverage.directly_covered(chess.Board()))

    def test_castling_rights_not_covered(self) -> None:
        # A <=7 position would be covered, but castling rights make it unrepresentable.
        board = chess.Board("4k2r/8/8/8/8/8/8/4K3 b k - 0 1")
        self.assertFalse(coverage.directly_covered(board))


class MoreThanLonePawnTest(unittest.TestCase):
    def test_lone_pawn_is_not_more(self) -> None:
        board = chess.Board("4k3/4p3/8/8/8/8/3PPPPP/4K3 w - - 0 1")
        self.assertFalse(coverage.more_than_lone_pawn(board, chess.BLACK))
        self.assertTrue(coverage.more_than_lone_pawn(board, chess.WHITE))


class VerifiableTest(unittest.TestCase):
    def test_directly_covered_is_verifiable(self) -> None:
        self.assertTrue(coverage.verifiable(chess.Board("4k3/8/8/8/8/8/8/Q3K3 w - - 0 1")))

    def test_nine_piece_capture_into_op1(self) -> None:
        # 9 pieces; Kxb3 captures into the 8-piece op1 position above.
        board = chess.Board("R7/8/8/8/7q/1nK1B2p/7P/2Bk4 w - - 0 1")
        self.assertFalse(coverage.directly_covered(board))
        self.assertTrue(coverage.verifiable(board))

    def test_eight_piece_capture_into_seven(self) -> None:
        # 8 pieces, no op1, but Rxd4 captures into a 7-piece position.
        board = chess.Board("1n2k3/8/b7/8/3r4/3R4/8/4KBN1 w - - 0 1")
        self.assertTrue(coverage.verifiable(board))

    def test_eight_piece_no_capture_not_verifiable(self) -> None:
        board = chess.Board("rnb1k3/8/8/8/8/8/8/1NB1K2R w - - 0 1")
        self.assertFalse(coverage.verifiable(board))

    def test_too_many_pieces_not_verifiable(self) -> None:
        self.assertFalse(coverage.verifiable(chess.Board()))


class CheapGateTest(unittest.TestCase):
    def test_rejects_when_minimum_exceeds_nine(self) -> None:
        # Opening position (32 pieces) with a few moves can never reach <=9.
        self.assertFalse(coverage.cheap_gate(chess.STARTING_FEN, 6))

    def test_accepts_reachable(self) -> None:
        # 12 pieces, 4 moves -> bottoms out at 8 <= 9.
        self.assertTrue(coverage.cheap_gate("4k3/8/8/3pppp1/3PPPP1/8/8/4K3 w - - 0 1", 4))

    def test_accepts_small_position(self) -> None:
        self.assertTrue(coverage.cheap_gate("4k3/8/8/8/8/8/8/Q3K3 w - - 0 1", 6))


if __name__ == "__main__":
    unittest.main()
