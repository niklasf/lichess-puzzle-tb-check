"""Stream the puzzle CSV, probe the tablebase, and write per-puzzle verdicts.

Resumable: existing ``PuzzleId``s in the output CSV are skipped. Interruptible:
the output is flushed after every row, so at most the in-flight puzzles are lost.
On an unrecoverable tablebase error the run stops and reports rather than
recording unverified puzzles.
"""

from __future__ import annotations

import asyncio
import compression.zstd as zstd
import csv
import os
import secrets
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import IO

import chess
import chess.pgn

from . import coverage
from .progress import Progress
from .tablebase import FatalTablebaseError, TablebaseClient
from .verify import MalformedPuzzle, PuzzleThemes, PuzzlerPosition, Rejection, verify_puzzle


# The only input columns we depend on; any others (Rating, GameUrl, ...) are
# ignored, and column order does not matter (rows are read by name).
REQUIRED_COLUMNS = ("PuzzleId", "FEN", "Moves", "Themes")


class InputError(Exception):
    """The input CSV is unusable (e.g. missing a required column)."""


@dataclass(frozen=True, slots=True)
class Config:
    """Run configuration, populated from the CLI."""

    input_path: str
    output_path: str
    endpoint: str
    max_rps: float | None
    concurrency: int
    timeout: float
    retries: int
    limit: int | None


@dataclass(slots=True)
class _Puzzle:
    puzzle_id: str
    fen: str
    moves: list[str]
    themes: PuzzleThemes
    # (move index, played uci, fen, capture seen earlier in the line)
    positions: list[tuple[int, str, str, bool]]


def _open_text(path: str) -> IO[str]:
    if path.endswith(".zst"):
        return zstd.open(path, "rt", encoding="utf-8", newline="")
    return open(path, "rt", encoding="utf-8", newline="")


def count_rows(path: str) -> int:
    """Count data rows (excluding the header) by counting newlines."""
    opener = zstd.open if path.endswith(".zst") else open
    newlines = 0
    with opener(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            newlines += chunk.count(b"\n")
    return max(0, newlines - 1)


def read_rows(path: str) -> Iterator[dict[str, str]]:
    """Yield puzzle rows as dicts keyed by CSV column name.

    Robust to extra columns and column reordering; only :data:`REQUIRED_COLUMNS`
    are used. Raises :class:`InputError` if a required column is absent, so
    callers can thereafter assume those keys are present.
    """
    with _open_text(path) as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in set(reader.fieldnames or ())]
        if missing:
            raise InputError(f"input CSV is missing required column(s): {', '.join(missing)}")
        yield from reader


def load_done(path: str) -> set[str]:
    """Read already-verified ``PuzzleId``s from the output CSV, if it exists."""
    if not os.path.exists(path):
        return set()
    done: set[str] = set()
    with open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return done
        for row in reader:
            if row:
                done.add(row[0])
    return done


def expand_puzzle(fen: str, moves: list[str]) -> list[tuple[int, str, str, bool]]:
    """Return the verifiable puzzler positions of a puzzle.

    Each position is ``(move_index, played_uci, fen, capture_seen)`` for a
    puzzler-to-move position that is :func:`coverage.verifiable`. ``capture_seen``
    is whether any earlier move in the line (indices < move_index) was a capture.
    The opponent's setup move (index 0) and responses (even indices) are applied
    but not verified. An illegal move raises :class:`MalformedPuzzle` (fatal).
    """
    board = chess.Board(fen)
    positions: list[tuple[int, str, str, bool]] = []
    capture_seen = False
    for index, uci in enumerate(moves):
        if index >= 1 and index % 2 == 1 and coverage.verifiable(board):
            positions.append((index, uci, board.fen(), capture_seen))
        try:
            move = board.parse_uci(uci)
        except (ValueError, AssertionError) as exc:
            raise MalformedPuzzle(f"illegal move {uci!r} (move {index}) in {fen!r}") from exc
        if board.is_capture(move):
            capture_seen = True
        board.push(move)
    return positions


def pgn_snippet(fen: str, moves: list[str], rejections: list[Rejection]) -> str:
    """A ``[FEN "..."] <SAN movetext>`` snippet for analysis.

    Rejections are attached as ``{ ... }`` comments on the move they refer to, e.g.::

        [FEN "..."] 45...Re1+ 46. Nf3 { NOT_UNIQUE:loss@5 } 46... Nf6
    """
    by_index: dict[int, list[Rejection]] = {}
    for rejection in rejections:
        by_index.setdefault(rejection.move_index, []).append(rejection)

    game = chess.pgn.Game()
    game.setup(chess.Board(fen))
    node: chess.pgn.GameNode = game
    attached: set[int] = set()
    for index, uci in enumerate(moves):
        try:
            move = node.board().parse_uci(uci)
        except ValueError:
            break
        node = node.add_main_variation(move)
        if index in by_index:
            node.comment = " ".join(str(r) for r in by_index[index])
            attached.add(index)

    leftover = [r for index, rs in by_index.items() if index not in attached for r in rs]
    if leftover:
        node.comment = " ".join(filter(None, [node.comment, *(str(r) for r in leftover)]))

    exporter = chess.pgn.StringExporter(columns=None, headers=False, variations=False, comments=True)
    movetext = game.accept(exporter).strip()
    if movetext.endswith("*"):  # drop the trailing PGN result token
        movetext = movetext[:-1].strip()
    return f'[FEN "{fen}"] {movetext}'


class ResultWriter(AbstractContextManager["ResultWriter"]):
    """Appends ``PuzzleId,PGN,CliCommand`` rows, flushing after each write.

    Fields are comma- and newline-free by construction, so rows are joined plainly
    rather than via ``csv`` -- this keeps the file ``cut``-friendly and avoids
    quoting the double-quotes inside the PGN's FEN tag. ``pgn`` and ``cli_command``
    are empty for valid puzzles.
    """

    def __init__(self, path: str) -> None:
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        self._handle = open(path, "at", encoding="utf-8", newline="")
        if is_new:
            self._handle.write("PuzzleId,PGN,CliCommand\n")
            self._handle.flush()

    def write(self, puzzle_id: str, pgn: str, cli_command: str) -> None:
        self._handle.write(f"{puzzle_id},{pgn},{cli_command}\n")
        self._handle.flush()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._handle.close()


async def _process_puzzle(
    client: TablebaseClient,
    puzzle: _Puzzle,
    writer: ResultWriter,
    progress: Progress,
    semaphore: asyncio.Semaphore,
    uid: str,
) -> None:
    try:
        responses = await asyncio.gather(
            *(client.probe(fen) for (_, _, fen, _) in puzzle.positions)
        )
        puzzler_positions = [
            PuzzlerPosition(
                move_index=index,
                played_uci=uci,
                response=response,
                capture_seen=capture_seen,
            )
            for (index, uci, _, capture_seen), response in zip(puzzle.positions, responses)
        ]
        rejections = verify_puzzle(puzzler_positions, puzzle.themes)
        if rejections:
            pgn = pgn_snippet(puzzle.fen, puzzle.moves, rejections)
            cli = f"puzzle issue {puzzle.puzzle_id} puzzle-tb:{uid}:{rejections[0]}"
            writer.write(puzzle.puzzle_id, pgn, cli)
            progress.rejected += 1
            progress.log(f"https://lichess.org/training/{puzzle.puzzle_id}: {pgn}")
        else:
            writer.write(puzzle.puzzle_id, "", "")
            progress.valid += 1
    finally:
        semaphore.release()


async def _render_loop(progress: Progress, stop: asyncio.Event) -> None:
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.2)
        except TimeoutError:
            progress.render()
            continue
        return


async def run(config: Config) -> None:
    """Execute a full verification run. Raises FatalTablebaseError on giving up."""
    done = load_done(config.output_path)
    total = config.limit if config.limit is not None else count_rows(config.input_path)
    uid = secrets.token_hex(4)  # identifies this run in emitted CLI commands

    async with TablebaseClient(
        config.endpoint,
        concurrency=config.concurrency,
        max_rps=config.max_rps,
        timeout=config.timeout,
        max_retries=config.retries,
    ) as client:
        progress = Progress(total, lambda: client.request_count)
        stop = asyncio.Event()
        renderer = asyncio.create_task(_render_loop(progress, stop))
        # Bound concurrent puzzles by the request concurrency: a puzzle only makes
        # progress by holding request slots, so this is enough to saturate the
        # client, and the producer then blocks here -- backpressured by how fast
        # the rate-limited API drains in-flight puzzles.
        semaphore = asyncio.Semaphore(config.concurrency)
        try:
            with ResultWriter(config.output_path) as writer:
                try:
                    async with asyncio.TaskGroup() as group:
                        for row in read_rows(config.input_path):
                            if config.limit is not None and progress.rows >= config.limit:
                                break
                            progress.rows += 1
                            # Yield periodically so progress stays live even through
                            # long stretches of cheaply-skipped (e.g. resumed) rows.
                            if progress.rows % 2000 == 0:
                                await asyncio.sleep(0)
                            puzzle = _prepare(row, done)
                            if puzzle is None:
                                continue
                            await semaphore.acquire()
                            group.create_task(
                                _process_puzzle(client, puzzle, writer, progress, semaphore, uid)
                            )
                except* (FatalTablebaseError, InputError, MalformedPuzzle) as group_error:
                    # Surface a single, plain error for the CLI to report.
                    raise group_error.exceptions[0] from None
        finally:
            stop.set()
            await renderer
            progress.render()
            progress.finish()


def _prepare(row: dict[str, str], done: set[str]) -> _Puzzle | None:
    """Filter and expand a CSV row into a schedulable puzzle, or None to skip."""
    puzzle_id = row["PuzzleId"]
    if puzzle_id in done:
        return None
    fen = row["FEN"]
    moves = row["Moves"].split()
    if not coverage.cheap_gate(fen, len(moves)):
        return None
    positions = expand_puzzle(fen, moves)
    if not positions:
        return None
    return _Puzzle(
        puzzle_id=puzzle_id,
        fen=fen,
        moves=moves,
        themes=PuzzleThemes.parse(row["Themes"]),
        positions=positions,
    )
