from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha
from backend.production.zel_production_pre_survivor_research_comparator_v1 import _compare_one

POLICY_SCHEMA = "zel.production_pre_survivor_research_controller_policy.v1"
INCUMBENT_SCHEMA = "zel.production_pre_survivor_research_incumbent.v1"
FEEDBACK_SCHEMA = "zel.production_pre_survivor_feedback_bridge.v1"
ACCUMULATING_STATE = "PASS_PRE_SURVIVOR_ACCUMULATING_CONTEXT_PROJECTED"
DEFAULT_POLICY = Path("config/zel_production_pre_survivor_research_controller_v1.json")
METRICS = ("trade_count", "win_rate_pct", "net_expectancy", "profit_factor", "net_pnl", "max_dd_pct")


def _safety() -> dict[str, Any]:
    return {
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "action": "hold",
    }


def _guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")
    if row.get("exchange_order_submitted") not in (None, False):
        raise RuntimeError(f"{prefix}_EXCHANGE_ORDER_FORBIDDEN")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_CONTROLLER_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_CONTROLLER_NON_PAPER_FORBIDDEN")
    for key in ("active_feedback_path", "research_feedback_path", "comparison_path", "challenger_evidence_path", "incumbent_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"PRE_SURVIVOR_RESEARCH_CONTROLLER_PATH_MISSING:{key}")
    if len({str(policy[k]) for k in ("research_feedback_path", "comparison_path", "challenger_evidence_path", "incumbent_path")}) != 4:
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_CONTROLLER_PATH_COLLISION")
    _guard(policy, "PRE_SURVIVOR_RESEARCH_CONTROLLER_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_CONTROLLER_MUTATION_FORBIDDEN")
    return dict(policy)


def _has_metrics(row: Mapping[str, Any]) -> bool:
    return all(key in row for key in METRICS)


def _rank(row: Mapping[str, Any]) -> tuple[float, float, float, float, float, int]:
    return (
        float(row.get("net_expectancy") or 0.0),
        float(row.get("net_pnl") or 0.0),
        float(row.get("profit_factor") or 0.0),
        -float(row.get("max_dd_pct") or 0.0),
        float(row.get("win_rate_pct") or 0.0),
        int(row.get("trade_count") or 0),
    )


def _feedback_from_incumbent(incumbent: Mapping[str, Any], now_ms: int) -> dict[str, Any]:
    _guard(incumbent, "PRE_SURVIVOR_RESEARCH_CONTROLLER_INCUMBENT")
    if not _has_metrics(incumbent):
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_CONTROLLER_INCUMBENT_METRICS_MISSING")
    out = {
        "schema_version": FEEDBACK_SCHEMA,
        "state": ACCUMULATING_STATE,
        "context_kind": "PROVISIONAL_ACCUMULATING",
        "non_terminal_context": True,
        "source_admission_state": "HOLD_PRE_SURVIVOR_RESEARCH_INCUMBENT",
        "family_id": str(incumbent.get("family_id") or ""),
        "contract_id": str(incumbent.get("contract_id") or ""),
        "template_id": str(incumbent.get("template_id") or ""),
        "progress_direction": "RESEARCH_INCUMBENT",
        "context_intent": "INFORM_NEXT_NEW_ECONOMIC_FAMILY_FROM_RESEARCH_INCUMBENT",
        "trade_count": int(incumbent["trade_count"]),
        "win_rate_pct": float(incumbent["win_rate_pct"]),
        "net_expectancy": float(incumbent["net_expectancy"]),
        "profit_factor": float(incumbent["profit_factor"]),
        "net_pnl": float(incumbent["net_pnl"]),
        "max_dd_pct": float(incumbent["max_dd_pct"]),
        "metric_units": {
            "trade_count": "trades",
            "win_rate_pct": "pct",
            "net_expectancy": "bps_per_trade",
            "profit_factor": "ratio",
            "net_pnl": "bps",
            "max_dd_pct": "pct"
        },
        "delta_vs_previous": None,
        "win_rate_role": "RESEARCH_GUARD_NOT_PROMOTION_GATE",
        "research_reference_source": "RESEARCH_INCUMBENT",
        "updated_at_ms": now_ms,
        **_safety(),
    }
    out["receipt_sha256"] = stable_sha(out)
    return out


def prepare_reference(policy: Mapping[str, Any], *, active: Mapping[str, Any] | None, incumbent: Mapping[str, Any] | None, now_ms: int | None = None) -> dict[str, Any]:
    validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(active, Mapping):
        if isinstance(incumbent, Mapping) and incumbent.get("schema_version") == INCUMBENT_SCHEMA:
            return _feedback_from_incumbent(incumbent, now)
        out = {"schema_version": FEEDBACK_SCHEMA, "state": "HOLD_PRE_SURVIVOR_RESEARCH_REFERENCE_MISSING", "updated_at_ms": now, **_safety()}
        out["receipt_sha256"] = stable_sha(out)
        return out
    _guard(active, "PRE_SURVIVOR_RESEARCH_CONTROLLER_ACTIVE")
    use_incumbent = isinstance(incumbent, Mapping) and incumbent.get("schema_version") == INCUMBENT_SCHEMA and _has_metrics(incumbent)
    if use_incumbent:
        _guard(incumbent, "PRE_SURVIVOR_RESEARCH_CONTROLLER_INCUMBENT")
        if _has_metrics(active):
            try:
                active_better = _compare_one(incumbent, active)["research_preference"] == "CHALLENGER_RESEARCH_PREFERRED"
            except RuntimeError:
                active_better = False
            if active_better:
                use_incumbent = False
    if use_incumbent:
        return _feedback_from_incumbent(incumbent, now)
    out = dict(active)
    out["research_reference_source"] = "ACTIVE_PRE_SURVIVOR"
    out["updated_at_ms"] = now
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out


def update_incumbent(policy: Mapping[str, Any], *, comparison: Mapping[str, Any] | None, challenger_evidence: Mapping[str, Any] | None, previous: Mapping[str, Any] | None, now_ms: int | None = None) -> tuple[Mapping[str, Any] | None, bool]:
    validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(comparison, Mapping) or not isinstance(challenger_evidence, Mapping):
        return previous, False
    _guard(comparison, "PRE_SURVIVOR_RESEARCH_CONTROLLER_COMPARISON")
    _guard(challenger_evidence, "PRE_SURVIVOR_RESEARCH_CONTROLLER_EVIDENCE")
    preferred = set(map(str, comparison.get("preferred_challenger_family_ids") or []))
    rows = [dict(x) for x in challenger_evidence.get("challengers") or [] if isinstance(x, Mapping) and str(x.get("family_id") or "") in preferred and _has_metrics(x)]
    if not rows:
        return previous, False
    for row in rows:
        _guard(row, "PRE_SURVIVOR_RESEARCH_CONTROLLER_CHALLENGER")
    winner = max(rows, key=_rank)
    if isinstance(previous, Mapping) and previous.get("schema_version") == INCUMBENT_SCHEMA:
        _guard(previous, "PRE_SURVIVOR_RESEARCH_CONTROLLER_PREVIOUS_INCUMBENT")
        try:
            if _compare_one(previous, winner)["research_preference"] != "CHALLENGER_RESEARCH_PREFERRED":
                return previous, False
        except RuntimeError:
            return previous, False
    generation = int(previous.get("generation") or 0) + 1 if isinstance(previous, Mapping) else 1
    out = {
        "schema_version": INCUMBENT_SCHEMA,
        "state": "PASS_PRE_SURVIVOR_RESEARCH_INCUMBENT",
        "family_id": str(winner.get("family_id") or ""),
        "contract_id": str(winner.get("contract_id") or ""),
        "template_id": str(winner.get("template_id") or ""),
        "trade_count": int(winner["trade_count"]),
        "win_rate_pct": float(winner["win_rate_pct"]),
        "net_expectancy": float(winner["net_expectancy"]),
        "profit_factor": float(winner["profit_factor"]),
        "net_pnl": float(winner["net_pnl"]),
        "max_dd_pct": float(winner["max_dd_pct"]),
        "metric_units": winner.get("metric_units"),
        "generation": generation,
        "research_incumbent_only": True,
        "production_promotion_applied": False,
        "source_comparison_receipt_sha256": str(comparison.get("receipt_sha256") or ""),
        "updated_at_ms": now,
        **_safety(),
    }
    out["receipt_sha256"] = stable_sha(out)
    return out, True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Maintain non-authoritative pre-survivor research reference/incumbent")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--phase", choices=("prepare", "update"), required=True)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    if ns.phase == "prepare":
        row = prepare_reference(
            cfg,
            active=read_json(Path(str(cfg["active_feedback_path"]))),
            incumbent=read_json(Path(str(cfg["incumbent_path"]))),
        )
        atomic_json_write(Path(str(cfg["research_feedback_path"])), row)
        print(json.dumps({"phase": "prepare", "state": row.get("state"), "family_id": row.get("family_id"), "research_reference_source": row.get("research_reference_source"), "receipt_sha256": row.get("receipt_sha256")}, sort_keys=True))
        return 0
    previous = read_json(Path(str(cfg["incumbent_path"])))
    row, changed = update_incumbent(
        cfg,
        comparison=read_json(Path(str(cfg["comparison_path"]))),
        challenger_evidence=read_json(Path(str(cfg["challenger_evidence_path"]))),
        previous=previous,
    )
    if changed and isinstance(row, Mapping):
        atomic_json_write(Path(str(cfg["incumbent_path"])), row)
    print(json.dumps({"phase": "update", "changed": changed, "family_id": row.get("family_id") if isinstance(row, Mapping) else None, "generation": int(row.get("generation") or 0) if isinstance(row, Mapping) else 0, "receipt_sha256": row.get("receipt_sha256") if isinstance(row, Mapping) else None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
