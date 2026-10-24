"""Fail-closed A1 SSOT G5 state transition regression."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "backend/research/rebuild"
sys.path.insert(0, str(HERE))
syncer = importlib.import_module("a1_top5_latest_only_ssot_sync_v2")


def data(path: Path) -> dict:
    result: dict = json.loads(path.read_text())
    return result


G5 = data(ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json")
SSOT = data(HERE / "a1_top5_latest_only_ssot_v1.json")
FREEZE = data(
    ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
)
PROSPECTIVE = data(HERE / "a1_top5_replacement_child_prospective_v2_latest.json")
SHADOW = data(
    ROOT / "backend/research/prep/g5_trendrider_atr_pct_shadow_probe_latest.json"
)


class G5StateTests(unittest.TestCase):
    def check_bad(self, changes: dict) -> None:
        x = copy.deepcopy(G5)
        for keys, value in changes.items():
            target = x
            for k in keys[:-1]:
                target = target[k]
            target[keys[-1]] = value
        with self.assertRaises(AssertionError):
            syncer.verify_g5_product_state(x)

    def test_real_snapshot_stays_hard_blocked(self) -> None:
        syncer.verify_g5_product_state(G5)
        out = syncer.sync(SSOT, FREEZE, PROSPECTIVE, G5, SHADOW)
        broad = next(
            v for v in out["top5"] if v["lane_id"] == "trend_rider_broad_wr7000"
        )
        self.assertEqual(broad["g5"]["state"], "WAIT_G5_FORWARD_REAL_ECONOMICS")
        self.assertEqual(broad["g5"]["postlock_closed_T"], 49)
        self.assertEqual(out["order_authority"], "BLOCKED")
        self.assertFalse(out["promotion_authority"])

    def test_future_state_unknown(self) -> None:
        self.check_bad({("state",): "G6_READY"})

    def test_replay_cannot_be_production(self) -> None:
        self.check_bad({("economic_ssot", "production_grade_T"): 49})

    def test_premature_production_ready_rejected(self) -> None:
        self.check_bad({("economic_ssot", "production_grade_ready"): True})

    def test_terminal_failure_cannot_flip(self) -> None:
        self.check_bad({("research_state",): "G5_PASS"})

    def test_w2_count_is_not_postlock_count(self) -> None:
        self.check_bad({("windows", "W2", "metrics", "trades"): 49})

    def test_mismatched_durable_provenance(self) -> None:
        self.check_bad({("economic_ssot", "durable_trade_count"): 48})

    def test_live_authority_rejected(self) -> None:
        self.check_bad({("order_authority",): "LIVE"})

    def test_g6_promotion_rejected(self) -> None:
        self.check_bad({("ai_gate", "g6_promotion_eligible"): True})

    def test_legacy_w2_state_preserved(self) -> None:
        x = copy.deepcopy(G5)
        x["state"] = "WAIT_G5_W2_12"
        x["postlock_closed_T"] = x["windows"]["W2"]["metrics"]["trades"]
        syncer.verify_g5_product_state(x)


if __name__ == "__main__":
    unittest.main()
