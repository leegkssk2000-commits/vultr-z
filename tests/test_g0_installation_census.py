import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "g0_installation_census.py"
SPEC = importlib.util.spec_from_file_location("g0_installation_census", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class G0InstallationCensusTests(unittest.TestCase):
    def test_workflow_trigger_parser(self):
        text = "name: x\non:\n  push:\n  pull_request:\njobs:\n  x:\n"
        self.assertEqual(["pull_request", "push"], MODULE.workflow_triggers(text))

    def test_static_census_holds_without_runtime_proof(self):
        receipt = MODULE.make_receipt(None)
        self.assertIn(receipt["state"], {"HOLD_G0A_RUNTIME_OR_STATIC_CENSUS", "PASS_G0A_STATIC_AND_RUNTIME_CENSUS"})
        self.assertIn("RUNTIME_CENSUS_REQUIRED", receipt["runtime_blockers"])
        self.assertFalse(receipt["destructive_cleanup_authority"])
        self.assertEqual("NONE", receipt["execution_authority"])
        self.assertEqual("BLOCKED", receipt["order_authority"])

    def test_runtime_pass_can_clear_runtime_blockers(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "runtime.json"
            p.write_text(json.dumps({
                "state": "PASS_G0_RUNTIME_CENSUS",
                "duplicate_active_owner_count": 0,
                "unresolved_active_reference_count": 0,
            }))
            receipt = MODULE.make_receipt(p)
            self.assertEqual([], receipt["runtime_blockers"])


if __name__ == "__main__":
    unittest.main()
