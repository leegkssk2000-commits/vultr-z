"""Non-economic parity proof for Exact8 single-parent feature evaluation.

No market API, live order, funding, replay dispatch, or selection authority.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import importlib
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

    def test_missing_parent_snapshot_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "EXACT8_CHILD_PARENT_FEATURE_MISSING"):
            core._parent_feature_from_child(SimpleNamespace())


if __name__ == "__main__":
    unittest.main()
