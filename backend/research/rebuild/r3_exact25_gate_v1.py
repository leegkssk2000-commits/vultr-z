from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REBUILD = ROOT / "backend" / "research" / "rebuild"

BATCHES = {
    "turtle": {"run_id": 31897374631, "strategies": ["turtle_trend"]},
    "bb": {"run_id": 31903045943, "strategies": ["bb_revert"]},
    "vwap": {"run_id": 31903331072, "strategies": ["anchor_vwap_trend", "vwap_revert"]},
    "breakout": {"run_id": 31908423179, "strategies": ["break_and_continue", "keltner_trend", "squeeze_break"]},
    "trend": {"run_id": 31910868190, "strategies": ["supertrend_pullback", "trend_ma_macd", "trend_rider"]},
    "microstructure": {"run_id": 31913675189, "strategies": ["liquidity_sweep", "scalp_snap", "vol_spike_fade"]},
    "reversal_range": {"run_id": 31916294824, "strategies": ["range_fade", "fvg_revert", "pivot_reversal", "rsi_swing_fail"]},
    "indicator_core": {"run_id": 31919102315, "strategies": ["alpha_combo", "ema_ribbon_scalp", "mfi_rsi_div", "obv_trend"]},
    "final_four": {"run_id": 31920870298, "strategies": ["grid_rebalance", "rbreaker_like", "session_bias", "sr_levels"]},
}


def load_json(path: Path):
    return json.loads(path.read_text())


def main() -> None:
    inventory = load_json(REBUILD / "strategy25_structural_inventory_v2.json")
    progress = load_json(REBUILD / "strategy25_complete_policy_progress_v1.json")
    recovery = load_json(REBUILD / "strategy25_recovery_evidence_v1.json")

    ids = set(inventory["strategies"])
    assert inventory["identity_count"] == 25
    assert inventory["complete_policy_count"] == 25
    assert len(ids) == 25
    assert set(progress["complete_policy_ids"]) == ids
    assert progress["complete_policy_count"] == 25
    assert progress["remaining_policy_ids"] == []
    assert progress["protected_mutations"] == 0
    assert inventory["authority"]["selection_authority"] is False
    assert inventory["authority"]["promotion_authority"] is False
    assert inventory["authority"]["execution_authority"] == "NONE"
    assert inventory["authority"]["order_authority"] == "BLOCKED"
    assert inventory["authority"]["live_trade_authority"] == "BLOCKED"
    assert inventory["authority"]["protected_mutations"] == 0

    covered = []
    for batch in BATCHES.values():
        assert int(batch["run_id"]) > 0
        covered.extend(batch["strategies"])
    assert len(covered) == 25
    assert len(set(covered)) == 25
    assert set(covered) == ids

    owners = set()
    evidence = set()
    for sid, row in inventory["strategies"].items():
        policy = ROOT / row["policy_owner"]
        packet = ROOT / row["evidence_packet"]
        assert policy.is_file(), f"MISSING_POLICY_OWNER:{sid}:{policy}"
        assert packet.is_file(), f"MISSING_EVIDENCE_PACKET:{sid}:{packet}"
        ast.parse(policy.read_text())
        assert packet.stat().st_size > 100, f"EMPTY_EVIDENCE_PACKET:{sid}"
        owners.add(row["policy_owner"])
        evidence.add(row["evidence_packet"])

    recovery_text = json.dumps(recovery, sort_keys=True)
    for sid in ids:
        assert sid in recovery_text, f"IDENTITY_NOT_IN_RECOVERY_AUTHORITY:{sid}"

    assert len(owners) == 9, owners
    assert len(evidence) >= 8, evidence
    print(json.dumps({
        "result": "PASS_R3_EXACT25_WHOLE_SET_STRUCTURAL_GATE",
        "identity_count": len(ids),
        "complete_policy_count": progress["complete_policy_count"],
        "r2t_batch_count": len(BATCHES),
        "unique_policy_owner_count": len(owners),
        "evidence_packet_count": len(evidence),
        "duplicate_strategy_coverage": 0,
        "missing_strategy_coverage": 0,
        "protected_mutations": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
