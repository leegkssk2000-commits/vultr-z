from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import (
    REGISTRY_SCHEMA,
    _registry,
    atomic_json_write,
    executable_authority,
    read_json,
    stable_sha,
)

SCHEMA = "zel.production_performance_bootstrap.v1"
POLICY_SCHEMA = "zel.production_performance_bootstrap_policy.v1"
RECOVERY_SCHEMA = "zel.strategy25.economic_recovery.v1"
ADMISSION_SCHEMA = "zel.production_bootstrap_admission_evidence.v1"
DEFAULT_POLICY = Path("config/zel_production_performance_bootstrap_v1.json")


def _float(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"BOOTSTRAP_NUMERIC_INVALID:{name}") from exc
    if out != out or out in (float("inf"), float("-inf")):
        raise RuntimeError(f"BOOTSTRAP_NUMERIC_NONFINITE:{name}")
    return out


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("BOOTSTRAP_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("BOOTSTRAP_NON_PAPER_FORBIDDEN")
    if int(policy.get("candidate_budget") or 0) != 1:
        raise RuntimeError("BOOTSTRAP_CANDIDATE_BUDGET_MUST_BE_1")
    for key in ("queue_path", "admission_evidence_path", "bootstrap_state_path", "improvement_registry_path", "authority_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"BOOTSTRAP_PATH_MISSING:{key}")
    if policy.get("order_authority") != "BLOCKED" or policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("BOOTSTRAP_LIVE_AUTHORITY_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("BOOTSTRAP_MUTATION_FORBIDDEN")
    gate = policy.get("seed_survivor_gate")
    if not isinstance(gate, Mapping):
        raise RuntimeError("BOOTSTRAP_SEED_GATE_MISSING")
    if list(gate.get("required_windows") or []) != ["W1", "W2", "W3"]:
        raise RuntimeError("BOOTSTRAP_WINDOWS_INVALID")
    return dict(policy)


def _paths(policy: Mapping[str, Any]) -> dict[str, Path]:
    return {
        "queue": Path(str(policy["queue_path"])),
        "evidence": Path(str(policy["admission_evidence_path"])),
        "state": Path(str(policy["bootstrap_state_path"])),
        "registry": Path(str(policy["improvement_registry_path"])),
        "authority": Path(str(policy["authority_path"])),
    }


def _hold(state: str, reason: str, *, candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "reason": reason,
        "candidate": dict(candidate or {}),
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def _validate_recovery(queue: Mapping[str, Any]) -> list[dict[str, Any]]:
    if queue.get("schema_version") != RECOVERY_SCHEMA:
        raise RuntimeError("BOOTSTRAP_QUEUE_SCHEMA_INVALID")
    if int(queue.get("economic_survivor_count") or 0) != 0:
        raise RuntimeError("BOOTSTRAP_QUEUE_EXPECTED_ZERO_SURVIVOR")
    if queue.get("selection_authority") is not False or queue.get("promotion_authority") is not False:
        raise RuntimeError("BOOTSTRAP_QUEUE_AUTHORITY_INVALID")
    if queue.get("execution_authority") != "NONE" or queue.get("order_authority") != "BLOCKED":
        raise RuntimeError("BOOTSTRAP_QUEUE_EXECUTION_INVALID")
    rows = queue.get("admission_queue") or []
    if not isinstance(rows, list) or len(rows) > 1:
        raise RuntimeError("BOOTSTRAP_QUEUE_CARDINALITY_INVALID")
    return [dict(v) for v in rows]


def _seed_gate(evidence: Mapping[str, Any], policy: Mapping[str, Any], strategy_id: str) -> tuple[dict[str, float], str]:
    if evidence.get("schema_version") != ADMISSION_SCHEMA:
        raise RuntimeError("BOOTSTRAP_EVIDENCE_SCHEMA_INVALID")
    if evidence.get("state") != "PASS_BOOTSTRAP_ADMISSION_EVIDENCE":
        raise RuntimeError("BOOTSTRAP_EVIDENCE_NOT_PASS")
    if str(evidence.get("strategy_id") or "") != strategy_id:
        raise RuntimeError("BOOTSTRAP_EVIDENCE_STRATEGY_MISMATCH")
    if evidence.get("sample_gate_pass") is not True:
        raise RuntimeError("BOOTSTRAP_SAMPLE_GATE_NOT_PASS")
    integrity = evidence.get("integrity")
    if not isinstance(integrity, Mapping):
        raise RuntimeError("BOOTSTRAP_INTEGRITY_MISSING")
    for key in ("error_count", "duplicate_count", "censored_count"):
        if int(integrity.get(key) or 0) != 0:
            raise RuntimeError(f"BOOTSTRAP_INTEGRITY_FAIL:{key}")
    windows = evidence.get("windows")
    if not isinstance(windows, Mapping) or set(windows) != {"W1", "W2", "W3"}:
        raise RuntimeError("BOOTSTRAP_WINDOW_SET_INVALID")
    for name in ("W1", "W2", "W3"):
        row = windows[name]
        if not isinstance(row, Mapping):
            raise RuntimeError(f"BOOTSTRAP_WINDOW_INVALID:{name}")
        if _float(row.get("net_pnl"), f"{name}.net_pnl") <= 0:
            raise RuntimeError(f"BOOTSTRAP_WINDOW_NET_FAIL:{name}")
        if _float(row.get("profit_factor"), f"{name}.profit_factor") < 1.0:
            raise RuntimeError(f"BOOTSTRAP_WINDOW_PF_FAIL:{name}")
        if _float(row.get("expectancy"), f"{name}.expectancy") <= 0:
            raise RuntimeError(f"BOOTSTRAP_WINDOW_EXPECTANCY_FAIL:{name}")
        if _float(row.get("payoff_ratio"), f"{name}.payoff_ratio") < 1.0:
            raise RuntimeError(f"BOOTSTRAP_WINDOW_PAYOFF_FAIL:{name}")
        if _float(row.get("retention"), f"{name}.retention") < 0.60:
            raise RuntimeError(f"BOOTSTRAP_WINDOW_RETENTION_FAIL:{name}")
    metrics = evidence.get("aggregate_metrics")
    if not isinstance(metrics, Mapping):
        raise RuntimeError("BOOTSTRAP_AGGREGATE_METRICS_MISSING")
    parsed = {
        "trade_count": _float(metrics.get("trade_count"), "trade_count"),
        "net_expectancy": _float(metrics.get("net_expectancy"), "net_expectancy"),
        "profit_factor": _float(metrics.get("profit_factor"), "profit_factor"),
        "net_pnl": _float(metrics.get("net_pnl"), "net_pnl"),
        "max_dd_pct": _float(metrics.get("max_dd_pct"), "max_dd_pct"),
        "score": _float(metrics.get("score"), "score"),
    }
    evidence_sha = str(evidence.get("receipt_sha256") or "").strip()
    if not evidence_sha:
        material = dict(evidence)
        material.pop("receipt_sha256", None)
        evidence_sha = stable_sha(material)
    return parsed, evidence_sha


def bootstrap_tick(policy: Mapping[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
    cfg = validate_policy(policy)
    paths = _paths(cfg)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)

    registry = read_json(paths["registry"])
    if registry is not None:
        if registry.get("schema_version") != REGISTRY_SCHEMA:
            raise RuntimeError("BOOTSTRAP_REGISTRY_SCHEMA_INVALID")
        current = registry.get("current_authority") or {}
        if isinstance(current, Mapping) and current:
            row = _hold("PASS_BOOTSTRAP_INCUMBENT_EXISTS", "INCUMBENT_ALREADY_REGISTERED")
            row["incumbent_strategy_id"] = current.get("strategy_id")
            row["incumbent_alpha_id"] = current.get("alpha_id")
            row["updated_at_ms"] = now
            row["receipt_sha256"] = stable_sha(row)
            atomic_json_write(paths["state"], row)
            return row

    queue = read_json(paths["queue"])
    if queue is None:
        row = _hold("HOLD_BOOTSTRAP_QUEUE_MISSING", "ECONOMIC_RECOVERY_QUEUE_NOT_BOUND")
        row["updated_at_ms"] = now
        row["receipt_sha256"] = stable_sha(row)
        atomic_json_write(paths["state"], row)
        return row
    candidates = _validate_recovery(queue)
    if not candidates:
        row = _hold("HOLD_BOOTSTRAP_ROUTE_CHANGE", "ZERO_SURVIVOR_AND_NO_ADMISSION_CANDIDATE")
        row["next"] = "ROUTE_CHANGE_TO_NEXT_SOURCE_READY_ECONOMIC_FAMILY"
        row["updated_at_ms"] = now
        row["receipt_sha256"] = stable_sha(row)
        atomic_json_write(paths["state"], row)
        return row
    candidate = candidates[0]
    strategy_id = str(candidate.get("strategy_id") or "")
    if not strategy_id:
        raise RuntimeError("BOOTSTRAP_CANDIDATE_STRATEGY_ID_MISSING")

    evidence = read_json(paths["evidence"])
    if evidence is None:
        row = _hold("HOLD_BOOTSTRAP_WAIT_ADMISSION_EVIDENCE", "ADMISSION_EVIDENCE_NOT_AVAILABLE", candidate=candidate)
        row["next"] = candidate.get("route")
        row["updated_at_ms"] = now
        row["receipt_sha256"] = stable_sha(row)
        atomic_json_write(paths["state"], row)
        return row
    if evidence.get("schema_version") != ADMISSION_SCHEMA:
        raise RuntimeError("BOOTSTRAP_EVIDENCE_SCHEMA_INVALID")
    if str(evidence.get("strategy_id") or "") != strategy_id:
        raise RuntimeError("BOOTSTRAP_EVIDENCE_STRATEGY_MISMATCH")
    if evidence.get("state") == "REJECT_BOOTSTRAP_ADMISSION_EVIDENCE":
        row = _hold("HOLD_BOOTSTRAP_ADMISSION_REJECTED_ROUTE_CHANGE", "ADMISSION_EVIDENCE_TERMINAL_REJECT", candidate=candidate)
        row["next"] = "ROUTE_CHANGE_TO_NEXT_SOURCE_READY_ECONOMIC_FAMILY"
        row["evidence_receipt_sha256"] = evidence.get("receipt_sha256")
        row["updated_at_ms"] = now
        row["receipt_sha256"] = stable_sha(row)
        atomic_json_write(paths["state"], row)
        return row

    metrics, evidence_sha = _seed_gate(evidence, cfg, strategy_id)
    authority_candidate = evidence.get("authority_candidate")
    if not isinstance(authority_candidate, Mapping):
        raise RuntimeError("BOOTSTRAP_AUTHORITY_CANDIDATE_MISSING")
    if str(authority_candidate.get("strategy_id") or "") != strategy_id:
        raise RuntimeError("BOOTSTRAP_AUTHORITY_STRATEGY_MISMATCH")
    authority = executable_authority(authority_candidate, evidence_sha=evidence_sha, promoted_at_ms=now)
    registry_row = _registry(authority, metrics, evidence_sha, now, history=[])
    atomic_json_write(paths["authority"], authority)
    atomic_json_write(paths["registry"], registry_row)

    row = {
        "schema_version": SCHEMA,
        "state": "PASS_BOOTSTRAP_SEED_INCUMBENT_REGISTERED",
        "action": "hold",
        "strategy_id": strategy_id,
        "alpha_id": authority.get("alpha_id"),
        "evidence_receipt_sha256": evidence_sha,
        "authority_receipt_sha256": authority.get("receipt_sha256"),
        "registry_last_evidence_receipt_sha256": registry_row.get("last_evidence_receipt_sha256"),
        "next": "EXISTING_CUMULATIVE_IMPROVEMENT_CONTROLLER",
        "updated_at_ms": now,
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    row["receipt_sha256"] = stable_sha(row)
    atomic_json_write(paths["state"], row)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--tick", action="store_true")
    args = ap.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    result = bootstrap_tick(policy)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
