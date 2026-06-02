"""Always-on progress reporting to stderr.

Shows a progress bar over rows scanned, throughput in puzzles/s and tablebase
requests/s (averaged over a sliding window so the figures stay steady), and an
ETA from the overall row rate. The bar is only drawn on a TTY; a one-line summary
is always printed at the end.
"""

from __future__ import annotations

import sys
import time
from collections import deque
from collections.abc import Callable
from typing import TextIO

_BAR_WIDTH = 30
# Throughput and ETA are averaged over a sliding window of this many seconds, so
# the figures stay steady and the ETA isn't skewed by the fast skip of already
# verified rows right after a resume.
_RATE_WINDOW = 15.0


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class Progress:
    """Mutable counters plus an stderr renderer."""

    def __init__(
        self,
        total: int | None,
        get_requests: Callable[[], int],
        *,
        stream: TextIO | None = None,
    ) -> None:
        self.total = total
        self.rows = 0
        self.valid = 0
        self.rejected = 0
        self._get_requests = get_requests
        self._stream = stream if stream is not None else sys.stderr
        self._enabled = self._stream.isatty()
        now = time.monotonic()
        self._start = now
        # (timestamp, rows, puzzles, requests) samples kept within _RATE_WINDOW.
        self._samples: deque[tuple[float, int, int, int]] = deque([(now, 0, 0, 0)])

    @property
    def puzzles(self) -> int:
        return self.valid + self.rejected

    def log(self, line: str) -> None:
        """Print a line to stdout, clearing the in-progress bar first if drawn."""
        if self._enabled:
            self._stream.write("\r\x1b[K")
            self._stream.flush()
        print(line, flush=True)

    def render(self) -> None:
        if not self._enabled:
            return
        now = time.monotonic()
        requests = self._get_requests()
        self._samples.append((now, self.rows, self.puzzles, requests))
        while len(self._samples) > 1 and now - self._samples[0][0] > _RATE_WINDOW:
            self._samples.popleft()
        base_t, base_rows, base_puzzles, base_requests = self._samples[0]
        span = max(now - base_t, 1e-6)
        row_rate = (self.rows - base_rows) / span
        puzzle_rate = (self.puzzles - base_puzzles) / span
        request_rate = (requests - base_requests) / span

        line = self._format_line(row_rate, puzzle_rate, request_rate)
        self._stream.write("\r\x1b[K" + line)
        self._stream.flush()

    def _format_line(self, row_rate: float, puzzle_rate: float, request_rate: float) -> str:
        if self.total:
            frac = min(1.0, self.rows / self.total)
            filled = int(frac * _BAR_WIDTH)
            bar = "#" * filled + "-" * (_BAR_WIDTH - filled)
            eta = (self.total - self.rows) / row_rate if row_rate > 0 else 0.0
            head = f"[{bar}] {frac * 100:5.1f}% {self.rows}/{self.total}"
            tail = f" ETA {_format_duration(eta)}"
        else:
            head = f"{self.rows} rows"
            tail = ""
        return (
            f"{head} | {self.puzzles} verified "
            f"({self.valid} ok, {self.rejected} rej) | "
            f"{puzzle_rate:.1f} verified/s | {request_rate:.1f} req/s{tail}"
        )

    def finish(self) -> None:
        elapsed = time.monotonic() - self._start
        if self._enabled:
            self._stream.write("\r\x1b[K")
        summary = (
            f"Done: scanned {self.rows} rows, verified {self.puzzles} puzzles "
            f"({self.valid} ok, {self.rejected} rejected), "
            f"{self._get_requests()} tablebase requests in {_format_duration(elapsed)}."
        )
        self._stream.write(summary + "\n")
        self._stream.flush()
