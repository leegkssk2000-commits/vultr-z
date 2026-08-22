#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_failure_economics_v1 as failure_econ
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v3 as econ
from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as af
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as v4
from backend.research.architecture_factory import a1_terminal_repair_swarm_v5 as v5
from backend.research.architecture_factory import gemini_provider_v1 as gemini

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_a5_no_idle_research_v1.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_a5_economic_improvement_latest.json"
SCHEMA = "zel.a1_a5_economic_improvement.v1"
MAX_PAID_REQUESTS = 3
REPAIR_BUDGET = 3
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def contract() -> dict[str, Any]:
    c = read(CONTRACT)
    if c.get("schema_version") != "zel.a1.a5_no_idle_research.v1":
        raise RuntimeError("A5_CONTRACT_SCHEMA_MISMATCH")
    return c


def a5_order(c: Mapping[str, Any]) -> list[str]:
    rows = [str(x) for x in (c.get("a5_priority_order") or [])]
    if len(rows) != 5 or len(set(rows)) != 5:
        raise RuntimeError("A5_EXACT5_REQUIRED")
    return rows


def contract_evidence(c: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in c.get("external_evidence") or []:
        if not isinstance(raw, Mapping) or not raw.get("id"):
            continue
        out.append({
            "id": str(raw.get("id")),
            "tier": str(raw.get("tier") or "external_primary"),
            "source_type": "A5_FROZEN_EXTERNAL_EVIDENCE",
            "identifier": str(raw.get("identifier") or ""),
            "title": str(raw.get("title") or ""),
            "claim": str(raw.get("use") or ""),
            "limitations": "Mechanism hypothesis only; numeric thresholds and holdout outcomes are not imported.",
            "promotion_authority": False,
        })
    return out


def source_readiness() -> dict[str, Any]:
    return v5._history_readiness()


def allowed_axes(c: Mapping[str, Any], readiness: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    ready_sources = {k for k, raw in readiness.items() if isinstance(raw, Mapping) and raw.get("ready") is True}
    ready_sources.update({"ohlcv", "volume"})
    strategies = c.get("strategies") or {}
    out: dict[str, list[dict[str, Any]]] = {}
    for sid in a5_order(c):
        block = strategies.get(sid) if isinstance(strategies, Mapping) else None
        if not isinstance(block, Mapping):
            raise RuntimeError(f"A5_STRATEGY_CONTRACT_MISSING:{sid}")
        sealed = str(block.get("sealed_exact25_axis") or "")
        rows: list[dict[str, Any]] = []
        for raw in block.get("repair_axes") or []:
            if not isinstance(raw, Mapping):
                continue
            axis = str(raw.get("axis") or "").strip()
            req = {str(x) for x in (raw.get("required_sources") or [])}
            if not axis or axis == sealed or not req or not req.issubset(ready_sources):
                continue
            rows.append({
                "axis": axis,
                "mechanism": str(raw.get("mechanism") or ""),
                "required_sources": sorted(req),
                "priority": float(raw.get("priority") or 0),
                "source_lane": str(raw.get("source_lane") or ""),
            })
        rows.sort(key=lambda x: (-float(x["priority"]), x["axis"]))
        out[sid] = rows
    return out


def _fingerprints(ledger: Mapping[str, Any], order: list[str]) -> list[dict[str, Any]]:
    states = ledger.get("strategies") or {}
    out = []
    for sid in order:
        raw = states.get(sid) if isinstance(states, Mapping) else None
        if not isinstance(raw, Mapping):
            raise RuntimeError(f"A5_LEDGER_ROW_MISSING:{sid}")
        out.append(v4.fingerprint(sid, raw))
    return out


def _prompt(kind: str, fps: list[dict[str, Any]], axes: Mapping[str, Any], evidence: list[dict[str, Any]], readiness: Mapping[str, Any], selected: list[dict[str, Any]] | None = None) -> str:
    base = {
        "task": kind,
        "a5_failures": fps,
        "allowed_axes_by_strategy": axes,
        "selected_failed_candidates": selected or [],
        "source_history_readiness": readiness,
        "external_evidence": evidence[:36],
        "constraints": {
            "mode": "REPAIR_ONLY",
            "exact_strategy_id_required": True,
            "one_changed_axis_only": True,
            "changed_axis_must_come_from_allowed_axes_by_strategy": True,
            "sealed_exact25_axis_reuse": False,
            "threshold_sweep": False,
            "best_horizon_selection": False,
            "holdout_access": False,
            "post_outcome_trade_deletion": False,
            "fee_reduction_rescue": False,
            "verified_round_trip_cost_bps": 14.0,
            "development_data": "STRICTLY_PRE_GEN1_BOUNDARY",
            "selection_authority": False,
            "promotion_authority": False,
        },
        "optimization": {
            "primary": "after-cost positive economic edge with lower fragility",
            "report_not_optimize_by_single_metric": ["net_expectancy_bps", "net_pnl_bps", "profit_factor", "payoff", "win_rate", "drawdown_bps", "retention", "concentration"],
            "volatility_scaling": "must preserve separate unscaled-signal and scaled-risk attribution",
        },
    }
    if kind == "INITIAL_A5_REPAIR_BATCH":
        instruction = (
            "Produce at most ONE best causal REPAIR for EACH of the five supplied A-grade strategies. "
            "Do not stop because a parent has a high PF/payoff. Choose one allowed post-sealed axis that directly attacks fragility or after-cost edge. "
        )
    else:
        instruction = (
            "For each selected failed strategy, produce at most ONE second-step causal REPAIR using a DISTINCT remaining allowed axis. "
            "Preserve the exact strategy family and do not repeat the failed parent changed_axis. "
        )
    return (
        "You are the A5 economic improvement builder. " + instruction +
        "Every emitted candidate MUST include a deterministic executable_spec compatible with EXECUTABLE_DSL_V1: "
        "bar_interval, features[{name,formula}], entry_rule, side_rule, exit_rule, max_hold_bars, entry_timing, cost_model, development_data_rule, parameter_provenance. "
        "Use only supplied evidence_ids; do not invent sources. Return generator-contract JSON only.\nCONTEXT=" +
        json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _filter_attach(raw: Mapping[str, Any], provider: str, source_ids: set[str], axes: Mapping[str, list[dict[str, Any]]], readiness: Mapping[str, Any]) -> list[dict[str, Any]]:
    allowed_sources = v4._allowed_sources(readiness)
    allowed_sources.update({"ohlcv", "volume"})
    targets = set(axes)
    validated = af.validate_candidates(raw, provider, source_ids, targets)
    filtered: list[dict[str, Any]] = []
    for row in validated:
        sid = str(row.get("strategy_id") or "")
        if row.get("mode") != "REPAIR" or sid not in axes:
            continue
        axis = str(row.get("changed_axis") or "")
        permitted = {str(x.get("axis") or "") for x in axes[sid]}
        req = {str(x) for x in (row.get("required_sources") or [])}
        if axis not in permitted or not req or not req.issubset(allowed_sources):
            continue
        filtered.append(dict(row))
    attached = v4._attach(raw, filtered, allowed_sources)
    best: dict[str, dict[str, Any]] = {}
    for row in attached:
        sid = str(row.get("strategy_id") or "")
        old = best.get(sid)
        if old is None or af.base_score(row) > af.base_score(old):
            best[sid] = row
    return [best[sid] for sid in axes if sid in best]


def _remaining_axes(axes: Mapping[str, list[dict[str, Any]]], selected: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for raw in selected:
        sid = str(raw.get("strategy_id") or "")
        failed_axis = str(raw.get("changed_axis") or "")
        if sid not in axes:
            continue
        rows = [dict(x) for x in axes[sid] if str(x.get("axis") or "") != failed_axis]
        if rows:
            out[sid] = rows
    return out


def _empty_dev() -> dict[str, Any]:
    return {"economic_pass_count": 0, "economic_fail_count": 0, "source_skip_count": 0, "spec_reject_count": 0, "passes": [], "rows": []}


def _provider_call(provider: str, prompt: str) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
    if provider == "openai":
        return af.call_openai_generator(prompt)
    if provider == "gemini":
        return gemini.call_gemini_generator(prompt)
    raise RuntimeError(f"UNKNOWN_PROVIDER:{provider}")


def _attempt(provider: str, prompt: str, source_ids: set[str], axes: Mapping[str, list[dict[str, Any]]], readiness: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        model, raw, lineage = _provider_call(provider, prompt)
        rows = _filter_attach(raw, provider, source_ids, axes, readiness)
        return rows, {"successful": bool(rows), "model": model, **dict(lineage), "candidate_count": len(rows), "request_count": 1}
    except Exception as exc:  # noqa: BLE001
        return [], {"successful": False, "error": af.safe_error(exc), "candidate_count": 0, "request_count": 1}


def run(output: Path) -> dict[str, Any]:
    c = contract(); order = a5_order(c)
    ledger = af.read_json(af.LEDGER); evidence_doc = af.read_json(af.EVIDENCE)
    readiness = source_readiness(); axes = allowed_axes(c, readiness)
    if any(not axes.get(sid) for sid in order):
        missing = [sid for sid in order if not axes.get(sid)]
        raise RuntimeError("A5_NO_SOURCE_READY_REPAIR_AXIS:" + ",".join(missing))

    evidence = af.evidence_compact(evidence_doc)
    evidence = [*contract_evidence(c), *evidence]
    source_ids = {str(x.get("id")) for x in evidence if x.get("id")}
    fps = _fingerprints(ledger, order)
    providers: dict[str, Any] = {}
    paid = 0

    prompt = _prompt("INITIAL_A5_REPAIR_BATCH", fps, axes, evidence, readiness)
    openai_rows, providers["openai_initial"] = _attempt("openai", prompt, source_ids, axes, readiness)
    paid += 1
    queue = af.dedup(openai_rows, 0.85)
    dev = econ.evaluate_queue(queue) if queue else _empty_dev()

    gemini_rows: list[dict[str, Any]] = []
    if int(dev.get("economic_pass_count") or 0) == 0 and os.environ.get("GEMINI_API_KEY", "").strip() and paid < MAX_PAID_REQUESTS:
        gemini_rows, providers["gemini_rescue"] = _attempt("gemini", prompt, source_ids, axes, readiness)
        paid += 1
        queue = af.dedup([*queue, *gemini_rows], 0.85)
        dev = econ.evaluate_queue(queue) if queue else _empty_dev()
    else:
        providers["gemini_rescue"] = {"successful": False, "skipped": True, "reason": "INITIAL_ECONOMIC_PASS_PRESENT_OR_GEMINI_UNAVAILABLE", "request_count": 0}

    analysis = failure_econ.analyze(dev, queue, REPAIR_BUDGET) if queue else {"selected_for_single_repair": []}
    selected = [dict(x) for x in (analysis.get("selected_for_single_repair") or []) if isinstance(x, Mapping)]
    remaining = _remaining_axes(axes, selected)
    repairs: list[dict[str, Any]] = []
    repair_dev = _empty_dev()
    if remaining and paid < MAX_PAID_REQUESTS:
        repair_prompt = _prompt("SECOND_STEP_DISTINCT_AXIS_BATCH", fps, remaining, evidence, readiness, selected)
        repairs, providers["openai_second_step"] = _attempt("openai", repair_prompt, source_ids, remaining, readiness)
        paid += 1
        repairs = af.dedup(repairs, 0.85)
        repair_dev = econ.evaluate_queue(repairs) if repairs else _empty_dev()
    else:
        providers["openai_second_step"] = {"successful": False, "skipped": True, "reason": "NO_SELECTED_FAILURE_OR_REQUEST_BUDGET", "request_count": 0}

    initial_pass_ids = {str(x.get("candidate_id") or "") for x in (dev.get("passes") or []) if isinstance(x, Mapping)}
    repair_pass_ids = {str(x.get("candidate_id") or "") for x in (repair_dev.get("passes") or []) if isinstance(x, Mapping)}
    all_rows = [*queue, *repairs]
    by_strategy: dict[str, Any] = {}
    for sid in order:
        rows = [x for x in all_rows if str(x.get("strategy_id") or "") == sid]
        passes = [x for x in rows if str(x.get("candidate_id") or "") in initial_pass_ids | repair_pass_ids]
        by_strategy[sid] = {
            "attempt_count": len(rows),
            "development_economic_pass_count": len(passes),
            "attempted_axes": [str(x.get("changed_axis") or "") for x in rows],
            "pass_candidate_ids": [str(x.get("candidate_id") or "") for x in passes],
            "next": "INDEPENDENT_OOS_WALK_FORWARD_STRESS" if passes else "NEXT_DISTINCT_ALLOWED_AXIS",
        }

    total_pass = len(initial_pass_ids | repair_pass_ids)
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_A5_DEVELOPMENT_ECONOMIC_CANDIDATE_FOUND" if total_pass else "HOLD_A5_NO_DEVELOPMENT_ECONOMIC_PASS_YET",
        "a5_order": order,
        "source_history_readiness": readiness,
        "allowed_axes_by_strategy": axes,
        "external_evidence_ids": [str(x.get("id")) for x in contract_evidence(c)],
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
            "one_best_initial_axis_per_strategy": True,
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
    c = contract(); order = a5_order(c)
    fake_readiness = {
        "ohlcv": {"ready": True}, "volume": {"ready": True}, "funding": {"ready": True},
        "basis": {"ready": False}, "open_interest": {"ready": False}, "l2_order_book": {"ready": False}, "trade_flow": {"ready": False},
    }
    axes = allowed_axes(c, fake_readiness)
    assert order == ["trend_rider", "break_and_continue", "supertrend_pullback", "keltner_trend", "trend_ma_macd"]
    assert len(axes["trend_rider"]) >= 9
    for sid in order:
        sealed = c["strategies"][sid]["sealed_exact25_axis"]
        assert sealed not in {x["axis"] for x in axes[sid]}
        assert len(axes[sid]) >= 4
    assert c["global_invariants"]["research_queue_must_continue_during_fresh_wait"] is True
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED" and AUTH["live_trade_authority"] == "BLOCKED"
    print("PASS_A1_A5_ECONOMIC_IMPROVEMENT_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_a5_economic_improvement_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r["state"],
        "development_pass": r["development_economic_pass_count"],
        "paid_requests": r["paid_request_count"],
        "by_strategy": r["by_strategy"],
        "receipt": r["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
