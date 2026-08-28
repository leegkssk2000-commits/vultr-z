#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_c_grade_pair_nursery_v1 as v1
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v3 as econ

SCHEMA = "zel.a1.c_grade_pair_nursery.generator_contract.v2"
SIDE_FORMS = (
    "long",
    "short",
    "long if <boolean_expr> else short",
    "short if <boolean_expr> else long",
)
TIME_EXITS = {"time_stop", "time stop", "max_hold", "max_hold_bars"}


def _stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def _engine_for(required_sources: set[str], rows: list[dict[str, float]], features: dict[str, list[float | None]]):
    if {"basis", "open_interest"} & required_sources:
        return econ.Expr(rows, features)
    if "funding" in required_sources:
        return econ.v2.Expr(rows, features)
    return econ.V1.Expr(rows, features)


def dsl_preflight(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Pure syntax/contract preflight mirroring the actual economic evaluator.

    No market/network calls are made.  The purpose is to prevent an AI candidate
    from being labelled executable by the generator validator and then dying on
    the evaluator's AST/side/hold contract.
    """
    cid = str(candidate.get("candidate_id") or "")
    spec = candidate.get("executable_spec")
    if not isinstance(spec, Mapping):
        return {"candidate_id": cid, "ok": False, "error": "SPEC_MISSING"}

    required = set(str(x) for x in (candidate.get("required_sources") or []) if str(x))
    if not required or not required.issubset(econ.SUPPORTED_SOURCES):
        return {
            "candidate_id": cid,
            "ok": False,
            "error": "SOURCE_CONTRACT",
            "required_sources": sorted(required),
            "supported_sources": sorted(econ.SUPPORTED_SOURCES),
        }

    interval = str(spec.get("bar_interval") or "")
    if interval not in econ.V1.INTERVAL_MAP:
        return {"candidate_id": cid, "ok": False, "error": f"INTERVAL_UNSUPPORTED:{interval}"}
    try:
        hold = int(spec.get("max_hold_bars") or 0)
    except Exception:
        hold = 0
    if not 1 <= hold <= 720:
        return {"candidate_id": cid, "ok": False, "error": f"HOLD_OUT_OF_RANGE:{hold}"}

    raw_features = spec.get("features") or []
    if not isinstance(raw_features, list):
        return {"candidate_id": cid, "ok": False, "error": "FEATURES_NOT_LIST"}

    rows: list[dict[str, float]] = []
    for i in range(96):
        # Values are irrelevant to AST validation; keep every supported raw field present.
        rows.append({
            "ts": float(i * 3_600_000),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
            "funding": 0.0,
            "funding_rate": 0.0,
            "funding_bps": 0.0,
            "basis": 0.0,
            "basis_bps": 0.0,
            "open_interest": 1.0,
            "oi": 1.0,
        })

    features: dict[str, list[float | None]] = {}
    feature_names: list[str] = []
    try:
        for raw in raw_features:
            if not isinstance(raw, Mapping):
                raise ValueError("FEATURE_ROW_NOT_OBJECT")
            name = str(raw.get("name") or "").strip()
            formula = str(raw.get("formula") or "").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"FEATURE_NAME_INVALID:{name}")
            if name in features:
                raise ValueError(f"FEATURE_DUPLICATE:{name}")
            if not formula:
                raise ValueError(f"FEATURE_FORMULA_EMPTY:{name}")
            normalized = econ.V1._feature_formula(formula)
            engine = _engine_for(required, rows, features)
            engine.validate(normalized)
            features[name] = [0.0] * len(rows)
            feature_names.append(name)

        engine = _engine_for(required, rows, features)
        entry = str(spec.get("entry_rule") or "").strip()
        side = str(spec.get("side_rule") or "").strip()
        exit_rule = str(spec.get("exit_rule") or "time_stop").strip()
        if not entry:
            raise ValueError("ENTRY_RULE_EMPTY")
        if not side:
            raise ValueError("SIDE_RULE_EMPTY")
        engine.validate(entry)
        econ.V1._validate_side(side, engine)
        if exit_rule.lower() not in TIME_EXITS:
            engine.validate(exit_rule)
    except Exception as exc:
        return {
            "candidate_id": cid,
            "ok": False,
            "error": f"{type(exc).__name__}:{str(exc)[:240]}",
            "executable_spec_sha256": _stable(spec),
            "feature_names": feature_names,
        }

    return {
        "candidate_id": cid,
        "ok": True,
        "error": None,
        "executable_spec_sha256": _stable(spec),
        "feature_names": feature_names,
        "bar_interval": interval,
        "max_hold_bars": hold,
    }


def prompt_v2(pairs: list[dict[str, Any]], evidence: list[dict[str, Any]], readiness: Mapping[str, Any]) -> str:
    allowed = sorted(k for k, raw in readiness.items() if isinstance(raw, Mapping) and raw.get("ready") is True)
    evidence_ids = [str(x.get("id")) for x in evidence if x.get("id")]
    dsl_funcs = sorted(econ.V1.Expr.FUNCS)
    contract = {
        "candidates": [{
            "candidate_id": "EXACT pair_id",
            "mode": "REPAIR",
            "strategy_id": "EXACT host_strategy_id",
            "architecture_family": "existing host family plus one donor mechanism",
            "changed_axis": "EXACT changed_axis from pair",
            "mechanism": "causal economic mechanism",
            "payer": "who/what pays",
            "entry_event": "entry-time observable event",
            "direction_rule": "long/short/both rule",
            "native_horizon": "natural untuned horizon",
            "regime_owner": "when mechanism owns risk",
            "invalidation": "causal invalidation",
            "exit_logic": "causal exit logic",
            "time_stop_rationale": "why time stop matches mechanism",
            "turnover_cost_budget": "why expected move can clear 14bps",
            "required_sources": ["ONLY replay-ready source names"],
            "evidence_ids": ["1 to 3 IDs copied exactly from EVIDENCE_IDS"],
            "expected_move_cost_multiple_target": 2.0,
            "falsification": "bounded prospective kill test",
            "forbidden_changes": ["fees", "best-horizon selection", "post-outcome loss deletion", "donor numeric threshold copy"],
            "why_distinct": "why the donor mechanism adds a distinct causal axis",
            "executable_spec": {
                "bar_interval": "5m|15m|30m|1h|4h|1d",
                "features": [{"name": "snake_case_identifier", "formula": "expression using only evaluator DSL"}],
                "entry_rule": "boolean evaluator-DSL expression",
                "side_rule": "long|short|long if <expr> else short|short if <expr> else long",
                "exit_rule": "time_stop|max_hold|max_hold_bars|boolean evaluator-DSL expression",
                "max_hold_bars": 48,
                "entry_timing": "next-bar/open or explicitly causal timing",
                "cost_model": "14bps verified development cost plus supported source costs",
                "development_data_rule": "fixed pre-boundary development replay only; no holdout",
                "parameter_provenance": "host native constants or mechanism-defined constants only; no sweep"
            }
        }]
    }
    return (
        "You are an EXECUTABLE C-grade material nursery. Return JSON only. This is not Top5 repair and not parameter optimization. "
        "For each supplied CxC pair emit AT MOST ONE candidate, and emit zero for a pair if you cannot satisfy every field below without inventing evidence. "
        "HARD IDENTITY: candidate_id=pair_id EXACTLY; mode=REPAIR EXACTLY; strategy_id=host_strategy_id EXACTLY; changed_axis=pair.changed_axis EXACTLY. "
        "Preserve host identity. Import exactly ONE qualitative donor_gene mechanism. Never copy donor numeric thresholds. Never add a second mechanism. "
        "required_sources MUST be non-empty and a subset of REPLAY_READY_SOURCES. evidence_ids MUST contain 1-3 IDs copied exactly from EVIDENCE_IDS. "
        "EXECUTOR DSL IS HARD, NOT ADVISORY. Feature names must be snake_case identifiers. Use only raw names open/high/low/close/volume plus replay-ready source fields, earlier declared feature names, operators, and ALLOWED_DSL_FUNCTIONS. "
        "Do NOT use prose, dotted attributes, arrays, dicts, assignments in entry/exit rules, unknown indicator names, or side syntax outside SIDE_RULE_FORMS. "
        "Every emitted candidate MUST include every generic architecture field AND a deterministic executable_spec. Numeric values are allowed only when inherited from host native constants or structurally defined by the mechanism; no threshold sweep, no best-horizon selection, no outcome-selected filtering. "
        "Same 14bps development economics will kill the child unless it achieves >=12T, Net PnL>0, Net expectancy>0, PF>1, payoff>=1, finite DD. Do not claim it passes; only emit an executable hypothesis. "
        "CONTRACT=" + json.dumps(contract, sort_keys=True, separators=(",", ":")) +
        "\nALLOWED_DSL_FUNCTIONS=" + json.dumps(dsl_funcs, separators=(",", ":")) +
        "\nSIDE_RULE_FORMS=" + json.dumps(SIDE_FORMS, separators=(",", ":")) +
        "\nREPLAY_READY_SOURCES=" + json.dumps(allowed, separators=(",", ":")) +
        "\nEVIDENCE_IDS=" + json.dumps(evidence_ids, separators=(",", ":")) +
        "\nSOURCE_READINESS=" + json.dumps(readiness, sort_keys=True, separators=(",", ":")) +
        "\nPAIRS=" + json.dumps(pairs, sort_keys=True, separators=(",", ":")) +
        "\nEVIDENCE=" + json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    )


def run(output: Path, *, no_ai: bool = False) -> dict[str, Any]:
    old_prompt = v1.prompt
    old_attach = v1.swarm._attach
    preflight_rows: list[dict[str, Any]] = []

    def checked_attach(raw: Mapping[str, Any], strict_rows: list[dict[str, Any]], allowed: set[str]):
        queue = old_attach(raw, strict_rows, allowed)
        accepted: list[dict[str, Any]] = []
        for candidate in queue:
            check = dsl_preflight(candidate)
            preflight_rows.append(check)
            if check["ok"]:
                accepted.append(candidate)
        return accepted

    v1.prompt = prompt_v2
    v1.swarm._attach = checked_attach
    try:
        result = v1.run(output, no_ai=no_ai)
    finally:
        v1.prompt = old_prompt
        v1.swarm._attach = old_attach

    by_id = {str(x.get("candidate_id") or ""): x for x in preflight_rows}
    for row in result.get("pair_results") or []:
        if not isinstance(row, dict):
            continue
        check = by_id.get(str(row.get("pair_id") or ""))
        if check:
            row["dsl_preflight"] = check
            if not check.get("ok") and row.get("development_state") in {None, "NOT_GENERATED_OR_NOT_EXECUTABLE"}:
                row["development_state"] = "REJECT_DSL_PREFLIGHT"
                row["error"] = check.get("error")
                row["executable_spec_sha256"] = check.get("executable_spec_sha256")

    provider = result.get("provider") if isinstance(result.get("provider"), dict) else {}
    provider["dsl_preflight_count"] = len(preflight_rows)
    provider["dsl_preflight_pass_count"] = sum(1 for x in preflight_rows if x.get("ok"))
    provider["dsl_preflight_reject_count"] = sum(1 for x in preflight_rows if not x.get("ok"))
    provider["dsl_preflight_errors"] = [
        {"candidate_id": x.get("candidate_id"), "error": x.get("error"), "executable_spec_sha256": x.get("executable_spec_sha256")}
        for x in preflight_rows if not x.get("ok")
    ]
    result["provider"] = provider
    result["dsl_preflight"] = {
        "contract": "MATCH_ECON_EVALUATOR_AST_SIDE_HOLD_CONTRACT",
        "count": len(preflight_rows),
        "pass_count": provider["dsl_preflight_pass_count"],
        "reject_count": provider["dsl_preflight_reject_count"],
        "rows": preflight_rows,
    }
    if provider["dsl_preflight_reject_count"] and provider["dsl_preflight_pass_count"] == 0 and result.get("pair_count_this_run"):
        result["state"] = "HOLD_C_PAIR_DSL_PREFLIGHT_REJECT"
        result["next"] = "RETRY_SAME_PAIR_WITH_HARD_DSL_CONTRACT"

    result["generator_contract_schema"] = SCHEMA
    result["generator_contract_hardened"] = True
    result["invalid_generation_is_auditable_hold_not_workflow_failure"] = True
    result["evaluator_dsl_preflight_required"] = True
    # Recompute receipt after wrapper annotations.
    result["receipt_sha256"] = v1.stable({k: val for k, val in result.items() if k != "receipt_sha256"})
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    evidence = [{"id": "F1", "claim": "x"}]
    p = [{"pair_id":"CPAIR__a__X__b__g","host_strategy_id":"a","host_family":"trend","donor_strategy_id":"b","donor_gene":"g","changed_axis":"C_PAIR__B__G__ONLY"}]
    text = prompt_v2(p, evidence, {"ohlcv":{"ready":True},"funding":{"ready":False}})
    for required in ("mode=REPAIR EXACTLY", "candidate_id=pair_id EXACTLY", "executable_spec", "evidence_ids", "REPLAY_READY_SOURCES", "ALLOWED_DSL_FUNCTIONS", "SIDE_RULE_FORMS"):
        assert required in text
    assert '"ohlcv"' in text

    good = {
        "candidate_id": "x",
        "required_sources": ["ohlcv"],
        "executable_spec": {
            "bar_interval": "1h",
            "features": [
                {"name": "m", "formula": "sma(close,24)"},
                {"name": "d", "formula": "close-m"},
            ],
            "entry_rule": "d > 0",
            "side_rule": "long if d > 0 else short",
            "exit_rule": "time_stop",
            "max_hold_bars": 24,
        },
    }
    assert dsl_preflight(good)["ok"] is True
    bad = json.loads(json.dumps(good))
    bad["candidate_id"] = "bad"
    bad["executable_spec"]["entry_rule"] = "mystery_indicator > 0"
    check = dsl_preflight(bad)
    assert check["ok"] is False and "UNKNOWN_NAME" in str(check["error"])
    print("PASS_A1_C_GRADE_PAIR_NURSERY_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_c_grade_pair_nursery_v2.json"))
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    r = run(a.out, no_ai=a.no_ai)
    print(json.dumps({"state":r["state"],"c":r["eligible_c_material_count"],"pairs":r["pair_count_this_run"],"upgrades":r["c_to_b_upgrade_count"],"provider":r["provider"],"next":r["next"],"receipt":r["receipt_sha256"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
