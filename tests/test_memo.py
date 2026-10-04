"""Memo-stage tests with the fake model only ($0). Fixture reviews are synthetic."""

import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

from pipeline import rank
from pipeline.clients import FakeClient
from pipeline.enrich import Enricher
from pipeline.group import Grouper
from pipeline.memo import MemoWriter, validate_memo
from tests.test_enrich import write_fixture


class MemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_fixture(self.dir / "fixture.csv", extra=[f"Can't skip songs without premium, bad ({i})" for i in range(4)])
        self.quiet = dict(sleep=lambda s: None, log=lambda *a: None)
        self.enricher = Enricher(self.dir / "fixture.csv", self.dir / "run", FakeClient(), **self.quiet)
        self.enricher.run()
        Grouper(self.dir / "run", FakeClient(), **self.quiet).run()
        rank.run(self.dir / "run", log=lambda *a: None)
        self.memo_dir = self.dir / "run" / "memo"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, client):
        return MemoWriter(self.dir / "run", client, **self.quiet).run()

    def test_numbers_in_memo_all_trace_to_claims_and_ranking(self):
        check = self.write(FakeClient())
        self.assertTrue(check["passed"], check)
        claims = list(csv.DictReader(open(self.memo_dir / "claims.csv")))
        self.assertTrue(claims)
        ranking = {r["issue_id"]: r for r in csv.DictReader(open(self.dir / "run" / "rank" / "ranking.csv"))}
        for c in claims:   # the same comparison the course checker makes
            self.assertEqual(ranking[c["issue_id"]][c["metric"]], c["value"])
        memo = (self.memo_dir / "memo.md").read_text()
        body = memo.split("## Numbers used in this memo")[0]
        for value, ref in re.findall(r"(\S+) \(([CX]\d+)\)", body):
            self.assertIn(ref, memo.split("## Numbers used in this memo")[1])

    def test_invented_numbers_and_ids_rejected_then_retry_once(self):
        check = self.write(FakeClient(behaviors=["bad_memo", "bad_memo"]))
        self.assertFalse(check["passed"])
        self.assertTrue(any("number not written as a reference" in p for p in check["problems"]))
        self.assertTrue(any("review id not in evidence" in p for p in check["problems"]))
        self.assertFalse((self.memo_dir / "memo.md").exists(), "no memo is written when checks fail")
        memo_calls = [c for c in self.enricher.store.calls() if c["role"] == "memo"]
        self.assertEqual(len(memo_calls), 2)
        self.assertTrue(all(c["outcome"] == "failed" for c in memo_calls))

    def test_bad_first_attempt_recovers_on_retry(self):
        check = self.write(FakeClient(behaviors=["bad_memo"]))
        self.assertTrue(check["passed"])

    def test_warm_rerun_reuses_memo_with_zero_calls(self):
        self.write(FakeClient())
        first = (self.memo_dir / "memo.md").read_text()
        again = FakeClient()
        check = self.write(again)
        self.assertEqual(again.calls, 0)
        self.assertEqual(check["model_calls_this_run"], 0)
        self.assertEqual(first, (self.memo_dir / "memo.md").read_text())

    def test_memo_input_is_bounded_aggregates_not_raw_data(self):
        client = FakeClient()
        self.write(client)
        _, message = client.messages[-1]
        quantities = json.loads((self.memo_dir / "quantities.json").read_text())
        quoted = message.count("[review:")
        self.assertLessEqual(quoted, 3 * 6, "at most 3 quotes for each of the top 6 issues")
        self.assertLess(len(message), 20_000)
        self.assertTrue(quantities["claims"])

    def test_validator_unit_cases(self):
        claims = [{"claim_id": "C1", "issue_id": "a.b", "metric": "complaint_count", "value": "5"}]
        extra = [{"id": "X1", "label": "x", "value": "9", "formula": "f"}]
        pack = {"a.b": {"examples": [{"review_id": "r1", "quote": "q"}]}}
        good = {"recommendation": "Fix `a.b` first, with {C1} complaints overall.",
                "supporting_evidence": "Shown by {C1} reports such as [review:r1] here.",
                "alternatives": "Other areas total {X1} complaints, which is lower.",
                "sensitivity": "No change to the top issue in the sensitivity check.",
                "limitations": "Self-selected reviews; cancellation intent is not churn."}
        self.assertIsNotNone(validate_memo(json.dumps(good), True, claims, extra, pack, {"a.b"})[0])
        for field, bad in (("recommendation", "Fix `a.b` now: 5 complaints and {C1}."),
                           ("recommendation", "Fix `zz.top` first {C1} complaints overall."),
                           ("alternatives", "Lower totals of {X7} complaints in other areas."),
                           ("supporting_evidence", "Shown by {C1} reports such as [review:r9] here.")):
            memo = {**good, field: bad}
            self.assertIsNone(validate_memo(json.dumps(memo), True, claims, extra, pack, {"a.b"})[0], bad)


if __name__ == "__main__":
    unittest.main()
