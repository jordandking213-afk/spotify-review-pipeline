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
        self.assertLessEqual(quoted, 3 * 12, "at most 3 quotes for each top issue of the two rankings")
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


class MemoRegressionTests(unittest.TestCase):
    """Pilot attempt 1 failed because fixed text handed to the memo model contained digits."""

    def test_fixed_limitations_text_is_digit_free(self):
        from pipeline.memo import LIMITATIONS
        self.assertFalse([t for t in LIMITATIONS if re.search(r"\d", t)])

    def test_memo_message_has_digits_only_in_values_and_review_ids(self):
        tmp = tempfile.TemporaryDirectory()
        d = Path(tmp.name)
        q = dict(sleep=lambda s: None, log=lambda *a: None)
        write_fixture(d / "f.csv")
        Enricher(d / "f.csv", d / "run", FakeClient(), **q).run()
        Grouper(d / "run", FakeClient(), **q).run()
        rank.run(d / "run", log=lambda *a: None)
        client = FakeClient()
        MemoWriter(d / "run", client, **q).run()
        _, message = client.messages[-1]
        for line in message.splitlines():
            if re.match(r"^[CX]\d+ = ", line) or "[review:" in line:
                continue
            self.assertFalse(re.search(r"\d", line), line)
        tmp.cleanup()

    def test_error_message_shows_offending_text(self):
        claims = [{"claim_id": "C1", "issue_id": "a.b", "metric": "complaint_count", "value": "5"}]
        pack = {"a.b": {"examples": [{"review_id": "r1", "quote": "q"}]}}
        memo = {"recommendation": "Fix `a.b` first with {C1} complaints since twenty twenty three.",
                "supporting_evidence": "Shown by {C1} reports such as [review:r1] here.",
                "alternatives": "Other areas are lower, as the totals show clearly.",
                "sensitivity": "No change to the top issue in the sensitivity check.",
                "limitations": "Reviews from May 2022 onward are self-selected."}
        _, problems = validate_memo(json.dumps(memo), True, claims, [], pack, {"a.b"})
        self.assertTrue(any("2022" in p for p in problems), problems)


class IssueLevelRuleTests(unittest.TestCase):
    """memo-v3 passed every check while misstating which area was largest; memo-v4 adds order facts and these checks."""
    claims = [{"claim_id": "C1", "issue_id": "playback.general", "metric": "priority_score", "value": "9"}]
    pack = {"playback.general": {"examples": [{"review_id": "r1", "quote": "q"}]}}
    facts = {"area_order": ["usability", "playback", "billing/support", "access"], "top_issue": "playback.general",
             "top_issue_area": "playback", "other_general_baseline_rank": "1"}
    base = {"recommendation": "Prioritize playback: `playback.general` is the top specific issue at {C1}.",
            "supporting_evidence": "It scores {C1}, as in [review:r1] about stopping.",
            "alternatives": "Usability has the largest area total, but it is spread across several issues.",
            "sensitivity": "The top issue does not change in the sensitivity check.",
            "limitations": "Self-selected reviews; cancellation intent is not churn."}

    def check(self, **changes):
        memo = {**self.base, **changes}
        return validate_memo(json.dumps(memo), True, self.claims, [], self.pack,
                             {"playback.general", "usability.ads"}, self.facts)

    def test_accepts_memo_following_the_rule(self):
        self.assertIsNotNone(self.check()[0])

    def test_rejects_recommendation_without_top_issue(self):
        memo, problems = self.check(recommendation="Prioritize usability, led by `usability.ads` at {C1}.")
        self.assertIsNone(memo)
        self.assertTrue(any("top specific issue" in p for p in problems))

    def test_rejects_memo_hiding_the_largest_area(self):
        memo, problems = self.check(alternatives="Other areas are smaller than playback overall.")
        self.assertIsNone(memo)
        self.assertTrue(any("largest area total" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
