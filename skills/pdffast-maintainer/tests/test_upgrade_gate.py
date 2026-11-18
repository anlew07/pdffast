"""Pure policy tests, without external OCR models."""
import importlib.util, unittest
from pathlib import Path
path = Path(__file__).resolve().parents[1] / "scripts/evaluate_upgrade.py"
spec = importlib.util.spec_from_file_location("pdffast_upgrade_gate", path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

class GateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = [{"page_id": "p"+str(i)} for i in range(5)]
        self.gt = [{"page_id": "p"+str(i), "label_status": "approved", "text_gt": "春天到来了"} for i in range(5)]
        self.base = [{"page_id": "p"+str(i), "provider":"old", "status":"SUCCESS", "text":"春天到来了", "elapsed_seconds":1.0} for i in range(5)]
        self.new = [{"page_id": "p"+str(i), "provider":"new", "status":"SUCCESS", "text":"春天到来了", "elapsed_seconds":1.1} for i in range(5)]
    def evaluate(self, **overrides):
        kw = dict(manifest=self.manifest, truth=self.gt, baseline=self.base, candidate=self.new,
                  baseline_name="old", candidate_name="new")
        kw.update(overrides)
        return gate.evaluate(**kw)
    def test_only_end_to_end_eligible(self):
        r = self.evaluate()
        self.assertEqual(r["decision"], "READY_FOR_END_TO_END")
        self.assertFalse(r["production_ready"])
    def test_no_gt_does_not_pass(self):
        self.assertEqual(self.evaluate(truth=None)["decision"], "INSUFFICIENT_EVIDENCE")
    def test_content_regression(self):
        self.new[0]["text"] = "错误识别"
        self.assertEqual(self.evaluate()["decision"], "BLOCKED")
    def test_missing_page(self):
        self.new.pop()
        self.assertEqual(self.evaluate()["decision"], "BLOCKED")
    def test_slow_candidate(self):
        for row in self.new:
            row["elapsed_seconds"] = 2
        self.assertEqual(self.evaluate()["decision"], "BLOCKED")
    def test_duplicate_prediction(self):
        self.new.append(dict(self.new[0]))
        with self.assertRaises(ValueError):
            self.evaluate()

if __name__ == "__main__":
    unittest.main()
