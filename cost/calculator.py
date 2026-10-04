"""100-review cost and runtime calculator (COST_CALCULATOR.md).

DEFAULT = OFFLINE REPLAY. No API key, no network, no model calls. Importing this file does nothing.
    python3 cost/calculator.py                       # recompute report.md from saved evidence + rates.csv
    python3 cost/calculator.py --rates my_rates.csv  # e.g. try different prices; measured usage never changes

PAID PILOT = a separate, explicit command (runs the real pipeline on cost_100.csv, cold then warm):
    python3 cost/calculator.py pilot --confirm-paid
    python3 cost/calculator.py pilot --client fake   # $0 rehearsal into cost/rehearsal-fake/ (simulated usage)

Billing: each call's usage is split into mutually exclusive items -- ordinary input (= input - cached - cache
writes), cached input, cache writes, output -- and each item costs billed units x price per unit. Reasoning tokens
are already inside output tokens and are shown but not billed again. Calls with unknown usage (timeouts) are
never silently zero: they are listed as unresolved, with their reserved worst case shown as an estimate.
"""

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ITEMS = ("ordinary_input", "cached_input", "cache_write", "output")


# ---------------------------------------------------------------------------------------------------- inputs
def load_rates(path):
    rates = defaultdict(dict)
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rates[row["model"]][row["item"]] = {
                "per_unit": float(row["usd_per_unit_size"]) / float(row["unit_size"]),
                "quoted": f"${row['usd_per_unit_size']} per {int(float(row['unit_size'])):,} {row['unit']}s",
                "source": row["source"], "checked": row["checked"], "tier": row["tier"], "currency": row["currency"]}
    return rates


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def billed_units(call):
    ordinary = call["input_tokens"] - call["cached_input_tokens"] - call["cache_write_tokens"]
    return {"ordinary_input": ordinary, "cached_input": call["cached_input_tokens"],
            "cache_write": call["cache_write_tokens"], "output": call["output_tokens"]}


def call_cost(call, rates):
    """Return ({item: usd}, None) for known usage, or (None, estimated_usd) when usage is unknown."""
    if not call["usage_known"]:
        return None, call["reserved_usd"]
    units = billed_units(call)
    return {item: units[item] * rates[call["model"]][item]["per_unit"] for item in ITEMS}, None


# ---------------------------------------------------------------------------------------------------- measured
def measured(evidence, rates):
    calls = load_jsonl(evidence / "pilot_calls.jsonl")
    records = load_jsonl(evidence / "pilot_records.jsonl")
    run = json.loads((evidence / "pilot_run.json").read_text())
    stages = defaultdict(lambda: {"requests": set(), "attempts": 0, "succeeded": 0, "failed": 0, "retries": 0,
                                  "review_ids_sent": 0, "max_batch": 0, "units": defaultdict(int), "reasoning": 0,
                                  "cost": defaultdict(float), "unresolved_calls": 0, "estimated_usd": 0.0,
                                  "call_seconds": 0.0, "model": set(), "configs": set(), "provider": set()})
    for c in calls:
        s = stages[(c["pilot_phase"], c["role"])]
        s["requests"].add(c["request_id"])
        s["attempts"] += 1
        s["succeeded" if c["outcome"] == "succeeded" else "failed"] += 1
        s["retries"] += int(c["attempt"] > 1 or c["is_retry_of_invalid"])
        s["review_ids_sent"] += len(c["review_ids"]) if c["outcome"] == "succeeded" else 0
        s["max_batch"] = max(s["max_batch"], len(c["review_ids"]))
        s["call_seconds"] += c["duration_s"]
        s["model"].add(c["model"])
        s["provider"].add(c.get("provider", "unknown"))
        s["configs"].add(c["label_config"])
        cost, estimate = call_cost(c, rates)
        if cost is None:
            s["unresolved_calls"] += 1
            s["estimated_usd"] += estimate
            continue
        for item, units in billed_units(c).items():
            s["units"][item] += units
            s["cost"][item] += cost[item]
        s["reasoning"] += c["reasoning_tokens"]
    status = defaultdict(int)
    for r in records:
        status[r["status"]] += 1
    phases = {}
    for phase in ("cold", "warm"):
        rows = {role: s for (p, role), s in stages.items() if p == phase}
        api = sum(sum(s["cost"].values()) for s in rows.values())
        phases[phase] = {
            "wall_clock_s": run[phase]["wall_clock_s"], "stage_wall_clock_s": run[phase]["stage_wall_clock_s"],
            "api_usd": api, "estimated_unresolved_usd": sum(s["estimated_usd"] for s in rows.values()),
            "enrich_attempts": rows.get("enrich", {}).get("attempts", 0),
            "stages": {role: {
                "model": sorted(s["model"]), "provider": sorted(s["provider"]), "config": sorted(s["configs"]), "requests": len(s["requests"]),
                "attempts": s["attempts"], "succeeded": s["succeeded"], "failed": s["failed"], "retries": s["retries"],
                "max_batch": s["max_batch"], "review_ids_sent": s["review_ids_sent"], "units": dict(s["units"]),
                "reasoning_tokens": s["reasoning"], "cost": dict(s["cost"]), "api_usd": sum(s["cost"].values()),
                "unresolved_calls": s["unresolved_calls"], "estimated_usd": s["estimated_usd"],
                "summed_call_seconds": round(s["call_seconds"], 3)} for role, s in sorted(rows.items())}}
    n = run["input_ids"]
    cold = phases["cold"]
    return {"run": run, "records": dict(status), "phases": phases,
            "per_1000_inputs_usd": cold["api_usd"] / n * 1000 if n else None,
            "per_completed_record_usd": cold["api_usd"] / status["completed"] if status["completed"] else None,
            "throughput_reviews_per_s": n / cold["wall_clock_s"] if cold["wall_clock_s"] else None}


# ---------------------------------------------------------------------------------------------------- projection
def project(m, rates, a):
    cold = m["phases"]["cold"]["stages"]
    enrich, verify = cold["enrich"], cold.get("verify")
    model = enrich["model"][0]
    r = {item: rates[model][item]["per_unit"] for item in ITEMS}
    full, ctl = a["full_run"], a["controls"]
    sent = enrich["review_ids_sent"]
    req = enrich["requests"]
    # Per-review and per-request usage measured in the cold pilot.
    system_tokens = (enrich["units"].get("cached_input", 0) + enrich["units"].get("cache_write", 0)) / req
    out_per_review = enrich["units"]["output"] / sent
    in_per_review = enrich["units"]["ordinary_input"] / sent
    seconds_per_request = enrich["summed_call_seconds"] / enrich["attempts"]
    verify_usd_per_review = verify["api_usd"] / verify["review_ids_sent"] if verify and verify["review_ids_sent"] else 0
    verify_seconds_per_request = verify["summed_call_seconds"] / verify["attempts"] if verify else 0
    group, memo = cold.get("group", {}), cold.get("memo", {})
    pilot_issues = m["run"].get("pilot_issue_count") or 1

    scenarios = {}
    for name, s in a["scenarios"].items():
        def enrich_cost(texts, workers):
            requests = math.ceil(texts / ctl["enrich_batch_size"])
            hours = requests * seconds_per_request * s["time_multiplier"] / workers / 3600
            writes = max(1, math.ceil(hours * 2)) * workers            # cache entries live 30 minutes
            variable = texts * (in_per_review * r["ordinary_input"] + out_per_review * r["output"])
            fixed_prompt = requests * system_tokens * r["cached_input"] + writes * system_tokens * r["cache_write"]
            base = (variable + fixed_prompt) * s["token_multiplier"]
            return base * (1 + s["invalid_retry_fraction"] + s["transient_retry_fraction"]), requests
        workers = ctl["max_workers"]
        enrich_usd, requests = enrich_cost(full["distinct_nonempty_texts"], workers)
        no_reuse_usd, _ = enrich_cost(full["nonempty_to_classify"], workers)
        verified = full["distinct_nonempty_texts"] * ctl["verify_rate_full_run"]
        verify_usd = verified * verify_usd_per_review * s["token_multiplier"] * (1 + s["invalid_retry_fraction"])
        group_usd = group.get("api_usd", 0) * a["expected_issues_full_run"] / pilot_issues * s["token_multiplier"]
        memo_usd = memo.get("api_usd", 0) * s["memo_multiplier"]
        fallback_usd = ctl["fallback_fraction"] * enrich_usd     # declared 0 unless a fallback is configured
        total = enrich_usd + verify_usd + group_usd + memo_usd + fallback_usd
        times = {}
        for w in a["workers_for_time_estimate"]:
            enrich_h = requests * (1 + s["transient_retry_fraction"]) * seconds_per_request * s["time_multiplier"] / w / 3600
            verify_h = math.ceil(verified / ctl["enrich_batch_size"]) * verify_seconds_per_request * s["time_multiplier"] / w / 3600
            rpm = w * 60 / seconds_per_request
            tokens_per_request = system_tokens + ctl["enrich_batch_size"] * (in_per_review + out_per_review)
            times[w] = {"hours": round(enrich_h + verify_h, 2), "requests_per_minute": round(rpm, 1),
                        "tokens_per_minute": round(rpm * tokens_per_request),
                        "within_provider_limits": rpm <= a["provider_limits"]["requests_per_minute"]
                        and rpm * tokens_per_request <= a["provider_limits"]["tokens_per_minute"]}
        scenarios[name] = {"enrich_usd": enrich_usd, "enrich_no_reuse_usd": no_reuse_usd, "verify_usd": verify_usd,
                           "verified_reviews": round(verified), "group_usd": group_usd, "memo_usd": memo_usd,
                           "fallback_usd": fallback_usd, "total_api_usd": total, "enrich_requests": requests,
                           "exceeds_budget": total > ctl["budget_usd"], "hours_by_workers": times}
    worst_case_output_cap = math.ceil(full["distinct_nonempty_texts"] / ctl["enrich_batch_size"]) \
        * ctl["max_output_tokens_per_request"] * r["output"]
    return {"inputs": {"system_prompt_tokens_per_request": round(system_tokens, 1),
                       "ordinary_input_tokens_per_review": round(in_per_review, 2),
                       "output_tokens_per_review": round(out_per_review, 2),
                       "seconds_per_enrich_request": round(seconds_per_request, 3),
                       "verify_usd_per_review": verify_usd_per_review, "pilot_issue_count": pilot_issues},
            "scenarios": scenarios, "worst_case_if_every_request_hit_output_cap_usd": worst_case_output_cap}


# ---------------------------------------------------------------------------------------------------- report
def usd(x):
    return "unknown" if x is None else f"${x:,.6f}" if x < 0.01 else f"${x:,.4f}" if x < 1 else f"${x:,.2f}"


def render(m, p, rates, a, evidence, rates_path):
    run, cold, warm = m["run"], m["phases"]["cold"], m["phases"]["warm"]
    sim = run.get("simulated")
    L = [f"# {run['input_ids']}-review cost and runtime report ({run['input_file']}){' — SIMULATED REHEARSAL (fake model, not real costs)' if sim else ''}",
         "", f"Recomputed offline from `{evidence.relative_to(REPO) if evidence.is_relative_to(REPO) else evidence.name}/pilot_calls.jsonl` and `{rates_path.name}` "
         f"by `python3 cost/calculator.py` (no API key, no model calls).", "",
         f"## Measured: {run['input_ids']}-review run", "",
         f"- Input: `{run['input_file']}` SHA-256 `{run['input_sha256']}` "
         f"({'matches' if run.get('input_matches_manifest') else 'DOES NOT match'} manifest); {run['input_ids']} IDs.",
         f"- Records: {m['records']}. Unique texts: {run['unique_texts']}. Result-cache reuse in cold run: "
         f"{run['cold_cache_reuses']} records.",
         f"- Workers: {run['workers']}. Verification sample (declared): {run['verify_rate']:.0%} of distinct texts. "
         f"Run directory started empty: {run['empty_cache_at_start']}.",
         f"- Cold wall-clock: **{cold['wall_clock_s']:.1f} s** (stages: {cold['stage_wall_clock_s']}). "
         f"Warm wall-clock: **{warm['wall_clock_s']:.1f} s**.",
         f"- Warm run new enrichment calls: **{warm['enrich_attempts']}** (all other warm-run calls: "
         f"{sum(s['attempts'] for s in warm['stages'].values())}).",
         f"- Cold API cost: **{usd(cold['api_usd'])}**; warm incremental API cost: **{usd(warm['api_usd'])}**; "
         f"unresolved (unknown-usage) estimate: {usd(cold['estimated_unresolved_usd'] + warm['estimated_unresolved_usd'])}.",
         f"- Cost per 1,000 inputs: {usd(m['per_1000_inputs_usd'])}; per completed record: "
         f"{usd(m['per_completed_record_usd'])}; throughput: {m['throughput_reviews_per_s']:.2f} reviews/s (cold).",
         "", "### By stage (cold run)", "",
         "| Stage | Provider / model | Config (model, effort, prompt, schema) | Max batch | Requests | Attempts | OK | Failed | Retries | Ordinary in | Cached in | Cache write | Output | (reasoning) | API cost |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for role, s in cold["stages"].items():
        u = s["units"]
        L.append(f"| {role} | {', '.join(s['provider'])} / {', '.join(s['model'])} | `{'; '.join(s['config'])}` | {s['max_batch']} | "
                 f"{s['requests']} | {s['attempts']} | {s['succeeded']} | {s['failed']} | {s['retries']} | "
                 f"{u.get('ordinary_input', 0):,} | {u.get('cached_input', 0):,} | {u.get('cache_write', 0):,} | "
                 f"{u.get('output', 0):,} | {s['reasoning_tokens']:,} | {usd(s['api_usd'])} |")
    L += ["", "### Billing items (cold + warm)", "", "| Model | Item | Billed units | Price | Cost | Source (checked) |",
          "|---|---|---|---|---|---|"]
    totals = defaultdict(lambda: [0, 0.0])
    for phase in (cold, warm):
        for s in phase["stages"].values():
            for item in ITEMS:
                totals[(s["model"][0], item)][0] += s["units"].get(item, 0)
                totals[(s["model"][0], item)][1] += s["cost"].get(item, 0.0)
    for (model, item), (units, cost) in sorted(totals.items()):
        rate = rates[model][item]
        L.append(f"| {model} | {item} | {units:,} | {rate['quoted']} | {usd(cost)} | {rate['source']} ({rate['checked']}) |")
    L += ["", "Reasoning tokens are included in output tokens by the provider and are not billed again.",
          f"Local compute: {a['local_compute']}", "",
          "## Estimated: full run (assumptions in `cost/assumptions.json`)", "",
          f"Scope: {a['full_run']['source_rows']:,} rows; {a['full_run']['nonempty_to_classify']:,} nonempty; "
          f"{a['full_run']['empty_text_quarantines']} empty-text quarantines; "
          f"{a['full_run']['distinct_nonempty_texts']:,} distinct texts sent once with exact-text reuse.", "",
          f"Measured per-unit inputs: {p['inputs']}", "",
          "| Scenario | Enrich | Enrich without reuse (comparison) | Verify | Group | Memo | Fallback | **Total API** | Budget |",
          "|---|---|---|---|---|---|---|---|---|"]
    ctl = a["controls"]
    for name, s in p["scenarios"].items():
        flag = f"**EXCEEDS ${ctl['budget_usd']:.2f}**" if s["exceeds_budget"] else f"within ${ctl['budget_usd']:.2f}"
        L.append(f"| {name} | {usd(s['enrich_usd'])} | {usd(s['enrich_no_reuse_usd'])} | {usd(s['verify_usd'])} "
                 f"({s['verified_reviews']:,} reviews) | {usd(s['group_usd'])} | {usd(s['memo_usd'])} | "
                 f"{usd(s['fallback_usd'])} | **{usd(s['total_api_usd'])}** | {flag} |")
    L += ["", "| Scenario | Workers | Hours (enrich + verify) | Requests/min | Tokens/min | Within provider limits |",
          "|---|---|---|---|---|---|"]
    for name, s in p["scenarios"].items():
        for w, t in s["hours_by_workers"].items():
            L.append(f"| {name} | {w} | {t['hours']} | {t['requests_per_minute']} | {t['tokens_per_minute']:,} | "
                     f"{'yes' if t['within_provider_limits'] else '**no**'} |")
    L += ["", "## Controls", "",
          f"- Spending limit: ${ctl['budget_usd']:.2f} (enforced in code before each request, counting in-flight reservations).",
          f"- Output-token cap: {ctl['max_output_tokens_per_request']:,} per request; worst case if every enrichment "
          f"request hit it: {usd(p['worst_case_if_every_request_hit_output_cap_usd'])}.",
          f"- Maximum workers: {ctl['max_workers']}. Fallback fraction: {ctl['fallback_fraction']} — {ctl['fallback_note']}",
          "- Retries: transient errors up to 3 attempts with exponential backoff and jitter; invalid output re-sent "
          "once in smaller requests, then quarantined.", "",
          "Measured values come only from the pilot evidence files; editing `assumptions.json` or `rates.csv` "
          "changes projections and prices, never the measured usage or time."]
    return "\n".join(L) + "\n"


def replay(evidence, rates_path, assumptions_path, out=None):
    evidence, rates_path = Path(evidence).resolve(), Path(rates_path).resolve()
    rates = load_rates(rates_path)
    a = json.loads(Path(assumptions_path).read_text())
    m = measured(evidence, rates)
    p = project(m, rates, a)
    report = render(m, p, rates, a, evidence, Path(rates_path))
    out = Path(out or evidence / "report.md")
    out.write_text(report)
    (out.with_suffix(".json")).write_text(json.dumps({"measured": m, "projection": p}, indent=1, default=str))
    return m, p, out


# ---------------------------------------------------------------------------------------------------- pilot
def pilot(client_name, overwrite=False, evidence=None, run_dir=None, source_name="cost_100.csv", workers=1,
          verify_rate=None):
    sys.path.insert(0, str(REPO))
    from pipeline import config
    from pipeline.__main__ import make_client
    from pipeline.export import contract_call, contract_record
    from pipeline.run import run_pipeline
    from pipeline.store import Store

    dataset = REPO.parent / "Final Assignment - Spotify Reviews Dataset"
    source = dataset / source_name
    manifest = json.loads((dataset / "manifest.json").read_text())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != manifest["files"][source_name]["sha256"]:
        raise SystemExit(f"{source_name} does not match the manifest checksum; refusing to run.")
    verify_rate = config.VERIFY_RATE_PILOT if verify_rate is None else verify_rate
    evidence = Path(evidence or (HERE if client_name == "openai" else HERE / "rehearsal-fake"))
    run_dir = Path(run_dir or config.RUNS / ("pilot-100" if client_name == "openai" else "pilot-100-fake"))
    if run_dir.exists() and not overwrite:
        raise SystemExit(f"{run_dir} already exists. The pilot must start from an empty result cache; "
                         "pass --overwrite only if you intend to pay for a new pilot.")
    if run_dir.exists():
        import shutil
        shutil.rmtree(run_dir)
    evidence.mkdir(parents=True, exist_ok=True)

    def clients():
        return {"enrich": make_client(client_name), "verify": make_client(client_name, effort=config.VERIFY_EFFORT),
                "group": make_client(client_name), "memo": make_client(client_name, effort=config.MEMO_EFFORT)}

    phases = {}
    for phase in ("cold", "warm"):
        start = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        summary = run_pipeline(source, run_dir, clients(), workers=workers, verify_rate=verify_rate)
        phases[phase] = {"started_at": start, "summary": summary}

    store = Store(run_dir / "state.sqlite")
    records = list(store.records())
    warm_start = phases["warm"]["started_at"]
    with open(evidence / "pilot_records.jsonl", "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(contract_record(rec), ensure_ascii=False) + "\n")
    calls = list(store.calls())
    with open(evidence / "pilot_calls.jsonl", "w", encoding="utf-8") as f:
        for c in calls:
            f.write(json.dumps({**contract_call(c), "pilot_phase": "warm" if c["started_at"] >= warm_start else "cold",
                                "provider": "openai" if not c["simulated"] else "fake"}) + "\n")
    with open(evidence / "usage.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["request_id", "pilot_phase", "role", "model", "label_config", "outcome", "usage_known",
                    "input_tokens", "cached_input_tokens", "cache_write_tokens", "ordinary_input_tokens",
                    "output_tokens", "reasoning_tokens", "duration_s", "simulated"])
        for c in calls:
            w.writerow([c["request_id"], "warm" if c["started_at"] >= warm_start else "cold", c["role"], c["model"],
                        c["label_config"], c["outcome"], c["usage_known"], c["input_tokens"], c["cached_input_tokens"],
                        c["cache_write_tokens"], c["input_tokens"] - c["cached_input_tokens"] - c["cache_write_tokens"],
                        c["output_tokens"], c["reasoning_tokens"], round(c["duration_s"], 3), c["simulated"]])
    texts = [row["review_text"] for row in csv.DictReader(open(source, encoding="utf-8-sig", newline=""))]
    issues = json.loads((run_dir / "group" / "issues.json").read_text())["issues"]
    run_info = {"input_file": source_name, "input_sha256": digest, "input_matches_manifest": True,
                "input_ids": len(texts), "unique_texts": len({t for t in texts if t.strip()}),
                "cold_cache_reuses": sum(1 for r in records if r["cache_source_id"]), "workers": workers,
                "verify_rate": verify_rate, "empty_cache_at_start": True, "run_dir": run_dir.name,
                "pilot_issue_count": len(issues), "simulated": client_name != "openai",
                "configs": phases["cold"]["summary"]["configs"]}
    for phase, info in phases.items():
        s = info["summary"]
        run_info[phase] = {"started_at": info["started_at"], "status": s["status"], "wall_clock_s": s["wall_clock_s"],
                           "stage_wall_clock_s": {k: v["wall_clock_s"] for k, v in s["stages"].items()},
                           "record_counts": s["record_counts"]}
    (evidence / "pilot_run.json").write_text(json.dumps(run_info, indent=1))
    return replay(evidence, HERE / "rates.csv", HERE / "assumptions.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", nargs="?", choices=["replay", "pilot", "checkpoint"], default="replay")
    parser.add_argument("--input", default="checkpoint_500.csv", help="checkpoint mode: dataset file to measure")
    parser.add_argument("--workers", type=int, default=2, help="checkpoint mode: worker count")
    parser.add_argument("--evidence", type=Path, default=HERE, help="folder with pilot_calls.jsonl etc.")
    parser.add_argument("--rates", type=Path, default=HERE / "rates.csv")
    parser.add_argument("--assumptions", type=Path, default=HERE / "assumptions.json")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--client", choices=["openai", "fake"], default="openai")
    parser.add_argument("--confirm-paid", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.mode == "checkpoint":
        if args.client == "openai" and not args.confirm_paid:
            raise SystemExit("A checkpoint run makes paid API calls. Re-run with --confirm-paid to proceed.")
        sys.path.insert(0, str(REPO))
        from pipeline import config as pc
        name = Path(args.input).stem + (f"-{args.workers}w" if args.client == "openai" else "-fake")
        m, p, out = pilot(args.client, overwrite=args.overwrite, evidence=HERE / name, run_dir=pc.RUNS / name,
                          source_name=args.input, workers=args.workers, verify_rate=pc.VERIFY_RATE)
    elif args.mode == "pilot":
        if args.client == "openai" and not args.confirm_paid:
            raise SystemExit("The pilot makes paid API calls. Re-run with --confirm-paid to proceed.")
        m, p, out = pilot(args.client, overwrite=args.overwrite)
    else:
        if not (args.evidence / "pilot_calls.jsonl").exists():
            raise SystemExit(f"No pilot evidence in {args.evidence}. Run the pilot first, or pass --evidence.")
        m, p, out = replay(args.evidence, args.rates, args.assumptions, args.out)
    base = p["scenarios"]["base"]
    print(f"report: {out}\ncold API ${m['phases']['cold']['api_usd']:.6f} | warm enrichment calls "
          f"{m['phases']['warm']['enrich_attempts']} | full-run base ${base['total_api_usd']:.2f} "
          f"({'EXCEEDS' if base['exceeds_budget'] else 'within'} budget)")


if __name__ == "__main__":
    main()
