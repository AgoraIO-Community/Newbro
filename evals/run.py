from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from newbro.runtime import load_settings

from evals.communication.runner import format_results, run_communication_eval


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Newbro behavior-quality evals.")
    parser.add_argument(
        "suite",
        choices=["communication"],
        help="Eval suite to run.",
    )
    return parser


async def _run(args) -> str:
    settings = load_settings()
    if args.suite == "communication":
        results = await run_communication_eval(settings)
        return format_results(results)
    raise RuntimeError(f"Unsupported eval suite: {args.suite}")


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    print(asyncio.run(_run(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
