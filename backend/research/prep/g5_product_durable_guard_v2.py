#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep.g5_trendrider_broad30_product_oos_v1 import stable

SCHEMA = "zel.g5.trendrider_broad30.product_oos.v1"
SSOT_SCHEMA = "zel.g5.production_economic_ssot.v1"
LANE_ID = "trend_rider_broad_wr7000"
STRATEGY_ID = "trend_rider"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def receipt_valid(value: Mapping[str, Any]) -> bool:
    supplied = str(value.get("receipt_sha256") or "")
    core = dict(value)
    core.pop("receipt_sha256", None)
    return bool(supplied) and supplied == stable(core)


def validate_product(value: Mapping[str, Any], *, label: str, require_hardened: bool) -> None:
    if value.get("schema_version") != SCHEMA:
        raise RuntimeError(f"{label}_SCHEMA_MISMATCH")
    if value.get("stage") != "G5":
        raise RuntimeError(f"{label}_STAGE_MISMATCH")
    if value.get("strategy_id") != STRATEGY_ID or value.get("lane_id") != LANE_ID:
        raise RuntimeError(f"{label}_IDENTITY_MISMATCH")
    if not receipt_valid(value):
        raise RuntimeError(f"{label}_RECEIPT_SHA_MISMATCH")
    if value.get("policy_retune") is not False or value.get("threshold_retune") is not False:
        raise RuntimeError(f"{label}_RETUNE_FORBIDDEN")
    if value.get("old_history_union") is not False:
        raise RuntimeError(f"{label}_OLD_HISTORY_UNION_FORBIDDEN")
    if value.get("selection_authority") is not False or value.get("promotion_authority") is not False:
        raise RuntimeError(f"{label}_AUTHORITY_DRIFT")
    if value.get("execution_authority") != "NONE" or value.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{label}_EXECUTION_AUTHORITY_DRIFT")
    if value.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{label}_LIVE_AUTHORITY_DRIFT")
    if require_hardened:
        ssot = value.get("economic_ssot")
        if not isinstance(ssot, Mapping) or ssot.get("schema_version") != SSOT_SCHEMA:
            raise RuntimeError(f"{label}_PRODUCTION_ECONOMIC_SSOT_REQUIRED")
        ai = value.get("ai_gate")
        if not isinstance(ai, Mapping) or ai.get("scope") != "G5_ONLY":
            raise RuntimeError(f"{label}_G5_ONLY_AI_GATE_REQUIRED")
        if int(ssot.get("runtime_trade_count") or 0) != int(value.get("postlock_closed_T") or 0):
            raise RuntimeError(f"{label}_RUNTIME_T_MISMATCH")


def economic_ssot(value: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = value.get("economic_ssot")
    return raw if isinstance(raw, Mapping) else {}


def decide(current: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    validate_product(current, label="CURRENT", require_hardened=False)
    validate_product(candidate, label="CANDIDATE", require_hardened=True)
    current_t = int(current.get("postlock_closed_T") or 0)
    candidate_t = int(candidate.get("postlock_closed_T") or 0)
    current_receipt = str(current.get("receipt_sha256") or "")
    candidate_receipt = str(candidate.get("receipt_sha256") or "")
    current_ssot = economic_ssot(current)
    candidate_ssot = economic_ssot(candidate)
    current_set = str(current_ssot.get("runtime_trade_set_sha256") or "")
    candidate_set = str(candidate_ssot.get("runtime_trade_set_sha256") or "")

    if candidate_t < current_t:
        decision = "BLOCK_T_REGRESSION"
    elif candidate_t > current_t:
        decision = "ALLOW_STRICT_T_ADVANCE"
    elif candidate_receipt == current_receipt:
        decision = "NOOP_IDENTICAL"
    elif current_ssot.get("schema_version") != SSOT_SCHEMA:
        decision = "ALLOW_SAME_T_SCHEMA_HARDENING"
    elif current_set and current_set == candidate_set and current_ssot.get("durable_matches_runtime") is not True and candidate_ssot.get("durable_matches_runtime") is True:
        decision = "ALLOW_SAME_T_DURABLE_RECONCILIATION"
    else:
        decision = "BLOCK_SAME_T_RECEIPT_REWRITE"

    return {
        "schema_version": "zel.g5.product_durable_guard.v2",
        "decision": decision,
        "lane_id": LANE_ID,
        "current_T": current_t,
        "candidate_T": candidate_t,
        "current_trade_set_sha256": current_set,
        "candidate_trade_set_sha256": candidate_set,
        "current_receipt_sha256": current_receipt,
        "candidate_receipt_sha256": candidate_receipt,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "hold",
    }


def fake_product(t: int, *, hardened: bool, durable_match: bool = False, salt: str = "x") -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA,
        "stage": "G5",
        "state": "WAIT_G5_FORWARD_REAL_ECONOMICS" if hardened else "WAIT_G5_W2_12",
        "strategy_id": STRATEGY_ID,
        "lane_id": LANE_ID,
        "source_receipt_sha256": f"source-{salt}",
        "postlock_closed_T": t,
        "windows": {
            "W1": {"role": "LOCKED_REFERENCE_ONLY", "metrics": {}, "retuned": False},
            "W2": {"role": "OOS_1", "metrics": {"trades": t}, "target_T": 12},
            "W3": {"role": "OOS_2", "metrics": {"trades": 0}, "target_T": 12},
        },
        "policy_retune": False,
        "threshold_retune": False,
        "old_history_union": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }
    if hardened:
        value["research_state"] = "WAIT_G5_W2_12"
        value["economic_ssot"] = {
            "schema_version": SSOT_SCHEMA,
            "runtime_trade_count": t,
            "runtime_trade_set_sha256": f"set-{t}",
            "durable_matches_runtime": durable_match,
        }
        value["ai_gate"] = {"scope": "G5_ONLY", "g6_promotion_eligible": False}
    value["receipt_sha256"] = stable(value)
    return value


def self_test() -> int:
    old = fake_product(6, hardened=False, salt="old")
    hardened = fake_product(6, hardened=True, durable_match=False, salt="h1")
    assert decide(old, hardened)["decision"] == "ALLOW_SAME_T_SCHEMA_HARDENING"

    reconciled = fake_product(6, hardened=True, durable_match=True, salt="h2")
    assert decide(hardened, reconciled)["decision"] == "ALLOW_SAME_T_DURABLE_RECONCILIATION"

    rewrite = fake_product(6, hardened=True, durable_match=True, salt="h3")
    assert decide(reconciled, rewrite)["decision"] == "BLOCK_SAME_T_RECEIPT_REWRITE"

    advance = fake_product(7, hardened=True, durable_match=False, salt="next")
    assert decide(reconciled, advance)["decision"] == "ALLOW_STRICT_T_ADVANCE"

    regression = fake_product(5, hardened=True, durable_match=False, salt="reg")
    assert decide(reconciled, regression)["decision"] == "BLOCK_T_REGRESSION"
    print("PASS_G5_PRODUCT_DURABLE_GUARD_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", type=Path)
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.current or not args.candidate:
        raise SystemExit("--current --candidate are required")
    print(json.dumps(decide(read(args.current), read(args.candidate)), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
