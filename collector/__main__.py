"""CLI: python -m collector --source mock|aws [--out snapshot.json]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import aws, mock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m collector", description="Collect a normalized resource snapshot.")
    parser.add_argument("--source", choices=["mock", "aws"], default="mock")
    parser.add_argument("--region", help="AWS region (mock default: us-east-1)")
    parser.add_argument("--lookback-days", type=int, default=14, help="metrics window in days")
    parser.add_argument("--count", type=int, default=30, help="mock only: number of resources")
    parser.add_argument("--seed", type=int, default=42, help="mock only: random seed")
    parser.add_argument("--out", help="write JSON to this file instead of stdout")
    args = parser.parse_args(argv)

    if args.source == "aws":
        snapshot = aws.collect(region=args.region, lookback_days=args.lookback_days)
    else:
        snapshot = mock.generate(
            count=args.count,
            seed=args.seed,
            lookback_days=args.lookback_days,
            region=args.region or "us-east-1",
        )

    payload = json.dumps(snapshot.to_dict(), indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n")
        print(f"Wrote {len(snapshot.resources)} resources to {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
