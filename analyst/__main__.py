"""CLI: python -m analyst snapshot.json [--out recommendations.json]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anthropic

from collector.schema import Snapshot

from .llm import AnalystError, recommend
from .report import build_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m analyst", description="Recommend cost savings for a snapshot.")
    parser.add_argument("snapshot", help="snapshot JSON produced by python -m collector")
    parser.add_argument("--out", help="write JSON to this file instead of stdout")
    args = parser.parse_args(argv)

    snapshot = Snapshot.from_dict(json.loads(Path(args.snapshot).read_text()))
    try:
        raw, model = recommend(snapshot)
    except anthropic.AuthenticationError:
        print("Claude API authentication failed: set ANTHROPIC_API_KEY", file=sys.stderr)
        return 1
    except anthropic.RateLimitError:
        print("Claude API rate limit reached: try again shortly", file=sys.stderr)
        return 1
    except anthropic.APIStatusError as error:
        print(f"Claude API error {error.status_code}: {error.message}", file=sys.stderr)
        return 1
    except anthropic.APIConnectionError:
        print("Could not reach the Claude API", file=sys.stderr)
        return 1
    except AnalystError as error:
        print(str(error), file=sys.stderr)
        return 1

    report = build_report(snapshot, raw, model)
    payload = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n")
        print(
            f"Wrote {len(report['recommendations'])} recommendations to {args.out} "
            f"(estimated saving ${report['total_monthly_saving_usd']}/month)",
            file=sys.stderr,
        )
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
