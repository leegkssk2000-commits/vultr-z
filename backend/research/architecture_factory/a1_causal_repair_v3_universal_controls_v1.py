from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_v3_universal_controls_v2 as base

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "backend/research/architecture_factory/a1_trend_rider_transition_repair_prereg_v1.json"
CANDIDATE_ID = "trend_rider_confirm_transition_v1"
MECHANISM_FEATURES = ["price", "supertrend", "ema", "atr", "candle_direction", "state_transition"]


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def evaluate(receipt: dict[str, Any]) -> dict[str, Any]:
    prereg = read(PREREG)
    if receipt.get("strategy_id") != CANDIDATE_ID or prereg.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("CAUSAL_REPAIR_IDENTITY_MISMATCH")
    if prereg.get("state") != "FROZEN_BEFORE_PROSPECTIVE_OUTCOMES" or prereg.get("changed_axis") != "ENTRY_ELIGIBILITY_STATE_TO_FALSE_TRUE_TRANSITION":
        raise RuntimeError("CAUSAL_REPAIR_PREREG_INVALID")

    original_read = base.read
    def patched_read(path: Path) -> dict[str, Any]:
        data = original_read(path)
        if path == base.OWNERSHIP:
            data = json.loads(json.dumps(data))
            data.setdefault("strategies", {})[CANDIDATE_ID] = {
                "mechanism_features": list(MECHANISM_FEATURES),
                "source": "FROZEN_CAUSAL_REPAIR_PREREG",
                "prereg_path": str(PREREG.relative_to(ROOT)),
            }
        return data
    base.read = patched_read
    try:
        result = base.evaluate(receipt)
    finally:
        base.read = original_read
    result = dict(result)
    result["schema_version"] = "zel.a1.causal_repair.v3_universal_controls.v1"
    result["mechanism_features"] = list(MECHANISM_FEATURES)
    result["ownership_source"] = "FROZEN_CAUSAL_REPAIR_PREREG"
    result["prereg_path"] = str(PREREG.relative_to(ROOT))

    blockers = [str(x) for x in result.get("blockers") or []]
    normal_wait = bool(blockers) and all(
        x.startswith("HARD_CONTROL_SAMPLE_LT25:") or x == "SOURCE_QUALITY_NOT_PASS:PENDING"
        for x in blockers
    )
    if normal_wait:
        result["state"] = "WAIT_REPAIR_CONTROL_EVIDENCE"
        result["normal_wait"] = True
        result["wait_reason"] = "FROZEN_FIRST25_AND_24BAR_SOURCE_QUALITY_NOT_YET_AVAILABLE"
    else:
        result["normal_wait"] = False

    result["receipt_sha256"] = base.stable_sha({k:v for k,v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    prereg = read(PREREG)
    assert prereg["candidate_id"] == CANDIDATE_ID
    assert not ({"timestamp", "session", "calendar", "time_of_day", "day_of_week"} & set(MECHANISM_FEATURES))
    pending = ["SOURCE_QUALITY_NOT_PASS:PENDING", "HARD_CONTROL_SAMPLE_LT25:0"]
    assert all(x.startswith("HARD_CONTROL_SAMPLE_LT25:") or x == "SOURCE_QUALITY_NOT_PASS:PENDING" for x in pending)
    print("PASS_A1_CAUSAL_REPAIR_V3_UNIVERSAL_CONTROLS_V1_SELF_TEST")
    return 0


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--receipt",type=Path); ap.add_argument("--output",type=Path,default=Path("out/a1_causal_repair_v3_universal_controls_v1.json")); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    if args.self_test:return self_test()
    if not args.receipt:raise SystemExit("--receipt required")
    result=evaluate(read(args.receipt)); args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"state":result["state"],"candidate_id":result["candidate_id"],"completed_trades":result["completed_trades"],"frozen_control_trade_count":result["frozen_control_trade_count"],"hard_control_states":result["hard_control_states"],"mechanism_features":result["mechanism_features"],"normal_wait":result.get("normal_wait"),"receipt_sha256":result["receipt_sha256"]},sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
