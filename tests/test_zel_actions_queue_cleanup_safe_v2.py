import copy
import datetime as dt
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "backend/research/ops/zel_actions_queue_cleanup_safe_v2.py"
modspec = importlib.util.spec_from_file_location("zq2", CODE)
if modspec is None or modspec.loader is None:
    raise RuntimeError("SAFE_QUEUE_MODULE")
mod = importlib.util.module_from_spec(modspec)
modspec.loader.exec_module(mod)


def fixture():
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "schema_version": mod.SCHEMA,
        "state": mod.STATE,
        "mode": "dry_run",
        "sequence": 1,
        "selected_before_utc": now.isoformat(),
        "ref": "master",
        "order_authority": "BLOCKED",
        "production_mutations": 0,
        "economic_full_launched": False,
        "verified_dry_run_id": None,
        "protected_run_ids": [40122207006, 40198981297],
        "targets": [
            {
                "id": 40198761075,
                "workflow_id": 336269619,
                "workflow_path": ".github/workflows/a1-improvement-session-bias-v2.yml",
                "event": "push",
                "head_branch": "master",
                "created_at": (now - dt.timedelta(minutes=10)).isoformat(),
                "status_at_selection": "pending",
                "name": "A1 Improvement Session Bias V2",
            }
        ],
    }


class Protection(unittest.TestCase):
    def test_23_paused_files(self):
        self.assertEqual(len(mod.PAUSED_FILES), 23)

    def test_dryrun_allowed(self):
        mod.validate_plan(fixture(), 99)

    def test_cancel_requires_prior_success_reference(self):
        x = fixture()
        x["mode"] = "cancel"
        x["sequence"] = 2
        x["verified_dry_run_id"] = 40199000123
        mod.validate_plan(x, 99)

    def assert_invalid(self, bad):
        with self.assertRaises((AssertionError, ValueError)):
            mod.validate_plan(bad, 99)

    def test_manual_workflow_never_canceled(self):
        x = fixture()
        x["targets"][0]["event"] = "workflow_dispatch"
        self.assert_invalid(x)

    def test_active_run_protected(self):
        x = fixture()
        x["targets"][0]["id"] = 40198981297
        self.assert_invalid(x)

    def test_squeeze_protected(self):
        x = fixture()
        x["targets"][0]["id"] = 40122207006
        self.assert_invalid(x)

    def test_trading_source_not_whitelisted(self):
        x = fixture()
        x["targets"][0][
            "workflow_path"
        ] = ".github/workflows/zel-production-bingx-ws-microstructure-v2.yml"
        self.assert_invalid(x)

    def test_wrong_seq_rejected(self):
        x = fixture()
        x["sequence"] = 2
        self.assert_invalid(x)

    def test_duplicate_targets_rejected(self):
        x = fixture()
        x["targets"].append(copy.deepcopy(x["targets"][0]))
        self.assert_invalid(x)

    def test_production_authority_rejected(self):
        x = fixture()
        x["order_authority"] = "LIVE"
        self.assert_invalid(x)

    def test_future_time_rejected(self):
        x = fixture()
        x["selected_before_utc"] = (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
        ).isoformat()
        self.assert_invalid(x)

    def test_old_selection_rejected(self):
        x = fixture()
        x["selected_before_utc"] = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
        ).isoformat()
        self.assert_invalid(x)

    def test_not_current_worker_target(self):
        x = fixture()
        x["targets"][0]["id"] = 99
        with self.assertRaises((ValueError, AssertionError)):
            mod.validate_plan(x, 99)


if __name__ == "__main__":
    unittest.main()
