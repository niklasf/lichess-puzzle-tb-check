# CLAUDE.md

Detailed requirements and conventions for `puzzle-tb`.

## Commands

```sh
uv sync                                  # install (deps + dev group: mypy)
uv run mypy                              # type check (strict)
uv run python -m unittest discover -s tests   # tests
uv run puzzle-tb INPUT.csv[.zst] --out report.csv [--endpoint URL] [--max-rps R] [--concurrency N] [--timeout S] [--retries N] [--limit N]
```

## Conventions

- Python 3.14+ (stdlib `compression.zstd`). Only third-party deps: `python-chess`,
  `aiohttp`. Tests use stdlib `unittest`, not pytest.
- **Keep it simple.** Prefer the straightforward approach; we deliberately kept the
  semaphore + `TaskGroup` scheduler over a fancier worker-pool refactor.
- **Strong typing**, `mypy --strict` must pass. The tablebase response is a typed
  frozen-dataclass model parsed once at the network boundary (`schema.py`); nothing
  downstream touches raw JSON.
- Core verdict logic (`verify.py`) is **pure and network-free** — unit-tested by
  building typed objects directly, no mocking.

## Modules

- `schema.py` — `Category` enum, `Move`/`TablebaseResponse` dataclasses, strict
  `parse_response` (raises `MalformedResponse`).
- `classify.py` — precise-category predicates + `effective(category, capture_seen)`.
- `coverage.py` — `is_op1`/`more_than_lone_pawn`/`directly_covered`/`verifiable`,
  `cheap_gate`, `piece_count`.
- `verify.py` — pure verdict logic → reason codes; `PuzzleThemes`, `ExactMate`/`AtLeastMate`.
- `tablebase.py` — async client (rate limit, concurrency, 429 pause, retries).
- `runner.py` — CSV streaming, resume, scheduling, result writing, `format_rejection`.
- `progress.py` — stderr progress renderer.
- `cli.py` — argparse entry point.

## Input

- Lichess puzzle CSV (plain or `.csv.zst`, streamed). Columns: `PuzzleId,FEN,Moves,
  Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags`.
- Only `PuzzleId,FEN,Moves,Themes` are used. Read by name (`csv.DictReader`); extra
  columns and reordering are fine. A missing required column raises `InputError`.
- `FEN` is the position **before** the opponent's setup move `Moves[0]`. Puzzler
  moves are the odd indices `Moves[1], Moves[3], …`; even indices are opponent
  responses (applied verbatim, not verified).

## Coverage ("verify the covered tail")

- `directly_covered`: ≤7 pieces (Syzygy), or 8-piece **op1** (lila-tablebase
  `src/op1.rs::is_op1` — a white pawn with a black pawn ahead on the same file —
  plus no castling rights and `more_than_lone_pawn` for both sides).
- `verifiable`: directly covered, or a ≤9-piece boundary position with a legal move
  into directly-covered territory (9→8-op1 capture, or 8→7 capture). lila reports
  known move categories for such moves even when the root is `unknown`.
- Cheap pre-filter (`cheap_gate`): with `n` = FEN piece count and `m` = move count,
  skip if `n - m > 9` (can never reach ≤9 pieces).
- Verify every *verifiable* puzzler-to-move position; ignore the rest. A puzzle with
  no verifiable position is skipped (no output).

## Tablebase API

- lila-tablebase `/standard`. `--endpoint` is the **base URL** (default
  `https://tablebase.lichess.ovh`); the client appends `/standard`. Supports a local
  instance.
- Rate limiting: token-bucket `--max-rps` (0 = unlimited) **and** a `--concurrency`
  semaphore (requests in flight). The CSV producer is bounded by the same
  concurrency, so it's backpressured by API throughput.
- HTTP **429** → pause a full minute, then retry (free). **5xx / network / timeout**
  → retry with backoff (`--retries`). **4xx other than 429** (e.g. 404, 400) →
  **immediately fatal** (the request itself is wrong). Retries exhausted or a
  malformed response → fatal.
- On any fatal error: stop, print it, exit non-zero. Never mis-verify. Re-run to
  resume. Default `--timeout` 60s.

## Verdict rules

A move's `Category` is from the **opponent's** perspective (the resulting position),
so `loss` = opponent lost = *we* win.

**Cleanness / 50-move rule:**
- `maybe-win`/`syzygy-win` and their losing variants `maybe-loss`/`syzygy-loss` are
  **clean**.
- `cursed-win`/`blessed-loss` are the 50-move-rule-distorted results.
- `is_clean_win` = `{loss, maybe-loss, syzygy-loss}` (a cursed win, `blessed-loss`, is
  never clean for the played move).
- `effective(category, capture_seen)` → WIN/DRAW/LOSS/UNKNOWN: cursed results
  (`cursed-win`/`blessed-loss`) keep their win/loss value **until a capture has been
  seen** in the line, then collapse to a draw (the puzzler does not know about
  the 50-move counter before the first capture).
  `capture_seen` = some earlier move (index < this one) was a capture.

**Evidence-based rejection:** reject only on *positive known* facts. `unknown` never
rejects or confirms — but incomplete info can still suffice (two known winning moves
prove non-uniqueness regardless of unknown moves; a known winning move different from
the played one proves the puzzle defective).

**Normal puzzle** — played move must be the unique clean winning move:
- played not winning (known) → `NOT_WINNING:<cat>`
- played a cursed win (`blessed-loss`) → `WIN_NOT_CLEAN:<cat>`
- a different move competes (`effective == WIN`) → `NOT_UNIQUE:<cat>` if the played
  move is itself a clean win, else `WRONG_MOVE:<cat>`

**`equality` puzzle** — played move must be the unique clean draw:
- any move is a clean win → `EQUALITY_HAS_WIN:<cat>`
- played move known but not a clean draw → `EQUALITY_NOT_DRAW:<cat>`
- a different move holds (`effective ∈ {WIN, DRAW}`) → `NOT_UNIQUE`/`WRONG_MOVE`

**Immediate checkmate** (`move.checkmate`): always an acceptable solution regardless
of other mating moves or longer wins — but it **still gets the DTM check** below.

**mateInX:** `ExactMate` for mateIn1–4, `AtLeastMate` for **mateIn5 = "5 or more"**
(a lower bound that propagates: ≥4 at the next move, etc.). DTM is in plies; at the
j-th puzzler move the remaining count is `X - j + 1`, so expected DTM = `2*(X-j+1)-1`.
Exact: `dtm == expected`; lower bound: `dtm >= expected`; else `DTM_MISMATCH:<dtm>`.
DTM is only available ≤5 pieces, so it's skipped when absent.

`MALFORMED@i` if a recorded move is illegal. Every reason is `CODE:detail@i` where
`i` is the move index in `Moves` and `detail` is the exact category/DTM (the strongest
relevant move, first in best-first order).

## Output & run behaviour

- `--out` CSV: `PuzzleId,Reasons` (space-separated codes; **empty = not rejected**).
  No fingerprints/timestamps. Flushed after every puzzle.
- **Resume:** skip any `PuzzleId` already in `--out`. An updated DB only verifies new
  puzzles. Interrupt (Ctrl-C) loses at most the in-flight puzzles.
- **stdout:** each rejected puzzle, one line, as a training link + PGN snippet with the
  reason as a `{ … }` comment on the offending move (`format_rejection`).
- **stderr:** always-on progress (bar, `verified/s`, `req/s`, ETA) + final summary.
  Throughput is averaged over a sliding 15s window; ETA uses the windowed row rate
  (so the post-resume skip burst doesn't skew it). `verified/s` = puzzles that got a
  verdict, not rows scanned.

## CI

`.github/workflows/ci.yml` runs `mypy` + `unittest` on push/PR. `.github/dependabot.yml`
groups `uv` and `github-actions` updates.
