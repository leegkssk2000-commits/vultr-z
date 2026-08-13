from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha
from backend.production.zel_production_pre_survivor_progress_v1 import FEEDBACK_SCHEMA, SCHEMA as PROGRESS_SCHEMA

SCHEMA = "zel.production_pre_survivor_feedback_bridge.v1"
POLICY_SCHEMA = "zel.production_pre_survivor_feedback_bridge_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_pre_survivor_feedback_bridge_v1.json")
REJECT_STATE = "REJECT_AI_ADMISSION_ECONOMIC_EDGE"


def _authority_guard(row: Mapping[str, Any], prefix: str) -> None:
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
        raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_NON_PAPER_FORBIDDEN")
    for key in ("feedback_path", "progress_path", "output_evidence_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"PRE_SURVIVOR_FEEDBACK_BRIDGE_PATH_MISSING:{key}")
    if policy.get("selection_rule") != "MOST_EVIDENCE_REJECTED_FAMILY_NO_OPTIMIZATION":
        raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_SELECTION_RULE_DRIFT")
    if policy.get("projection_role") != "CONTEXT_ONLY_NOT_GATE":
        raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_ROLE_DRIFT")
    if policy.get("numeric_threshold_proposals_allowed") is not False or policy.get("parameter_search_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_SEARCH_FORBIDDEN")
    _authority_guard(policy, "PRE_SURVIVOR_FEEDBACK_BRIDGE_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_MUTATION_FORBIDDEN")
    return dict(policy)


def _base(state: str, now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "state": state,
        "projection_role": "CONTEXT_ONLY_NOT_GATE",
        "numeric_threshold_proposals_allowed": False,
        "parameter_search_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "action": "hold",
        "updated_at_ms": now_ms,
    }


def project_feedback(
    policy: Mapping[str, Any],
    *,
    feedback: Mapping[str, Any] | None,
    progress: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(feedback, Mapping):
        out = _base("HOLD_PRE_SURVIVOR_FEEDBACK_BRIDGE_INPUT_MISSING", now)
        out["receipt_sha256"] = stable_sha(out)
        return out
    if feedback.get("schema_version") != FEEDBACK_SCHEMA:
        raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_FEEDBACK_SCHEMA_INVALID")
    _authority_guard(feedback, "PRE_SURVIVOR_FEEDBACK_BRIDGE_FEEDBACK")
    if isinstance(progress, Mapping):
        if progress.get("schema_version") != PROGRESS_SCHEMA:
            raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_PROGRESS_SCHEMA_INVALID")
        _authority_guard(progress, "PRE_SURVIVOR_FEEDBACK_BRIDGE_PROGRESS")

    rejected: list[dict[str, Any]] = []
    for raw in feedback.get("entries") or []:
        if not isinstance(raw, Mapping) or str(raw.get("admission_state") or "") != REJECT_STATE:
            continue
        metrics = raw.get("metrics")
        if not isinstance(metrics, Mapping):
            raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_METRICS_MISSING")
        rejected.append(dict(raw))
    if not rejected:
        out = _base("HOLD_PRE_SURVIVOR_FEEDBACK_BRIDGE_NO_REJECTED_FAMILY", now)
        out.update(
            {
                "source_feedback_receipt_sha256": str(feedback.get("receipt_sha256") or ""),
                "source_progress_receipt_sha256": str((progress or {}).get("receipt_sha256") or ""),
                "selection_rule": cfg["selection_rule"],
            }
        )
        out["receipt_sha256"] = stable_sha(out)
        return out

    selected = max(
        rejected,
        key=lambda row: (
            int((row.get("metrics") or {}).get("trade_count") or 0),
            str(row.get("family_id") or ""),
            str(row.get("contract_id") or ""),
        ),
    )
    metrics = selected["metrics"]
    required = (
        "trade_count",
        "win_rate_pct",
        "net_pnl_bps",
        "net_expectancy_bps",
        "profit_factor",
        "max_drawdown_pct",
    )
    if any(key not in metrics for key in required):
        raise RuntimeError("PRE_SURVIVOR_FEEDBACK_BRIDGE_REQUIRED_METRIC_MISSING")

    out = _base("PASS_PRE_SURVIVOR_REJECT_CONTEXT_PROJECTED", now)
    out.update(
        {
            "source_feedback_receipt_sha256": str(feedback.get("receipt_sha256") or ""),
            "source_progress_receipt_sha256": str((progress or {}).get("receipt_sha256") or ""),
            "selection_rule": cfg["selection_rule"],
            "family_id": str(selected.get("family_id") or ""),
            "contract_id": str(selected.get("contract_id") or ""),
            "template_id": str(selected.get("template_id") or ""),
            "progress_direction": str(selected.get("progress_direction") or ""),
            "delta_vs_previous": selected.get("delta_vs_previous"),
            "trade_count": int(metrics["trade_count"]),
            "win_rate_pct": float(metrics["win_rate_pct"]),
            "net_expectancy": float(metrics["net_expectancy_bps"]),
            "profit_factor": float(metrics["profit_factor"]),
            "net_pnl": float(metrics["net_pnl_bps"]),
            "max_dd_pct": float(metrics["max_drawdown_pct"]),
            "metric_units": {
                "win_rate_pct": "pct",
                "net_expectancy": "bps_per_trade",
                "net_pnl": "bps",
                "max_dd_pct": "pct",
                "profit_factor": "ratio",
                "trade_count": "trades",
            },
            "win_rate_role": "OBSERVATION_ONLY_NOT_GATE",
            "context_intent": "INFORM_NEXT_NEW_ECONOMIC_FAMILY_AFTER_TERMINAL_REJECT",
        }
    )
    out["receipt_sha256"] = stable_sha(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Project pre-survivor rejected economics into proposal-only AI context")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    result = project_feedback(
        cfg,
        feedback=read_json(Path(str(cfg["feedback_path"]))),
        progress=read_json(Path(str(cfg["progress_path"]))),
    )
    atomic_json_write(Path(str(cfg["output_evidence_path"])), result)
    print(
        json.dumps(
            {
                "state": result["state"],
                "family_id": result.get("family_id"),
                "trade_count": result.get("trade_count"),
                "win_rate_pct": result.get("win_rate_pct"),
                "net_pnl": result.get("net_pnl"),
                "net_expectancy": result.get("net_expectancy"),
                "profit_factor": result.get("profit_factor"),
                "max_dd_pct": result.get("max_dd_pct"),
                "receipt_sha256": result["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
