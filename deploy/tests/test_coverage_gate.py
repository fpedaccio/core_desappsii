"""Regression checks for incomplete reports and separate line/branch gates."""

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("coverage_gate", Path(__file__).resolve().parents[1] / "check_coverage.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class CoverageGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        for name in ("services", "models"):
            (self.source / name).mkdir()
            (self.source / name / "example.py").write_text("pass\n")
        self.report = {"meta": {"branch_coverage": True}, "files": {
            "app/services/example.py": {"summary": {"covered_lines": 80, "num_statements": 100, "covered_branches": 7, "num_branches": 10}},
            "app/models/example.py": {"summary": {"covered_lines": 20, "num_statements": 20, "covered_branches": 0, "num_branches": 0}},
        }}

    def test_exact_thresholds_pass_without_rounding_up(self):
        self.assertTrue(gate.evaluate(self.report, self.source)["gate"]["passed"])
        self.report["files"]["app/services/example.py"]["summary"]["num_statements"] = 101
        self.assertFalse(gate.evaluate(self.report, self.source)["gate"]["passed"])

    def test_high_model_coverage_cannot_hide_service_branch_deficit(self):
        self.report["files"]["app/services/example.py"]["summary"]["covered_branches"] = 6
        self.assertFalse(gate.evaluate(self.report, self.source)["gate"]["passed"])

    def test_report_without_branch_measurement_is_rejected(self):
        self.report["meta"]["branch_coverage"] = False
        with self.assertRaisesRegex(ValueError, "not enabled"):
            gate.evaluate(self.report, self.source)

    def test_omitting_business_source_cannot_improve_the_result(self):
        (self.source / "services" / "untested.py").write_text("pass\n")
        with self.assertRaisesRegex(ValueError, "missing from coverage"):
            gate.evaluate(self.report, self.source)

    def test_missing_counts_are_not_assumed_zero(self):
        del self.report["files"]["app/services/example.py"]["summary"]["covered_branches"]
        with self.assertRaisesRegex(ValueError, "missing coverage count"):
            gate.evaluate(self.report, self.source)

    def test_models_without_branches_are_na_not_a_hundred_percent(self):
        result = gate.evaluate(self.report, self.source)
        self.assertIsNone(result["groups"]["models"]["branches_percent"])

    def test_absolute_and_windows_paths_are_recognized(self):
        original = copy.deepcopy(self.report["files"])
        self.report["files"] = {"C:\\repo\\" + name.replace("/", "\\"): data for name, data in original.items()}
        self.assertTrue(gate.evaluate(self.report, self.source)["gate"]["passed"])
