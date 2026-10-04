"""Verification-stage tests with the fake model only ($0). Fixture reviews are synthetic."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import config
from pipeline.clients import FakeClient
from pipeline.enrich import Enricher
from pipeline.verify import Verifier, in_sample
from tests.test_enrich import write_fixture


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.csv = self.dir / "fixture.csv"
        write_fixture(self.csv)
        quiet = dict(sleep=lambda s: None, log=lambda *a: None)
        self.enricher = Enricher(self.csv, self.dir / "run", FakeClient(), **quiet)
        self.enricher.run()
        self.quiet = quiet

    def tearDown(self):
        self.tmp.cleanup()

    def verifier(self, client, rate=0.3, **kw):
        return Verifier(self.dir / "run", client, rate=rate, **self.quiet, **kw)

    def test_sample_is_declared_reproducible_and_excludes_cache_copies(self):
        v = self.verifier(FakeClient())
        ids = [r["review_id"] for r in v.sample()]
        self.assertEqual(ids, [r["review_id"] for r in self.verifier(FakeClient()).sample()])
        self.assertTrue(all(in_sample(i, 0.3) for i in ids))
        recs = {r["review_id"]: r for r in v.store.records()}
        self.assertTrue(all(recs[i]["cache_source_id"] is None and recs[i]["status"] == "completed" for i in ids))
        self.assertTrue(10 < len(ids) < 70, len(ids))

    def test_verifier_never_sees_enrichment_labels(self):
        client = FakeClient()
        self.verifier(client).run()
        enrich_prompt = config.PROMPT_FILE.read_text()
        for system, message in client.messages:
            self.assertEqual(system, config.VERIFY_PROMPT_FILE.read_text(), "separate instructions")
            self.assertNotEqual(system, enrich_prompt)
            self.assertNotIn('"t":', message)
            self.assertNotIn("complaint", message.replace("complain", ""))  # no label words injected by code

    def test_full_agreement_when_fake_models_match(self):
        s = self.verifier(FakeClient()).run()
        self.assertEqual(s["verified"], s["sample_size"])
        self.assertEqual(s["agreement"]["topic"], 1.0)
        self.assertEqual(s["disagreements"], 0)

    def test_disagreements_are_reported_with_both_labels(self):
        s = self.verifier(FakeClient(perturb_every=3)).run()
        self.assertGreater(s["disagreements"], 0)
        self.assertLess(s["agreement"]["topic"], 1.0)
        rows = list(csv.DictReader(open(self.dir / "run" / "verify" / "disagreements.csv")))
        self.assertEqual(len(rows), s["disagreements"])
        self.assertTrue(all(r["enrich_topic"] != r["verify_topic"] for r in rows if "topic" in r["fields_differing"]))

    def test_planted_errors_are_caught_and_marked_synthetic(self):
        v = self.verifier(FakeClient())
        v.run()
        result = v.planted_error_test(10)
        self.assertTrue(result["synthetic"] and result["exclude_from_business_results"])
        self.assertEqual(result["planted"], 10)
        self.assertEqual(result["caught"], 10)
        self.assertTrue(all(c["planted_wrong_topic"] != c["original_topic"] for c in result["cases"]))
        recs = {r["review_id"]: r["labels"]["topic"] for r in v.store.records() if r["labels"]}
        self.assertTrue(all(recs[c["review_id"]] == c["original_topic"] for c in result["cases"]), "real records untouched")

    def test_calls_logged_as_verify_role_and_resume_makes_no_new_calls(self):
        self.verifier(FakeClient()).run()
        calls = [c for c in self.enricher.store.calls() if c["role"] == "verify"]
        self.assertTrue(calls and all(c["label_config"] == config.VERIFY_CONFIG for c in calls))
        self.assertTrue(all(len(c["review_ids"]) <= 50 for c in calls))
        again = FakeClient()
        self.verifier(again).run()
        self.assertEqual(again.calls, 0)

    def test_invalid_verifier_items_retry_once_then_fail_visibly(self):
        s = self.verifier(FakeClient(behaviors=["bad_segment", "bad_segment"])).run()
        self.assertGreaterEqual(s["failed"], 1)
        self.assertEqual(s["verified"] + s["failed"], s["sample_size"])

    def test_shared_spend_cap(self):
        s = self.verifier(FakeClient(), spend_cap=self.enricher.store.spent_usd()).run()
        self.assertEqual(s["stop_reason"], "spend_cap")
        self.assertEqual(s["verified"], 0)


if __name__ == "__main__":
    unittest.main()
