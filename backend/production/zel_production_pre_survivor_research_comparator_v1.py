from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production import zel_production_ai_admission_executor_v2 as executor_v2
from backend.production import zel_production_ai_admission_executor_v3 as executor_v3
from backend.production import zel_production_ai_admission_materializer_v1 as materializer_v1
from backend.production.zel_production_ai_admission_executor_v1 import _execution_cost_bps
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha
from backend.production.zel_production_pre_survivor_progress_v1 import _returns_for_contract, economic_metrics

SCHEMA = "zel.production_pre_survivor_research_comparator.v1"
POLICY_SCHEMA = "zel.production_pre_survivor_research_comparator_policy.v1"
CHALLENGER_EVIDENCE_SCHEMA = "zel.production_pre_survivor_challenger_evidence.v1"
DEFAULT_POLICY = Path("config/zel_production_pre_survivor_research_comparator_v1.json")
NEXT_HYPOTHESIS_PASS = "PASS_PRE_SURVIVOR_NEXT_HYPOTHESIS_SOURCE_READY"
ACTIVE_CONTRACT_PATH = "/home/z/z/ledger/production_ai_admission_contracts_v1.json"
ACTIVE_HISTORY_PATH = "/home/z/z/ledger/production_ai_admission_observations_v1.ndjson"
ACTIVE_ECONOMIC_PATH = "/home/z/z/ledger/production_ai_admission_economic_v1.json"
METRIC_KEYS = (
    "trade_count",
    "win_rate_pct",
    "net_expectancy",
    "profit_factor",
    "net_pnl",
    "max_dd_pct",
)


def _authority_guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")
    if row.get("exchange_order_submitted") not in (None, False):
        raise RuntimeError(f"{prefix}_EXCHANGE_ORDER_FORBIDDEN")


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


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COMPARATOR_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COMPARATOR_NON_PAPER_FORBIDDEN")
    if policy.get("comparison_role") != "RESEARCH_ONLY_NOT_ROUTE":
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COMPARATOR_ROLE_DRIFT")
    required_paths = (
        "reference_feedback_path",
        "next_hypothesis_path",
        "materializer_policy_path",
        "source_registry_path",
        "template_registry_path",
        "executor_policy_path",
        "challenger_contract_state_path",
        "challenger_history_path",
        "challenger_economic_path",
        "challenger_evidence_path",
        "output_path",
    )
    for key in required_paths:
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"PRE_SURVIVOR_RESEARCH_COMPARATOR_PATH_MISSING:{key}")
    isolated = {
        str(policy["challenger_contract_state_path"]),
        str(policy["challenger_history_path"]),
        str(policy["challenger_economic_path"]),
        str(policy["challenger_evidence_path"]),
        str(policy["output_path"]),
    }
    if len(isolated) != 5:
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COMPARATOR_ISOLATED_PATH_COLLISION")
    if isolated & {ACTIVE_CONTRACT_PATH, ACTIVE_HISTORY_PATH, ACTIVE_ECONOMIC_PATH}:
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COMPARATOR_ACTIVE_PATH_FORBIDDEN")
    _authority_guard(policy, "PRE_SURVIVOR_RESEARCH_COMPARATOR_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COMPARATOR_MUTATION_FORBIDDEN")
    return dict(policy)


def _finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"PRE_SURVIVOR_RESEARCH_COMPARATOR_NUMERIC_INVALID:{label}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"PRE_SURVIVOR_RESEARCH_COMPARATOR_NUMERIC_NONFINITE:{label}")
    return out


def _metrics(row: Mapping[str, Any], prefix: str) -> dict[str, float | int]:
    missing = [key for key in METRIC_KEYS if key not in row]
    if missing:
        raise RuntimeError(f"PRE_SURVIVOR_RESEARCH_COMPARATOR_METRICS_MISSING:{prefix}:" + ",".join(missing))
    try:
        trade_count = int(row["trade_count"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"PRE_SURVIVOR_RESEARCH_COMPARATOR_TRADE_COUNT_INVALID:{prefix}") from exc
    if trade_count < 0:
        raise RuntimeError(f"PRE_SURVIVOR_RESEARCH_COMPARATOR_TRADE_COUNT_INVALID:{prefix}")
    return {
        "trade_count": trade_count,
        "win_rate_pct": _finite(row["win_rate_pct"], f"{prefix}.win_rate_pct"),
        "net_expectancy": _finite(row["net_expectancy"], f"{prefix}.net_expectancy"),
        "profit_factor": _finite(row["profit_factor"], f"{prefix}.profit_factor"),
        "net_pnl": _finite(row["net_pnl"], f"{prefix}.net_pnl"),
        "max_dd_pct": _finite(row["max_dd_pct"], f"{prefix}.max_dd_pct"),
    }


def _base(state: str, now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "state": state,
        "comparison_role": "RESEARCH_ONLY_NOT_ROUTE",
        "research_preference": "NONE",
        "updated_at_ms": now_ms,
        **_safety(),
    }


def _compare_one(reference: Mapping[str, Any], challenger: Mapping[str, Any]) -> dict[str, Any]:
    _authority_guard(reference, "PRE_SURVIVOR_RESEARCH_REFERENCE")
    _authority_guard(challenger, "PRE_SURVIVOR_RESEARCH_CHALLENGER")
    ref = _metrics(reference, "reference")
    ch = _metrics(challenger, "challenger")
    deltas = {
        "trade_count": int(ch["trade_count"]) - int(ref["trade_count"]),
        "win_rate_pct": float(ch["win_rate_pct"]) - float(ref["win_rate_pct"]),
        "net_expectancy": float(ch["net_expectancy"]) - float(ref["net_expectancy"]),
        "profit_factor": float(ch["profit_factor"]) - float(ref["profit_factor"]),
        "net_pnl": float(ch["net_pnl"]) - float(ref["net_pnl"]),
        "max_dd_pct": float(ch["max_dd_pct"]) - float(ref["max_dd_pct"]),
    }
    guards = {
        "evidence_not_less": int(ch["trade_count"]) >= int(ref["trade_count"]),
        "expectancy_improved": float(ch["net_expectancy"]) > float(ref["net_expectancy"]),
        "net_pnl_improved": float(ch["net_pnl"]) > float(ref["net_pnl"]),
        "profit_factor_not_worse": float(ch["profit_factor"]) >= float(ref["profit_factor"]),
        "drawdown_not_worse": float(ch["max_dd_pct"]) <= float(ref["max_dd_pct"]),
        "win_rate_not_worse": float(ch["win_rate_pct"]) >= float(ref["win_rate_pct"]),
    }
    return {
        "reference_family_id": str(reference.get("family_id") or ""),
        "challenger_family_id": str(challenger.get("family_id") or ""),
        "challenger_contract_id": str(challenger.get("contract_id") or ""),
        "reference_metrics": ref,
        "challenger_metrics": ch,
        "delta_challenger_minus_reference": deltas,
        "research_guards": guards,
        "research_preference": "CHALLENGER_RESEARCH_PREFERRED" if all(guards.values()) else "REFERENCE_RESEARCH_PREFERRED",
        "win_rate_role": "RESEARCH_GUARD_NOT_PROMOTION_GATE",
        "preference_is_authority": False,
    }


def _challenger_rows(challenger: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = challenger.get("challengers")
    if isinstance(rows, list):
        out = [dict(x) for x in rows if isinstance(x, Mapping)]
        if out:
            return out
    if all(key in challenger for key in METRIC_KEYS):
        return [dict(challenger)]
    return []


def compare_tick(
    policy: Mapping[str, Any],
    *,
    reference: Mapping[str, Any] | None,
    challenger: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(reference, Mapping):
        out = _base("HOLD_PRE_SURVIVOR_RESEARCH_REFERENCE_MISSING", now)
        out["receipt_sha256"] = stable_sha(out)
        return out
    _authority_guard(reference, "PRE_SURVIVOR_RESEARCH_REFERENCE")
    try:
        _metrics(reference, "reference")
    except RuntimeError as exc:
        state = "HOLD_PRE_SURVIVOR_RESEARCH_REFERENCE_METRICS_MISSING" if "METRICS_MISSING:reference" in str(exc) else "HOLD_PRE_SURVIVOR_RESEARCH_REFERENCE_METRICS_INVALID"
        out = _base(state, now)
        out["reference_family_id"] = str(reference.get("family_id") or "")
        out["reference_state"] = str(reference.get("state") or "")
        out["reference_metric_error"] = str(exc)[:500]
        out["receipt_sha256"] = stable_sha(out)
        return out
    if not isinstance(challenger, Mapping):
        out = _base("HOLD_PRE_SURVIVOR_RESEARCH_CHALLENGER_MISSING", now)
        out["reference_family_id"] = str(reference.get("family_id") or "")
        out["receipt_sha256"] = stable_sha(out)
        return out
    _authority_guard(challenger, "PRE_SURVIVOR_RESEARCH_CHALLENGER_EVIDENCE")
    rows = _challenger_rows(challenger)
    if not rows:
        out = _base("HOLD_PRE_SURVIVOR_RESEARCH_CHALLENGER_MISSING", now)
        out["reference_family_id"] = str(reference.get("family_id") or "")
        out["challenger_evidence_state"] = str(challenger.get("state") or "")
        out["receipt_sha256"] = stable_sha(out)
        return out
    comparisons = [_compare_one(reference, row) for row in rows]
    preferred = [row["challenger_family_id"] for row in comparisons if row["research_preference"] == "CHALLENGER_RESEARCH_PREFERRED"]
    out = _base("PASS_PRE_SURVIVOR_RESEARCH_COMPARISON_CAPTURED", now)
    out.update(
        {
            "reference_family_id": str(reference.get("family_id") or ""),
            "comparison_count": len(comparisons),
            "comparisons": comparisons,
            "preferred_challenger_family_ids": preferred,
            "research_preference": "CHALLENGER_RESEARCH_PREFERRED" if preferred else "REFERENCE_RESEARCH_PREFERRED",
            "win_rate_role": "RESEARCH_GUARD_NOT_PROMOTION_GATE",
            "preference_is_authority": False,
            "next": "KEEP_QUALIFYING_CHALLENGERS_IN_ISOLATED_RESEARCH_LANE" if preferred else "ACCUMULATE_MORE_PROSPECTIVE_EVIDENCE",
        }
    )
    if len(comparisons) == 1:
        out.update({k: v for k, v in comparisons[0].items() if k not in {"research_preference"}})
    out["receipt_sha256"] = stable_sha(out)
    return out


def _proposal_state(next_hypothesis: Mapping[str, Any]) -> dict[str, Any] | None:
    if next_hypothesis.get("state") != NEXT_HYPOTHESIS_PASS:
        return None
    _authority_guard(next_hypothesis, "PRE_SURVIVOR_RESEARCH_NEXT_HYPOTHESIS")
    proposals = next_hypothesis.get("proposals")
    if not isinstance(proposals, list) or not proposals:
        return None
    frozen: list[dict[str, Any]] = []
    for raw in proposals:
        if not isinstance(raw, Mapping) or raw.get("source_ready") is not True:
            continue
        row = dict(raw)
        if not str(row.get("proposal_id") or ""):
            row["proposal_id"] = stable_sha(
                {
                    "lane": "PRE_SURVIVOR_CHALLENGER",
                    "family_id": row.get("family_id"),
                    "required_sources": row.get("required_sources"),
                    "economic_mechanism": row.get("economic_mechanism"),
                }
            )[:32]
        frozen.append(row)
    if not frozen:
        return None
    out = {
        "schema_version": materializer_v1.PROPOSAL_SCHEMA,
        "state": "PASS_AI_PROPOSAL_CANDIDATE",
        "proposals": frozen,
        **_safety(),
    }
    out["receipt_sha256"] = stable_sha(out)
    return out


def produce_challenger_evidence(
    policy: Mapping[str, Any],
    *,
    next_hypothesis: Mapping[str, Any] | None,
    materializer_policy: Mapping[str, Any],
    source_registry: Mapping[str, Any] | None,
    template_registry: Mapping[str, Any] | None,
    executor_policy: Mapping[str, Any],
    l2_snapshot: Mapping[str, Any] | None,
    carry_snapshot: Mapping[str, Any] | None,
    cost_authority: Mapping[str, Any] | None,
    history: Sequence[Mapping[str, Any]],
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    base = {
        "schema_version": CHALLENGER_EVIDENCE_SCHEMA,
        "state": "HOLD_PRE_SURVIVOR_CHALLENGER_NO_SOURCE_READY_HYPOTHESIS",
        "challengers": [],
        "history_appended": 0,
        "updated_at_ms": now,
        **_safety(),
    }
    if not isinstance(next_hypothesis, Mapping):
        base["receipt_sha256"] = stable_sha(base)
        return base, {}, [], {}
    proposal = _proposal_state(next_hypothesis)
    if proposal is None:
        base["source_next_hypothesis_state"] = str(next_hypothesis.get("state") or "")
        base["receipt_sha256"] = stable_sha(base)
        return base, {}, [], {}

    mat_cfg = dict(materializer_policy)
    mat_cfg["proposal_state_path"] = str(cfg["next_hypothesis_path"])
    mat_cfg["source_registry_path"] = str(cfg["source_registry_path"])
    mat_cfg["template_registry_path"] = str(cfg["template_registry_path"])
    mat_cfg["output_path"] = str(cfg["challenger_contract_state_path"])
    contracts = materializer_v1.materialize_tick(
        mat_cfg,
        proposal=proposal,
        source_registry=source_registry,
        template_registry=template_registry,
        now_ms=now,
    )
    if not contracts.get("contracts"):
        base.update(
            {
                "state": "HOLD_PRE_SURVIVOR_CHALLENGER_NO_FROZEN_TEMPLATE",
                "materializer_state": contracts.get("state"),
                "materializer_blockers": contracts.get("blockers") or [],
                "source_next_hypothesis_receipt_sha256": str(next_hypothesis.get("receipt_sha256") or ""),
            }
        )
        base["receipt_sha256"] = stable_sha(base)
        return base, contracts, [], {}

    exec_cfg = dict(executor_policy)
    exec_cfg["contract_state_path"] = str(cfg["challenger_contract_state_path"])
    exec_cfg["observation_history_path"] = str(cfg["challenger_history_path"])
    exec_cfg["output_path"] = str(cfg["challenger_economic_path"])
    result, observations = executor_v3.executor_tick(
        exec_cfg,
        contract_state=contracts,
        template_registry=template_registry,
        l2_snapshot=l2_snapshot,
        carry_snapshot=carry_snapshot,
        cost_authority=cost_authority,
        candles_by_symbol=candles_by_symbol,
        history=history,
    )
    merged_history = list(history) + list(observations)
    if not isinstance(cost_authority, Mapping):
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COST_AUTHORITY_MISSING")
    cost_bps = _execution_cost_bps(cost_authority)
    result_by_contract = {
        str(row.get("contract_id") or ""): dict(row)
        for row in result.get("results") or []
        if isinstance(row, Mapping) and str(row.get("contract_id") or "")
    }
    challengers: list[dict[str, Any]] = []
    for contract in contracts.get("contracts") or []:
        if not isinstance(contract, Mapping):
            continue
        cid = str(contract.get("contract_id") or "")
        metrics = economic_metrics(_returns_for_contract(merged_history, cid, cost_bps))
        economic = result_by_contract.get(cid, {})
        row = {
            "family_id": str(contract.get("family_id") or ""),
            "contract_id": cid,
            "template_id": str(contract.get("template_id") or ""),
            "admission_state": str(economic.get("state") or result.get("state") or ""),
            "trade_count": int(metrics["trade_count"]),
            "win_rate_pct": float(metrics["win_rate_pct"]),
            "net_expectancy": float(metrics["net_expectancy_bps"]),
            "profit_factor": float(metrics["profit_factor"]),
            "net_pnl": float(metrics["net_pnl_bps"]),
            "max_dd_pct": float(metrics["max_drawdown_pct"]),
            "metric_units": {
                "trade_count": "trades",
                "win_rate_pct": "pct",
                "net_expectancy": "bps_per_trade",
                "profit_factor": "ratio",
                "net_pnl": "bps",
                "max_dd_pct": "pct",
            },
            **_safety(),
        }
        row["receipt_sha256"] = stable_sha(row)
        challengers.append(row)
    base.update(
        {
            "state": "PASS_PRE_SURVIVOR_CHALLENGER_EVIDENCE_CAPTURED" if challengers else "HOLD_PRE_SURVIVOR_CHALLENGER_HISTORY_ACCUMULATING",
            "challengers": challengers,
            "challenger_count": len(challengers),
            "observation_count_new": len(observations),
            "materializer_state": contracts.get("state"),
            "executor_state": result.get("state"),
            "source_next_hypothesis_receipt_sha256": str(next_hypothesis.get("receipt_sha256") or ""),
        }
    )
    base["receipt_sha256"] = stable_sha(base)
    return base, contracts, list(observations), result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run PAPER-only pre-survivor challenger research and compare economics")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    materializer_policy = json.loads(Path(str(cfg["materializer_policy_path"])).read_text(encoding="utf-8"))
    executor_policy = json.loads(Path(str(cfg["executor_policy_path"])).read_text(encoding="utf-8"))
    history_path = Path(str(cfg["challenger_history_path"]))
    history = executor_v2.read_history(history_path)
    evidence, contracts, observations, economic = produce_challenger_evidence(
        cfg,
        next_hypothesis=read_json(Path(str(cfg["next_hypothesis_path"]))),
        materializer_policy=materializer_policy,
        source_registry=read_json(Path(str(cfg["source_registry_path"]))),
        template_registry=read_json(Path(str(cfg["template_registry_path"]))),
        executor_policy=executor_policy,
        l2_snapshot=read_json(Path(str(executor_policy["l2_snapshot_path"]))),
        carry_snapshot=read_json(Path(str(executor_policy["carry_snapshot_path"]))),
        cost_authority=read_json(Path(str(executor_policy["execution_cost_authority_path"]))),
        history=history,
    )
    added = executor_v2.append_observations(history_path, observations)
    evidence["history_appended"] = added
    evidence["receipt_sha256"] = stable_sha({k: v for k, v in evidence.items() if k != "receipt_sha256"})
    if contracts:
        atomic_json_write(Path(str(cfg["challenger_contract_state_path"])), contracts)
    if economic:
        atomic_json_write(Path(str(cfg["challenger_economic_path"])), economic)
    atomic_json_write(Path(str(cfg["challenger_evidence_path"])), evidence)
    comparison = compare_tick(
        cfg,
        reference=read_json(Path(str(cfg["reference_feedback_path"]))),
        challenger=evidence,
    )
    atomic_json_write(Path(str(cfg["output_path"])), comparison)
    print(
        json.dumps(
            {
                "state": comparison["state"],
                "research_preference": comparison.get("research_preference"),
                "comparison_count": int(comparison.get("comparison_count") or 0),
                "preferred_challenger_family_ids": comparison.get("preferred_challenger_family_ids") or [],
                "challenger_evidence_state": evidence.get("state"),
                "challenger_count": int(evidence.get("challenger_count") or 0),
                "history_appended": added,
                "receipt_sha256": comparison["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
