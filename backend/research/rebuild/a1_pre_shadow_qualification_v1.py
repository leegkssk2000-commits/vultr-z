#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def evaluate(candidate: Mapping[str, Any], stage_policy: Mapping[str, Any], hardening: Mapping[str, Any]) -> dict[str, Any]:
    if stage_policy.get("state") != "FROZEN_STAGE_SEPARATION_POLICY":
        raise RuntimeError("PRE_SHADOW_STAGE_POLICY_NOT_FROZEN")
    if stage_policy.get("execution_authority") != "NONE" or stage_policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("PRE_SHADOW_AUTHORITY_NOT_BLOCKED")

    dev = candidate.get("development_evidence") if isinstance(candidate.get("development_evidence"), Mapping) else candidate
    rules = candidate.get("frozen_rules") if isinstance(candidate.get("frozen_rules"), Mapping) else {}
    gate = hardening.get("survivor_gate") if isinstance(hardening.get("survivor_gate"), Mapping) else {}

    trades = int(dev.get("completed_trades") or dev.get("trades") or 0)
    retention = _num(dev.get("trade_retention_pct"))
    net_exp_bps = _num(dev.get("net_expectancy_bps"))
    net_pnl_bps = _num(dev.get("net_pnl_bps"))
    pf = _num(dev.get("profit_factor") or dev.get("net_profit_factor"))
    payoff = _num(dev.get("payoff") or dev.get("net_payoff"))
    dd_bps = _num(dev.get("drawdown_bps") or dev.get("max_drawdown_bps"))

    blockers: list[str] = []
    if trades <= 0:
        blockers.append("NO_DEVELOPMENT_TRADES")
    if retention is None or retention < float(gate.get("minimum_retention_pct", 60.0)):
        blockers.append("RETENTION_BELOW_SSOT_SURVIVOR_GATE")
    if net_exp_bps is None or net_exp_bps <= float(gate.get("minimum_expectancy_R", 0.0)) * 100.0:
        blockers.append("NET_EXPECTANCY_NON_POSITIVE")
    if net_pnl_bps is not None and net_pnl_bps <= float(gate.get("minimum_net_R", 0.0)) * 100.0:
        blockers.append("NET_PNL_NON_POSITIVE")
    if pf is None or pf < float(gate.get("minimum_profit_factor", 1.0)):
        blockers.append("PROFIT_FACTOR_BELOW_SSOT_SURVIVOR_GATE")
    if payoff is None or payoff < float(gate.get("minimum_payoff_ratio", 1.0)):
        blockers.append("PAYOFF_BELOW_SSOT_SURVIVOR_GATE")

    forbidden_true = {
        "parameter_sweep": rules.get("parameter_sweep"),
        "post_outcome_trade_deletion": rules.get("post_outcome_trade_deletion"),
        "h4_h5_thresholds_changed": rules.get("h4_h5_thresholds_changed"),
        "new_trade_admission": rules.get("new_trade_admission"),
    }
    for key, value in forbidden_true.items():
        if value is True:
            blockers.append(f"FORBIDDEN_{key.upper()}")

    if candidate.get("execution_authority") not in (None, "NONE"):
        blockers.append("EXECUTION_AUTHORITY_NOT_NONE")
    if candidate.get("order_authority") not in (None, "BLOCKED"):
        blockers.append("ORDER_AUTHORITY_NOT_BLOCKED")
    if candidate.get("live_trade_authority") not in (None, "BLOCKED"):
        blockers.append("LIVE_AUTHORITY_NOT_BLOCKED")
    if candidate.get("exchange_order_submitted") is True:
        blockers.append("EXCHANGE_ORDER_SUBMITTED")
    if int(candidate.get("protected_mutations") or 0) != 0:
        blockers.append("PROTECTED_MUTATION_DETECTED")

    h5 = dev.get("child_h5_blockers") if isinstance(dev.get("child_h5_blockers"), list) else []
    h4_state = dev.get("h4_state") or dev.get("development_h4_state") or "PENDING_SHADOW_MEASUREMENT"
    ready = not blockers
    out = {
        "schema_version": "zel.a1.pre_shadow_qualification.receipt.v1",
        "candidate_id": candidate.get("challenger_id") or candidate.get("candidate_id") or candidate.get("strategy_id"),
        "parent_strategy_id": candidate.get("parent_strategy_id") or candidate.get("strategy_id"),
        "state": "SHADOW_CHALLENGER_READY" if ready else "HOLD_PRE_SHADOW_QUALIFICATION",
        "pre_shadow_ready": ready,
        "development_metrics": {
            "trades": trades,
            "trade_retention_pct": retention,
            "net_expectancy_bps": net_exp_bps,
            "net_pnl_bps": net_pnl_bps,
            "profit_factor": pf,
            "payoff": payoff,
            "drawdown_bps": dd_bps,
        },
        "pre_shadow_blockers": blockers,
        "carried_shadow_objectives": {
            "h4_state": h4_state,
            "h5_blockers": h5,
            "full_h4_required_before_paper": True,
            "full_h5_required_before_paper": True,
            "fresh_prospective_evidence_accumulates_in_parallel": True,
        },
        "full_survivor_seal_granted": False,
        "paper_entry_granted": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    out["receipt_sha256"] = stable(out)
    return out


def self_test() -> int:
    policy = {"state": "FROZEN_STAGE_SEPARATION_POLICY", "execution_authority": "NONE", "order_authority": "BLOCKED"}
    hardening = {"survivor_gate": {"minimum_expectancy_R": 0.0, "minimum_net_R": 0.0, "minimum_payoff_ratio": 1.0, "minimum_profit_factor": 1.0, "minimum_retention_pct": 60.0}}
    candidate = {
        "challenger_id": "fixture",
        "development_evidence": {"completed_trades": 30, "trade_retention_pct": 80.0, "net_expectancy_bps": 10.0, "net_pnl_bps": 300.0, "profit_factor": 1.5, "payoff": 1.2, "drawdown_bps": 100.0, "child_h5_blockers": ["TOP10_TRADE_CONCENTRATION"]},
        "frozen_rules": {"parameter_sweep": False, "post_outcome_trade_deletion": False, "h4_h5_thresholds_changed": False, "new_trade_admission": False},
        "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "exchange_order_submitted": False, "protected_mutations": 0,
    }
    out = evaluate(candidate, policy, hardening)
    assert out["state"] == "SHADOW_CHALLENGER_READY"
    assert out["paper_entry_granted"] is False and out["full_survivor_seal_granted"] is False
    print("PASS_A1_PRE_SHADOW_QUALIFICATION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--stage-policy", type=Path)
    ap.add_argument("--hardening-policy", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_pre_shadow_qualification_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.candidate or not args.stage_policy or not args.hardening_policy:
        raise SystemExit("--candidate --stage-policy --hardening-policy required")
    result = evaluate(read(args.candidate), read(args.stage_policy), read(args.hardening_policy))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("A1_PRE_SHADOW_QUALIFICATION=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
