"""Command-line entry point for ``puzzle-tb``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from .runner import Config, InputError, run
from .tablebase import DEFAULT_ENDPOINT, FatalTablebaseError


def _build_config(argv: Sequence[str] | None) -> Config:
    parser = argparse.ArgumentParser(
        prog="puzzle-tb",
        description="Verify Lichess puzzles against chess tablebase data.",
    )
    parser.add_argument("input", help="puzzle CSV (.csv or .csv.zst)")
    parser.add_argument("--out", required=True, help="results CSV (created/appended; resumable)")
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"lila-tablebase base URL; requests go to <endpoint>/standard (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--max-rps", type=float, default=0.95, help="max requests/second; 0 = unlimited (default: 0.95)"
    )
    parser.add_argument("--concurrency", type=int, default=20, help="max requests in flight (default: 20)")
    parser.add_argument("--timeout", type=float, default=60.0, help="per-request timeout in seconds (default: 60)")
    parser.add_argument("--retries", type=int, default=5, help="retries per request on transient errors (default: 5)")
    parser.add_argument("--limit", type=int, default=None, help="only scan the first N rows")
    args = parser.parse_args(argv)

    max_rps = args.max_rps if args.max_rps and args.max_rps > 0 else None
    return Config(
        input_path=args.input,
        output_path=args.out,
        endpoint=args.endpoint,
        max_rps=max_rps,
        concurrency=args.concurrency,
        timeout=args.timeout,
        retries=args.retries,
        limit=args.limit,
    )


def main(argv: Sequence[str] | None = None) -> int:
    config = _build_config(argv)
    try:
        asyncio.run(run(config))
    except (InputError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FatalTablebaseError as exc:
        print(f"\nfatal: {exc}", file=sys.stderr)
        print("Stopped without mis-verifying. Re-run with the same --out to resume.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run with the same --out to resume.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
