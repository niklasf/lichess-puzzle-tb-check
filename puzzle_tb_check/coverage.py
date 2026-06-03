"""Tablebase coverage decisions.

Ported from lila-tablebase ``src/op1.rs`` and extended with Syzygy (<=7) and
capture-boundary positions. Used purely to avoid wasting API calls on positions
the tablebase cannot evaluate; the HTTP API remains the source of truth.
"""

from __future__ import annotations

import chess


def piece_count(board: chess.Board) -> int:
    """Number of pieces on the board."""
    return chess.popcount(board.occupied)


def is_op1(board: chess.Board) -> bool:
    """Whether some white pawn has a black pawn ahead of it on the same file.

    Mirrors ``op1.rs::is_op1``: the union of squares directly in front of white
    pawns (same file, any number of ranks up) intersected with black pawns.
    """
    white_pawns = board.pawns & board.occupied_co[chess.WHITE]
    paths = (
        (white_pawns << 8)
        | (white_pawns << 16)
        | (white_pawns << 24)
        | (white_pawns << 32)
        | (white_pawns << 40)
    )
    black_pawns = board.pawns & board.occupied_co[chess.BLACK]
    return bool(paths & black_pawns)


def more_than_lone_pawn(board: chess.Board, color: chess.Color) -> bool:
    """Whether ``color`` has more than just a king and a single pawn.

    Mirrors ``op1.rs::more_than_lone_pawn``.
    """
    pawns = board.pawns & board.occupied_co[color]
    if chess.popcount(pawns) > 1:
        return True
    others = board.occupied_co[color] & ~board.kings & ~board.pawns
    return bool(others)


def directly_covered(board: chess.Board) -> bool:
    """Whether the position itself is in the tablebase (<=7 Syzygy, or 8-piece op1).

    Mirrors ``op1.rs::use_op1`` extended to Syzygy. Castling rights make a
    position unrepresentable by the tablebases, so it is never directly covered.
    """
    if board.castling_rights:
        return False
    count = piece_count(board)
    if count <= 7:
        return True
    if count == 8:
        return (
            is_op1(board)
            and more_than_lone_pawn(board, chess.WHITE)
            and more_than_lone_pawn(board, chess.BLACK)
        )
    return False


def verifiable(board: chess.Board) -> bool:
    """Whether probing this position yields usable (known) evidence.

    Either directly covered, or a <=9-piece boundary position with a legal move
    into directly-covered territory (a 9->8-op1 capture, or an 8->7 capture --
    since 7-piece is always covered). lila-tablebase reports known categories for
    such moves even when the root position itself is ``unknown``, so the played
    move can still be evaluated.
    """
    if directly_covered(board):
        return True
    if piece_count(board) > 9:
        return False
    for move in list(board.legal_moves):
        board.push(move)
        try:
            if directly_covered(board):
                return True
        finally:
            board.pop()
    return False


def cheap_gate(fen: str, num_moves: int) -> bool:
    """Fast pre-filter without parsing: can the puzzle ever reach <=9 pieces?

    Each move captures at most one piece, so the puzzle bottoms out at ``n - m``
    pieces, where ``n`` is the starting piece count and ``m`` the number of moves.
    Counts piece letters directly in the FEN board field.
    """
    board_field = fen.split(" ", 1)[0]
    n = sum(1 for c in board_field if c.isalpha())
    return n - num_moves <= 9
