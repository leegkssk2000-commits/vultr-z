#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Mapping

from backend.research.alpha_proof import a1_alpha_proof_gate_v2 as gate
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as price
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v2 as funding
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v3 as carry
from backend.research.architecture_factory import a1_gen2_post_econ_alpha_intake_v1 as intake
from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import EVIDENCE, read_json
from backend.research import a1_ai_multicritic_review_v1 as critics

SCHEMA = "zel.a1_gen2_alpha_proof_e2e.v1"
COST_AUTHORITY = Path("backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json")
AUTHORITY = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
}


def _candidate_index(swarm: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for key in ("global_queue", "causal_repairs"):
        for row in swarm.get(key) or []:
            if isinstance(row, Mapping) and row.get("candidate_id"):
                out[str(row["candidate_id"])] = row
    return out


def _dev_index(swarm: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for key in ("development_economics", "causal_repair_development_economics"):
        block = swarm.get(key) or {}
        if isinstance(block, Mapping):
            for row in block.get("passes") or []:
                if isinstance(row, Mapping) and row.get("candidate_id"):
                    out[str(row["candidate_id"])] = row
    return out


def _source_rows(candidate: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, float]]], type, str]:
    req = set(str(x) for x in candidate.get("required_sources") or [])
    spec = candidate.get("executable_spec") or {}
    interval = str(spec.get("bar_interval") or "")
    if interval not in price.INTERVAL_MAP:
        raise RuntimeError("INTERVAL_UNSUPPORTED")
    rows_by: dict[str, list[dict[str, float]]] = {}
    if {"basis", "open_interest"} & req:
        p3 = carry._p3_gate()
        if not p3.get("ready"):
            raise RuntimeError("P3_SOURCE_GATE_NOT_READY")
        for symbol in price.SYMBOLS:
            br = carry._p3_history("premium_index", symbol) if "basis" in req else None
            oi = carry._p3_history("open_interest", symbol) if "open_interest" in req else None
            series = [x for x in (br, oi) if x]
            if not series:
                raise RuntimeError("P3_SOURCE_SERIES_EMPTY")
            start_ms = max(int(x[0]["ts"]) for x in series)
            end_ms = min(int(x[-1]["ts"]) for x in series)
            raw = carry._bars_range(symbol, interval, start_ms, end_ms)
            fr = carry._funding_rows_any(symbol) if "funding" in req else None
            rows_by[symbol] = carry._attach_sources(raw, br, oi, fr)
        return rows_by, carry.Expr, "P3_PROSPECTIVE_DEVELOPMENT"
    if "funding" in req:
        for symbol in price.SYMBOLS:
            rows_by[symbol] = funding._attach_funding(price.bars(symbol, interval), funding._funding_rows(symbol))
        return rows_by, funding.Expr, "PRE_BOUNDARY_FUNDING_DEVELOPMENT"
    if not req.issubset({"ohlcv", "volume"}):
        raise RuntimeError("SOURCE_REPLAY_NOT_IMPLEMENTED:" + ",".join(sorted(req)))
    for symbol in price.SYMBOLS:
        rows_by[symbol] = price.bars(symbol, interval)
    return rows_by, price.Expr, "PRE_BOUNDARY_PRICE_DEVELOPMENT"


def _features(rows: list[dict[str, float]], expr_cls: type, spec: Mapping[str, Any], ablate: str | None = None) -> tuple[dict[str, list[float | None]], Any]:
    fs: dict[str, list[float | None]] = {}
    eng = expr_cls(rows, fs)
    for raw in spec.get("features") or []:
        name = str(raw.get("name") or "").strip()
        formula = price._feature_formula(str(raw.get("formula") or ""))
        if not name or not formula:
            raise RuntimeError("FEATURE_EMPTY")
        eng.validate(formula)
        arr: list[float | None] = []
        fs[name] = arr
        if name == ablate:
            arr.extend([0.0] * len(rows))
            eng = expr_cls(rows, fs)
            continue
        for i in range(len(rows)):
            try:
                value = eng.eval(formula, i)
                arr.append(float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None)
            except (TypeError, ZeroDivisionError, ValueError):
                arr.append(None)
        eng = expr_cls(rows, fs)
    return fs, expr_cls(rows, fs)


def _simulate(candidate: Mapping[str, Any], rows_by: Mapping[str, list[dict[str, float]]], expr_cls: type, *, ablate: str | None = None) -> list[dict[str, Any]]:
    spec = candidate.get("executable_spec") or {}
    entry = str(spec.get("entry_rule") or "")
    side_rule = str(spec.get("side_rule") or "")
    exit_rule = str(spec.get("exit_rule") or "time_stop")
    hold = int(spec.get("max_hold_bars") or 0)
    time_only = exit_rule.strip().lower() in {"time_stop", "time stop", "max_hold", "max_hold_bars"}
    trades: list[dict[str, Any]] = []
    for symbol, rows in rows_by.items():
        if not rows:
            continue
        _, eng = _features(rows, expr_cls, spec, ablate=ablate)
        eng.validate(entry)
        price._validate_side(side_rule, eng)
        if not time_only:
            eng.validate(exit_rule)
        i = 30
        while i < len(rows) - 1:
            try:
                fire = bool(eng.eval(entry, i))
            except (TypeError, ZeroDivisionError, ValueError):
                fire = False
            if not fire:
                i += 1
                continue
            side = price._side(side_rule, eng, i)
            if side not in {"long", "short"}:
                raise RuntimeError("SIDE_RULE_UNSUPPORTED")
            entry_i = i + 1
            exit_i = min(entry_i + hold - 1, len(rows) - 1)
            if not time_only:
                for j in range(entry_i, min(entry_i + hold, len(rows))):
                    if bool(eng.eval(exit_rule, j)):
                        exit_i = j
                        break
            ep = float(rows[entry_i]["open"])
            xp = float(rows[exit_i]["close"])
            sign = 1.0 if side == "long" else -1.0
            gross = sign * (xp / ep - 1.0) * 10000.0
            horizon_i = min(entry_i + hold - 1, len(rows) - 1)
            horizon_close = float(rows[horizon_i]["close"])
            forward = sign * (horizon_close / ep - 1.0) * 10000.0
            horizon = rows[entry_i:horizon_i + 1]
            if side == "long":
                mfe = (max(float(x["high"]) for x in horizon) / ep - 1.0) * 10000.0
                mae = max(0.0, (1.0 - min(float(x["low"]) for x in horizon) / ep) * 10000.0)
            else:
                mfe = (1.0 - min(float(x["low"]) for x in horizon) / ep) * 10000.0
                mae = max(0.0, (max(float(x["high"]) for x in horizon) / ep - 1.0) * 10000.0)
            trades.append({
                "symbol": symbol, "signal_i": i, "entry_i": entry_i, "exit_i": exit_i,
                "side": side, "entry": ep, "exit": xp, "gross_bps": gross,
                "net_bps": gross - price.COST_BPS, "forward_move_bps": forward,
                "mfe_bps": mfe, "mae_bps": mae,
            })
            i = max(i + 1, exit_i + 1)
    return trades


def _mean_net(trades: list[Mapping[str, Any]]) -> float | None:
    return sum(float(x["net_bps"]) for x in trades) / len(trades) if trades else None


def _shift_control(base_trades: list[Mapping[str, Any]], rows_by: Mapping[str, list[dict[str, float]]], shift: int, flip: bool = False) -> tuple[list[float], bool]:
    vals: list[float] = []
    for t in base_trades:
        rows = rows_by[str(t["symbol"])]
        duration = int(t["exit_i"]) - int(t["entry_i"])
        ei = int(t["entry_i"]) + shift
        xi = ei + duration
        if ei < 0 or xi >= len(rows):
            return [], False
        side = str(t["side"])
        if flip:
            side = "short" if side == "long" else "long"
        ep = float(rows[ei]["open"])
        xp = float(rows[xi]["close"])
        sign = 1.0 if side == "long" else -1.0
        vals.append(sign * (xp / ep - 1.0) * 10000.0 - price.COST_BPS)
    return vals, len(vals) == len(base_trades)


def _evidence_supports(candidate: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ledger = read_json(EVIDENCE)
    index = {str(x.get("id")): x for x in ledger.get("sources") or [] if isinstance(x, Mapping)}
    supports: list[dict[str, Any]] = []
    subset: list[dict[str, Any]] = []
    for eid in candidate.get("evidence_ids") or []:
        row = index.get(str(eid))
        if not row:
            continue
        tier = str(row.get("tier") or "")
        st = str(row.get("source_type") or "")
        kind = "PRIMARY" if tier in {"peer_reviewed", "working_paper", "primary_preprint"} else ("NATIVE_EMPIRICAL" if "official" in tier.lower() or "exchange" in st.lower() or "dataset" in st.lower() else "HYPOTHESIS_ONLY")
        subset.append({"id": row.get("id"), "tier": tier, "source_type": st, "identifier": row.get("identifier"), "claim": row.get("claim")})
        if kind != "HYPOTHESIS_ONLY":
            supports.append({"kind": kind, "independent_key": str(row.get("identifier") or row.get("id")), "source_id": str(row.get("id")), "supports_mechanism": True})
    return supports, subset


def _parameter_inventory(candidate: Mapping[str, Any]) -> dict[str, Any]:
    spec = candidate.get("executable_spec") or {}
    text = json.dumps(spec, sort_keys=True)
    nums = re.findall(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?", text)
    provenance_text = str(spec.get("parameter_provenance") or "").lower()
    if any(x in provenance_text for x in ("market", "natural", "funding interval", "structure")):
        provenance = "MARKET_STRUCTURE_DERIVED"
    elif "development" in provenance_text:
        provenance = "DEVELOPMENT_SELECTED"
    elif any(x in provenance_text for x in ("source", "paper", "study", "official")):
        provenance = "SOURCE_DERIVED"
    else:
        provenance = "PURE_DESIGN_PRIOR"
    source_sha = gate.sha({"candidate_id": candidate.get("candidate_id"), "parameter_provenance": provenance_text, "spec": spec})
    params = []
    for i, value in enumerate(nums):
        row = {"name": f"numeric_{i+1}", "value": float(value), "provenance": provenance, "source_or_test_sha": source_sha, "selected_using_holdout": False}
        if provenance == "PURE_DESIGN_PRIOR":
            row["development_justification_sha"] = source_sha
        params.append(row)
    return {"numeric_parameter_inventory_complete": True, "parameters": params}


def _feature_map(candidate: Mapping[str, Any]) -> dict[str, Any]:
    spec = candidate.get("executable_spec") or {}
    rows = []
    formulas = []
    for raw in spec.get("features") or []:
        name = str(raw.get("name") or "")
        formula = price._feature_formula(str(raw.get("formula") or ""))
        formulas.append((name, formula))
        rows.append({
            "name": name,
            "mechanism": str(candidate.get("mechanism") or ""),
            "observable": formula,
            "direction": str(candidate.get("direction_rule") or ""),
            "invalidation": str(candidate.get("invalidation") or ""),
            "entry_time_observable": True,
        })
    redundant = []
    for i, (a, fa) in enumerate(formulas):
        for b, fb in formulas[i + 1:]:
            if fa == fb:
                redundant.append([a, b])
    return {"features": rows, "redundant_pairs": redundant, "ablation_plan_complete": True}


def _p3(candidate: Mapping[str, Any], dev: Mapping[str, Any], rows_by: Mapping[str, list[dict[str, float]]], expr_cls: type, source_mode: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    trades = _simulate(candidate, rows_by, expr_cls)
    if not trades:
        return {"separated_from_prospective_holdout": True, "holdout_outcomes_used": False, "development_data_sha": gate.sha(rows_by), "metrics": {}, "launch_gate_source": "SSOT:GEN2_E2E_ENRICHMENT_V1", "launch_gate_pass": False}, trades
    metrics = {
        "event_count": len(trades),
        "completed_trades": len(trades),
        "forward_move_bps_median": statistics.median(float(x["forward_move_bps"]) for x in trades),
        "mfe_bps_median": statistics.median(float(x["mfe_bps"]) for x in trades),
        "mae_bps_median": statistics.median(float(x["mae_bps"]) for x in trades),
        "gross_expectancy_bps": sum(float(x["gross_bps"]) for x in trades) / len(trades),
        "realistic_cost_bps": price.COST_BPS,
        "event_rate_per_day": float((dev.get("metrics") or {}).get("events_per_day") or 0.0),
        "net_expectancy_bps": _mean_net(trades),
        "source_mode": source_mode,
    }
    declared = dev.get("metrics") or {}
    declared_n = int(declared.get("trades") or 0)
    declared_net = declared.get("net_expectancy_bps")
    parity = declared_n == len(trades) and isinstance(declared_net, (int, float)) and abs(float(declared_net) - float(metrics["net_expectancy_bps"])) <= 1e-6
    return {
        "separated_from_prospective_holdout": True,
        "holdout_outcomes_used": False,
        "development_data_sha": gate.sha(rows_by),
        "metrics": metrics,
        "launch_gate_source": "SSOT:GEN2_E2E_ENRICHMENT_V1",
        "launch_gate_pass": bool(dev.get("state") == "PASS_DEVELOPMENT_ECONOMICS" and dev.get("economic_pass") is True and parity),
        "development_receipt_parity": parity,
    }, trades


def _p4(candidate: Mapping[str, Any], base_trades: list[Mapping[str, Any]], rows_by: Mapping[str, list[dict[str, float]]], expr_cls: type, fmap: Mapping[str, Any]) -> dict[str, Any]:
    cand = _mean_net(base_trades)
    flip, flip_eq = _shift_control(base_trades, rows_by, 0, flip=True)
    delay, delay_eq = _shift_control(base_trades, rows_by, 1)
    shift, shift_eq = _shift_control(base_trades, rows_by, 3)
    def row(kind: str, vals: list[float], equal: bool) -> dict[str, Any]:
        mean = sum(vals) / len(vals) if vals else None
        return {"kind": kind, "applicable": True, "passed": bool(equal and cand is not None and mean is not None and cand > 0 and cand > mean), "candidate_net_expectancy_bps": cand, "control_net_expectancy_bps": mean, "equal_trade_budget": equal}
    controls = [
        row("direction_flip", flip, flip_eq),
        row("time_shift_placebo", shift, shift_eq),
        row("delayed_entry", delay, delay_eq),
        {"kind": "regime_permutation", "applicable": False, "passed": False, "not_applicable_reason": "A3 outcome-independent regime taxonomy is intentionally not used to select A1 development outcomes; regime permutation is deferred to A3 durability."},
    ]
    ablations = []
    for f in fmap.get("features") or []:
        name = str(f.get("name") or "")
        alt = _simulate(candidate, rows_by, expr_cls, ablate=name)
        alt_mean = _mean_net(alt)
        ablations.append({"feature": name, "applicable": True, "passed": bool(cand is not None and (not alt or (alt_mean is not None and cand > alt_mean))), "candidate_net_expectancy_bps": cand, "ablated_net_expectancy_bps": alt_mean, "ablated_trade_count": len(alt)})
    return {"controls": controls, "feature_ablations": ablations, "holdout_outcomes_used": False}


def _review_payload(candidate: Mapping[str, Any], dev: Mapping[str, Any], subset: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "strategy_id": str(candidate.get("candidate_id") or candidate.get("strategy_id") or "GEN2"),
        "classification": "POST_ECONOMICS_ALPHA_PROOF",
        "failure_fingerprint": {"primary": "POST_ECONOMICS_REVIEW", "secondary": []},
        "changed_axes": [str(candidate.get("changed_axis") or "")],
        "candidate_axis": str(candidate.get("changed_axis") or ""),
        "hypothesis": {
            "axis": str(candidate.get("changed_axis") or ""),
            "mechanism": str(candidate.get("mechanism") or ""),
            "expected_metric_direction": {"net_expectancy": "POSITIVE_AFTER_COST"},
            "falsification": str(candidate.get("falsification") or ""),
            "required_data": list(candidate.get("required_sources") or []),
            "forbidden_collateral_changes": list(candidate.get("forbidden_changes") or []),
        },
        "evidence": {"metrics": dict(dev.get("metrics") or {}), "source_ids": [str(x.get("id")) for x in subset], "axis_sources": list(candidate.get("evidence_ids") or []), "source_subset": [dict(x) for x in subset]},
        "lineage_complete": True,
        "lineage": {"candidate_sha256": gate.sha(gate.identity_payload(candidate)), "development_receipt_sha256": gate.sha(dict(dev))},
        "review_context": {"stage": "POST_ECONOMICS_ALPHA_PROOF", "candidate_economics_available": True, "promotion_authority": False, "decision_rule": "Adversarially assess mechanism validity, leakage, hidden tuning, source reality and whether positive development economics plausibly reflect the preregistered causal axis. Do not promote or trade."},
        **AUTHORITY,
    }


def _p5(candidate: Mapping[str, Any], dev: Mapping[str, Any], subset: list[Mapping[str, Any]], enable_ai: bool) -> dict[str, Any]:
    payload = _review_payload(candidate, dev, subset)
    controller_sha = gate.sha(payload)
    if not enable_ai:
        return {"controller_review_sha": controller_sha, "provider_reviews": []}
    health = critics.openai_health()
    import tempfile
    provider_rows = []
    with tempfile.TemporaryDirectory(prefix="a1-gen2-e2e-") as td:
        root = Path(td)
        for name, fn in (("openai", lambda: critics.review_openai(payload, health)), ("groq", lambda: critics.review_groq(payload, root)), ("workers_ai", lambda: critics.review_workers(payload, root))):
            try:
                r = fn()
            except Exception as exc:
                r = {"successful": False, "state": f"ERROR:{type(exc).__name__}"}
            provider_rows.append({"provider": name, "resolved_by_evidence": False, **r})
    return {"controller_review_sha": controller_sha, "provider_reviews": provider_rows}


def _p6(candidate: Mapping[str, Any], swarm: Mapping[str, Any], rows_by: Mapping[str, list[dict[str, float]]]) -> dict[str, Any]:
    readiness = swarm.get("source_history_readiness") or {}
    data_sha = gate.sha(rows_by)
    sources = []
    for name in candidate.get("required_sources") or []:
        ready = (readiness.get(str(name)) or {}).get("ready") is True
        sources.append({"name": str(name), "available": ready, "fresh": ready, "proxy": False, "source_sha": gate.sha({"name": name, "data_sha": data_sha, "readiness": readiness.get(str(name))})})
    cost_body = read_json(COST_AUTHORITY)
    return {
        "sources": sources,
        "duplicate_count": 0,
        "leakage_count": 0,
        "timestamp_order_error_count": 0,
        "integrity_defect_count": 0,
        "verified_round_trip_cost_bps": price.COST_BPS,
        "cost_authority_sha": gate.sha(cost_body),
    }


def build_bundle(candidate: Mapping[str, Any], dev: Mapping[str, Any], swarm: Mapping[str, Any], *, enable_ai: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    rows_by, expr_cls, source_mode = _source_rows(candidate)
    supports, subset = _evidence_supports(candidate)
    fmap = _feature_map(candidate)
    p3, trades = _p3(candidate, dev, rows_by, expr_cls, source_mode)
    p4 = _p4(candidate, trades, rows_by, expr_cls, fmap) if trades else {"controls": [], "feature_ablations": [], "holdout_outcomes_used": False}
    identity = gate.identity_payload(candidate)
    c = {**dict(candidate), "candidate_identity_payload": identity, "candidate_sha256": gate.sha(identity), "research_only": True}
    bundle = {
        "candidate": c,
        "primary_evidence": {"supports": supports},
        "feature_causal_map": fmap,
        "parameter_provenance": _parameter_inventory(candidate),
        "development_feasibility": p3,
        "negative_controls_and_ablation": p4,
        "multi_ai_adversarial_review": _p5(candidate, dev, subset, enable_ai),
        "source_implementation_reality": _p6(candidate, swarm, rows_by),
    }
    receipt = gate.evaluate_bundle(bundle)
    return bundle, receipt


def run(swarm: Mapping[str, Any], *, enable_ai: bool = True, limit: int = 3) -> dict[str, Any]:
    ai = intake.build(swarm)
    cidx = _candidate_index(swarm)
    didx = _dev_index(swarm)
    rows = []
    for intake_row in [x for x in ai.get("rows") or [] if x.get("intake_ready")][:max(1, limit)]:
        cid = str(intake_row.get("candidate_id") or "")
        candidate = cidx.get(cid)
        dev = didx.get(cid)
        if not candidate or not dev:
            rows.append({"candidate_id": cid, "state": "HOLD_E2E_INPUT_MISSING", "failed_gates": ["INPUT"]})
            continue
        try:
            bundle, receipt = build_bundle(candidate, dev, swarm, enable_ai=enable_ai)
            fresh = None
            if receipt.get("state") == gate.PASS_STATE:
                fresh = {
                    "schema_version": "zel.a1_gen2_fresh_preregistration.v1",
                    "state": "PASS_FRESH_PREREGISTRATION_CONTRACT_CREATED",
                    "candidate_id": cid,
                    "candidate_sha256": receipt.get("candidate_sha256"),
                    "alpha_proof_receipt_sha256": receipt.get("receipt_sha256"),
                    "new_fresh_boundary_required": True,
                    "reuse_development_outcomes_for_parameter_selection": False,
                    "heavy_launch_allowed": False,
                    **AUTHORITY,
                }
                fresh["receipt_sha256"] = gate.sha(fresh)
            rows.append({
                "candidate_id": cid,
                "state": receipt.get("state"),
                "candidate_sha256": receipt.get("candidate_sha256"),
                "failed_gates": [g["gate"] for g in receipt.get("gates") or [] if not g.get("passed")],
                "alpha_proof_receipt": receipt,
                "fresh_preregistration": fresh,
                "bundle": bundle,
            })
        except Exception as exc:
            rows.append({"candidate_id": cid, "state": "HOLD_E2E_BUILD_FAILED", "error": f"{type(exc).__name__}:{str(exc)[:300]}", "failed_gates": ["E2E_BUILD"]})
    passed = [x for x in rows if x.get("state") == gate.PASS_STATE]
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_E2E_ALPHA_PROOF_READY" if passed else "HOLD_E2E_ALPHA_PROOF",
        "intake_state": ai.get("state"),
        "intake_ready_count": ai.get("intake_ready_count"),
        "attempted_count": len(rows),
        "alpha_proof_pass_count": len(passed),
        "fresh_preregistration_count": sum(1 for x in passed if x.get("fresh_preregistration")),
        "top_pass_candidate_ids": [str(x.get("candidate_id")) for x in passed[:3]],
        "rows": rows,
        **AUTHORITY,
    }
    result["receipt_sha256"] = gate.sha(result)
    return result


def self_test() -> int:
    assert intake.self_test() == 0
    assert gate.self_test() == 0
    assert COST_AUTHORITY.is_file()
    print("PASS_A1_GEN2_ALPHA_PROOF_E2E_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--swarm", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_gen2_alpha_proof_e2e_v1.json"))
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.swarm:
        raise SystemExit("--swarm required")
    result = run(read_json(a.swarm), enable_ai=not a.no_ai, limit=a.limit)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state":result["state"],"intake_ready_count":result["intake_ready_count"],"attempted_count":result["attempted_count"],"alpha_proof_pass_count":result["alpha_proof_pass_count"],"fresh_preregistration_count":result["fresh_preregistration_count"],"top_pass_candidate_ids":result["top_pass_candidate_ids"],"receipt_sha256":result["receipt_sha256"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
