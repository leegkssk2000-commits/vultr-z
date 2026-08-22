#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_failure_economics_v1 as failure_econ
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v3 as econ
from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as af
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as v4
from backend.research.architecture_factory import gemini_provider_v1 as gemini
from backend.research.architecture_factory import a1_a5_economic_improvement_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
LATEST = ROOT / "backend/research/architecture_factory/a1_a5_economic_improvement_latest.json"
SCHEMA = "zel.a1_a5_economic_improvement.v2"
MAX_PAID_REQUESTS = 3
REPAIR_BUDGET = 3
AUTH = dict(v1.AUTH)


def _json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _openai_schema(node: Any) -> Any:
    if isinstance(node, list):
        return [_openai_schema(x) for x in node]
    if not isinstance(node, Mapping):
        return node
    out: dict[str, Any] = {}
    type_map = {"OBJECT": "object", "ARRAY": "array", "STRING": "string", "INTEGER": "integer", "NUMBER": "number", "BOOLEAN": "boolean"}
    for key, value in node.items():
        if key == "type" and isinstance(value, str):
            out[key] = type_map.get(value, value.lower())
        elif key == "properties" and isinstance(value, Mapping):
            out[key] = {str(k): _openai_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = _openai_schema(value)
        else:
            out[key] = _openai_schema(value)
    if out.get("type") == "object":
        out["additionalProperties"] = False
    return out


OPENAI_GENERATOR_SCHEMA = _openai_schema(gemini.GENERATOR_RESPONSE_SCHEMA)


def _strict_openai_generator(prompt: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip() or "gpt-5-mini"
    if not key:
        raise RuntimeError("OPENAI_API_KEY_MISSING")
    body: dict[str, Any] = {
        "model": model,
        "store": False,
        "instructions": (
            "Return only the requested A5 strategy-repair JSON. Every candidate must include the complete executable_spec. "
            "Use only supplied evidence IDs. Do not browse, tune from outcomes, or infer sealed holdout outcomes."
        ),
        "input": prompt,
        "max_output_tokens": 8000,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "a1_a5_economic_improvement_v2",
                "strict": True,
                "schema": OPENAI_GENERATOR_SCHEMA,
            }
        },
    }
    if model.lower().startswith("gpt-5"):
        body["reasoning"] = {"effort": "minimal"}
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:900]
        raise RuntimeError(f"OPENAI_A5_V2_HTTP_{exc.code}:{detail}") from exc
    text = af.extract_openai_text(payload)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OPENAI_A5_V2_STRICT_JSON_INVALID:{exc.msg}:{exc.lineno}:{exc.colno}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("OPENAI_A5_V2_OBJECT_REQUIRED")
    return model, value, {
        "prompt_sha": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "structured_output": "strict",
        "provider_contract": "A5_ECONOMIC_V2",
    }


def _compact_gemini_prompt(prompt: str) -> str:
    marker = "CONTEXT="
    if marker not in prompt:
        return prompt
    prefix, raw = prompt.split(marker, 1)
    try:
        context = json.loads(raw)
    except Exception:
        return prompt
    if not isinstance(context, dict):
        return prompt
    readiness = context.get("source_history_readiness")
    if isinstance(readiness, Mapping):
        compact_ready: dict[str, Any] = {}
        for source, row in readiness.items():
            if not isinstance(row, Mapping):
                continue
            compact_ready[str(source)] = {
                k: row.get(k)
                for k in ("ready", "reason", "coverage_progress_ratio", "remaining_days", "prospective_only")
                if row.get(k) is not None
            }
        context["source_history_readiness"] = compact_ready
    evidence = context.get("external_evidence")
    if isinstance(evidence, list):
        compact_evidence = []
        for row in evidence[:24]:
            if not isinstance(row, Mapping):
                continue
            compact_evidence.append({
                "id": row.get("id"),
                "tier": row.get("tier"),
                "identifier": row.get("identifier"),
                "claim": str(row.get("claim") or "")[:500],
                "limitations": str(row.get("limitations") or "")[:240],
            })
        context["external_evidence"] = compact_evidence
    return prefix + marker + json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _provider_call(provider: str, prompt: str) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
    if provider == "openai":
        return _strict_openai_generator(prompt)
    if provider == "gemini":
        return gemini.call_gemini_generator(_compact_gemini_prompt(prompt))
    raise RuntimeError(f"UNKNOWN_PROVIDER:{provider}")


def _attempt(provider: str, prompt: str, source_ids: set[str], axes: Mapping[str, list[dict[str, Any]]], readiness: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        model, raw, lineage = _provider_call(provider, prompt)
        rows = v1._filter_attach(raw, provider, source_ids, axes, readiness)
        return rows, {
            "successful": bool(rows),
            "model": model,
            **dict(lineage),
            "candidate_count": len(rows),
            "request_count": 1,
        }
    except Exception as exc:  # noqa: BLE001
        return [], {
            "successful": False,
            "error": af.safe_error(exc),
            "candidate_count": 0,
            "request_count": 1,
        }


def _prior_attempts(order: list[str]) -> dict[str, list[str]]:
    prior = _json(LATEST)
    cumulative = prior.get("cumulative_attempted_axes")
    out: dict[str, list[str]] = {sid: [] for sid in order}
    if isinstance(cumulative, Mapping):
        for sid in order:
            rows = cumulative.get(sid)
            if isinstance(rows, list):
                out[sid] = list(dict.fromkeys(str(x) for x in rows if str(x)))
        return out
    by = prior.get("by_strategy")
    if isinstance(by, Mapping):
        for sid in order:
            row = by.get(sid)
            if not isinstance(row, Mapping):
                continue
            rows = row.get("attempted_axes")
            if isinstance(rows, list):
                out[sid] = list(dict.fromkeys(str(x) for x in rows if str(x)))
    return out


def _filter_untried_axes(
    axes: Mapping[str, list[dict[str, Any]]],
    prior: Mapping[str, list[str]],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for sid, rows in axes.items():
        used = set(prior.get(sid) or [])
        remain = [dict(x) for x in rows if str(x.get("axis") or "") not in used]
        if remain:
            out[sid] = remain
    return out


def _prompt(
    kind: str,
    fps: list[dict[str, Any]],
    axes: Mapping[str, Any],
    evidence: list[dict[str, Any]],
    readiness: Mapping[str, Any],
    prior_attempts: Mapping[str, list[str]],
    selected: list[dict[str, Any]] | None = None,
) -> str:
    base = {
        "task": kind,
        "a5_failures": fps,
        "allowed_untried_axes_by_strategy": axes,
        "prior_attempted_axes_by_strategy": prior_attempts,
        "selected_failed_candidates": selected or [],
        "source_history_readiness": readiness,
        "external_evidence": evidence[:36],
        "constraints": {
            "mode": "REPAIR_ONLY",
            "exact_strategy_id_required": True,
            "one_changed_axis_only": True,
            "changed_axis_must_come_from_allowed_untried_axes_by_strategy": True,
            "sealed_exact25_axis_reuse": False,
            "previously_attempted_axis_reuse": False,
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
            "joint_metrics": [
                "net_expectancy_bps", "net_pnl_bps", "profit_factor", "payoff", "win_rate",
                "drawdown_bps", "retention", "cost_turnover", "symbol_regime_side_robustness", "concentration",
            ],
            "volatility_scaling": "report unscaled signal edge and scaled risk-management effect separately",
        },
    }
    if kind == "INITIAL_A5_REPAIR_BATCH":
        instruction = (
            "Produce at most ONE best causal REPAIR for EACH supplied A-grade strategy. "
            "Do not stop because the current parent already has a high PF/payoff. Use one UNTRIED post-sealed axis that attacks fragility or after-cost edge. "
        )
    else:
        instruction = (
            "For each selected failed strategy, produce at most ONE second-step causal REPAIR using a DISTINCT remaining UNTRIED axis. "
            "Do not repeat either historical attempted axes or the current failed changed_axis. "
        )
    contract_shape = af.generator_contract()
    contract_shape["candidates"][0]["executable_spec"] = {
        "bar_interval": "5m|15m|30m|1h|4h|1d",
        "features": [{"name": "string", "formula": "deterministic completed-bar formula"}],
        "entry_rule": "deterministic rule",
        "side_rule": "deterministic rule",
        "exit_rule": "deterministic rule",
        "max_hold_bars": 1,
        "entry_timing": "completed-bar timing",
        "cost_model": "14bps verified round trip",
        "development_data_rule": "STRICTLY_PRE_GEN1_BOUNDARY",
        "parameter_provenance": "causal/mechanism prior, never outcome sweep",
    }
    return (
        "You are the A5 economic improvement builder. " + instruction +
        "Every emitted candidate MUST include deterministic EXECUTABLE_DSL_V1 and use only supplied evidence_ids. "
        "No numeric threshold sweep, outcome rescue, loss deletion, fee rescue, or holdout access. Return JSON only matching: " +
        json.dumps(contract_shape, ensure_ascii=False, sort_keys=True, separators=(",", ":")) +
        "\nCONTEXT=" + json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _empty_dev() -> dict[str, Any]:
    return {"economic_pass_count": 0, "economic_fail_count": 0, "source_skip_count": 0, "spec_reject_count": 0, "passes": [], "rows": []}


def run(output: Path) -> dict[str, Any]:
    c = v1.contract()
    order = v1.a5_order(c)
    ledger = af.read_json(af.LEDGER)
    evidence_doc = af.read_json(af.EVIDENCE)
    readiness = v1.source_readiness()
    all_axes = v1.allowed_axes(c, readiness)
    prior = _prior_attempts(order)
    axes = _filter_untried_axes(all_axes, prior)
    active = [sid for sid in order if sid in axes]

    evidence = [*v1.contract_evidence(c), *af.evidence_compact(evidence_doc)]
    source_ids = {str(x.get("id")) for x in evidence if x.get("id")}
    providers: dict[str, Any] = {}
    paid = 0
    queue: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    dev = _empty_dev()
    repair_dev = _empty_dev()
    analysis: dict[str, Any] = {"selected_for_single_repair": []}

    if active:
        fps = v1._fingerprints(ledger, active)
        prompt = _prompt("INITIAL_A5_REPAIR_BATCH", fps, axes, evidence, readiness, prior)
        openai_rows, providers["openai_initial"] = _attempt("openai", prompt, source_ids, axes, readiness)
        paid += 1
        queue = af.dedup(openai_rows, 0.85)
        dev = econ.evaluate_queue(queue) if queue else _empty_dev()

        if int(dev.get("economic_pass_count") or 0) == 0 and os.environ.get("GEMINI_API_KEY", "").strip() and paid < MAX_PAID_REQUESTS:
            gemini_rows, providers["gemini_rescue"] = _attempt("gemini", prompt, source_ids, axes, readiness)
            paid += 1
            queue = af.dedup([*queue, *gemini_rows], 0.85)
            dev = econ.evaluate_queue(queue) if queue else _empty_dev()
        else:
            providers["gemini_rescue"] = {
                "successful": False,
                "skipped": True,
                "reason": "INITIAL_ECONOMIC_PASS_PRESENT_OR_GEMINI_UNAVAILABLE",
                "request_count": 0,
            }

        analysis = failure_econ.analyze(dev, queue, REPAIR_BUDGET) if queue else {"selected_for_single_repair": []}
        selected = [dict(x) for x in (analysis.get("selected_for_single_repair") or []) if isinstance(x, Mapping)]
        remaining = v1._remaining_axes(axes, selected)
        if remaining and paid < MAX_PAID_REQUESTS:
            repair_fps = v1._fingerprints(ledger, [sid for sid in active if sid in remaining])
            repair_prompt = _prompt("SECOND_STEP_DISTINCT_AXIS_BATCH", repair_fps, remaining, evidence, readiness, prior, selected)
            repairs, providers["openai_second_step"] = _attempt("openai", repair_prompt, source_ids, remaining, readiness)
            paid += 1
            repairs = af.dedup(repairs, 0.85)
            repair_dev = econ.evaluate_queue(repairs) if repairs else _empty_dev()
        else:
            providers["openai_second_step"] = {
                "successful": False,
                "skipped": True,
                "reason": "NO_SELECTED_FAILURE_OR_REQUEST_BUDGET",
                "request_count": 0,
            }
    else:
        providers = {
            "openai_initial": {"successful": False, "skipped": True, "reason": "ALL_A5_AXES_EXHAUSTED", "request_count": 0},
            "gemini_rescue": {"successful": False, "skipped": True, "reason": "ALL_A5_AXES_EXHAUSTED", "request_count": 0},
            "openai_second_step": {"successful": False, "skipped": True, "reason": "ALL_A5_AXES_EXHAUSTED", "request_count": 0},
        }

    initial_pass_ids = {str(x.get("candidate_id") or "") for x in (dev.get("passes") or []) if isinstance(x, Mapping)}
    repair_pass_ids = {str(x.get("candidate_id") or "") for x in (repair_dev.get("passes") or []) if isinstance(x, Mapping)}
    all_rows = [*queue, *repairs]
    current_attempted: dict[str, list[str]] = {sid: [] for sid in order}
    for row in all_rows:
        sid = str(row.get("strategy_id") or "")
        axis = str(row.get("changed_axis") or "")
        if sid in current_attempted and axis and axis not in current_attempted[sid]:
            current_attempted[sid].append(axis)

    cumulative: dict[str, list[str]] = {}
    by_strategy: dict[str, Any] = {}
    all_pass_ids = initial_pass_ids | repair_pass_ids
    for sid in order:
        cumulative[sid] = list(dict.fromkeys([*(prior.get(sid) or []), *current_attempted[sid]]))
        rows = [x for x in all_rows if str(x.get("strategy_id") or "") == sid]
        passes = [x for x in rows if str(x.get("candidate_id") or "") in all_pass_ids]
        remaining_axes = [x for x in all_axes[sid] if str(x.get("axis") or "") not in set(cumulative[sid])]
        by_strategy[sid] = {
            "attempt_count": len(rows),
            "attempted_axes": current_attempted[sid],
            "cumulative_attempted_axes": cumulative[sid],
            "remaining_axis_count": len(remaining_axes),
            "development_economic_pass_count": len(passes),
            "pass_candidate_ids": [str(x.get("candidate_id") or "") for x in passes],
            "next": (
                "INDEPENDENT_OOS_WALK_FORWARD_STRESS_AND_CONTINUE_RESEARCH" if passes
                else "NEXT_DISTINCT_ALLOWED_AXIS" if remaining_axes
                else "AXIS_EXHAUSTED_NO_DEVELOPMENT_PASS"
            ),
        }

    total_pass = len(all_pass_ids)
    exhausted = all(by_strategy[sid]["remaining_axis_count"] == 0 for sid in order)
    state = (
        "PASS_A5_V2_DEVELOPMENT_ECONOMIC_CANDIDATE_FOUND" if total_pass
        else "HOLD_A5_V2_ALL_AXES_EXHAUSTED" if exhausted
        else "HOLD_A5_V2_CONTINUE_DISTINCT_AXIS_RESEARCH"
    )
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "a5_order": order,
        "active_strategy_ids": active,
        "source_history_readiness": readiness,
        "allowed_axes_by_strategy": all_axes,
        "untried_axes_this_run": axes,
        "prior_attempted_axes": prior,
        "cumulative_attempted_axes": cumulative,
        "external_evidence_ids": [str(x.get("id")) for x in v1.contract_evidence(c)],
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
            "strict_openai_structured_output": True,
            "gemini_prompt_compaction": True,
            "cumulative_axis_memory": True,
            "previously_attempted_axis_reuse_forbidden": True,
            "stop_paid_calls_when_all_axes_exhausted": True,
            "one_best_initial_axis_per_active_strategy": True,
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
    schema = OPENAI_GENERATOR_SCHEMA
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    item = schema["properties"]["candidates"]["items"]
    assert item["type"] == "object" and item["additionalProperties"] is False
    assert "executable_spec" in item["properties"] and "executable_spec" in item["required"]
    axes = {
        "trend_rider": [{"axis": "A"}, {"axis": "B"}],
        "break_and_continue": [{"axis": "C"}],
    }
    remain = _filter_untried_axes(axes, {"trend_rider": ["A"], "break_and_continue": []})
    assert [x["axis"] for x in remain["trend_rider"]] == ["B"]
    assert [x["axis"] for x in remain["break_and_continue"]] == ["C"]
    compact = _compact_gemini_prompt('X CONTEXT={"source_history_readiness":{"x":{"ready":true,"reason":"ok","noise":123}},"external_evidence":[]}')
    assert '"noise"' not in compact and '"ready":true' in compact
    c = v1.contract(); order = v1.a5_order(c)
    assert order == ["trend_rider", "break_and_continue", "supertrend_pullback", "keltner_trend", "trend_ma_macd"]
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED" and AUTH["live_trade_authority"] == "BLOCKED"
    print("PASS_A1_A5_ECONOMIC_IMPROVEMENT_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_a5_economic_improvement_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r["state"],
        "development_pass": r["development_economic_pass_count"],
        "paid_requests": r["paid_request_count"],
        "active": r["active_strategy_ids"],
        "by_strategy": r["by_strategy"],
        "receipt": r["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
