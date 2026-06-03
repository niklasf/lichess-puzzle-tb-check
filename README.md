# lichess-puzzle-tb

Verify Lichess puzzles against tablebase data.

Reads a [Lichess puzzle database](https://database.lichess.org/#puzzles) CSV,
looks at the positions that have tablebase coverage, probes the
[lila-tablebase](https://github.com/lichess-org/lila-tablebase) HTTP API, and
records — per puzzle — whether every puzzler move is the **unique winning move**
(or the **unique drawing move** for `equality` puzzles), plus a DTM check for
`mateInX` puzzles.

## Requirements

Python 3.14+ (uses the stdlib `compression.zstd` module).

```sh
uv venv --python 3.14
uv pip install -e .
```

## Usage

```sh
puzzle-tb lichess_db_puzzle.csv.zst --out report.csv
```

The input may be a plain `.csv` or a `.csv.zst` (streamed).

Verification runs are **resumable**: any `PuzzleId` already present in `--out`
is skipped. So interrupt with Ctrl-C or check new puzzles from an updated
database at any time.

## Output

The `--out` CSV has columns `PuzzleId,PGN,CliCommand`, both empty for valid
puzzles. For a rejected puzzle, `PGN` is an analysis snippet
(`[FEN "..."] 1. e4 { NOT_UNIQUE:draw@1 }`) and `CliCommand` is a ready-to-run
`puzzle issue …` command tagged with this run's id. Rejections are also printed to
stdout live as a clickable training link.

No field contains a comma, so columns extract with `cut`. For example, the CLI
commands for all rejected puzzles (skip the header, drop empty rows):

```sh
tail -n +2 report.csv | cut -d, -f3 | grep .
```

## Rejection reasons

| Code | Meaning |
|---|---|
| `NOT_WINNING:<cat>` | the played move is known not to win |
| `WIN_FRUSTRATED:<cat>` | the played move is only a frustrated win (`blessed-loss`) |
| `NOT_UNIQUE:<cat>` | a different move also wins/holds |
| `WRONG_MOVE:<cat>` | a different move wins/holds while the played is not known to |
| `EQUALITY_HAS_WIN:<cat>` | an `equality` puzzle where a winning move exists |
| `EQUALITY_NOT_DRAW:<cat>` | an `equality` puzzle whose played move does not draw |
| `DTM_MISMATCH:<dtm>` | a `mateInX` puzzle whose DTM does not match the expected mate distance (exact for mateIn1–4; a lower bound for mateIn5 = "5 or more") |

## Tablebase coverage

A position is *verifiable* if it is directly covered (≤7 pieces via Syzygy, or an
8-piece **op1** position) or is a ≤9-piece boundary position with a capture into
covered territory (9→8-op1, or 8→7). The verifier checks every verifiable
puzzler-to-move position and ignores the rest; a puzzle with no verifiable
position is skipped.

## Unconditional vs frustrated wins, the 50-move rule, and unknowns

`maybe-win`/`syzygy-win` (and their losing variants) are treated as
**unconditional** wins/losses — the WDL is known. `cursed-win`/`blessed-loss` are
**frustrated** wins/losses (real, but the 50-move rule can turn them into draws): a
frustrated win is never an unconditional win for the played move, and as an
*alternative* it refutes uniqueness only **until the puzzler has seen a capture**.
The 50-move counter isn't visible on the board, so before the first capture the
puzzler can't know it; after a capture resets it, a frustrated result collapses to a
draw and no longer competes.

Rejection is otherwise **evidence-based**: only *positive known* tablebase facts
reject a puzzle. An `unknown` move never rejects (nor confirms) — but incomplete
information can still suffice (two known winning moves prove non-uniqueness
regardless of unknown moves). The precise category is always recorded in each
reason, so the policy can be revisited later without re-querying.
