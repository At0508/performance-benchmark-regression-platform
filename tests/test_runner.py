import json
import sys
import tempfile
import unittest
from pathlib import Path

from benchreg.runner import run_suite


class RunnerTests(unittest.TestCase):
    def test_runs_commands_and_writes_reports(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            root = Path(temp)
            suite = root / "suite.json"
            suite.write_text(json.dumps({
                "schema_version": 1,
                "name": "tiny",
                "benchmarks": [{"id": "ok", "command": [sys.executable, "-c", "print('ok')"],
                                "warmups": 1, "repetitions": 2}],
            }), encoding="utf-8")
            report = run_suite(suite, root / "out")
            case = report["cases"][0]
            self.assertEqual(case["status"], "new")
            self.assertEqual(len(case["samples_ms"]), 2)
            self.assertTrue((root / "out" / "report.json").exists())
            self.assertTrue((root / "out" / "summary.csv").exists())
            self.assertTrue((root / "out" / "summary.md").exists())

    def test_marks_nonzero_exit_as_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            root = Path(temp)
            suite = root / "suite.json"
            suite.write_text(json.dumps({
                "schema_version": 1,
                "benchmarks": [{"id": "bad", "command": [sys.executable, "-c", "raise SystemExit(3)"],
                                "repetitions": 1}],
            }), encoding="utf-8")
            report = run_suite(suite, root / "out")
            self.assertEqual(report["cases"][0]["status"], "failed")
            self.assertEqual(report["cases"][0]["failures"][0]["return_code"], 3)

    def test_compares_against_baseline_with_threshold(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            root = Path(temp)
            suite = root / "suite.json"
            suite.write_text(json.dumps({
                "schema_version": 1,
                "benchmarks": [{"id": "ok", "command": [sys.executable, "-c", "print('ok')"],
                                "repetitions": 2}],
            }), encoding="utf-8")
            baseline_path = root / "baseline.json"
            baseline_path.write_text(json.dumps({"cases": [{"id": "ok", "median_ms": 1e9}]}),
                                     encoding="utf-8")
            report = run_suite(suite, root / "out", baseline_path)
            self.assertEqual(report["cases"][0]["status"], "improvement")

    def test_timeout_is_recorded(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            root = Path(temp)
            suite = root / "suite.json"
            suite.write_text(json.dumps({
                "schema_version": 1,
                "benchmarks": [{"id": "slow", "command": [sys.executable, "-c",
                                "import time; time.sleep(1)"], "repetitions": 1,
                                "timeout_seconds": 0.05}],
            }), encoding="utf-8")
            report = run_suite(suite, root / "out")
            failure = report["cases"][0]["failures"][0]
            self.assertTrue(failure["timed_out"])
            self.assertEqual(report["cases"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
