#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_a5_economic_improvement_v6 as v6
from backend.research.architecture_factory import a1_a5_economic_improvement_v5 as v5
from backend.research.architecture_factory import a1_a5_economic_improvement_v4 as v4
from backend.research.architecture_factory import a1_a5_economic_improvement_v3 as v3
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

ROOT = Path(__file__).resolve().parents[3]
NAMED = ROOT / "backend/research/architecture_factory/a1_named_channel_gemini_latest.json"
SCHEMA = "zel.a1_a5_economic_improvement.v7"
ORIGIN = "NAMED_CHANNEL_GEMINI_EXECUTABLE_BRIDGE_V1"
TREND_ORIGIN = v5.ORIGIN
COMMON_READY = {"ohlcv", "volume"}
MAX_AXES_PER_STRATEGY = 8
BLOCKED_DSL_TERMS = {
    "stochastic": "DSL_FUNCTION_UNAVAILABLE",
    "fibonacci": "DSL_FUNCTION_UNAVAILABLE",
    "order book": "SOURCE_OR_DSL_UNAVAILABLE",
    "orderbook": "SOURCE_OR_DSL_UNAVAILABLE",
    "l2": "SOURCE_OR_DSL_UNAVAILABLE",
    "trade flow": "SOURCE_OR_DSL_UNAVAILABLE",
    "order flow": "SOURCE_OR_DSL_UNAVAILABLE",
    "trendline": "EXACT_DYNAMIC_TRENDLINE_NOT_IN_FROZEN_DSL",
    "account equity": "POSITION_SIZING_REQUIRES_DEDICATED_EVALUATOR",
    "position size": "POSITION_SIZING_REQUIRES_DEDICATED_EVALUATOR",
    "risk per trade": "POSITION_SIZING_REQUIRES_DEDICATED_EVALUATOR",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _text(raw: Mapping[str, Any], mapping: Mapping[str, Any]) -> str:
    fields: list[Any] = [
        raw.get("mechanism"), raw.get("entry_logic"), raw.get("exit_logic"), raw.get("local_test_needed"),
        raw.get("position_or_exposure_logic"), raw.get("risk_and_drawdown_control"),
        mapping.get("local_test"), mapping.get("mechanism_fit"),
        *(raw.get("data_requirements") or []), *(raw.get("entry_time_features") or []),
        *(raw.get("regime_conditions") or []), *(raw.get("failure_modes") or []),
    ]
    return " ".join(str(x) for x in fields if x).lower()


def _required_sources(text: str) -> set[str]:
    req = {"ohlcv"}
    if "volume" in text:
        req.add("volume")
    if "funding" in text:
        req.add("funding")
    if "open interest" in text or "open_interest" in text:
        req.add("open_interest")
    if "basis" in text:
        req.add("basis")
    if "order book" in text or "orderbook" in text or "l2" in text:
        req.add("l2_order_book")
    if "trade flow" in text or "order flow" in text:
        req.add("trade_flow")
    if "account equity" in text or "position size" in text or "risk per trade" in text:
        req.add("account_equity")
    return req


def _axis_name(source_id: str, strategy_id: str, layer: str, mechanism: str) -> str:
    digest = hashlib.sha256(f"{source_id}|{strategy_id}|{layer}|{mechanism}".encode()).hexdigest()[:12].upper()
    tag = re.sub(r"[^A-Z0-9]+", "_", layer.upper()).strip("_") or "MECH"
    return f"YTNAMED_{tag}_{digest}"


def _priority(layer: str, mode: str, index: int) -> float:
    layer_score = {"entry": 60.0, "context": 55.0, "regime": 54.0, "exit": 50.0}.get(layer, 40.0)
    mode_score = 30.0 if "REPAIR" in mode else 20.0 if "PARALLEL" in mode else 10.0
    return 30000.0 + layer_score + mode_score - min(index, 500) * 0.001


def _extract(doc: Mapping[str, Any], focus: list[str]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    wanted = set(focus)
    axes: dict[str, list[dict[str, Any]]] = {sid: [] for sid in focus}
    evidence: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    seen_mech: set[tuple[str, str]] = set()

    for src_index, src in enumerate(doc.get("accepted_sources") or []):
        if not isinstance(src, Mapping):
            continue
        source_id = str(src.get("id") or "")
        if not source_id.startswith("YTNAMED:"):
            continue
        if src.get("accepted_for_hypothesis_only") is not True or src.get("direct_video_analysis") is not True:
            continue
        if src.get("channel_identity_verified_by_direct_analysis") is not True:
            continue
        for mech in src.get("reproducible_mechanisms") or []:
            if not isinstance(mech, Mapping):
                continue
            layer = str(mech.get("architecture_layer") or "").lower().strip()
            mechanism = str(mech.get("mechanism") or "").strip()
            for mapping in mech.get("candidate_strategy_mappings") or []:
                if not isinstance(mapping, Mapping):
                    continue
                sid = str(mapping.get("strategy_id") or "")
                if sid not in wanted or not mechanism:
                    continue
                mode = str(mapping.get("application_mode") or "")
                text = _text(mech, mapping)
                required = _required_sources(text)
                reason = None
                if layer not in {"entry", "context", "regime", "exit"}:
                    reason = f"UNSUPPORTED_ARCHITECTURE_LAYER:{layer or '<missing>'}"
                elif not required.issubset(COMMON_READY):
                    reason = "NON_COMMON_SOURCE_REQUIRES_SEPARATE_EVALUATOR:" + ",".join(sorted(required - COMMON_READY))
                else:
                    for term, why in BLOCKED_DSL_TERMS.items():
                        if term in text:
                            reason = f"{why}:{term}"
                            break
                if reason:
                    rejected.append({"strategy_id": sid, "source_id": source_id, "channel": src.get("target_channel"), "reason": reason})
                    continue
                norm = re.sub(r"\s+", " ", mechanism.lower()).strip()
                key = (sid, norm)
                if key in seen_mech:
                    continue
                seen_mech.add(key)
                axis = _axis_name(source_id, sid, layer, mechanism)
                row = {
                    "axis": axis,
                    "mechanism": mechanism,
                    "falsification": "Reject unless after-cost PnL and expectancy improve with PF non-degradation, DD non-worsening, and no concentration/retention failure on the frozen development replay.",
                    "required_sources": sorted(required),
                    "priority": _priority(layer, mode, src_index),
                    "source_lane": "READY_COMMON",
                    "external_evidence_ids": [source_id],
                    "named_channel_executable_bridge": True,
                    "named_channel": str(src.get("target_channel") or src.get("actual_channel") or ""),
                    "video_id": str(src.get("video_id") or ""),
                    "architecture_layer": layer,
                    "application_mode": mode,
                    "local_test": str(mapping.get("local_test") or mech.get("local_test_needed") or ""),
                    "creator_numeric_threshold_imported": False,
                    "origin": TREND_ORIGIN if sid == "trend_rider" else ORIGIN,
                }
                if sid == "trend_rider":
                    row["baseline_identity"] = v4.BASELINE_IDENTITY
                axes[sid].append(row)
                evidence[source_id] = {
                    "id": source_id,
                    "tier": "named_channel_direct_gemini_hypothesis",
                    "source_type": "NAMED_CHANNEL_GEMINI_EXECUTABLE_BRIDGE",
                    "identifier": str(src.get("video_id") or ""),
                    "title": str(src.get("title") or ""),
                    "claim": mechanism,
                    "limitations": "Creator performance claims and numeric thresholds are not imported. Mechanism only; local replay and fresh/OOS required.",
                    "channel": str(src.get("target_channel") or src.get("actual_channel") or ""),
                    "promotion_authority": False,
                }

    for sid in focus:
        rows = axes[sid]
        rows.sort(key=lambda x: (-float(x.get("priority") or 0.0), str(x.get("axis") or "")))
        # Diversity first: do not burn the whole cycle on one creator when alternatives exist.
        diverse: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        used_channels: set[str] = set()
        for row in rows:
            ch = str(row.get("named_channel") or "")
            if ch and ch not in used_channels:
                diverse.append(row); used_channels.add(ch)
            else:
                rest.append(row)
        axes[sid] = (diverse + rest)[:MAX_AXES_PER_STRATEGY]
    return axes, list(evidence.values()), rejected


def _merge(primary: Mapping[str, list[dict[str, Any]]], named_axes: Mapping[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    out = {str(k): [dict(x) for x in v] for k, v in primary.items()}
    for sid, named in named_axes.items():
        current = out.setdefault(sid, [])
        best: dict[str, dict[str, Any]] = {str(x.get("axis") or ""): dict(x) for x in current if x.get("axis")}
        for row in named:
            best[str(row["axis"])] = dict(row)
        out[sid] = sorted(best.values(), key=lambda x: (-float(x.get("priority") or 0.0), str(x.get("axis") or "")))
    return out


def _wrap_prompt(original):
    def wrapped(kind, fps, axes, evidence, readiness, prior, selected=None):
        text = original(kind, fps, axes, evidence, readiness, prior, selected)
        marker = "\nCONTEXT="
        if marker not in text:
            return text
        head, raw = text.split(marker, 1)
        try:
            context = json.loads(raw)
        except Exception:
            return text
        allowed = context.get("allowed_untried_axes_by_strategy")
        exact: dict[str, str] = {}
        if isinstance(allowed, Mapping):
            narrowed = {str(k): v for k, v in allowed.items()}
            for sid, rows in allowed.items():
                if not isinstance(rows, list):
                    continue
                named = [x for x in rows if isinstance(x, Mapping) and x.get("named_channel_executable_bridge") is True]
                if named:
                    chosen = dict(named[0])
                    narrowed[str(sid)] = [chosen]
                    exact[str(sid)] = str(chosen.get("axis") or "")
            context["allowed_untried_axes_by_strategy"] = narrowed
        context["named_channel_exact_next_axis_by_strategy"] = exact
        context["named_channel_bridge_policy"] = {
            "mechanism_only": True,
            "creator_numeric_threshold_import_forbidden": True,
            "creator_winrate_or_income_claim_import_forbidden": True,
            "one_axis_per_family_per_generation": True,
            "local_replay_required": True,
            "fresh_oos_required_before_promotion": True,
        }
        constraints = context.setdefault("constraints", {})
        constraints["named_channel_candidate_must_use_exact_axis_when_available"] = True
        constraints["named_channel_candidate_must_include_axis_evidence_id"] = True
        constraints["creator_numeric_threshold_import_forbidden"] = True
        constraints["creator_performance_claim_import_forbidden"] = True
        return head + marker + json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return wrapped


def _wrap_attempt(original):
    def wrapped(provider, prompt, source_ids, axes, readiness):
        rows, meta = original(provider, prompt, source_ids, axes, readiness)
        kept: list[dict[str, Any]] = []
        dropped = 0
        for row in rows:
            sid = str(row.get("strategy_id") or "")
            axis = str(row.get("changed_axis") or "")
            spec = next((x for x in axes.get(sid, []) if str(x.get("axis") or "") == axis), None)
            if isinstance(spec, Mapping) and spec.get("named_channel_executable_bridge") is True:
                required = {str(x) for x in (spec.get("external_evidence_ids") or [])}
                observed = {str(x) for x in (row.get("evidence_ids") or [])}
                if not required.issubset(observed):
                    dropped += 1
                    continue
            kept.append(row)
        m = dict(meta)
        m["named_channel_evidence_guard_dropped"] = dropped
        m["candidate_count_after_named_guard"] = len(kept)
        if rows and not kept:
            m["successful"] = False
        return kept, m
    return wrapped


def _attempted_named(result: Mapping[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key in ("initial_candidates", "second_step_candidates"):
        for raw in result.get(key) or []:
            if not isinstance(raw, Mapping):
                continue
            axis = str(raw.get("changed_axis") or "")
            sid = str(raw.get("strategy_id") or "")
            if axis.startswith("YTNAMED_") and sid:
                out.setdefault(sid, [])
                if axis not in out[sid]:
                    out[sid].append(axis)
    return out


def run(output: Path) -> dict[str, Any]:
    focus, _ = v6._focus_order()
    doc = _read(NAMED)
    named_axes, named_evidence, rejected = _extract(doc, focus)
    eligible_count = sum(len(v) for v in named_axes.values())
    if eligible_count <= 0:
        raise RuntimeError("NAMED_CHANNEL_TOP5_EXECUTABLE_AXIS_EMPTY")

    original_allowed = v3.v1.allowed_axes
    original_evidence = v3.v1.contract_evidence
    original_prompt = v3._prompt
    original_attempt = v3._attempt

    def allowed_with_named(c: Mapping[str, Any], readiness: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
        return _merge(original_allowed(c, readiness), named_axes)

    def evidence_with_named(c: Mapping[str, Any]) -> list[dict[str, Any]]:
        base = original_evidence(c)
        seen = {str(x.get("id") or "") for x in named_evidence}
        return [*named_evidence, *[dict(x) for x in base if str(x.get("id") or "") not in seen]]

    try:
        v3.v1.allowed_axes = allowed_with_named
        v3.v1.contract_evidence = evidence_with_named
        v3._prompt = _wrap_prompt(original_prompt)
        v3._attempt = _wrap_attempt(original_attempt)
        result = dict(v6.run(output))
    finally:
        v3.v1.allowed_axes = original_allowed
        v3.v1.contract_evidence = original_evidence
        v3._prompt = original_prompt
        v3._attempt = original_attempt

    attempted = _attempted_named(result)
    available_by_strategy = {sid: len(named_axes.get(sid) or []) for sid in focus}
    result["named_channel_executable_bridge"] = {
        "state": "PASS_NAMED_CHANNEL_TO_TOP5_ECONOMIC_REPLAY_BOUND",
        "source_path": str(NAMED.relative_to(ROOT)),
        "focus_order": focus,
        "accepted_named_source_count": len(doc.get("accepted_sources") or []),
        "eligible_evidence_count": len(named_evidence),
        "eligible_axis_count": eligible_count,
        "eligible_axis_count_by_strategy": available_by_strategy,
        "attempted_named_axes_by_strategy": attempted,
        "attempted_named_axis_count": sum(len(v) for v in attempted.values()),
        "rejected_mapping_count": len(rejected),
        "rejected_mapping_sample": rejected[:20],
        "creator_numeric_threshold_imported": False,
        "creator_performance_claim_imported": False,
        "local_replay_executed_by_economic_engine": True,
        "fresh_oos_required_before_promotion": True,
    }
    result.setdefault("policy", {})["named_channel_mechanisms_must_enter_top5_economic_replay"] = True
    result["policy"]["creator_numeric_threshold_import_forbidden"] = True
    result["policy"]["creator_performance_claim_import_forbidden"] = True
    result["policy"]["named_channel_risk_sizing_requires_dedicated_evaluator"] = True
    result["schema_version"] = SCHEMA
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    doc = {
        "accepted_sources": [{
            "id": "YTNAMED:abc12345678", "accepted_for_hypothesis_only": True,
            "direct_video_analysis": True, "channel_identity_verified_by_direct_analysis": True,
            "target_channel": "Test Channel", "video_id": "abc12345678", "title": "MA slope",
            "reproducible_mechanisms": [{
                "architecture_layer": "context", "mechanism": "Moving average slope regime filter",
                "data_requirements": ["OHLCV"],
                "candidate_strategy_mappings": [{"strategy_id": "trend_rider", "application_mode": "PARALLEL_HYPOTHESIS_ONLY", "local_test": "Test MA slope regime filter"}],
            }, {
                "architecture_layer": "risk", "mechanism": "Fixed risk per trade using account equity",
                "data_requirements": ["Account Equity"],
                "candidate_strategy_mappings": [{"strategy_id": "trend_rider", "application_mode": "ONE_AXIS_REPAIR_AFTER_LOCAL_ATTRIBUTION"}],
            }],
        }]
    }
    axes, evidence, rejected = _extract(doc, ["trend_rider", "a", "b", "c", "d"])
    assert len(axes["trend_rider"]) == 1, axes
    assert axes["trend_rider"][0]["axis"].startswith("YTNAMED_")
    assert axes["trend_rider"][0]["external_evidence_ids"] == ["YTNAMED:abc12345678"]
    assert axes["trend_rider"][0]["creator_numeric_threshold_imported"] is False
    assert len(evidence) == 1 and rejected, (evidence, rejected)
    merged = _merge({"trend_rider": [{"axis": "OLD", "priority": 1.0}]}, axes)
    assert merged["trend_rider"][0]["axis"].startswith("YTNAMED_")
    assert v3.AUTH["execution_authority"] == "NONE" and v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_A5_ECONOMIC_IMPROVEMENT_V7_SELF_TEST")
    print("PASS_NAMED_CHANNEL_GEMINI_TO_TOP5_EXECUTABLE_BRIDGE")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_a5_economic_improvement_v7.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    b = r.get("named_channel_executable_bridge") or {}
    print(json.dumps({
        "state": r.get("state"),
        "focus": r.get("performance_focus_order"),
        "development_pass": r.get("development_economic_pass_count"),
        "yt_eligible_axes": b.get("eligible_axis_count"),
        "yt_attempted_axes": b.get("attempted_named_axis_count"),
        "yt_by_strategy": b.get("attempted_named_axes_by_strategy"),
        "paid": r.get("paid_request_count"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
