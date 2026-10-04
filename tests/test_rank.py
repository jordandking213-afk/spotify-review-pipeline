"""Rank-stage tests: pure code, no model client involved at all."""

import csv
import filecmp
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pipeline import rank
from pipeline.clients import FakeClient
from pipeline.enrich import Enricher
from pipeline.group import Grouper
from tests.test_enrich import write_fixture


class ComputeRankingTests(unittest.TestCase):
    def test_contract_formula_tiebreak_and_rounding(self):
        severity = {"a": 3, "b": 3, "c": 2, "d": 4, "e": 2, "f": 1, "g": 1, "h": 1}
        membership = [("z.issue", "a"), ("z.issue", "b"),          # score 6
                      ("a.issue", "d"), ("a.issue", "c"),          # score 6, wins tie (ascending id)
                      ("m.issue", "e"), ("m.issue", "f"), ("m.issue", "g")]  # score 4, mean 4/3
        rows = rank.compute_ranking(severity, membership)
        self.assertEqual([r["issue_id"] for r in rows], ["a.issue", "z.issue", "m.issue"])
        self.assertEqual([r["rank"] for r in rows], [1, 2, 3])
        self.assertEqual(rows[2]["mean_severity"], "1.333333")
        self.assertEqual(rows[0]["mean_severity"], "3.000000")
        for r in rows:
            self.assertEqual(r["priority_score"], r["severity_sum"])

    def test_half_up_rounding(self):
        # 2.0000005 must round up to 2.000001 (banker's rounding would give 2.000000)
        severity = {str(i): (3 if i == 0 else 2) for i in range(2_000_000)}
        rows = rank.compute_ranking(severity, [("x", str(i)) for i in range(2_000_000)])
        self.assertEqual(rows[0]["mean_severity"], "2.000001")   # 4_000_001 / 2_000_000 = 2.0000005


class RankStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # Synthetic paywall complaints so the sensitivity check has something to re-score.
        write_fixture(self.dir / "fixture.csv", extra=[f"Can't skip songs without premium, bad ({i})" for i in range(4)])
        quiet = dict(sleep=lambda s: None, log=lambda *a: None)
        Enricher(self.dir / "fixture.csv", self.dir / "run", FakeClient(), **quiet).run()
        Grouper(self.dir / "run", FakeClient(), **quiet).run()

    def tearDown(self):
        self.tmp.cleanup()

    def test_outputs_and_byte_identical_rerun(self):
        rank.run(self.dir / "run", log=lambda *a: None)
        first = self.dir / "first"
        shutil.copytree(self.dir / "run" / "rank", first)
        rank.run(self.dir / "run", log=lambda *a: None)
        for name in ("ranking.csv", "aggregates.csv", "ranking_paywall_sev2.csv", "sensitivity.json"):
            self.assertTrue(filecmp.cmp(first / name, self.dir / "run" / "rank" / name, shallow=False), name)
        header = next(csv.reader(open(first / "ranking.csv")))
        self.assertEqual(header, ["rank", "issue_id", "complaint_count", "severity_sum", "mean_severity", "priority_score"])

    def test_counts_match_membership(self):
        rank.run(self.dir / "run", log=lambda *a: None)
        membership = list(csv.DictReader(open(self.dir / "run" / "group" / "membership.csv")))
        rows = list(csv.DictReader(open(self.dir / "run" / "rank" / "ranking.csv")))
        self.assertEqual(sum(int(r["complaint_count"]) for r in rows), len(membership))

    def test_sensitivity_only_lowers_paywall_named_severity_3(self):
        summary = rank.run(self.dir / "run", log=lambda *a: None)
        base = {r["issue_id"]: int(r["priority_score"]) for r in csv.DictReader(open(self.dir / "run" / "rank" / "ranking.csv"))}
        alt = {r["issue_id"]: int(r["priority_score"]) for r in csv.DictReader(open(self.dir / "run" / "rank" / "ranking_paywall_sev2.csv"))}
        drop = {i: base[i] - alt[i] for i in base if base[i] != alt[i]}
        self.assertGreater(summary["sensitivity"]["reviews_rescored"], 0)
        self.assertEqual(set(drop), {"billing.paywall_named_feature"}, drop)
        self.assertEqual(sum(drop.values()), summary["sensitivity"]["reviews_rescored"])


if __name__ == "__main__":
    unittest.main()
