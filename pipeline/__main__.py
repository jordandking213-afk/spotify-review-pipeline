"""Command-line entry point. Nothing here spends money unless `--client openai --confirm-paid` is passed.

    python3 -m pipeline enrich --input PATH.csv --run NAME                       # fake model, $0
    python3 -m pipeline enrich --input PATH.csv --run NAME --client openai --confirm-paid
    python3 -m pipeline smoke --confirm-paid      # 1 request, 5 development reviews (~$0.001)
"""

import argparse
import csv
import json
from pathlib import Path

from . import config
from .clients import FakeClient

DATASET = config.REPO.parent / "Final Assignment - Spotify Reviews Dataset"


def make_client(name, behaviors=""):
    if name == "openai":
        from .openai_client import OpenAIClient
        return OpenAIClient()
    return FakeClient(behaviors=[b for b in behaviors.split(",") if b])


def write_smoke_input(path, n=5):
    """The last n rows of analysis_10000.csv: development data, outside the 100/500 pilot files and the golden 50."""
    with open(DATASET / "analysis_10000.csv", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        rows, fields = list(reader)[-n:], reader.fieldnames
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(prog="python3 -m pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("enrich", help="label reviews (default client: fake, $0)")
    p.add_argument("--input", type=Path, required=True, help="any CSV with the six source columns")
    p.add_argument("--run", required=True, help="run directory name under runs/")
    p.add_argument("--client", choices=["fake", "openai"], default="fake")
    p.add_argument("--confirm-paid", action="store_true", help="required with --client openai")
    p.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    p.add_argument("--spend-cap", type=float, default=config.SPEND_CAP_USD)
    p.add_argument("--max-batches", type=int, help="stop after this many requests (interruption demo)")
    p.add_argument("--time-cap-s", type=float)
    p.add_argument("--fake-behaviors", default="", help="comma list for the fake client, e.g. drop_one,timeout")
    v = sub.add_parser("verify", help="independent re-label of a declared random sample (default client: fake)")
    v.add_argument("--run", required=True)
    v.add_argument("--client", choices=["fake", "openai"], default="fake")
    v.add_argument("--confirm-paid", action="store_true")
    v.add_argument("--rate", type=float, default=config.VERIFY_RATE)
    v.add_argument("--plant", type=int, default=10, help="planted-error test size (synthetic copy)")
    v.add_argument("--spend-cap", type=float, default=config.SPEND_CAP_USD)
    s = sub.add_parser("smoke", help="paid connection test: one request with 5 development reviews")
    s.add_argument("--confirm-paid", action="store_true")
    args = parser.parse_args()

    from .enrich import Enricher
    if args.command == "verify":
        if args.client == "openai" and not args.confirm_paid:
            raise SystemExit("--client openai makes paid calls. Re-run with --confirm-paid to proceed.")
        from .verify import Verifier
        verifier = Verifier(config.RUNS / args.run, make_client(args.client), rate=args.rate, spend_cap=args.spend_cap)
        summary = verifier.run()
        summary["planted_error_test"] = {k: v for k, v in verifier.planted_error_test(args.plant).items() if k != "cases"}
        print(json.dumps(summary, indent=1))
        return
    if args.command == "smoke":
        if not args.confirm_paid:
            raise SystemExit("The smoke test makes one paid call (~$0.001). Re-run with --confirm-paid.")
        run_dir = config.RUNS / f"smoke-{config.PROMPT_VERSION}"   # one folder per prompt version; v1 results stay intact
        write_smoke_input(run_dir / "input.csv")
        summary = Enricher(run_dir / "input.csv", run_dir, make_client("openai"), spend_cap=0.05).run()
    else:
        if args.client == "openai" and not args.confirm_paid:
            raise SystemExit("--client openai makes paid calls. Re-run with --confirm-paid to proceed.")
        summary = Enricher(args.input, config.RUNS / args.run, make_client(args.client, args.fake_behaviors),
                           workers=args.workers, spend_cap=args.spend_cap, max_batches=args.max_batches,
                           time_cap_s=args.time_cap_s).run()
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
