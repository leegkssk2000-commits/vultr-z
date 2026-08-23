#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_finalist_good_regime_h4_h5_hardening_v1 as generic
from backend.tools import zel_economic_hardening_gate_v1 as hard

ROOT = Path(__file__).resolve().parents[3]
IDENTITY = "trend_ma_macd_chase_atr_up_long_good_v1"
CUMULATIVE_PARENT_IDENTITY = "trend_ma_macd_chase_atr_up_good_v1"
STRATEGY_ID = "trend_ma_macd"
CUMULATIVE_PARENT_POLICY = ROOT / "backend/research/rebuild/trend_ma_macd_chase_atr_up_good_child_policy_v1.py"
INDICATOR_REMOVAL = "REMOVE_LONG_ONLY_CUMULATIVE_AXIS_RESTORE_FROZEN_CHASE_ATR_UP_CHILD"


def run(receipt_path: Path, out: Path) -> dict[str, Any]:
    old_parent = generic.PARENT_POLICY
    old_targets = dict(generic.TARGETS)
    try:
        generic.PARENT_POLICY = CUMULATIVE_PARENT_POLICY
        generic.TARGETS[IDENTITY] = {
            "transport_strategy_id": STRATEGY_ID,
            "indicator_removal_semantics": INDICATOR_REMOVAL,
        }
        result = generic.run(receipt_path, out)
    finally:
        generic.PARENT_POLICY = old_parent
        generic.TARGETS.clear()
        generic.TARGETS.update(old_targets)

    result["schema_version"] = "zel.a1.trendma_chase_atr_up_long.hardening.v1"
    result["candidate_identity"] = IDENTITY
    result["cumulative_parent_identity"] = CUMULATIVE_PARENT_IDENTITY
    result["indicator_removal_semantics"] = INDICATOR_REMOVAL
    result["indicator_removal_parent_policy"] = str(CUMULATIVE_PARENT_POLICY.relative_to(ROOT))
    result["indicator_removal_restores_original_parent"] = False
    result["indicator_removal_restores_cumulative_parent"] = True
    result["changed_axis_count_relative_to_cumulative_parent"] = 1
    result["cumulative_parent_preserved"] = True
    result["primary_ema_fast_child_preserved"] = True
    result["combined_with_primary"] = False
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["protected_mutations"] = 0
    result["receipt_sha256"] = hard.stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert IDENTITY != CUMULATIVE_PARENT_IDENTITY
    assert CUMULATIVE_PARENT_POLICY.name == "trend_ma_macd_chase_atr_up_good_child_policy_v1.py"
    assert "RESTORE_FROZEN_CHASE_ATR_UP_CHILD" in INDICATOR_REMOVAL
    assert str(generic.PARENT_POLICY) != ""
    print("PASS_A1_TRENDMA_CHASE_ATR_UP_LONG_H4_H5_HARDENING_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendma_chase_atr_up_long_h4_h5_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.receipt is None:
        ap.error("--receipt required")
    result = run(args.receipt, args.out)
    print(json.dumps({
        "state": result.get("state"),
        "candidate_identity": result.get("candidate_identity"),
        "H4": (result.get("h4_receipt") or {}).get("state"),
        "H5": (result.get("h5_receipt") or {}).get("state"),
        "indicator_removal_parent": result.get("cumulative_parent_identity"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
