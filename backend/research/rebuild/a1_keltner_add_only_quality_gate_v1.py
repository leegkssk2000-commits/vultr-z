#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_a4_exact_parent_repair_batch_v1 import _maps
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import (
    concentration,
    economic_gate,
    metrics,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FROZEN = ROOT / "backend/research/rebuild/a1_keltner_trend_highwr_frozen_parent_v1.json"
DEFAULT_ANCHOR = ROOT / "backend/research/rebuild/a1_keltner_add_only_quality_anchor_v1.json"
HARDENING_POLICY = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
SCHEMA = "zel.a1.keltner.add_only_quality_gate.v1"
STRATEGY = "keltner_trend"
AXIS = "LONG_SHORT_ASYMMETRY_LONG_ONLY"


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode()
    ).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def semantic_key(trade: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(trade["symbol"]),
        int(trade["signal_ts"]),
        int(trade["entry_ts"]),
        str(trade["side"]),
    )


def key_from_row(row: Any) -> tuple[str, int, int, str]:
    if not isinstance(row, list) or len(row) != 4:
        raise RuntimeError("SEMANTIC_KEY_ROW_INVALID")
    return str(row[0]), int(row[1]), int(row[2]), str(row[3])


def ordered(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(x) for x in trades),
        key=lambda x: (int(x["entry_ts"]), int(x["signal_ts"]), str(x["symbol"]), str(x["side"])),
    )


def gate_accepts(trade: Mapping[str, Any]) -> bool:
    # Frozen one-axis rule. It is entry-time observable and never reads outcome fields.
    return str(trade["side"]) == "long"


def _ge(a: Any, b: Any) -> bool:
    if b is None:
        return a is None
    if a is None:
        return False
    return float(a) >= float(b)


def _le(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    return float(a) <= float(b)


def validate_anchor(anchor: Mapping[str, Any]) -> None:
    if anchor.get("schema_version") != "zel.a1.keltner.add_only_quality_anchor.v1":
        raise RuntimeError("KELTNER_ADD_ONLY_ANCHOR_SCHEMA_MISMATCH")
    if anchor.get("strategy_id") != STRATEGY:
        raise RuntimeError("KELTNER_ADD_ONLY_ANCHOR_STRATEGY_MISMATCH")
    supplied = str(anchor.get("anchor_sha256") or "")
    core = dict(anchor)
    core.pop("anchor_sha256", None)
    if supplied != stable(core):
        raise RuntimeError("KELTNER_ADD_ONLY_ANCHOR_SHA_MISMATCH")
    gate = anchor.get("frozen_gate") or {}
    if gate.get("changed_axis") != AXIS or int(gate.get("changed_axis_count") or 0) != 1:
        raise RuntimeError("KELTNER_ADD_ONLY_GATE_AXIS_NOT_FROZEN")
    if gate.get("predicate") != {"field": "side", "op": "eq", "value": "long"}:
        raise RuntimeError("KELTNER_ADD_ONLY_GATE_PREDICATE_MISMATCH")
    if gate.get("entry_time_observable") is not True or gate.get("parameter_sweep") is not False:
        raise RuntimeError("KELTNER_ADD_ONLY_GATE_INTEGRITY_INVALID")
    if gate.get("post_outcome_trade_deletion") is not False or gate.get("parent_mutation") is not False:
        raise RuntimeError("KELTNER_ADD_ONLY_GATE_MUTATION_INVALID")


def validate_inputs(frozen: Mapping[str, Any], anchor: Mapping[str, Any], current: Mapping[str, Any]) -> tuple[set[tuple[str, int, int, str]], set[tuple[str, int, int, str]]]:
    validate_anchor(anchor)
    if frozen.get("strategy_id") != STRATEGY or current.get("strategy_id") != STRATEGY:
        raise RuntimeError("KELTNER_ADD_ONLY_STRATEGY_ID_MISMATCH")
    if frozen.get("role") != "FROZEN_PARENT_FOR_ADDITIVE_T_EXPANSION_ONLY":
        raise RuntimeError("KELTNER_ADD_ONLY_PARENT_ROLE_MISMATCH")
    expected_receipt = str((anchor.get("frozen_parent") or {}).get("receipt_sha256") or "")
    if str(frozen.get("receipt_sha256") or "") != expected_receipt:
        raise RuntimeError("KELTNER_ADD_ONLY_FROZEN_PARENT_RECEIPT_MISMATCH")
    frozen_trades = [dict(x) for x in frozen.get("trades") or []]
    current_trades = [dict(x) for x in current.get("trades") or []]
    if len(frozen_trades) != int((anchor.get("frozen_parent") or {}).get("trade_count") or -1):
        raise RuntimeError("KELTNER_ADD_ONLY_FROZEN_PARENT_COUNT_MISMATCH")
    if len(current_trades) != int(current.get("completed_trades") or -1):
        raise RuntimeError("KELTNER_ADD_ONLY_CURRENT_COUNT_MISMATCH")
    if current.get("execution_authority") not in ("NONE", None):
        raise RuntimeError("KELTNER_ADD_ONLY_CURRENT_EXECUTION_AUTHORITY_INVALID")
    if current.get("order_authority") not in ("BLOCKED", None):
        raise RuntimeError("KELTNER_ADD_ONLY_CURRENT_ORDER_AUTHORITY_INVALID")
    if current.get("live_trade_authority") not in ("BLOCKED", None):
        raise RuntimeError("KELTNER_ADD_ONLY_CURRENT_LIVE_AUTHORITY_INVALID")

    frozen_keys = {semantic_key(x) for x in frozen_trades}
    current_keys = {semantic_key(x) for x in current_trades}
    anchor_frozen_keys = {key_from_row(x) for x in (anchor.get("frozen_parent") or {}).get("semantic_trade_keys") or []}
    baseline_keys = {key_from_row(x) for x in (anchor.get("validation_freeze") or {}).get("semantic_trade_keys") or []}
    if frozen_keys != anchor_frozen_keys:
        raise RuntimeError("KELTNER_ADD_ONLY_FROZEN_KEYSET_MISMATCH")
    if not frozen_keys.issubset(current_keys):
        raise RuntimeError("KELTNER_ADD_ONLY_FROZEN_KEYS_MISSING_FROM_CURRENT")
    if not baseline_keys.issubset(current_keys):
        raise RuntimeError("KELTNER_ADD_ONLY_VALIDATION_BASELINE_KEYS_MISSING_FROM_CURRENT")
    return frozen_keys, baseline_keys


def evaluate(frozen: Mapping[str, Any], anchor: Mapping[str, Any], current: Mapping[str, Any], hard: Mapping[str, Any]) -> dict[str, Any]:
    frozen_keys, baseline_keys = validate_inputs(frozen, anchor, current)
    frozen_trades = ordered([dict(x) for x in frozen.get("trades") or []])
    current_by = {semantic_key(x): dict(x) for x in current.get("trades") or []}
    current_keys = set(current_by)

    current_added_keys = current_keys - frozen_keys
    accepted_added_keys = {k for k in current_added_keys if gate_accepts(current_by[k])}
    rejected_added_keys = current_added_keys - accepted_added_keys
    prospective_keys = current_keys - baseline_keys
    prospective_accepted = {k for k in prospective_keys if gate_accepts(current_by[k])}
    prospective_rejected = prospective_keys - prospective_accepted

    child_trades = ordered(frozen_trades + [current_by[k] for k in accepted_added_keys])
    frozen_m = metrics(frozen_trades)
    child_m = metrics(child_trades)
    prospective_all_m = metrics(ordered([current_by[k] for k in prospective_keys]))
    prospective_accepted_m = metrics(ordered([current_by[k] for k in prospective_accepted]))
    prospective_rejected_m = metrics(ordered([current_by[k] for k in prospective_rejected]))

    bars_by, maps = _maps(current)
    frozen_h5 = concentration(frozen_trades, bars_by, maps, hard)
    child_h5 = concentration(child_trades, bars_by, maps, hard)
    retention = 100.0 * len(child_trades) / max(1, len(current_by))
    econ_ok, econ_blockers = economic_gate(child_m, retention, hard)

    comparisons = {
        "trades_increased": int(child_m["trades"]) > int(frozen_m["trades"]),
        "win_rate_non_decrease": _ge(child_m.get("win_rate"), frozen_m.get("win_rate")),
        "net_pnl_non_decrease": _ge(child_m.get("net_pnl_bps"), frozen_m.get("net_pnl_bps")),
        "net_expectancy_non_decrease": _ge(child_m.get("net_expectancy_bps"), frozen_m.get("net_expectancy_bps")),
        "profit_factor_non_decrease": _ge(child_m.get("profit_factor"), frozen_m.get("profit_factor")),
        "drawdown_non_increase": _le(child_m.get("drawdown_bps"), frozen_m.get("drawdown_bps")),
        "h5_blocker_count_improved": int(child_h5["blocker_count"]) < int(frozen_h5["blocker_count"]),
        "economic_gate_pass": bool(econ_ok),
        "fresh_prospective_sample_present": len(prospective_keys) > 0,
    }
    blockers = [k.upper() for k, v in comparisons.items() if not v]
    ready = all(comparisons.values())
    if not prospective_keys:
        state = "WAIT_KELTNER_ADD_ONLY_FRESH_PROSPECTIVE_SAMPLE"
    elif ready:
        state = "PASS_KELTNER_ADD_ONLY_DEVELOPMENT_READY"
    else:
        state = "HOLD_KELTNER_ADD_ONLY_PARENT_NOT_BEATEN"

    diagnosis = anchor.get("loss_concentration_diagnosis") or {}
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": STRATEGY,
        "changed_axis": AXIS,
        "changed_axis_count": 1,
        "gate": dict(anchor.get("frozen_gate") or {}),
        "frozen_parent_receipt_sha256": frozen.get("receipt_sha256"),
        "discovery_parent_receipt_sha256": (anchor.get("discovery_source") or {}).get("broad_parent_receipt_sha256"),
        "validation_boundary_receipt_sha256": (anchor.get("validation_freeze") or {}).get("broad_parent_receipt_sha256"),
        "current_parent_receipt_sha256": current.get("receipt_sha256"),
        "cohorts": {
            "frozen_parent": {"trades": len(frozen_trades), "metrics": frozen_m},
            "discovery_added": diagnosis,
            "pre_freeze_corroboration": (anchor.get("validation_freeze") or {}).get("pre_freeze_corroboration_only"),
            "current_added_all": {"trades": len(current_added_keys)},
            "current_added_accepted": {"trades": len(accepted_added_keys)},
            "current_added_rejected": {"trades": len(rejected_added_keys)},
            "fresh_prospective_all": {"trades": len(prospective_keys), "metrics": prospective_all_m},
            "fresh_prospective_accepted": {"trades": len(prospective_accepted), "metrics": prospective_accepted_m},
            "fresh_prospective_rejected": {"trades": len(prospective_rejected), "metrics": prospective_rejected_m},
        },
        "child": {
            "completed_trades": len(child_trades),
            "trade_retention_pct_vs_current_broad_parent": retention,
            "metrics": child_m,
            "concentration": child_h5,
            "trade_identity_sha256": stable([list(semantic_key(x)) for x in child_trades]),
        },
        "frozen_parent_concentration": frozen_h5,
        "economic_gate_pass": bool(econ_ok),
        "economic_gate_blockers": econ_blockers,
        "strict_top5_comparisons": comparisons,
        "development_candidate_ready": ready,
        "promotion_blockers": blockers,
        "policy": {
            "parent_immutable": True,
            "additive_only": True,
            "one_axis_only": True,
            "post_outcome_trade_deletion": False,
            "parameter_sweep": False,
            "pre_freeze_corroboration_is_not_promotion_evidence": True,
            "fresh_prospective_validation_required": True,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    return result


def self_test(frozen_path: Path, anchor_path: Path) -> int:
    frozen, anchor = read(frozen_path), read(anchor_path)
    validate_anchor(anchor)
    assert frozen.get("receipt_sha256") == (anchor.get("frozen_parent") or {}).get("receipt_sha256")
    assert len(frozen.get("trades") or []) == 10
    discovery = (anchor.get("discovery_source") or {}).get("semantic_trade_keys") or []
    assert len(discovery) == 60
    diag = anchor.get("loss_concentration_diagnosis") or {}
    assert int((diag.get("added_short") or {}).get("trades") or 0) == 17
    assert int((diag.get("added_short") or {}).get("wins", -1)) == 0
    pref = ((anchor.get("validation_freeze") or {}).get("pre_freeze_corroboration_only") or {})
    assert int(pref.get("trade_count") or 0) == 6
    assert pref.get("promotion_evidence_allowed") is False
    assert gate_accepts({"side": "long"}) is True and gate_accepts({"side": "short"}) is False
    print("PASS_A1_KELTNER_ADD_ONLY_QUALITY_GATE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen-parent", type=Path, default=DEFAULT_FROZEN)
    ap.add_argument("--anchor", type=Path, default=DEFAULT_ANCHOR)
    ap.add_argument("--current-parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_add_only_quality_gate_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test(args.frozen_parent, args.anchor)
    if args.current_parent is None:
        raise SystemExit("--current-parent is required")
    result = evaluate(read(args.frozen_parent), read(args.anchor), read(args.current_parent), read(HARDENING_POLICY))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print("A1_KELTNER_ADD_ONLY_QUALITY=" + json.dumps({
        "state": result["state"],
        "frozen_T": result["cohorts"]["frozen_parent"]["trades"],
        "child_T": result["child"]["completed_trades"],
        "fresh_T": result["cohorts"]["fresh_prospective_all"]["trades"],
        "wr": result["child"]["metrics"]["win_rate"],
        "pf": result["child"]["metrics"]["profit_factor"],
        "dd": result["child"]["metrics"]["drawdown_bps"],
        "ready": result["development_candidate_ready"],
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
