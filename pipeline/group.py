"""Grouping stage. Code owns membership; the model only names issues.

1. Code assigns every completed complaint/cancellation to exactly one issue (pipeline/issues.py rules) and saves
   membership.csv (issue_id, review_id). Every original review ID is kept, including exact-duplicate copies.
2. Code builds a bounded evidence pack: up to 6 example quotes per issue, chosen by a seeded hash.
3. One model call names each issue from that pack. Code accepts a name only if the issue IDs match exactly, the
   cited examples come from that issue's pack, and the description contains no numbers. Invalid output is retried
   once; after that the rule text is used as the name and the failure is recorded.
4. If the evidence pack and settings are unchanged, the saved names are reused with no model call.

Outputs under <run>/group/: membership.csv, issues.json, evidence_pack.json
"""

import csv
import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone

from . import config
from .enrich import call_with_backoff, record_attempts, reservation_usd
from .issues import ISSUE_RULES_VERSION, issue_for
from .store import Store

RANKED_INTENTS = {"complaint", "cancellation"}


def _seeded(review_id, seed="group-v1"):
    return hashlib.sha256(f"{seed}:{review_id}".encode("utf-8")).hexdigest()


def assign(store):
    """Return {issue_id: {"rule": str, "members": [review_id, ...]}} for completed complaints/cancellations."""
    issues = defaultdict(lambda: {"rule": None, "members": [], "originals": []})
    for r in store.records():
        if r["status"] != "completed" or r["labels"]["intent"] not in RANKED_INTENTS:
            continue
        issue_id, rule = issue_for(r["labels"])
        issues[issue_id]["rule"] = rule
        issues[issue_id]["members"].append(r["review_id"])
        if not r["cache_source_id"]:
            issues[issue_id]["originals"].append((r["review_id"], r["labels"]["evidence_quote"]))
    return dict(sorted(issues.items()))


def evidence_pack(issues):
    pack = {}
    for issue_id, info in issues.items():
        chosen = sorted(info["originals"], key=lambda x: _seeded(x[0]))[:config.GROUP_EXAMPLES_PER_ISSUE]
        pack[issue_id] = {"rule": info["rule"], "examples": [
            {"review_id": rid, "quote": q if len(q) <= config.GROUP_QUOTE_CHARS else q[:config.GROUP_QUOTE_CHARS] + "…"}
            for rid, q in chosen]}
    return pack


def render_pack(pack):
    lines = []
    for issue_id, info in pack.items():
        lines.append(f"ISSUE {issue_id} (grouping rule: {info['rule']})")
        lines += [f"[{e['review_id']}] {e['quote']}" for e in info["examples"]]
        lines.append("")
    return "<issues>\n" + "\n".join(lines) + "</issues>"


def validate_names(raw_text, complete, pack):
    """Return (accepted names by issue id, error or None)."""
    if not complete:
        return {}, "incomplete_output"
    try:
        items = json.loads(raw_text)["issues"]
    except (ValueError, KeyError, TypeError):
        return {}, "unparseable_json"
    ids = [i.get("id") for i in items if isinstance(i, dict)]
    if sorted(ids) != sorted(pack):
        return {}, "issue_ids_do_not_match"
    accepted, problems = {}, []
    for item in items:
        allowed = {e["review_id"] for e in pack[item["id"]]["examples"]}
        ok = (isinstance(item["name"], str) and 0 < len(item["name"]) <= 60
              and isinstance(item["description"], str) and 0 < len(item["description"]) <= 200
              and not re.search(r"\d", item["description"])
              and isinstance(item["examples"], list) and 1 <= len(item["examples"]) <= 3
              and set(item["examples"]) <= allowed)
        if ok:
            accepted[item["id"]] = item
        else:
            problems.append(item["id"])
    return accepted, (f"rejected:{','.join(problems)}" if problems else None)


class Grouper:
    def __init__(self, run_dir, client, spend_cap=config.SPEND_CAP_USD, sleep=time.sleep, log=print):
        self.run_dir, self.client, self.spend_cap, self.sleep, self.log = run_dir, client, spend_cap, sleep, log
        self.store = Store(run_dir / "state.sqlite")
        self.out = run_dir / "group"
        self.system_prompt = config.GROUP_PROMPT_FILE.read_text(encoding="utf-8")
        self.schema = json.loads(config.GROUP_SCHEMA_FILE.read_text(encoding="utf-8"))

    def run(self):
        t0 = time.monotonic()
        run_id = datetime.now(timezone.utc).strftime("group-%Y%m%dT%H%M%S%fZ")
        issues = assign(self.store)
        self.out.mkdir(parents=True, exist_ok=True)
        with open(self.out / "membership.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["issue_id", "review_id"])
            for issue_id, info in issues.items():
                w.writerows([issue_id, rid] for rid in info["members"])
        pack = evidence_pack(issues)
        message = render_pack(pack)
        pack_hash = hashlib.sha256((config.GROUP_CONFIG + self.system_prompt + message).encode("utf-8")).hexdigest()
        (self.out / "evidence_pack.json").write_text(json.dumps({"pack_sha256": pack_hash, "issues": pack}, indent=1))

        saved = self._load_saved()
        if saved.get("pack_sha256") == pack_hash:
            names, calls, source = {i["issue_id"]: i for i in saved["issues"]}, 0, "reused_saved_names"
        else:
            names, calls, source = self._name(run_id, pack, message), 1, "model"
        result = {"group_config": config.GROUP_CONFIG, "issue_rules": ISSUE_RULES_VERSION, "pack_sha256": pack_hash,
                  "naming_source": source, "issues": []}
        for issue_id, info in issues.items():
            named = names.get(issue_id, {})
            result["issues"].append({
                "issue_id": issue_id, "rule": info["rule"], "member_count": len(info["members"]),
                "name": named.get("name") or issue_id.replace(".", ": ").replace("_", " "),
                "description": named.get("description") or f"Grouped by rule: {info['rule']}",
                "example_review_ids": named.get("example_review_ids") or named.get("examples") or [],
                "name_source": named.get("name_source", "model" if named else "rule_fallback")})
        (self.out / "issues.json").write_text(json.dumps(result, indent=1))
        members = sum(len(i["members"]) for i in issues.values())
        self.log(f"[{run_id}] issues={len(issues)} members={members} naming={source} "
                 f"({time.monotonic() - t0:.1f}s)")
        return {"run_id": run_id, "issues": len(issues), "members": members, "naming_source": source,
                "model_calls": calls}

    def _load_saved(self):
        try:
            return json.loads((self.out / "issues.json").read_text())
        except (OSError, ValueError):
            return {}

    def _name(self, run_id, pack, message):
        if not pack:
            return {}
        ids = [e["review_id"] for info in pack.values() for e in info["examples"]]
        reserved = reservation_usd(self.client.model, self.system_prompt, message)
        if self.store.spent_usd() + reserved > self.spend_cap:
            self.log("group: spend cap reached; using rule names")
            return {}
        for attempt_round in (1, 2):                      # one retry for invalid output
            resp, attempts, permanent = call_with_backoff(self.client, self.system_prompt, message, self.schema, self.sleep)
            accepted, error = validate_names(resp.text, resp.complete, pack) if resp else ({}, "transient_exhausted")
            with self.store.transaction() as db:
                record_attempts(self.store, db, self.client, attempts, run_id=run_id, role="group", phase="group",
                                label_config=config.GROUP_CONFIG, review_ids=ids, reserved=reserved,
                                succeeded=bool(accepted), error=error, is_retry=attempt_round == 2)
            if accepted and not error:
                break
            if permanent or resp is None:
                break
        return {k: {**v, "example_review_ids": v["examples"], "name_source": "model"} for k, v in accepted.items()}
