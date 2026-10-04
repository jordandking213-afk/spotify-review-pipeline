"""Command-line entry point. Nothing here spends money unless --client openai is passed explicitly.

    python3 -m pipeline enrich --input PATH.csv --run NAME [--client fake] [--workers 1] [--max-batches N]
"""

import argparse
import json
from pathlib import Path

from . import config
from .clients import FakeClient


def main():
    parser = argparse.ArgumentParser(prog="python3 -m pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("enrich", help="label reviews (default client: fake, $0)")
    p.add_argument("--input", type=Path, required=True, help="any CSV with the six source columns")
    p.add_argument("--run", required=True, help="run directory name under runs/")
    p.add_argument("--client", choices=["fake", "openai"], default="fake")
    p.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    p.add_argument("--spend-cap", type=float, default=config.SPEND_CAP_USD)
    p.add_argument("--max-batches", type=int, help="stop after this many requests (interruption demo)")
    p.add_argument("--time-cap-s", type=float)
    p.add_argument("--fake-behaviors", default="", help="comma list for the fake client, e.g. drop_one,timeout")
    args = parser.parse_args()

    if args.command == "enrich":
        if args.client == "openai":
            raise SystemExit("The OpenAI client is not built yet; it comes after the fake-model tests are approved.")
        from .enrich import Enricher
        client = FakeClient(behaviors=[b for b in args.fake_behaviors.split(",") if b])
        summary = Enricher(args.input, config.RUNS / args.run, client, workers=args.workers,
                           spend_cap=args.spend_cap, max_batches=args.max_batches, time_cap_s=args.time_cap_s).run()
        print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
