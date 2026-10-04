"""A real Ctrl-C (SIGINT) delivered to a running enrichment process, then a resume. Fake model, $0."""

import json
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from pipeline.clients import FakeClient
from pipeline.enrich import Enricher
from tests.test_enrich import write_fixture

REPO = Path(__file__).resolve().parent.parent
SCRIPT = """
import sys
from pathlib import Path
from pipeline.clients import FakeClient
from pipeline.enrich import Enricher
from pipeline import config
config.MAX_BATCH = 5                       # many small requests so the interrupt lands mid-run
Enricher(Path(sys.argv[1]), Path(sys.argv[2]), FakeClient(latency_s=0.3), workers=2, sleep=lambda s: None).run()
"""


class CtrlCTests(unittest.TestCase):
    def test_sigint_saves_in_flight_work_and_resume_finishes_without_relabeling(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_fixture(d / "f.csv")
            proc = subprocess.Popen([sys.executable, "-c", SCRIPT, str(d / "f.csv"), str(d / "run")], cwd=REPO,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            time.sleep(2.0)
            proc.send_signal(signal.SIGINT)
            out, _ = proc.communicate(timeout=30)
            self.assertEqual(proc.returncode, 0, out)
            self.assertIn("Ctrl-C received", out)
            checkpoint = next((d / "run" / "checkpoints").glob("*_interrupted.json"))
            before = json.loads(checkpoint.read_text())
            self.assertGreater(len(before["completed_ids"]), 0)
            self.assertGreater(before["counts"].get("pending", 0), 0)
            e = Enricher(d / "f.csv", d / "run", FakeClient(), sleep=lambda s: None, log=lambda *a: None)
            calls_before = {c["request_id"] for c in e.store.calls()}
            self.assertTrue(all(c["outcome"] in ("succeeded", "failed") for c in e.store.calls()))
            summary = e.run()
            self.assertEqual(summary["phase"], "resume")
            self.assertEqual(summary["stop_reason"], "complete")
            resumed = [c for c in e.store.calls() if c["request_id"] not in calls_before]
            sent_again = set(before["completed_ids"]) & {rid for c in resumed for rid in c["review_ids"]}
            self.assertFalse(sent_again, "no completed ID re-sent after resume")
            self.assertEqual(summary["counts"], {"completed": 140, "quarantined": 2})


if __name__ == "__main__":
    unittest.main()
