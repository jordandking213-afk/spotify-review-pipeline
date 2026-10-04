"""End to end with the fake model: interrupted run -> resume -> verify/group/rank/memo -> grading export ->
the course's own checker. Expect a clean pass. Fixture reviews are synthetic; $0."""

import tempfile
import unittest
from pathlib import Path

from pipeline import rank
from pipeline.clients import FakeClient
from pipeline.enrich import Enricher
from pipeline.grading_export import export, self_check
from pipeline.group import Grouper
from pipeline.memo import MemoWriter
from pipeline.verify import Verifier
from tests.test_enrich import write_fixture


class GradingExportTests(unittest.TestCase):
    def test_course_checker_passes_on_interrupted_then_resumed_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            q = dict(sleep=lambda s: None, log=lambda *a: None)
            write_fixture(d / "f.csv", extra=[f"Can't skip songs without premium, bad ({i})" for i in range(4)])
            first = Enricher(d / "f.csv", d / "run", FakeClient(), max_batches=1, **q).run()
            self.assertEqual(first["stop_reason"], "max_batches")
            Enricher(d / "f.csv", d / "run", FakeClient(), **q).run()
            Verifier(d / "run", FakeClient(), rate=0.3, **q).run()
            Grouper(d / "run", FakeClient(), **q).run()
            rank.run(d / "run", log=lambda *a: None)
            self.assertTrue(MemoWriter(d / "run", FakeClient(), **q).run()["passed"])
            summary = export(d / "run", d / "grading")
            self.assertGreater(summary["checkpoint_before_ids"], 0)
            report = self_check(d / "run", d / "grading")
            self.assertEqual(report["issue_counts"], {}, report["examples"])
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["working_coverage_point_candidate"], 1.0)
            self.assertFalse((d / "grading" / "self-check.json").exists(), "report stays outside the grading folder")


if __name__ == "__main__":
    unittest.main()
