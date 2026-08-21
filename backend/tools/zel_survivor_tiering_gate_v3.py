#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

POLICY_PATH = Path("backend/research/zel_survivor_tiering_policy_v3.json")
SCHEMA = "zel.survivor_tiering_receipt.v3"

AUTHORITY = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def finite(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError("FINITE_NUMBER_REQUIRED")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError("FINITE_NUMBER_REQUIRED")
    return out


def economics_pass(row: Mapping[str, Any], gate: Mapping[str, Any]) -> bool:
    return (
        finite(row.get("net_R")) > finite(gate["minimum_net_R"])
        and finite(row.get("expectancy_R")) > finite(gate["minimum_expectancy_R"])
        and finite(row.get("profit_factor")) >= finite(gate["minimum_profit_factor"])
        and finite(row.get("payoff_ratio")) >= finite(gate["minimum_payoff_ratio"])
        and finite(row.get("retention_pct")) >= finite(gate["minimum_retention_pct"])
        and row.get("realistic_cost_authority") is True
    )


def control_state(row: Mapping[str, Any], rule: Mapping[str, Any]) -> str:
    state = str(row.get("state") or "").upper()
    if state in {"PENDING", "INSUFFICIENT_SAMPLE", "NOT_RUN", "NOT_APPLICABLE"}:
        return "PENDING" if state != "NOT_APPLICABLE" else "NOT_APPLICABLE"
    lineage_ok = row.get("equal_trade_budget") is True and row.get("identical_window_lineage") is True and row.get("identical_cost_lineage") is True
    try:
        passed = (
            lineage_ok
            and finite(row.get("p_value")) <= finite(rule["maximum_p_value"])
            and finite(row.get("candidate_minus_control_ci_low_R")) > finite(rule["minimum_candidate_minus_control_ci_low_R"])
        )
    except Exception:
        return "PENDING"
    return "PASS" if passed else "FAIL"


def _mechanism_features(evidence: Mapping[str, Any]) -> set[str]:
    return {str(x).strip().lower() for x in evidence.get("mechanism_features") or [] if str(x).strip()}


def _active_controls(evidence: Mapping[str, Any], a1p: Mapping[str, Any]) -> tuple[list[str], list[str], dict[str, str]]:
    hard = [str(x) for x in a1p.get("hard_negative_controls") or []]
    diagnostics = [str(x) for x in (a1p.get("diagnostic_controls") or {}).keys()]
    reasons: dict[str, str] = {}
    features = _mechanism_features(evidence)
    for name, cfg in (a1p.get("conditional_hard_controls") or {}).items():
        if not isinstance(cfg, Mapping):
            continue
        owners = {str(x).strip().lower() for x in cfg.get("required_if_any_feature_owner") or [] if str(x).strip()}
        applicable = bool(features & owners)
        if applicable:
            if str(name) not in hard:
                hard.append(str(name))
            reasons[str(name)] = "HARD:FEATURE_OWNER=" + ",".join(sorted(features & owners))
        else:
            if str(name) not in diagnostics:
                diagnostics.append(str(name))
            reasons[str(name)] = "DIAGNOSTIC:MECHANISM_DOES_NOT_OWN_TIME_FEATURE"
    return hard, diagnostics, reasons


def _activation(evidence: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    a = evidence.get("activation") or {}
    no_reuse = a.get("reused_v2_promotion_outcome") is False
    new_fresh = bool(a.get("new_fresh_boundary_after_v3_install"))
    accepted = set((policy.get("activation") or {}).get("a1_evidence_modes") or ["NEW_FRESH_BOUNDARY"])
    minimum_oos = int((policy.get("activation") or {}).get("minimum_sealed_independent_oos_trades") or 0)
    sealed_oos = (
        "SEALED_INDEPENDENT_OOS" in accepted
        and a.get("sealed_independent_oos") is True
        and a.get("policy_frozen_before_oos") is True
        and a.get("oos_outcomes_used_for_retune") is False
        and int(a.get("sealed_oos_trade_count") or 0) >= minimum_oos
    )
    a1_ok = no_reuse and (new_fresh or sealed_oos)
    # Final Survivor promotion is deliberately stricter than A1 causal readiness.
    promotion_ok = no_reuse and new_fresh
    mode = "NEW_FRESH_BOUNDARY" if new_fresh else "SEALED_INDEPENDENT_OOS" if sealed_oos else "NONE"
    return {"a1_activation_ok": a1_ok, "promotion_activation_ok": promotion_ok, "mode": mode, "sealed_oos_ok": sealed_oos, "minimum_sealed_oos_trades": minimum_oos}


def evaluate(evidence: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    activation = _activation(evidence, policy)
    a1p = policy["a1_causal_alpha_gate"]
    econ = evidence.get("economics") or {}
    integrity = evidence.get("integrity") or {}
    econ_ok = economics_pass(econ, a1p["economics_required"])
    integrity_ok = (
        integrity.get("state") == "PASS"
        and int(integrity.get("leakage_lookahead") or 0) <= int(a1p["economics_required"]["leakage_lookahead_max"])
        and not list(integrity.get("defects") or [])
    )

    controls = evidence.get("negative_controls") or {}
    hard_names, diagnostic_names, applicability = _active_controls(evidence, a1p)
    hard_states = {name: control_state(controls.get(name) or {}, a1p["hard_control_rule"]) for name in hard_names}
    diagnostics = {name: str((controls.get(name) or {}).get("state") or "NOT_RUN") for name in diagnostic_names}
    any_hard_fail = any(v == "FAIL" for v in hard_states.values())
    all_hard_pass = bool(hard_states) and all(v == "PASS" for v in hard_states.values())
    any_hard_pending = any(v in {"PENDING", "NOT_APPLICABLE"} for v in hard_states.values())

    concentration = evidence.get("concentration") or {}
    global_h5_pass = concentration.get("global_h5_state") == "PASS_CONCENTRATION_FRAGILITY"

    if not activation["a1_activation_ok"]:
        a1_tier = "HOLD_V3_ACTIVATION_REQUIRED"
    elif not econ_ok or not integrity_ok or any_hard_fail:
        a1_tier = "A1_REJECT"
    elif any_hard_pending:
        a1_tier = "A1_PARKED_STRONG"
    elif all_hard_pass and global_h5_pass:
        a1_tier = "A1_CAUSAL_CORE_READY"
    elif all_hard_pass:
        a1_tier = "A1_CAUSAL_CONDITIONAL_READY"
    else:
        a1_tier = "A1_PARKED_STRONG"

    a2 = evidence.get("a2") or {}
    a3 = evidence.get("a3") or {}
    a2_pass = a2.get("state") == "PASS_A2_COST_TURNOVER"
    a3_global = a3.get("state") == "PASS_A3_GLOBAL_DURABILITY"
    a3_conditional = (
        a3.get("state") == "PASS_A3_EXPLICIT_REGIME_OWNER"
        and bool(a3.get("entry_time_regime_owner"))
        and a3.get("owned_regime_net_positive") is True
        and a3.get("fail_closed_outside_owned_regime") is True
        and a3.get("outcome_defined_regime") is False
    )

    # A1 can hand a causally-ready candidate to A2 using a sealed independent OOS.
    # Final Survivor promotion still requires a new post-V3 fresh boundary.
    if not activation["promotion_activation_ok"]:
        final_tier = "PARKED_STRONG" if a1_tier in {"A1_PARKED_STRONG", "A1_CAUSAL_CORE_READY", "A1_CAUSAL_CONDITIONAL_READY"} else "REJECT" if a1_tier == "A1_REJECT" else "HOLD"
    elif a1_tier == "A1_CAUSAL_CORE_READY" and a2_pass and a3_global and global_h5_pass:
        final_tier = "CORE_SURVIVOR"
    elif a1_tier in {"A1_CAUSAL_CORE_READY", "A1_CAUSAL_CONDITIONAL_READY"} and a2_pass and a3_conditional:
        final_tier = "CONDITIONAL_SURVIVOR"
    elif a1_tier in {"A1_PARKED_STRONG", "A1_CAUSAL_CORE_READY", "A1_CAUSAL_CONDITIONAL_READY"}:
        final_tier = "PARKED_STRONG"
    elif a1_tier == "A1_REJECT":
        final_tier = "REJECT"
    else:
        final_tier = "HOLD"

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TIERING_EVALUATED" if activation["a1_activation_ok"] else "HOLD_V3_ACTIVATION_REQUIRED",
        "candidate_id": evidence.get("candidate_id"),
        "activation": activation,
        "economics_pass": econ_ok,
        "integrity_pass": integrity_ok,
        "hard_controls_active": hard_names,
        "control_applicability": applicability,
        "hard_control_states": hard_states,
        "diagnostic_control_states": diagnostics,
        "global_h5_pass": global_h5_pass,
        "a1_tier": a1_tier,
        "a2_entry_allowed": a1_tier in {"A1_CAUSAL_CORE_READY", "A1_CAUSAL_CONDITIONAL_READY"},
        "a2_pass": a2_pass,
        "a3_global_pass": a3_global,
        "a3_conditional_owner_pass": a3_conditional,
        "final_tier": final_tier,
        "shadow_eligibility": policy["final_tiers"].get(final_tier, {}).get("shadow_eligibility", "NONE"),
        "note": "V3 never rewrites an original V2 receipt. Sealed independent OOS may establish A1 causal readiness; final Survivor promotion still requires a new post-V3 fresh boundary plus A2/A3.",
        **AUTHORITY,
    }
    result["receipt_sha256"] = sha(result)
    return result


def self_test() -> int:
    policy = json.loads(POLICY_PATH.read_text())
    good = {"state":"PASS", "p_value":0.01, "candidate_minus_control_ci_low_R":1.0, "equal_trade_budget":True, "identical_window_lineage":True, "identical_cost_lineage":True}
    e = {
        "candidate_id":"fixture",
        "mechanism_features":["price","ema","atr"],
        "activation":{"new_fresh_boundary_after_v3_install":True,"reused_v2_promotion_outcome":False},
        "economics":{"net_R":10,"expectancy_R":1,"profit_factor":1.5,"payoff_ratio":2,"retention_pct":70,"realistic_cost_authority":True},
        "integrity":{"state":"PASS","leakage_lookahead":0,"defects":[]},
        "negative_controls":{"same_count_random_entry":good,"direction_inversion":good,"timestamp_shuffle":good,"one_bar_delay":{"state":"FAIL"},"indicator_removal":{"state":"FAIL"}},
        "concentration":{"global_h5_state":"HOLD_CONCENTRATION_FRAGILITY"},
        "a2":{"state":"PASS_A2_COST_TURNOVER"},
        "a3":{"state":"PASS_A3_EXPLICIT_REGIME_OWNER","entry_time_regime_owner":"TREND_HIGH_VOL","owned_regime_net_positive":True,"fail_closed_outside_owned_regime":True,"outcome_defined_regime":False},
    }
    r = evaluate(e, policy)
    assert r["a1_tier"] == "A1_CAUSAL_CONDITIONAL_READY", r
    assert r["final_tier"] == "CONDITIONAL_SURVIVOR", r
    assert r["diagnostic_control_states"]["one_bar_delay"] == "FAIL"

    # Backward compatibility while the old policy still lists timestamp_shuffle as universally hard.
    if "timestamp_shuffle" in set(policy["a1_causal_alpha_gate"].get("hard_negative_controls") or []):
        bad = json.loads(json.dumps(e)); bad["negative_controls"]["timestamp_shuffle"] = {**good, "p_value":0.5}
        assert evaluate(bad, policy)["a1_tier"] == "A1_REJECT"
    else:
        # Under mechanism-aware V3, timestamp is diagnostic for price-only mechanisms,
        # but becomes hard when the mechanism explicitly owns session/time features.
        bad = json.loads(json.dumps(e)); bad["negative_controls"]["timestamp_shuffle"] = {**good, "p_value":0.5}
        assert evaluate(bad, policy)["a1_tier"] == "A1_CAUSAL_CONDITIONAL_READY"
        bad["mechanism_features"].append("session")
        assert evaluate(bad, policy)["a1_tier"] == "A1_REJECT"

    if "SEALED_INDEPENDENT_OOS" in set((policy.get("activation") or {}).get("a1_evidence_modes") or []):
        sealed = json.loads(json.dumps(e))
        sealed["activation"] = {"new_fresh_boundary_after_v3_install":False,"reused_v2_promotion_outcome":False,"sealed_independent_oos":True,"policy_frozen_before_oos":True,"oos_outcomes_used_for_retune":False,"sealed_oos_trade_count":max(20,int((policy.get('activation') or {}).get('minimum_sealed_independent_oos_trades') or 0))}
        sr = evaluate(sealed, policy)
        assert sr["a2_entry_allowed"] is True and sr["activation"]["promotion_activation_ok"] is False
        assert sr["final_tier"] == "PARKED_STRONG"
    print("PASS_ZEL_SURVIVOR_TIERING_GATE_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", type=Path)
    ap.add_argument("--policy", type=Path, default=POLICY_PATH)
    ap.add_argument("--output", type=Path, default=Path("out/zel_survivor_tiering_v3.json"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.evidence:
        raise SystemExit("--evidence required")
    policy = json.loads(a.policy.read_text())
    evidence = json.loads(a.evidence.read_text())
    result = evaluate(evidence, policy)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps({k:result[k] for k in ("state","candidate_id","a1_tier","a2_entry_allowed","final_tier","shadow_eligibility","receipt_sha256")}, sort_keys=True))
    return 0 if result["state"] == "PASS_TIERING_EVALUATED" else 2

if __name__ == "__main__":
    raise SystemExit(main())
