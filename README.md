# lichess-puzzles-tb

Verify Lichess puzzles against chess tablebase data.

Reads the [Lichess puzzle database](https://database.lichess.org/#puzzles), keeps
the puzzles whose positions are within tablebase coverage, probes a
[lila-tablebase](https://github.com/lichess-org/lila-tablebase) HTTP API, and
records — per puzzle — whether every puzzler move is the **unique winning move**
(or the **unique drawing move** for `equality` puzzles), plus a DTM check for
`mateInX` puzzles.

## Requirements

- Python 3.14+ (uses the stdlib `compression.zstd` module).
- `python-chess` and `aiohttp`.

```sh
uv venv --python 3.14
uv pip install -e .
```

## Usage

```sh
puzzle-tb lichess_db_puzzle.csv.zst --out report.csv
```

The input may be a plain `.csv` or a `.csv.zst` (streamed). The run is
**resumable**: any `PuzzleId` already present in `--out` is skipped, so an updated
database only verifies the new puzzles. The output is flushed after every puzzle,
so an interrupt (Ctrl-C) loses at most the in-flight puzzles — just re-run with
the same `--out` to continue.

### Options

| Option | Default | Meaning |
|---|---|---|
| `--endpoint URL` | `https://tablebase.lichess.ovh/standard` | lila-tablebase endpoint (point at a local instance if you have one) |
| `--max-rps R` | `1.5` | max requests/second (`0` = unlimited) |
| `--concurrency N` | `20` | max requests in flight |
| `--timeout S` | `60` | per-request timeout (seconds) |
| `--retries N` | `5` | retries per request on transient errors |
| `--limit N` | — | only scan the first N rows |

On HTTP 429 the client pauses a full minute, then retries. Server errors (5xx) and
network/timeout errors are retried with backoff. A client error (4xx other than
429 — e.g. 404 or 400) means the request itself is wrong, so it is **immediately
fatal and reported**. If retries are exhausted, the run also **stops and reports**
rather than risk mis-verifying a puzzle. Re-run with the same `--out` to resume.

## Output

A CSV of `PuzzleId,Reasons`. `Reasons` is a space-separated list of rejection
codes; an **empty** list means the puzzle was not rejected by any known evidence.
Each reason is `CODE:detail@i`, where `i` is the index of the offending move in
the puzzle's `Moves` and `detail` is the exact tablebase category (or DTM).

| Code | Meaning |
|---|---|
| `NOT_WINNING:<cat>` | the played move is known not to win |
| `WIN_NOT_CLEAN:<cat>` | the played move is only a cursed win (`blessed-loss`) |
| `NOT_UNIQUE:<cat>` | a different move also wins (the strongest such category) |
| `WRONG_MOVE:<cat>` | a different move wins/holds while the played move does not |
| `EQUALITY_HAS_WIN:<cat>` | an `equality` puzzle where a winning move exists |
| `EQUALITY_NOT_DRAW:<cat>` | an `equality` puzzle whose played move does not cleanly draw |
| `DTM_MISMATCH:<dtm>` | a `mateInX` puzzle whose DTM does not match the expected mate distance |
| `MALFORMED` | a recorded move is illegal / not offered by the tablebase |

### Coverage and the "verify the covered tail" policy

A position is *verifiable* if it is directly covered (≤7 pieces via Syzygy, or an
8-piece **op1** position) or is a ≤9-piece boundary position with a capture into
covered territory (9→8-op1, or 8→7). The verifier checks every verifiable
puzzler-to-move position and ignores the rest; a puzzle with no verifiable
position is skipped.

### Cleanness, the 50-move rule, and unknowns

`maybe-win`/`syzygy-win` (and their losing variants) are treated as **clean** —
the WDL is known, only DTZ precision is fuzzy. The genuinely 50-move-distorted
results are `cursed-win`/`blessed-loss`: a cursed win is never a *clean* win for
the played move, and as an *alternative* it refutes uniqueness only **until the
puzzler has seen a capture** — after a capture it collapses to a draw (the
50-move rule) and no longer competes.

Rejection is otherwise **evidence-based**: only *positive known* tablebase facts
reject a puzzle. An `unknown` move never rejects (nor confirms) — but incomplete
information can still suffice (two known winning moves prove non-uniqueness
regardless of unknown moves). The precise category is always recorded in each
reason, so the policy can be revisited later without re-querying.
```
