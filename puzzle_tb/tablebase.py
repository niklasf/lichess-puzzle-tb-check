"""Async client for the lila-tablebase ``/standard`` endpoint.

Provides configurable rate limiting (a token bucket for requests/second and a
semaphore for concurrent requests in flight), a full-minute pause on HTTP 429,
and bounded retries on transient errors. If retries are exhausted -- or the
response is malformed -- it raises :class:`FatalTablebaseError` so the caller can
stop and report.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType

import aiohttp

from .schema import MalformedResponse, TablebaseResponse, parse_response

DEFAULT_ENDPOINT = "https://tablebase.lichess.ovh"
_USER_AGENT = "lichess-puzzles-tb/0.1.0"
_RATE_LIMIT_PAUSE = 60.0  # seconds to wait after an HTTP 429


class FatalTablebaseError(Exception):
    """Unrecoverable error; verification must stop rather than continue."""


class _Retryable(Exception):
    """Internal marker for a transient failure worth retrying."""


class _PausedRetry(Exception):
    """Internal: a 429 was handled and the request should be retried for free."""


class _TokenBucket:
    """Paces acquisitions to at most ``rate`` per second (``None`` = unlimited)."""

    def __init__(self, rate: float | None) -> None:
        self._rate = rate
        self._capacity = max(1.0, rate) if rate else 0.0
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if not self._rate:
            return
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
            self._updated = now
            if self._tokens < 1.0:
                await asyncio.sleep((1.0 - self._tokens) / self._rate)
                self._tokens = 0.0
                self._updated = time.monotonic()
            else:
                self._tokens -= 1.0


class TablebaseClient:
    """Probes positions, honouring rate limits, 429 pauses, and retries."""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        concurrency: int = 20,
        max_rps: float | None = 1.5,
        timeout: float = 60.0,
        max_retries: int = 5,
        backoff: float = 1.0,
    ) -> None:
        # ``endpoint`` is the base URL; standard chess positions go to /standard.
        self._url = endpoint.rstrip("/") + "/standard"
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._max_retries = max_retries
        self._backoff = backoff
        self._semaphore = asyncio.Semaphore(concurrency)
        self._limiter = _TokenBucket(max_rps)
        self._session: aiohttp.ClientSession | None = None
        self._request_count = 0

        # Global pause: ``_resume`` is set except during a 429 cooldown.
        self._resume = asyncio.Event()
        self._resume.set()
        self._pause_lock = asyncio.Lock()
        self._paused_until = 0.0

    @property
    def request_count(self) -> int:
        """Total number of HTTP requests issued (including retries)."""
        return self._request_count

    async def __aenter__(self) -> TablebaseClient:
        self._session = aiohttp.ClientSession(
            timeout=self._timeout, headers={"User-Agent": _USER_AGENT}
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _handle_429(self) -> None:
        async with self._pause_lock:
            self._paused_until = max(self._paused_until, time.monotonic() + _RATE_LIMIT_PAUSE)
            self._resume.clear()
        while True:
            remaining = self._paused_until - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(remaining)
        self._resume.set()

    async def probe(self, fen: str) -> TablebaseResponse:
        """Probe ``fen`` and return the parsed, validated response."""
        if self._session is None:
            raise RuntimeError("TablebaseClient must be used as an async context manager")

        attempt = 0
        while True:
            await self._resume.wait()
            await self._limiter.acquire()
            try:
                data = await self._request(fen)
            except _PausedRetry:
                continue  # 429 handled; retry without consuming the budget
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, _Retryable) as exc:
                attempt += 1
                if attempt > self._max_retries:
                    raise FatalTablebaseError(f"giving up on {fen!r} after retries: {exc}") from exc
                await asyncio.sleep(self._backoff * 2 ** (attempt - 1))
                continue

            try:
                return parse_response(data)
            except MalformedResponse as exc:
                raise FatalTablebaseError(f"malformed response for {fen!r}: {exc}") from exc

    async def _request(self, fen: str) -> object:
        assert self._session is not None
        async with self._semaphore:
            self._request_count += 1
            async with self._session.get(self._url, params={"fen": fen}) as resp:
                if resp.status == 429:
                    await self._handle_429()
                    raise _PausedRetry
                if resp.status >= 500:
                    raise _Retryable(f"HTTP {resp.status}")
                if resp.status >= 400:
                    # A client error (e.g. 404, 400) means the request itself is
                    # wrong; retrying cannot help, so fail fast and report.
                    body = " ".join((await resp.text()).split())[:200]
                    raise FatalTablebaseError(
                        f"tablebase rejected request (HTTP {resp.status}) for {fen!r}: {body}"
                    )
                resp.raise_for_status()
                return await resp.json(content_type=None)
