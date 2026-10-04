"""Calculator tests: the instructor's checks, run against a $0 fake-model rehearsal of the real cost_100.csv."""

import csv
import importlib
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cost import calculator

REPO = Path(__file__).resolve().parent.parent


class CalculatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.evidence = cls.dir / "evidence"
        with mock.patch("builtins.print"):
            calculator.pilot("fake", evidence=cls.evidence, run_dir=cls.dir / "run")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def replay(self, rates=None, assumptions=None, name="r.md"):
        return calculator.replay(self.evidence, rates or REPO / "cost" / "rates.csv",
                                 assumptions or REPO / "cost" / "assumptions.json", self.dir / name)

    def test_pilot_evidence_covers_the_100_ids(self):
        records = calculator.load_jsonl(self.evidence / "pilot_records.jsonl")
        source = REPO.parent / "Final Assignment - Spotify Reviews Dataset" / "cost_100.csv"
        ids = [r["review_id"] for r in csv.DictReader(open(source, encoding="utf-8-sig", newline=""))]
        self.assertEqual(sorted(r["review_id"] for r in records), sorted(ids))
        self.assertTrue(all(r["status"] in ("completed", "quarantined") for r in records))

    def test_warm_run_has_zero_enrichment_calls(self):
        m, _, _ = self.replay()
        self.assertGreater(m["phases"]["cold"]["enrich_attempts"], 0)
        self.assertEqual(m["phases"]["warm"]["enrich_attempts"], 0)

    def test_doubling_rates_doubles_api_cost_and_leaves_time_unchanged(self):
        doubled = self.dir / "doubled.csv"
        rows = list(csv.DictReader(open(REPO / "cost" / "rates.csv")))
        with open(doubled, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            for r in rows:
                w.writerow({**r, "usd_per_unit_size": str(float(r["usd_per_unit_size"]) * 2)})
        m1, p1, _ = self.replay()
        m2, p2, _ = self.replay(rates=doubled, name="d.md")
        self.assertAlmostEqual(m2["phases"]["cold"]["api_usd"], 2 * m1["phases"]["cold"]["api_usd"])
        self.assertEqual(m1["phases"]["cold"]["wall_clock_s"], m2["phases"]["cold"]["wall_clock_s"])
        self.assertAlmostEqual(p2["scenarios"]["base"]["total_api_usd"], 2 * p1["scenarios"]["base"]["total_api_usd"])

    def test_changing_projected_volume_does_not_change_measured_results(self):
        a = json.loads((REPO / "cost" / "assumptions.json").read_text())
        a["full_run"]["distinct_nonempty_texts"] *= 3
        bigger = self.dir / "a.json"
        bigger.write_text(json.dumps(a))
        m1, p1, _ = self.replay()
        m2, p2, _ = self.replay(assumptions=bigger, name="b.md")
        self.assertEqual(json.dumps(m1, sort_keys=True, default=str), json.dumps(m2, sort_keys=True, default=str))
        self.assertGreater(p2["scenarios"]["base"]["enrich_usd"], p1["scenarios"]["base"]["enrich_usd"])

    def test_budget_warning(self):
        a = json.loads((REPO / "cost" / "assumptions.json").read_text())
        a["controls"]["budget_usd"] = 0.0001
        tiny = self.dir / "tiny.json"
        tiny.write_text(json.dumps(a))
        _, p, out = self.replay(assumptions=tiny, name="t.md")
        self.assertTrue(p["scenarios"]["base"]["exceeds_budget"])
        self.assertIn("EXCEEDS", out.read_text())

    def test_arithmetic_is_units_times_price(self):
        calls = calculator.load_jsonl(self.evidence / "pilot_calls.jsonl")
        rates = calculator.load_rates(REPO / "cost" / "rates.csv")
        c = next(c for c in calls if c["usage_known"])
        cost, _ = calculator.call_cost(c, rates)
        units = calculator.billed_units(c)
        self.assertAlmostEqual(sum(cost.values()), sum(units[i] * rates[c["model"]][i]["per_unit"] for i in units))
        self.assertEqual(units["ordinary_input"], c["input_tokens"] - c["cached_input_tokens"] - c["cache_write_tokens"])

    def test_offline_replay_needs_no_network_or_key(self):
        def no_network(*a, **k):
            raise AssertionError("network used during offline replay")
        with mock.patch.object(socket, "create_connection", no_network), mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            self.replay(name="offline.md")

    def test_importing_calculator_starts_nothing(self):
        out = subprocess.run([sys.executable, "-c", "import cost.calculator; print('imported')"], cwd=REPO,
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), "imported")

    def test_paid_pilot_requires_explicit_flag(self):
        out = subprocess.run([sys.executable, "cost/calculator.py", "pilot"], cwd=REPO, capture_output=True,
                             text=True, timeout=30)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("--confirm-paid", out.stderr)


if __name__ == "__main__":
    unittest.main()
