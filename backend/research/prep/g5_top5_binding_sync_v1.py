#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep.g5_trendrider_broad30_product_oos_v1 import stable

TOP5_SCHEMA = "zel.a1.top5.latest_only_ssot.v1"
PRODUCT_SCHEMA = "zel.g5.trendrider_broad30.product_oos.v1"
SSOT_SCHEMA = "zel.g5.production_economic_ssot.v1"
LANE_ID = "trend_rider_broad_wr7000"
STRATEGY_ID = "trend_rider"
SOURCE_PATH = "backend/research/prep/g5_trendrider_broad30_product_latest.json"


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


def validate_product(product: Mapping[str, Any]) -> None:
    if product.get("schema_version") != PRODUCT_SCHEMA:
        raise RuntimeError("G5_PRODUCT_SCHEMA_MISMATCH")
    if product.get("stage") != "G5" or product.get("strategy_id") != STRATEGY_ID or product.get("lane_id") != LANE_ID:
        raise RuntimeError("G5_PRODUCT_IDENTITY_MISMATCH")
    if not receipt_valid(product):
        raise RuntimeError("G5_PRODUCT_RECEIPT_SHA_MISMATCH")
    if product.get("policy_retune") is not False or product.get("threshold_retune") is not False:
        raise RuntimeError("G5_PRODUCT_RETUNE_FORBIDDEN")
    if product.get("old_history_union") is not False:
        raise RuntimeError("G5_PRODUCT_OLD_HISTORY_UNION_FORBIDDEN")
    if product.get("selection_authority") is not False or product.get("promotion_authority") is not False:
        raise RuntimeError("G5_PRODUCT_AUTHORITY_DRIFT")
    if product.get("execution_authority") != "NONE" or product.get("order_authority") != "BLOCKED" or product.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("G5_PRODUCT_EXECUTION_AUTHORITY_DRIFT")
    if int(product.get("protected_mutations") or 0) != 0:
        raise RuntimeError("G5_PRODUCT_PROTECTED_MUTATION")
    ssot = product.get("economic_ssot")
    if not isinstance(ssot, Mapping) or ssot.get("schema_version") != SSOT_SCHEMA:
        raise RuntimeError("G5_PRODUCT_HARDENED_SSOT_REQUIRED")
    if int(ssot.get("runtime_trade_count") or 0) != int(product.get("postlock_closed_T") or 0):
        raise RuntimeError("G5_PRODUCT_RUNTIME_T_MISMATCH")


def find_lane(top5: Mapping[str, Any]) -> tuple[int, Mapping[str, Any]]:
    if top5.get("schema_version") != TOP5_SCHEMA or top5.get("state") != "CURRENT_TOP5_ONLY":
        raise RuntimeError("TOP5_AUTHORITY_DRIFT")
    matches = [
        (i, row)
        for i, row in enumerate(top5.get("top5") or [])
        if isinstance(row, Mapping) and row.get("lane_id") == LANE_ID
    ]
    if len(matches) != 1:
        raise RuntimeError(f"TOP5_G5_LANE_CARDINALITY:{len(matches)}")
    return matches[0]


def _targets(product: Mapping[str, Any]) -> tuple[int, int]:
    windows = product.get("windows") or {}
    w2 = windows.get("W2") or {}
    w3 = windows.get("W3") or {}
    return int(w2.get("target_T") or 0), int(w3.get("target_T") or 0)


def sync(top5: Mapping[str, Any], product: Mapping[str, Any]) -> dict[str, Any]:
    validate_product(product)
    lane_index, lane = find_lane(top5)
    current_g5 = lane.get("g5")
    if not isinstance(current_g5, Mapping):
        raise RuntimeError("TOP5_G5_BINDING_MISSING")
    if current_g5.get("source_path") != SOURCE_PATH:
        raise RuntimeError("TOP5_G5_SOURCE_PATH_MISMATCH")

    product_t = int(product.get("postlock_closed_T") or 0)
    current_t = int(current_g5.get("postlock_closed_T") or 0)
    if product_t < current_t:
        raise RuntimeError(f"TOP5_G5_T_REGRESSION:{product_t}<{current_t}")

    ssot = product["economic_ssot"]
    ai = product.get("ai_gate") if isinstance(product.get("ai_gate"), Mapping) else {}
    w2_target, w3_target = _targets(product)
    ledger = ssot.get("ledger") if isinstance(ssot.get("ledger"), Mapping) else {}

    updated_g5 = dict(current_g5)
    updated_g5.update({
        "state": product.get("state"),
        "research_state": product.get("research_state", product.get("state")),
        "postlock_closed_T": product_t,
        "W2_target_T": w2_target,
        "W3_target_T": w3_target,
        "source_path": SOURCE_PATH,
        "source_receipt_sha256": product.get("receipt_sha256"),
        "source_input_receipt_sha256": product.get("source_receipt_sha256"),
        "policy_retune": False,
        "threshold_retune": False,
        "economic_ssot": {
            "schema_version": SSOT_SCHEMA,
            "state": ssot.get("state"),
            "runtime_trade_count": ssot.get("runtime_trade_count"),
            "runtime_trade_set_sha256": ssot.get("runtime_trade_set_sha256"),
            "durable_trade_count": ssot.get("durable_trade_count"),
            "durable_trade_set_sha256": ssot.get("durable_trade_set_sha256"),
            "durable_matches_runtime": ssot.get("durable_matches_runtime"),
            "production_grade_T": ssot.get("production_grade_T"),
            "replay_or_proxy_T": ssot.get("replay_or_proxy_T"),
            "production_grade_ready": ssot.get("production_grade_ready"),
            "ledger_sha256": ledger.get("ledger_sha256"),
        },
        "ai_gate": {
            "scope": ai.get("scope"),
            "production_grade_claim_eligible": ai.get("production_grade_claim_eligible"),
            "g6_promotion_eligible": ai.get("g6_promotion_eligible"),
            "g6_promotion_forbidden": ai.get("g6_promotion_forbidden"),
        },
    })

    out = copy.deepcopy(dict(top5))
    out["top5"][lane_index]["g5"] = updated_g5
    check_index, check_lane = find_lane(out)
    if check_index != lane_index:
        raise RuntimeError("TOP5_G5_LANE_MOVED")
    bound = check_lane["g5"]
    if int(bound["postlock_closed_T"]) != product_t:
        raise RuntimeError("TOP5_G5_T_SYNC_FAILED")
    if str(bound["source_receipt_sha256"]) != str(product["receipt_sha256"]):
        raise RuntimeError("TOP5_G5_RECEIPT_SYNC_FAILED")
    if str(bound["source_input_receipt_sha256"]) != str(product.get("source_receipt_sha256") or ""):
        raise RuntimeError("TOP5_G5_INPUT_RECEIPT_SYNC_FAILED")
    return out


def _fake_product(t: int) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": PRODUCT_SCHEMA,
        "stage": "G5",
        "state": "WAIT_G5_FORWARD_REAL_ECONOMICS",
        "research_state": "WAIT_G5_W2_12",
        "strategy_id": STRATEGY_ID,
        "lane_id": LANE_ID,
        "postlock_closed_T": t,
        "source_receipt_sha256": "source-new",
        "policy_retune": False,
        "threshold_retune": False,
        "old_history_union": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "windows": {"W2": {"target_T": 12}, "W3": {"target_T": 12}},
        "economic_ssot": {
            "schema_version": SSOT_SCHEMA,
            "state": "WAIT_FORWARD_REAL_PRODUCTION_EVIDENCE",
            "runtime_trade_count": t,
            "runtime_trade_set_sha256": f"set-{t}",
            "durable_trade_count": t,
            "durable_trade_set_sha256": f"set-{t}",
            "durable_matches_runtime": True,
            "production_grade_T": 0,
            "replay_or_proxy_T": t,
            "production_grade_ready": False,
            "ledger": {"ledger_sha256": "ledger"},
        },
        "ai_gate": {
            "scope": "G5_ONLY",
            "production_grade_claim_eligible": False,
            "g6_promotion_eligible": False,
            "g6_promotion_forbidden": True,
        },
        "action": "hold",
    }
    value["receipt_sha256"] = stable(value)
    return value


def self_test() -> int:
    top5 = {
        "schema_version": TOP5_SCHEMA,
        "state": "CURRENT_TOP5_ONLY",
        "sentinel": {"must_not_change": [1, 2, 3]},
        "top5": [
            {"lane_id": "other", "x": 1},
            {"lane_id": LANE_ID, "g5": {"source_path": SOURCE_PATH, "postlock_closed_T": 4, "causal_shadow": {"keep": True}}},
        ],
    }
    before_other = hashlib.sha256(json.dumps(top5["top5"][0], sort_keys=True).encode()).hexdigest()
    out = sync(top5, _fake_product(8))
    _, lane = find_lane(out)
    assert lane["g5"]["postlock_closed_T"] == 8
    assert lane["g5"]["causal_shadow"] == {"keep": True}
    assert lane["g5"]["economic_ssot"]["runtime_trade_set_sha256"] == "set-8"
    assert lane["g5"]["ai_gate"]["g6_promotion_eligible"] is False
    after_other = hashlib.sha256(json.dumps(out["top5"][0], sort_keys=True).encode()).hexdigest()
    assert before_other == after_other
    try:
        sync(out, _fake_product(7))
    except RuntimeError as exc:
        assert str(exc).startswith("TOP5_G5_T_REGRESSION")
    else:
        raise AssertionError("Top5 T regression must fail closed")
    print("PASS_G5_TOP5_BINDING_SYNC_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top5", type=Path)
    ap.add_argument("--product", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.top5 or not args.product or not args.out:
        raise SystemExit("--top5 --product --out are required")
    result = sync(read(args.top5), read(args.product))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=False, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    _, lane = find_lane(result)
    print(json.dumps({
        "state": lane["g5"].get("state"),
        "postlock_closed_T": lane["g5"].get("postlock_closed_T"),
        "source_receipt_sha256": lane["g5"].get("source_receipt_sha256"),
        "runtime_trade_set_sha256": (lane["g5"].get("economic_ssot") or {}).get("runtime_trade_set_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
