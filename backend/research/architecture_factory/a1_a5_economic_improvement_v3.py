#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_failure_economics_v1 as failure_econ
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v3 as econ
from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as af
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as v4
from backend.research.architecture_factory import a1_a5_economic_improvement_v1 as v1
from backend.research.architecture_factory import a1_a5_economic_improvement_v2 as v2

ROOT = Path(__file__).resolve().parents[3]
LATEST = ROOT / "backend/research/architecture_factory/a1_a5_economic_improvement_latest.json"
SCHEMA = "zel.a1_a5_economic_improvement.v3"
MAX_PAID_REQUESTS = 3
REPAIR_BUDGET = 3
AUTH = dict(v1.AUTH)
ECONOMIC_TERMINAL_STATES = {
    "PASS_DEVELOPMENT_ECONOMICS",
    "FAIL_DEVELOPMENT_ECONOMICS",
    "FAIL_INSUFFICIENT_EVENTS",
}
DSL_FUNCTIONS = [
    "abs", "min", "max", "sma", "ema", "std", "lag", "ret", "roc", "atr", "vwap",
    "zscore", "highest", "lowest", "percentile", "pct_rank", "vol_ratio", "range_pct",
    "body_pct", "upper_wick_pct", "lower_wick_pct", "breakout_dist", "hour", "dow",
]


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _candidate_axis_map(receipt: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for key in ("initial_candidates", "second_step_candidates"):
        for row in receipt.get(key) or []:
            if not isinstance(row, Mapping):
                continue
            cid = str(row.get("candidate_id") or "")
            sid = str(row.get("strategy_id") or "")
            axis = str(row.get("changed_axis") or "")
            if cid and sid and axis:
                out[cid] = (sid, axis)
    return out


def _economic_prior_attempts(order: list[str]) -> dict[str, list[str]]:
    prior = _read(LATEST)
    out: dict[str, list[str]] = {sid: [] for sid in order}
    explicit = prior.get("economic_attempted_axes")
    if isinstance(explicit, Mapping):
        for sid in order:
            rows = explicit.get(sid)
            if isinstance(rows, list):
                out[sid] = list(dict.fromkeys(str(x) for x in rows if str(x)))
        return out

    cmap = _candidate_axis_map(prior)
    for block_key in ("initial_development_economics", "second_step_development_economics"):
        block = prior.get(block_key) or {}
        if not isinstance(block, Mapping):
            continue
        for row in block.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            state = str(row.get("state") or "")
            if state not in ECONOMIC_TERMINAL_STATES:
                continue
            cid = str(row.get("candidate_id") or "")
            pair = cmap.get(cid)
            if not pair:
                continue
            sid, axis = pair
            if sid in out and axis not in out[sid]:
                out[sid].append(axis)
    return out


def _filter_axes(all_axes: Mapping[str, list[dict[str, Any]]], used: Mapping[str, list[str]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for sid, rows in all_axes.items():
        taken = set(used.get(sid) or [])
        remain = [dict(x) for x in rows if str(x.get("axis") or "") not in taken]
        if remain:
            out[sid] = remain
    return out


def _grammar() -> dict[str, Any]:
    return {
        "expression_only": True,
        "assignments_forbidden": True,
        "prose_forbidden_in_dsl_fields": True,
        "allowed_price_names": ["open", "high", "low", "close", "volume", "funding", "funding_rate", "funding_bps", "basis", "basis_bps", "open_interest", "oi"],
        "allowed_functions": DSL_FUNCTIONS,
        "feature_formula_examples": [
            "std(close,20) / max(sma(close,20),0.00000001)",
            "ema(close,20) - ema(close,50)",
            "vol_ratio(20)",
            "pct_rank(volume,50)",
        ],
        "entry_rule_examples": [
            "ema(close,20) > ema(close,50) and vol_ratio(20) > 1",
            "close > highest(close,20) and volume > sma(volume,20)",
        ],
        "side_rule_allowed": ["long", "short", "long if <boolean expression> else short", "short if <boolean expression> else long"],
        "exit_rule_allowed": ["time_stop", "max_hold_bars", "boolean expression"],
        "forbidden_examples": [
            "x = expression",
            "both",
            "sqrt(...) unless represented with supported operators/functions",
            "median_symbol_universe(...) or any function not in allowed_functions",
            "natural-language sentences inside entry_rule/side_rule/exit_rule/features.formula",
        ],
    }


def _prompt(kind: str, fps: list[dict[str, Any]], axes: Mapping[str, Any], evidence: list[dict[str, Any]], readiness: Mapping[str, Any], prior: Mapping[str, list[str]], selected: list[dict[str, Any]] | None = None) -> str:
    base = {
        "task": kind,
        "a5_failures": fps,
        "allowed_untried_axes_by_strategy": axes,
        "prior_economically_tested_axes_by_strategy": prior,
        "selected_failed_candidates": selected or [],
        "source_history_readiness": readiness,
        "external_evidence": evidence[:36],
        "executable_dsl_v1": _grammar(),
        "constraints": {
            "repair_only": True,
            "exactly_one_candidate_per_supplied_strategy": True,
            "exact_strategy_id_required": True,
            "one_changed_axis_only": True,
            "changed_axis_must_be_untried": True,
            "sealed_axis_reuse": False,
            "threshold_sweep": False,
            "best_horizon_selection": False,
            "holdout_access": False,
            "post_outcome_trade_deletion": False,
            "fee_reduction_rescue": False,
            "verified_round_trip_cost_bps": 14.0,
            "development_data": "STRICTLY_PRE_GEN1_BOUNDARY",
        },
    }
    instruction = (
        "Return exactly ONE executable REPAIR per supplied strategy, preserving one-axis identity. "
        if kind == "INITIAL_A5_REPAIR_BATCH" else
        "Return exactly ONE second-step executable REPAIR per supplied selected strategy using a different remaining axis. "
    )
    shape = af.generator_contract()
    shape["candidates"][0]["executable_spec"] = {
        "bar_interval": "5m|15m|30m|1h|4h|1d",
        "features": [{"name": "identifier", "formula": "expression only"}],
        "entry_rule": "boolean expression only",
        "side_rule": "long|short|long if <expr> else short|short if <expr> else long",
        "exit_rule": "time_stop|max_hold_bars|boolean expression",
        "max_hold_bars": 12,
        "entry_timing": "completed-bar timing",
        "cost_model": "14bps verified round trip",
        "development_data_rule": "STRICTLY_PRE_GEN1_BOUNDARY",
        "parameter_provenance": "mechanism prior only; no outcome sweep",
    }
    return (
        "You are the A5 economic improvement builder. " + instruction +
        "DSL fields are machine expressions, not prose. Do not use assignment statements or unsupported function names. "
        "Use only supplied evidence_ids. Return JSON only matching: " +
        json.dumps(shape, ensure_ascii=False, sort_keys=True, separators=(",", ":")) +
        "\nCONTEXT=" + json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _strict_openai(prompt: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    marker = "CONTEXT="
    active_n = 1
    if marker in prompt:
        try:
            context = json.loads(prompt.split(marker, 1)[1])
            axes = context.get("allowed_untried_axes_by_strategy") or {}
            if isinstance(axes, Mapping):
                active_n = max(1, len(axes))
        except Exception:
            pass
    original = v2.OPENAI_GENERATOR_SCHEMA
    schema = copy.deepcopy(original)
    candidates = schema["properties"]["candidates"]
    candidates["minItems"] = active_n
    candidates["maxItems"] = active_n
    old = v2.OPENAI_GENERATOR_SCHEMA
    try:
        v2.OPENAI_GENERATOR_SCHEMA = schema
        return v2._strict_openai_generator(prompt)
    finally:
        v2.OPENAI_GENERATOR_SCHEMA = old


def _provider_call(provider: str, prompt: str) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
    if provider == "openai":
        return _strict_openai(prompt)
    return v2._provider_call(provider, prompt)


def _attempt(provider: str, prompt: str, source_ids: set[str], axes: Mapping[str, list[dict[str, Any]]], readiness: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        model, raw, lineage = _provider_call(provider, prompt)
        rows = v1._filter_attach(raw, provider, source_ids, axes, readiness)
        represented = sorted({str(x.get("strategy_id") or "") for x in rows})
        expected = sorted(axes)
        return rows, {
            "successful": bool(rows) and represented == expected,
            "model": model,
            **dict(lineage),
            "candidate_count": len(rows),
            "represented_strategy_ids": represented,
            "expected_strategy_ids": expected,
            "complete_strategy_coverage": represented == expected,
            "request_count": 1,
        }
    except Exception as exc:  # noqa: BLE001
        return [], {"successful": False, "error": af.safe_error(exc), "candidate_count": 0, "request_count": 1}


def _spec_rejected_ids(dev: Mapping[str, Any]) -> set[str]:
    return {
        str(x.get("candidate_id") or "")
        for x in (dev.get("rows") or [])
        if isinstance(x, Mapping) and str(x.get("state") or "") == "REJECT_UNEXECUTABLE_SPEC"
    }


def _repair_spec_prompt(parents: list[dict[str, Any]]) -> str:
    return (
        "Translate ONLY executable_spec into the frozen EXECUTABLE_DSL_V1 grammar below. "
        "Preserve candidate_id, strategy_id, changed_axis, mechanism, evidence_ids, required_sources and every non-executable semantic field exactly. "
        "Do not change strategy economics or add a new axis. Return exactly the same number of candidates. "
        "DSL_GRAMMAR=" + json.dumps(_grammar(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) +
        "\nPARENTS=" + json.dumps(parents, ensure_ascii=False, sort_keys=True, separators=(",", ":")) +
        "\nCONTEXT=" + json.dumps({"allowed_untried_axes_by_strategy": {str(x.get('strategy_id')): [{"axis": x.get('changed_axis')}] for x in parents}}, separators=(",", ":"))
    )


def _repair_specs(parents: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not parents:
        return [], {"successful": False, "skipped": True, "reason": "NO_SPEC_REJECTS", "request_count": 0}
    try:
        model, raw, lineage = _strict_openai(_repair_spec_prompt(parents))
        generated = [x for x in (raw.get("candidates") or []) if isinstance(x, Mapping)] if isinstance(raw, Mapping) else []
        repaired: list[dict[str, Any]] = []
        for idx, parent in enumerate(parents):
            if idx >= len(generated):
                break
            spec = generated[idx].get("executable_spec")
            if not isinstance(spec, Mapping):
                continue
            row = dict(parent)
            row["executable_spec"] = dict(spec)
            row["spec_repair_iteration"] = 1
            row["spec_repair_semantics_frozen"] = True
            repaired.append(row)
        return repaired, {
            "successful": len(repaired) == len(parents),
            "model": model,
            **dict(lineage),
            "candidate_count": len(repaired),
            "request_count": 1,
            "repair_scope": "EXECUTABLE_SPEC_ONLY",
        }
    except Exception as exc:  # noqa: BLE001
        return [], {"successful": False, "error": af.safe_error(exc), "candidate_count": 0, "request_count": 1}


def _terminal_axes(candidates: list[dict[str, Any]], dev: Mapping[str, Any]) -> dict[str, list[str]]:
    cmap = {str(x.get("candidate_id") or ""): (str(x.get("strategy_id") or ""), str(x.get("changed_axis") or "")) for x in candidates}
    out: dict[str, list[str]] = {}
    for row in dev.get("rows") or []:
        if not isinstance(row, Mapping) or str(row.get("state") or "") not in ECONOMIC_TERMINAL_STATES:
            continue
        pair = cmap.get(str(row.get("candidate_id") or ""))
        if not pair:
            continue
        sid, axis = pair
        if sid and axis:
            out.setdefault(sid, [])
            if axis not in out[sid]:
                out[sid].append(axis)
    return out


def _empty_dev() -> dict[str, Any]:
    return {"economic_pass_count": 0, "economic_fail_count": 0, "source_skip_count": 0, "spec_reject_count": 0, "passes": [], "rows": []}


def run(output: Path) -> dict[str, Any]:
    c = v1.contract(); order = v1.a5_order(c)
    ledger = af.read_json(af.LEDGER); evidence_doc = af.read_json(af.EVIDENCE)
    readiness = v1.source_readiness(); all_axes = v1.allowed_axes(c, readiness)
    prior = _economic_prior_attempts(order); axes = _filter_axes(all_axes, prior)
    active = [sid for sid in order if sid in axes]
    evidence = [*v1.contract_evidence(c), *af.evidence_compact(evidence_doc)]
    source_ids = {str(x.get("id")) for x in evidence if x.get("id")}
    providers: dict[str, Any] = {}; paid = 0
    queue: list[dict[str, Any]] = []; repairs: list[dict[str, Any]] = []
    dev = _empty_dev(); repair_dev = _empty_dev(); analysis: dict[str, Any] = {"selected_for_single_repair": []}
    technical_reject_axes: dict[str, list[str]] = {sid: [] for sid in order}

    if active:
        fps = v1._fingerprints(ledger, active)
        prompt = _prompt("INITIAL_A5_REPAIR_BATCH", fps, axes, evidence, readiness, prior)
        queue, providers["openai_initial"] = _attempt("openai", prompt, source_ids, axes, readiness)
        paid += 1; queue = af.dedup(queue, 0.85)
        dev = econ.evaluate_queue(queue) if queue else _empty_dev()

        rejected_ids = _spec_rejected_ids(dev)
        rejected = [x for x in queue if str(x.get("candidate_id") or "") in rejected_ids]
        for row in rejected:
            sid = str(row.get("strategy_id") or ""); axis = str(row.get("changed_axis") or "")
            if sid in technical_reject_axes and axis and axis not in technical_reject_axes[sid]: technical_reject_axes[sid].append(axis)
        if rejected and paid < MAX_PAID_REQUESTS:
            fixed, providers["openai_spec_repair"] = _repair_specs(rejected)
            paid += 1
            fixed_by_id = {str(x.get("candidate_id") or ""): x for x in fixed}
            queue = [fixed_by_id.get(str(x.get("candidate_id") or ""), x) for x in queue]
            dev = econ.evaluate_queue(queue) if queue else _empty_dev()
        else:
            providers["openai_spec_repair"] = {"successful": False, "skipped": True, "reason": "NO_SPEC_REJECT_OR_REQUEST_BUDGET", "request_count": 0}

        # Gemini is a transport/provider rescue only when OpenAI produced no usable queue.
        if not queue and os.environ.get("GEMINI_API_KEY", "").strip() and paid < MAX_PAID_REQUESTS:
            queue, providers["gemini_transport_rescue"] = _attempt("gemini", prompt, source_ids, axes, readiness)
            paid += 1; queue = af.dedup(queue, 0.85); dev = econ.evaluate_queue(queue) if queue else _empty_dev()
        else:
            providers["gemini_transport_rescue"] = {"successful": False, "skipped": True, "reason": "OPENAI_QUEUE_PRESENT_OR_GEMINI_UNAVAILABLE", "request_count": 0}

        analysis = failure_econ.analyze(dev, queue, REPAIR_BUDGET) if queue else {"selected_for_single_repair": []}
        selected = [dict(x) for x in (analysis.get("selected_for_single_repair") or []) if isinstance(x, Mapping)]
        remaining = v1._remaining_axes(axes, selected)
        if remaining and paid < MAX_PAID_REQUESTS:
            rfps = v1._fingerprints(ledger, [sid for sid in active if sid in remaining])
            repairs, providers["openai_second_step"] = _attempt("openai", _prompt("SECOND_STEP_DISTINCT_AXIS_BATCH", rfps, remaining, evidence, readiness, prior, selected), source_ids, remaining, readiness)
            paid += 1; repairs = af.dedup(repairs, 0.85); repair_dev = econ.evaluate_queue(repairs) if repairs else _empty_dev()
        else:
            providers["openai_second_step"] = {"successful": False, "skipped": True, "reason": "NO_SELECTED_FAILURE_OR_REQUEST_BUDGET", "request_count": 0}
    else:
        for key in ("openai_initial", "openai_spec_repair", "gemini_transport_rescue", "openai_second_step"):
            providers[key] = {"successful": False, "skipped": True, "reason": "ALL_A5_AXES_ECONOMICALLY_EXHAUSTED", "request_count": 0}

    initial_pass_ids = {str(x.get("candidate_id") or "") for x in dev.get("passes") or [] if isinstance(x, Mapping)}
    repair_pass_ids = {str(x.get("candidate_id") or "") for x in repair_dev.get("passes") or [] if isinstance(x, Mapping)}
    run_terminal = _terminal_axes(queue, dev)
    for sid, rows in _terminal_axes(repairs, repair_dev).items():
        run_terminal.setdefault(sid, [])
        for axis in rows:
            if axis not in run_terminal[sid]: run_terminal[sid].append(axis)

    economic_attempted_axes: dict[str, list[str]] = {}
    by_strategy: dict[str, Any] = {}
    all_pass = initial_pass_ids | repair_pass_ids
    all_rows = [*queue, *repairs]
    for sid in order:
        economic_attempted_axes[sid] = list(dict.fromkeys([*(prior.get(sid) or []), *(run_terminal.get(sid) or [])]))
        rows = [x for x in all_rows if str(x.get("strategy_id") or "") == sid]
        passes = [x for x in rows if str(x.get("candidate_id") or "") in all_pass]
        remaining = [x for x in all_axes[sid] if str(x.get("axis") or "") not in set(economic_attempted_axes[sid])]
        by_strategy[sid] = {
            "candidate_count": len(rows),
            "technical_rejected_axes": technical_reject_axes[sid],
            "economically_tested_axes_this_run": run_terminal.get(sid) or [],
            "economic_attempted_axes": economic_attempted_axes[sid],
            "remaining_axis_count": len(remaining),
            "development_economic_pass_count": len(passes),
            "pass_candidate_ids": [str(x.get("candidate_id") or "") for x in passes],
            "next": "INDEPENDENT_OOS_WALK_FORWARD_STRESS_AND_CONTINUE_RESEARCH" if passes else "NEXT_DISTINCT_ALLOWED_AXIS" if remaining else "AXIS_EXHAUSTED_NO_DEVELOPMENT_PASS",
        }

    total_pass = len(all_pass)
    exhausted = all(by_strategy[sid]["remaining_axis_count"] == 0 for sid in order)
    state = "PASS_A5_V3_DEVELOPMENT_ECONOMIC_CANDIDATE_FOUND" if total_pass else "HOLD_A5_V3_ALL_AXES_EXHAUSTED" if exhausted else "HOLD_A5_V3_CONTINUE_DISTINCT_AXIS_RESEARCH"
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "a5_order": order,
        "active_strategy_ids": active,
        "source_history_readiness": readiness,
        "allowed_axes_by_strategy": all_axes,
        "prior_economic_attempted_axes": prior,
        "economic_attempted_axes": economic_attempted_axes,
        "initial_candidates": queue,
        "initial_development_economics": dev,
        "failure_decomposition": analysis,
        "second_step_candidates": repairs,
        "second_step_development_economics": repair_dev,
        "by_strategy": by_strategy,
        "development_economic_pass_count": total_pass,
        "paid_request_count": paid,
        "paid_request_cap": MAX_PAID_REQUESTS,
        "providers": providers,
        "policy": {
            "a5_only": True,
            "fresh_validation_wait_does_not_block_development_research": True,
            "strict_full_candidate_count_schema": True,
            "executable_dsl_v1_grammar_enforced_in_prompt": True,
            "spec_repair_semantics_frozen": True,
            "technical_spec_reject_does_not_consume_axis": True,
            "economic_terminal_state_required_to_consume_axis": True,
            "previously_economically_tested_axis_reuse_forbidden": True,
            "gemini_is_transport_rescue_not_default_second_builder": True,
            "second_step_must_use_distinct_axis": True,
            "no_threshold_sweep": True,
            "no_holdout_access": True,
            "no_post_outcome_trade_deletion": True,
            "sealed_axis_reuse_forbidden": True,
            "development_pass_is_not_survivor": True,
            "independent_oos_walk_forward_stress_still_required": True,
        },
        **AUTH,
    }
    result["receipt_sha256"] = v4.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    order = ["trend_rider", "break_and_continue"]
    prior = {
        "initial_candidates": [{"candidate_id": "a", "strategy_id": "trend_rider", "changed_axis": "X"}],
        "initial_development_economics": {"rows": [{"candidate_id": "a", "state": "REJECT_UNEXECUTABLE_SPEC"}]},
    }
    assert _candidate_axis_map(prior)["a"] == ("trend_rider", "X")
    # technical reject must not be considered an economic attempt
    tmp = _terminal_axes(prior["initial_candidates"], prior["initial_development_economics"])
    assert tmp == {}
    grammar = _grammar()
    assert grammar["assignments_forbidden"] is True and "both" in grammar["forbidden_examples"]
    assert "sma" in grammar["allowed_functions"] and "median_symbol_universe" not in grammar["allowed_functions"]
    c = v1.contract(); assert v1.a5_order(c) == ["trend_rider", "break_and_continue", "supertrend_pullback", "keltner_trend", "trend_ma_macd"]
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED" and AUTH["live_trade_authority"] == "BLOCKED"
    print("PASS_A1_A5_ECONOMIC_IMPROVEMENT_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_a5_economic_improvement_v3.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({"state": r["state"], "development_pass": r["development_economic_pass_count"], "paid": r["paid_request_count"], "by_strategy": r["by_strategy"], "receipt": r["receipt_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
