from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import zel_trade_method_historical_adapter_v1 as v1

VERSION = "ZEL_TRADE_METHOD_HISTORICAL_ADAPTER_V2"


def classify_behavior(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        return {
            "state": "HOLD_TRADE_METHOD_BEHAVIOR_MISSING",
            "counterfactual_mode": "NONE",
            "registry_enabled": False,
            "policy_active": False,
            "size_multiplier": None,
            "target_r": None,
            "target_r_raw": None,
            "r_delta_allowed": False,
            "usdt_reweight_allowed": False,
            "blockers": ["runtime_behavior_missing"],
        }
    registry_enabled = row.get("registry_enabled") is True
    size_multiplier = v1.safe_float(row.get("size_multiplier"))
    target_raw = row.get("target_r")
    target_r = v1.safe_float(target_raw)
    policy_active = registry_enabled or (size_multiplier is not None and size_multiplier > 0)
    authority_safe = (
        str(row.get("execution_authority") or "").upper() == "NONE"
        and str(row.get("order_authority") or "").upper() == "BLOCKED"
        and row.get("paper_execution_allowed") is False
        and row.get("live_execution_allowed") is False
    )
    blockers: list[str] = []
    if not authority_safe:
        blockers.append("authority_boundary_unsafe")
    if not policy_active:
        blockers.append("registry_disabled_and_zero_size")
    if target_r is not None:
        blockers.append("numeric_target_r_requires_intratrade_price_path")
    if blockers:
        state = "HOLD_TRADE_METHOD_HISTORICAL_COUNTERFACTUAL"
        mode = "DISABLED_OR_PATH_DEPENDENT"
    elif size_multiplier is None:
        state = "HOLD_TRADE_METHOD_SIZE_MULTIPLIER_MISSING"
        mode = "SIZE_UNKNOWN"
        blockers.append("size_multiplier_missing")
    elif abs(size_multiplier - 1.0) < 1e-12:
        state = "PASS_TRADE_METHOD_R_PARITY_ONLY"
        mode = "IDENTITY_SIZE_POLICY"
    else:
        state = "PASS_TRADE_METHOD_USDT_REWEIGHT_PLAN_ONLY"
        mode = "LINEAR_SIZE_PLAN"
    return {
        "state": state,
        "counterfactual_mode": mode,
        "registry_enabled": registry_enabled,
        "policy_active": policy_active,
        "size_multiplier": size_multiplier,
        "target_r": target_r,
        "target_r_raw": target_raw,
        "r_delta_allowed": False,
        "usdt_reweight_allowed": state == "PASS_TRADE_METHOD_USDT_REWEIGHT_PLAN_ONLY",
        "blockers": sorted(set(blockers)),
    }


def build(trades_path: Path, behavior_path: Path) -> dict[str, Any]:
    original = v1.classify_behavior
    v1.classify_behavior = classify_behavior
    try:
        result = v1.build(trades_path, behavior_path)
    finally:
        v1.classify_behavior = original
    result["version"] = VERSION
    result["classification_rule"] = "policy_active=registry_enabled_or_positive_size_multiplier"
    result["receipt_sha256"] = v1.stable_sha({key: value for key, value in result.items() if key != "receipt_sha256"})
    return result


def self_test() -> None:
    allow_policy = {
        "strategy_id": "s1",
        "decision": "ALLOW_POLICY",
        "registry_enabled": False,
        "size_multiplier": 1.0,
        "target_r": "policy",
        "execution_authority": "none",
        "order_authority": "blocked",
        "paper_execution_allowed": False,
        "live_execution_allowed": False,
    }
    row = classify_behavior(allow_policy)
    assert row["state"] == "PASS_TRADE_METHOD_R_PARITY_ONLY", row
    assert row["policy_active"] is True, row
    disabled = dict(allow_policy, size_multiplier=0.0)
    hold = classify_behavior(disabled)
    assert hold["state"] == "HOLD_TRADE_METHOD_HISTORICAL_COUNTERFACTUAL", hold
    numeric_target = dict(allow_policy, target_r=2.5)
    target_hold = classify_behavior(numeric_target)
    assert "numeric_target_r_requires_intratrade_price_path" in target_hold["blockers"], target_hold
    scaled = dict(allow_policy, size_multiplier=0.5)
    scale = classify_behavior(scaled)
    assert scale["state"] == "PASS_TRADE_METHOD_USDT_REWEIGHT_PLAN_ONLY", scale
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path)
    parser.add_argument("--behavior", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.trades or not args.behavior:
        parser.error("trades and behavior are required")
    row = build(args.trades, args.behavior)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
