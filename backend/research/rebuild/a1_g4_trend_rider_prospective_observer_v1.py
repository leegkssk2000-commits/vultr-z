#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.a1.g4.trend_rider.prospective_observer.v1"
CANDIDATE = "trend_rider_delayed_fill_long_only_v1"
PARENT = "trend_rider_one_bar_delayed_fill_v1"
CURRENT_STAGE = "G4"
CANONICAL_SHADOW_STAGE = "G12"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def authority_guard(value: Mapping[str, Any], label: str) -> None:
    if value.get("selection_authority") is not False:
        raise RuntimeError(f"{label}:SELECTION_AUTHORITY_NOT_FALSE")
    if value.get("promotion_authority") is not False:
        raise RuntimeError(f"{label}:PROMOTION_AUTHORITY_NOT_FALSE")
    if value.get("execution_authority") != "NONE":
        raise RuntimeError(f"{label}:EXECUTION_AUTHORITY_NOT_NONE")
    if value.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{label}:ORDER_AUTHORITY_NOT_BLOCKED")
    if value.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{label}:LIVE_AUTHORITY_NOT_BLOCKED")
    if value.get("exchange_order_submitted") not in (False, None):
        raise RuntimeError(f"{label}:EXCHANGE_ORDER_SUBMITTED")
    if int(value.get("protected_mutations") or 0) != 0:
        raise RuntimeError(f"{label}:PROTECTED_MUTATION")


def validate_inputs(legacy: Mapping[str, Any], fresh: Mapping[str, Any]) -> None:
    if legacy.get("candidate_id") != CANDIDATE:
        raise RuntimeError("LEGACY_PRE_SHADOW_CANDIDATE_MISMATCH")
    if legacy.get("parent_strategy_id") != "trend_rider":
        raise RuntimeError("LEGACY_PRE_SHADOW_STRATEGY_MISMATCH")
    authority_guard(legacy, "LEGACY_PRE_SHADOW")

    if fresh.get("strategy_id") != "trend_rider":
        raise RuntimeError("FRESH_STRATEGY_MISMATCH")
    if fresh.get("challenger_id") != CANDIDATE:
        raise RuntimeError("FRESH_CANDIDATE_MISMATCH")
    if fresh.get("parent_challenger_id") != PARENT:
        raise RuntimeError("FRESH_PARENT_MISMATCH")
    if fresh.get("evaluation_mode") != "prospective":
        raise RuntimeError("FRESH_NOT_PROSPECTIVE")
    integrity = fresh.get("exact_parent_integrity") if isinstance(fresh.get("exact_parent_integrity"), Mapping) else {}
    if integrity.get("state") != "PASS" or integrity.get("parent_trade_identity_subset_only") is not True:
        raise RuntimeError("FRESH_EXACT_PARENT_INTEGRITY_FAIL")
    if integrity.get("new_trade_admission") is not False:
        raise RuntimeError("FRESH_NEW_TRADE_ADMISSION_NOT_FALSE")
    authority_guard(fresh, "FRESH")


def extract_hardening(hardening: Mapping[str, Any] | None) -> tuple[str, int | None, str, list[str], str]:
    if not hardening:
        return "WAIT_SAMPLE", None, "WAIT_SAMPLE", [], "NOT_RUN"
    h4 = hardening.get("h4_receipt") if isinstance(hardening.get("h4_receipt"), Mapping) else {}
    h5 = hardening.get("h5_receipt") if isinstance(hardening.get("h5_receipt"), Mapping) else {}
    integrity = hardening.get("candidate_integrity") if isinstance(hardening.get("candidate_integrity"), Mapping) else {}
    return (
        str(h4.get("state") or "UNKNOWN"),
        int(h4.get("passed_control_count")) if h4.get("passed_control_count") is not None else None,
        str(h5.get("state") or "UNKNOWN"),
        [str(x) for x in (h5.get("blockers") or [])],
        str(integrity.get("state") or "UNKNOWN"),
    )


def build(legacy: Mapping[str, Any], fresh: Mapping[str, Any], hardening: Mapping[str, Any] | None) -> dict[str, Any]:
    validate_inputs(legacy, fresh)
    trades = [x for x in (fresh.get("trades") or []) if isinstance(x, Mapping)]
    symbols = sorted({str(x.get("symbol")) for x in trades if x.get("symbol")})
    fresh_count = int(fresh.get("completed_trades") or 0)
    if fresh_count != len(trades):
        raise RuntimeError("FRESH_TRADE_COUNT_MISMATCH")
    source_quality = fresh.get("source_quality_gate") if isinstance(fresh.get("source_quality_gate"), Mapping) else {}
    source_quality_state = str(source_quality.get("state") or "UNKNOWN")
    mature = fresh_count >= 25 and len(symbols) >= 2 and source_quality_state == "PASS"
    h4_state, h4_passed, h5_state, h5_blockers, hardening_integrity = extract_hardening(hardening)
    hardening_pass = (
        h4_state == "PASS_H4_PLACEBO_NEGATIVE_CONTROLS"
        and h5_state == "PASS_CONCENTRATION_FRAGILITY"
        and hardening_integrity == "PASS"
    )
    evidence_ready = mature and hardening_pass

    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "G4_PROSPECTIVE_EVIDENCE_READY" if evidence_ready else "G4_PROSPECTIVE_OBSERVING",
        "current_fsm_stage": CURRENT_STAGE,
        "canonical_shadow_stage": CANONICAL_SHADOW_STAGE,
        "observer_mode": "READ_ONLY_RESEARCH_FORWARD_OBSERVER",
        "candidate_id": CANDIDATE,
        "parent_challenger_id": PARENT,
        "fresh_boundary_utc": fresh.get("prospective_boundary_utc"),
        "fresh_trade_count": fresh_count,
        "fresh_symbols": symbols,
        "fresh_symbol_count": len(symbols),
        "fresh_metrics": fresh.get("metrics"),
        "fresh_source_quality_state": source_quality_state,
        "mature_fresh_sample": mature,
        "h4_state": h4_state,
        "h4_passed_control_count": h4_passed,
        "h5_state": h5_state,
        "h5_blockers": h5_blockers,
        "hardening_integrity_state": hardening_integrity,
        "full_h4_h5_evidence_ready": evidence_ready,
        "legacy_pre_shadow_ready": bool(legacy.get("pre_shadow_ready")),
        "legacy_pre_shadow_state": legacy.get("state"),
        "legacy_name_does_not_grant_g12_shadow": True,
        "canonical_shadow_entry_granted": False,
        "canonical_shadow_mutation": False,
        "paper_entry_granted": False,
        "full_survivor_seal_granted": False,
        "research_may_continue_while_observing": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = stable(result)
    return result


def self_test() -> int:
    legacy = {
        "candidate_id": CANDIDATE,
        "parent_strategy_id": "trend_rider",
        "pre_shadow_ready": True,
        "state": "SHADOW_CHALLENGER_READY",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    fresh = {
        "strategy_id": "trend_rider",
        "challenger_id": CANDIDATE,
        "parent_challenger_id": PARENT,
        "evaluation_mode": "prospective",
        "prospective_boundary_utc": "2026-08-22T09:55:34Z",
        "completed_trades": 1,
        "trades": [{"symbol": "BTC-USDT"}],
        "metrics": {"profit_factor": 2.0},
        "source_quality_gate": {"state": "PASS"},
        "exact_parent_integrity": {"state": "PASS", "parent_trade_identity_subset_only": True, "new_trade_admission": False},
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    out = build(legacy, fresh, None)
    assert out["current_fsm_stage"] == "G4"
    assert out["canonical_shadow_stage"] == "G12"
    assert out["canonical_shadow_entry_granted"] is False
    assert out["canonical_shadow_mutation"] is False
    assert out["legacy_name_does_not_grant_g12_shadow"] is True
    assert out["state"] == "G4_PROSPECTIVE_OBSERVING"
    assert out["execution_authority"] == "NONE" and out["order_authority"] == "BLOCKED"
    print("PASS_A1_G4_TREND_RIDER_PROSPECTIVE_OBSERVER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-pre-shadow", type=Path)
    ap.add_argument("--fresh", type=Path)
    ap.add_argument("--hardening", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_g4_trend_rider_prospective_observer_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.legacy_pre_shadow is None or args.fresh is None:
        raise SystemExit("--legacy-pre-shadow and --fresh are required")
    hardening = read(args.hardening) if args.hardening and args.hardening.exists() else None
    result = build(read(args.legacy_pre_shadow), read(args.fresh), hardening)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("A1_G4_TREND_RIDER_PROSPECTIVE_OBSERVER=" + json.dumps({
        "state": result["state"],
        "fresh_trade_count": result["fresh_trade_count"],
        "fresh_symbol_count": result["fresh_symbol_count"],
        "h4_state": result["h4_state"],
        "h5_state": result["h5_state"],
        "canonical_shadow_entry_granted": result["canonical_shadow_entry_granted"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
