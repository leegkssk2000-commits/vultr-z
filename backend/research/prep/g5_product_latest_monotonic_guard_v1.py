#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.g5.trendrider_broad30.product_oos.v1"
TOP5_SCHEMA = "zel.a1.top5.latest_only_ssot.v1"
LANE_ID = "trend_rider_broad_wr7000"
STRATEGY_ID = "trend_rider"
SOURCE_PATH = "backend/research/prep/g5_trendrider_broad30_product_latest.json"


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode()
    ).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _receipt_valid(value: Mapping[str, Any]) -> bool:
    supplied = str(value.get("receipt_sha256") or "")
    core = dict(value)
    core.pop("receipt_sha256", None)
    return bool(supplied) and supplied == stable(core)


def _window_trades(value: Mapping[str, Any], window: str) -> int:
    windows = value.get("windows")
    if not isinstance(windows, Mapping):
        raise RuntimeError("G5_WINDOWS_REQUIRED")
    row = windows.get(window)
    if not isinstance(row, Mapping):
        raise RuntimeError(f"G5_WINDOW_REQUIRED:{window}")
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        raise RuntimeError(f"G5_WINDOW_METRICS_REQUIRED:{window}")
    return int(metrics.get("trades") or 0)


def validate_product(value: Mapping[str, Any], *, label: str) -> None:
    if value.get("schema_version") != SCHEMA:
        raise RuntimeError(f"{label}_SCHEMA_MISMATCH")
    if value.get("stage") != "G5":
        raise RuntimeError(f"{label}_STAGE_MISMATCH")
    if value.get("strategy_id") != STRATEGY_ID or value.get("lane_id") != LANE_ID:
        raise RuntimeError(f"{label}_IDENTITY_MISMATCH")
    if not _receipt_valid(value):
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
    if int(value.get("protected_mutations") or 0) != 0:
        raise RuntimeError(f"{label}_PROTECTED_MUTATION")
    postlock = int(value.get("postlock_closed_T") or 0)
    if postlock != _window_trades(value, "W2") + _window_trades(value, "W3"):
        raise RuntimeError(f"{label}_T_WINDOW_MISMATCH")


def top5_g5(top5: Mapping[str, Any]) -> Mapping[str, Any]:
    if top5.get("schema_version") != TOP5_SCHEMA:
        raise RuntimeError("TOP5_SCHEMA_MISMATCH")
    if top5.get("state") != "CURRENT_TOP5_ONLY":
        raise RuntimeError("TOP5_STATE_MISMATCH")
    for row in top5.get("top5") or []:
        if isinstance(row, Mapping) and row.get("lane_id") == LANE_ID:
            g5 = row.get("g5")
            if not isinstance(g5, Mapping):
                raise RuntimeError("TOP5_G5_BINDING_REQUIRED")
            if g5.get("source_path") != SOURCE_PATH:
                raise RuntimeError("TOP5_G5_SOURCE_PATH_MISMATCH")
            return g5
    raise RuntimeError("TOP5_G5_LANE_MISSING")


def decide(
    current: Mapping[str, Any], candidate: Mapping[str, Any], top5: Mapping[str, Any]
) -> dict[str, Any]:
    validate_product(current, label="CURRENT")
    validate_product(candidate, label="CANDIDATE")
    g5 = top5_g5(top5)

    current_receipt = str(current["receipt_sha256"])
    current_input = str(current.get("source_receipt_sha256") or "")
    if str(g5.get("source_receipt_sha256") or "") != current_receipt:
        raise RuntimeError("CURRENT_PRODUCT_TOP5_RECEIPT_MISMATCH")
    if str(g5.get("source_input_receipt_sha256") or "") != current_input:
        raise RuntimeError("CURRENT_PRODUCT_TOP5_INPUT_RECEIPT_MISMATCH")

    current_t = int(current.get("postlock_closed_T") or 0)
    candidate_t = int(candidate.get("postlock_closed_T") or 0)
    candidate_receipt = str(candidate["receipt_sha256"])

    if candidate_t < current_t:
        decision = "BLOCK_T_REGRESSION"
    elif candidate_t == current_t and candidate_receipt == current_receipt:
        decision = "NOOP_IDENTICAL"
    elif candidate_t == current_t:
        decision = "BLOCK_SAME_T_RECEIPT_REWRITE"
    else:
        decision = "ALLOW_STRICT_T_ADVANCE"

    return {
        "schema_version": "zel.g5.product_latest_monotonic_guard.v1",
        "decision": decision,
        "lane_id": LANE_ID,
        "current_T": current_t,
        "candidate_T": candidate_t,
        "current_receipt_sha256": current_receipt,
        "candidate_receipt_sha256": candidate_receipt,
        "top5_bound_receipt_sha256": str(g5.get("source_receipt_sha256") or ""),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "hold",
    }


def _fake_product(t: int, source: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA,
        "stage": "G5",
        "state": "WAIT_G5_W2_12",
        "strategy_id": STRATEGY_ID,
        "lane_id": LANE_ID,
        "source_receipt_sha256": source,
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
    value["receipt_sha256"] = stable(value)
    return value


def _fake_top5(current: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": TOP5_SCHEMA,
        "state": "CURRENT_TOP5_ONLY",
        "top5": [
            {
                "lane_id": LANE_ID,
                "g5": {
                    "source_path": SOURCE_PATH,
                    "source_receipt_sha256": current["receipt_sha256"],
                    "source_input_receipt_sha256": current["source_receipt_sha256"],
                },
            }
        ],
    }


def self_test() -> int:
    current = _fake_product(4, "source-a")
    top5 = _fake_top5(current)
    same = json.loads(json.dumps(current))
    assert decide(current, same, top5)["decision"] == "NOOP_IDENTICAL"

    rewrite = _fake_product(4, "source-b")
    assert decide(current, rewrite, top5)["decision"] == "BLOCK_SAME_T_RECEIPT_REWRITE"

    regression = _fake_product(3, "source-c")
    assert decide(current, regression, top5)["decision"] == "BLOCK_T_REGRESSION"

    advance = _fake_product(5, "source-d")
    assert decide(current, advance, top5)["decision"] == "ALLOW_STRICT_T_ADVANCE"

    bad_top5 = _fake_top5(current)
    bad_top5["top5"][0]["g5"]["source_receipt_sha256"] = "wrong"
    try:
        decide(current, same, bad_top5)
    except RuntimeError as exc:
        assert str(exc) == "CURRENT_PRODUCT_TOP5_RECEIPT_MISMATCH"
    else:
        raise AssertionError("TOP5 receipt mismatch must fail closed")

    print("PASS_G5_PRODUCT_LATEST_MONOTONIC_GUARD_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", type=Path)
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--top5", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.current or not args.candidate or not args.top5:
        raise SystemExit("--current --candidate --top5 are required")
    result = decide(read(args.current), read(args.candidate), read(args.top5))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
