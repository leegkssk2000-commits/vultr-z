#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import backend.research.architecture_factory.a1_research_factory_v1 as v1
import backend.research.architecture_factory.a1_research_factory_v2 as v2
import backend.research.architecture_factory.a1_research_factory_v3 as v3
import backend.research.architecture_factory.a1_research_factory_v5 as v5

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_a5_no_idle_research_v1.json"
TREND_RIDER_EXPANSION = ROOT / "backend/research/contracts/a1_trend_rider_online_expansion_v1.json"
P3_CONTRACT = ROOT / "backend/research/contracts/p3_carry_flow_prospective_native_v1.json"
SCHEMA = "zel.a1_research_factory.v6"
COMMON_READY = {"ohlcv", "volume"}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _contract() -> dict[str, Any]:
    c = _read(CONTRACT)
    if c.get("schema_version") != "zel.a1.a5_no_idle_research.v1":
        raise RuntimeError("A5_NO_IDLE_CONTRACT_SCHEMA_MISMATCH")
    return c


def _trend_rider_expansion() -> dict[str, Any]:
    c = _read(TREND_RIDER_EXPANSION)
    if c.get("schema_version") != "zel.a1.trend_rider.online_expansion.v1":
        raise RuntimeError("TREND_RIDER_ONLINE_EXPANSION_SCHEMA_MISMATCH")
    if c.get("strategy_id") != "trend_rider":
        raise RuntimeError("TREND_RIDER_ONLINE_EXPANSION_IDENTITY_MISMATCH")
    if c.get("baseline_identity") != "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3":
        raise RuntimeError("TREND_RIDER_ONLINE_EXPANSION_BASELINE_MISMATCH")
    return c


def _a5_order(c: Mapping[str, Any]) -> list[str]:
    rows = [str(x) for x in (c.get("a5_priority_order") or [])]
    if len(rows) != 5 or len(set(rows)) != 5:
        raise RuntimeError("A5_PRIORITY_EXACT5_REQUIRED")
    return rows


def _contract_ready_rows(c: Mapping[str, Any], strategy_id: str) -> list[dict[str, Any]]:
    strategies = c.get("strategies") or {}
    block = strategies.get(strategy_id) if isinstance(strategies, Mapping) else None
    if not isinstance(block, Mapping):
        return []
    sealed = str(block.get("sealed_exact25_axis") or "")
    out: list[dict[str, Any]] = []
    for raw in block.get("repair_axes") or []:
        if not isinstance(raw, Mapping):
            continue
        axis = str(raw.get("axis") or "").strip()
        required = [str(x) for x in (raw.get("required_sources") or [])]
        if not axis or axis == sealed:
            continue
        if raw.get("source_lane") != "READY_COMMON" or not set(required).issubset(COMMON_READY):
            continue
        out.append({
            "strategy_id": strategy_id,
            "axis": axis,
            "mechanism": str(raw.get("mechanism") or ""),
            "required_sources": required,
            "source_ids": [],
            "score": 10000.0 + float(raw.get("priority") or 0),
            "origin": "A5_NO_IDLE_CONTRACT",
            "status": "FROZEN_POST_SEALED_REPAIR_AXIS",
            "source_gate": "READY_COMMON",
            "eligible_for_experiment_queue": False,
        })
    out.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("axis") or "")))
    return out


def _supplemental_ready_rows(strategy_id: str) -> list[dict[str, Any]]:
    if strategy_id != "trend_rider":
        return []
    c = _trend_rider_expansion()
    out: list[dict[str, Any]] = []
    for raw in c.get("repair_axes") or []:
        if not isinstance(raw, Mapping):
            continue
        axis = str(raw.get("axis") or "").strip()
        required = [str(x) for x in (raw.get("required_sources") or [])]
        if not axis:
            continue
        if raw.get("source_lane") != "READY_COMMON" or not set(required).issubset(COMMON_READY):
            continue
        out.append({
            "strategy_id": "trend_rider",
            "axis": axis,
            "mechanism": str(raw.get("mechanism") or ""),
            "falsification": str(raw.get("falsification") or ""),
            "required_sources": required,
            "source_ids": [],
            "external_evidence_ids": [str(x) for x in (raw.get("evidence_ids") or [])],
            "baseline_identity": c.get("baseline_identity"),
            "score": 20000.0 + float(raw.get("priority") or 0),
            "origin": "TREND_RIDER_ONLINE_EXPANSION",
            "status": "FROZEN_EXTERNAL_EVIDENCE_AXIS",
            "source_gate": "READY_COMMON",
            "eligible_for_experiment_queue": False,
        })
    out.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("axis") or "")))
    return out


def _lineage_pool(rows: Any) -> list[str]:
    """Reuse only evidence already admitted for the exact strategy READY_COMMON backlog.

    Contract-added axes may be new post-sealed identities, but their executable lineage
    cannot be fabricated. Supplemental online-evidence IDs remain hypothesis metadata;
    source_ids are still seeded only from the exact strategy READY backlog and then
    independently reviewed before any replay can become eligible.
    """
    out: list[str] = []
    if not isinstance(rows, list):
        return out
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("origin") == "SEALED_EXACT25_AXIS" or raw.get("source_gate") != "READY_COMMON":
            continue
        for source_id in raw.get("source_ids") or []:
            value = str(source_id).strip()
            if value and value not in out:
                out.append(value)
    return out[:12]


def a5_strict_priority_targets(
    ledger: Mapping[str, Any], strategy_ids: list[str], backlogs: Mapping[str, Any], limit: int
) -> list[str]:
    """Keep all A5 research active even while another candidate waits for fresh validation.

    This function only schedules source-ready research/design work. It does not launch a
    heavy replay, select, promote, paper trade, live trade, or submit an order.
    """
    c = _contract()
    order = _a5_order(c)
    v3._READY_BY_STRATEGY = {}

    for sid in strategy_ids:
        ready_by_axis: dict[str, dict[str, Any]] = {}
        rows = backlogs.get(sid) if isinstance(backlogs, Mapping) else []
        lineage = _lineage_pool(rows)
        if isinstance(rows, list):
            for raw in rows:
                if not isinstance(raw, Mapping):
                    continue
                if raw.get("origin") == "SEALED_EXACT25_AXIS" or raw.get("source_gate") != "READY_COMMON":
                    continue
                axis = str(raw.get("axis") or "").strip()
                if axis:
                    ready_by_axis[axis] = dict(raw)
        candidates = _contract_ready_rows(c, sid) + _supplemental_ready_rows(sid)
        for row in candidates:
            if lineage and not row.get("source_ids"):
                row["source_ids"] = lineage[:6]
                row["lineage_seed_policy"] = "EXACT_STRATEGY_READY_BACKLOG_ONLY"
            axis = str(row["axis"])
            old = ready_by_axis.get(axis)
            if old is None or float(row.get("score") or 0) > float(old.get("score") or 0):
                ready_by_axis[axis] = row
        ready = sorted(ready_by_axis.values(), key=lambda x: (-float(x.get("score") or 0), str(x.get("axis") or "")))
        v3._READY_BY_STRATEGY[sid] = ready[:12]

    n = max(0, int(limit))
    chosen = [sid for sid in order if sid in strategy_ids and v3._READY_BY_STRATEGY.get(sid)][:n]
    if len(chosen) >= n:
        return chosen

    generic = v2.priority_targets(ledger, strategy_ids, backlogs, len(strategy_ids))
    for sid in generic:
        if sid in chosen or not v3._READY_BY_STRATEGY.get(sid):
            continue
        chosen.append(sid)
        if len(chosen) >= n:
            break
    return chosen


def _source_lane_readiness(c: Mapping[str, Any]) -> dict[str, Any]:
    funding_ready = False
    funding_reason = "P3_CONTRACT_UNREADABLE"
    try:
        p3 = _read(P3_CONTRACT)
        funding = ((p3.get("native_sources") or {}).get("funding") or {})
        funding_ready = funding.get("status") == "HISTORICAL_W1_W2_BOUND" and bool(funding.get("endpoint"))
        funding_reason = "HISTORICAL_W1_W2_BOUND" if funding_ready else "FUNDING_HISTORY_NOT_BOUND"
    except Exception:
        pass
    return {
        "READY_COMMON": {"ready": True, "sources": ["ohlcv", "volume"]},
        "FUNDING_NATIVE": {"ready": funding_ready, "reason": funding_reason},
        "BASIS_OI_NATIVE": {"ready": False, "reason": "FROZEN_DURATION_GATE_REQUIRED"},
        "L2_FLOW_NATIVE": {"ready": False, "reason": "SEPARATE_VERIFIED_NATIVE_FLOW_BINDING_REQUIRED"},
    }


def _trend_rider_expansion_summary() -> dict[str, Any]:
    c = _trend_rider_expansion()
    ready = _supplemental_ready_rows("trend_rider")
    return {
        "state": c.get("state"),
        "baseline_identity": c.get("baseline_identity"),
        "evidence_count": len(c.get("external_evidence") or []),
        "total_axis_count": len(c.get("repair_axes") or []),
        "ready_common_axis_count": len(ready),
        "ready_common_axes": [x["axis"] for x in ready],
        "a1_a2_a3_gate_order_preserved": bool((c.get("acceptance_contract") or {}).get("a1_a2_a3_gate_order_preserved")),
    }


def run(output: Path, *, network: bool = True, ai: bool = True, ai_strategy_limit: int = 5) -> dict[str, Any]:
    c = _contract()
    old = v3.strict_priority_targets
    try:
        v3.strict_priority_targets = a5_strict_priority_targets
        result = dict(v5.run(output, network=network, ai=ai, ai_strategy_limit=ai_strategy_limit))
    finally:
        v3.strict_priority_targets = old

    targets = [str(x) for x in (result.get("ai_scout_priority_strategy_ids") or [])]
    seeded = 0
    supplemental_seeded = 0
    for sid in targets:
        for row in v3._READY_BY_STRATEGY.get(sid) or []:
            if row.get("lineage_seed_policy") == "EXACT_STRATEGY_READY_BACKLOG_ONLY" and row.get("source_ids"):
                seeded += 1
                if row.get("origin") == "TREND_RIDER_ONLINE_EXPANSION":
                    supplemental_seeded += 1
    result["schema_version"] = SCHEMA
    result["a5_no_idle"] = {
        "contract_state": c.get("state"),
        "priority_order": _a5_order(c),
        "targets_this_run": targets,
        "validation_wait_blocks_research": False,
        "fresh_wait_blocks_validation_only": True,
        "queue_generation_continues_during_fresh_wait": True,
        "independent_pre_replay_review_continues_during_fresh_wait": True,
        "one_heavy_replay_at_a_time": True,
        "sealed_exact25_axis_mutation_forbidden": True,
        "lineage_seed_policy": "EXACT_STRATEGY_READY_BACKLOG_ONLY",
        "lineage_seeded_contract_axis_count": seeded,
        "trend_rider_online_expansion_seeded_axis_count": supplemental_seeded,
        "trend_rider_online_expansion": _trend_rider_expansion_summary(),
        "source_lane_readiness": _source_lane_readiness(c),
        "trend_rider_known_hardening_failures": ((c.get("strategies") or {}).get("trend_rider") or {}).get("known_hardening_failures") or [],
        "pareto_metrics": ((c.get("optimization_objective") or {}).get("metrics") or []),
        "risk_scaling_dual_attribution": ((c.get("optimization_objective") or {}).get("risk_scaling_requires_dual_attribution") or {}),
    }
    result["policy"]["a5_no_idle_research"] = True
    result["policy"]["fresh_wait_blocks_validation_only"] = True
    result["policy"]["a5_priority_until_g4_survivors_or_axis_exhaustion"] = True
    result["policy"]["sealed_axis_replay_from_contract_forbidden"] = True
    result["policy"]["contract_axis_lineage_must_come_from_exact_strategy_ready_backlog"] = True
    result["policy"]["trend_rider_original_fresh_online_expansion"] = True
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = _contract()
    order = _a5_order(c)
    expansion = _trend_rider_expansion()
    supplemental = _supplemental_ready_rows("trend_rider")
    assert order == ["trend_rider", "break_and_continue", "supertrend_pullback", "keltner_trend", "trend_ma_macd"]
    assert c["global_invariants"]["fresh_wait_blocks_validation_only"] is True
    assert c["global_invariants"]["research_queue_must_continue_during_fresh_wait"] is True
    assert c["selection_authority"] is False and c["promotion_authority"] is False
    assert c["execution_authority"] == "NONE" and c["order_authority"] == "BLOCKED" and c["live_trade_authority"] == "BLOCKED"
    assert expansion["baseline_identity"] == "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3"
    assert expansion["acceptance_contract"]["same_original_fresh_baseline_required"] is True
    assert expansion["acceptance_contract"]["a1_a2_a3_gate_order_preserved"] is True
    assert len(expansion.get("external_evidence") or []) >= 4
    assert len(supplemental) >= 5
    assert all(x.get("external_evidence_ids") for x in supplemental)
    assert all(x.get("source_ids") == [] for x in supplemental)
    strategies = c.get("strategies") or {}
    for sid in order:
        block = strategies[sid]
        sealed = block["sealed_exact25_axis"]
        axes = [x["axis"] for x in block["repair_axes"]]
        assert sealed not in axes, (sid, sealed)
        assert len(_contract_ready_rows(c, sid)) >= 4, sid
    seeded_backlogs = {
        sid: [{
            "axis": "VOLATILITY_REGIME_OWNER_ONLY",
            "source_gate": "READY_COMMON",
            "origin": "CONTINUOUS_EVIDENCE_DISCOVERY",
            "source_ids": [f"EVIDENCE_{sid}"],
            "required_sources": ["ohlcv"],
            "score": 5.0,
        }]
        for sid in order
    }
    targets = a5_strict_priority_targets({"strategies": {}}, list(order), seeded_backlogs, 5)
    assert targets == order, targets
    trend_ready = v3._READY_BY_STRATEGY["trend_rider"]
    assert len(trend_ready) == 12
    supplemental_rows = [x for x in trend_ready if x.get("origin") == "TREND_RIDER_ONLINE_EXPANSION"]
    assert len(supplemental_rows) >= 5
    assert all(x.get("source_ids") == ["EVIDENCE_trend_rider"] for x in supplemental_rows)
    assert all(x.get("lineage_seed_policy") == "EXACT_STRATEGY_READY_BACKLOG_ONLY" for x in supplemental_rows)
    seeded_rows = [x for x in trend_ready if x.get("origin") == "A5_NO_IDLE_CONTRACT"]
    assert seeded_rows and all(x.get("source_ids") for x in seeded_rows), seeded_rows
    assert all(x.get("lineage_seed_policy") == "EXACT_STRATEGY_READY_BACKLOG_ONLY" for x in seeded_rows)
    print("PASS_A1_RESEARCH_FACTORY_V6_A5_NO_IDLE_SELF_TEST")
    print("PASS_TREND_RIDER_ORIGINAL_FRESH_ONLINE_EXPANSION_BINDING")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_research_factory_v6.json"))
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--ai-strategy-limit", type=int, default=5)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output, network=not args.no_network, ai=not args.no_ai, ai_strategy_limit=max(0, args.ai_strategy_limit))
    print(json.dumps({
        "state": r.get("state"),
        "targets": (r.get("a5_no_idle") or {}).get("targets_this_run"),
        "sources": r.get("external_source_count"),
        "new_discovered": r.get("new_discovered_source_count"),
        "reviewed_ready_common": r.get("reviewed_ready_common_count"),
        "trend_rider_online_expansion": (r.get("a5_no_idle") or {}).get("trend_rider_online_expansion"),
        "next": r.get("next_experiment_candidate"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
