"""Non-economic parity proof for Exact8 single-parent feature evaluation.

No market API, live order, funding, replay dispatch, or selection authority.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from backend.research.architecture_factory import a1_external_research_exact8_through_a3_runner_v1 as runner
from backend.research.architecture_factory.test_a1_external_research_exact8_adapters_v1 import fixture_bars


core = runner.core


def _snapshot_dict(obj: object) -> object:
    return asdict(obj) if is_dataclass(obj) else dict(vars(obj))


class Exact8ParentReuseParityTests(unittest.TestCase):
    def test_frozen_child_parent_snapshot_matches_original_parent_compute(self) -> None:
        spec = core.read(core.SPEC_PATH)
        for parent_id in core.SOURCE_READY:
            with self.subTest(parent_id=parent_id):
                child_module = importlib.import_module(core.CHILD_MODULES[parent_id])
                cfg = core.ev.config_instance(child_module)
                parent_path = core.ROOT / str(spec["specs"][parent_id]["parent_policy"])
                parent_module = core._load_parent(parent_path, parent_id)
                original_parent_compute, parent_build = core.ev.policy_functions(
                    parent_module, parent_id
                )
                timeframe_ms = int(spec["specs"][parent_id]["timeframe_ms"])
                bars = fixture_bars(150.0, count=150, timeframe_ms=timeframe_ms)
                signal_ts = int(bars[-1]["ts_ms"])
                original = original_parent_compute(
                    bars, symbol="BTC-USDT", now_ts_ms=signal_ts, config=cfg
                )
                child = child_module.compute_feature_snapshot(
                    bars, symbol="BTC-USDT", now_ts_ms=signal_ts, config=cfg
                )
                reused = core._parent_feature_from_child(child)
                self.assertEqual(
                    core.stable_sha(_snapshot_dict(original)),
                    core.stable_sha(_snapshot_dict(reused)),
                    "parent feature source parity changed",
                )
                source_sha = core.ev.git_blob_sha(parent_path)
                baseline = parent_build(
                    original,
                    policy_source_sha=source_sha,
                    verified_round_trip_cost_bps=14.0,
                    config=cfg,
                )
                optimized = parent_build(
                    reused,
                    policy_source_sha=source_sha,
                    verified_round_trip_cost_bps=14.0,
                    config=cfg,
                )
                self.assertEqual(core._intent_sha(baseline), core._intent_sha(optimized))
                self.assertEqual(
                    getattr(baseline, "no_trade", None),
                    getattr(optimized, "no_trade", None),
                )

    def test_partial_checkpoint_is_hash_bound_fail_closed_not_a_pass(self) -> None:
        spec = core.read(core.SPEC_PATH)
        parent_id = "anchor_vwap_trend"
        child_id = spec["specs"][parent_id]["child_id"]
        state = {
            "boundary_utc": core.read(core.BOUNDARY_PATH)["boundary_utc"],
            "receipt_sha256": "a" * 64,
            "source_audit_receipt_sha256": "b" * 64,
        }
        row = {
            "parent_id": parent_id, "child_id": child_id,
            "completed_child_trades": 0,
            "a1_state": "WAIT_EXACT8_A1_FRESH_SAMPLE",
            "a2_state": "BLOCKED_BEFORE_A2",
            "a3_state": "BLOCKED_BEFORE_A3",
        }
        with TemporaryDirectory() as workdir:
            root = Path(workdir)
            dest = core._write_lane_checkpoint(root, state=state, spec=spec, row=row)
            saved = json.loads(dest.read_text(encoding="utf-8"))
            receipt = saved.pop("receipt_sha256")
            self.assertEqual(core.stable_sha(saved), receipt)
            self.assertEqual(saved["formal_credit"], 0)
            self.assertEqual(saved["selection_authority"], False)
            self.assertEqual(saved["promotion_authority"], False)
            self.assertEqual(saved["order_authority"], "BLOCKED")
            self.assertIn("PARTIAL_DIAGNOSTIC_ONLY", saved["state"])
            self.assertEqual(
                core._write_lane_checkpoint(root, state=state, spec=spec, row=row), dest,
            )
            changed = dict(row, completed_child_trades=1)
            with self.assertRaisesRegex(RuntimeError, "EXACT8_CHECKPOINT_CONTENT_DRIFT"):
                core._write_lane_checkpoint(root, state=state, spec=spec, row=changed)
            invalid = dict(row, parent_id="../unknown")
            with self.assertRaisesRegex(RuntimeError, "EXACT8_CHECKPOINT_PARENT_UNKNOWN"):
                core._write_lane_checkpoint(root, state=state, spec=spec, row=invalid)

    def test_missing_parent_snapshot_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "EXACT8_CHILD_PARENT_FEATURE_MISSING"):
            core._parent_feature_from_child(SimpleNamespace())


if __name__ == "__main__":
    unittest.main()
