from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_pre_survivor_research_comparator.v1"
POLICY_SCHEMA = "zel.production_pre_survivor_research_comparator_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_pre_survivor_research_comparator_v1.json")
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


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COMPARATOR_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COMPARATOR_NON_PAPER_FORBIDDEN")
    if policy.get("comparison_role") != "RESEARCH_ONLY_NOT_ROUTE":
        raise RuntimeError("PRE_SURVIVOR_RESEARCH_COMPARATOR_ROLE_DRIFT")
    for key in ("reference_feedback_path", "challenger_evidence_path", "output_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"PRE_SURVIVOR_RESEARCH_COMPARATOR_PATH_MISSING:{key}")
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
        "action": "hold",
        "research_preference": "NONE",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "updated_at_ms": now_ms,
    }


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
    if not isinstance(challenger, Mapping):
        out = _base("HOLD_PRE_SURVIVOR_RESEARCH_CHALLENGER_MISSING", now)
        out["reference_family_id"] = str(reference.get("family_id") or "")
        out["receipt_sha256"] = stable_sha(out)
        return out
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
    challenger_preferred = all(guards.values())
    out = _base("PASS_PRE_SURVIVOR_RESEARCH_COMPARISON_CAPTURED", now)
    out.update(
        {
            "reference_family_id": str(reference.get("family_id") or ""),
            "challenger_family_id": str(challenger.get("family_id") or ""),
            "reference_metrics": ref,
            "challenger_metrics": ch,
            "delta_challenger_minus_reference": deltas,
            "research_guards": guards,
            "research_preference": "CHALLENGER_RESEARCH_PREFERRED" if challenger_preferred else "REFERENCE_RESEARCH_PREFERRED",
            "win_rate_role": "RESEARCH_GUARD_NOT_PROMOTION_GATE",
            "preference_is_authority": False,
            "next": "ACCUMULATE_MORE_PROSPECTIVE_EVIDENCE" if not challenger_preferred else "KEEP_CHALLENGER_IN_ISOLATED_RESEARCH_LANE",
        }
    )
    out["receipt_sha256"] = stable_sha(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare PAPER-only pre-survivor research economics")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    result = compare_tick(
        cfg,
        reference=read_json(Path(str(cfg["reference_feedback_path"]))),
        challenger=read_json(Path(str(cfg["challenger_evidence_path"]))),
    )
    atomic_json_write(Path(str(cfg["output_path"])), result)
    print(json.dumps({
        "state": result["state"],
        "research_preference": result.get("research_preference"),
        "reference_family_id": result.get("reference_family_id"),
        "challenger_family_id": result.get("challenger_family_id"),
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
