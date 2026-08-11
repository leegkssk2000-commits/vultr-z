from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_auto_cycle_supervisor_v1 import SupervisorPolicy, evaluate_improvement

SCHEMA = "zel.production_improvement_controller.v1"
POLICY_SCHEMA = "zel.production_improvement_policy.v1"
EVIDENCE_SCHEMA = "zel.production_improvement_evidence.v1"
REGISTRY_SCHEMA = "zel.production_incumbent_registry.v1"
QUEUE_SCHEMA = "zel.production_candidate_queue.v1"
DEFAULT_POLICY = Path("config/zel_production_improvement_v1.json")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (AttributeError, OSError):
            pass
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def read_json(path: Path, *, required: bool = False) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise RuntimeError(f"IMPROVEMENT_JSON_MISSING:{path}")
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"IMPROVEMENT_JSON_INVALID:{path}:{type(exc).__name__}") from exc
    if not isinstance(row, dict):
        raise RuntimeError(f"IMPROVEMENT_JSON_NOT_OBJECT:{path}")
    return row


def _float(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"IMPROVEMENT_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"IMPROVEMENT_NUMERIC_NONFINITE:{name}")
    return out


def _int(value: Any, name: str) -> int:
    out = _float(value, name)
    if not out.is_integer():
        raise RuntimeError(f"IMPROVEMENT_INTEGER_INVALID:{name}")
    return int(out)


def validate_policy_shape(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("IMPROVEMENT_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("IMPROVEMENT_POLICY_NON_PAPER_FORBIDDEN")
    if _int(policy.get("candidate_budget"), "candidate_budget") != 2:
        raise RuntimeError("IMPROVEMENT_CANDIDATE_BUDGET_MUST_BE_2")
    if str(policy.get("mutation_class") or "") != "CONFIG_ONLY":
        raise RuntimeError("IMPROVEMENT_MUTATION_CLASS_INVALID")
    rules = policy.get("candidate_rules")
    if not isinstance(rules, Mapping):
        raise RuntimeError("IMPROVEMENT_CANDIDATE_RULES_MISSING")
    if _int(rules.get("max_changed_axes"), "max_changed_axes") != 1:
        raise RuntimeError("IMPROVEMENT_MAX_CHANGED_AXES_MUST_BE_1")
    for key in ("allow_new_features", "allow_new_strategy_family", "allow_source_code_mutation"):
        if rules.get(key) is not False:
            raise RuntimeError(f"IMPROVEMENT_RULE_MUST_BE_FALSE:{key}")
    if policy.get("order_authority") != "BLOCKED" or policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("IMPROVEMENT_LIVE_AUTHORITY_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("IMPROVEMENT_SELF_MODIFICATION_FORBIDDEN")
    for key in ("registry_path", "authority_path", "evidence_path", "candidate_queue_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"IMPROVEMENT_POLICY_PATH_MISSING:{key}")
    return dict(policy)


def _threshold(policy: Mapping[str, Any], key: str) -> float:
    thresholds = policy.get("thresholds")
    if not isinstance(thresholds, Mapping) or key not in thresholds:
        raise RuntimeError(f"IMPROVEMENT_THRESHOLD_MISSING:{key}")
    value = thresholds.get(key)
    if value is None:
        env_map = policy.get("required_env_when_null")
        env_name = env_map.get(key) if isinstance(env_map, Mapping) else None
        if not env_name:
            raise RuntimeError(f"IMPROVEMENT_THRESHOLD_ENV_NAME_MISSING:{key}")
        value = os.environ.get(str(env_name))
        if value is None or not str(value).strip():
            raise RuntimeError(f"IMPROVEMENT_THRESHOLD_ENV_UNBOUND:{key}:{env_name}")
    return _float(value, key)


def resolved_thresholds(policy: Mapping[str, Any]) -> dict[str, float]:
    cfg = {key: _threshold(policy, key) for key in (
        "min_trades",
        "min_expectancy",
        "min_profit_factor",
        "min_net_pnl",
        "max_dd_pct",
        "min_score_gain",
        "max_dd_regression_pct",
        "error_budget",
    )}
    if cfg["min_trades"] < 1 or not cfg["min_trades"].is_integer():
        raise RuntimeError("IMPROVEMENT_MIN_TRADES_INVALID")
    if cfg["error_budget"] < 0 or not cfg["error_budget"].is_integer():
        raise RuntimeError("IMPROVEMENT_ERROR_BUDGET_INVALID")
    if cfg["max_dd_pct"] < 0 or cfg["max_dd_regression_pct"] < 0:
        raise RuntimeError("IMPROVEMENT_DD_THRESHOLD_INVALID")
    return cfg


def validate_integrity(evidence: Mapping[str, Any]) -> int:
    if evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise RuntimeError("IMPROVEMENT_EVIDENCE_SCHEMA_INVALID")
    if str(evidence.get("state") or "") != "PASS_IMPROVEMENT_EVIDENCE":
        raise RuntimeError("IMPROVEMENT_EVIDENCE_NOT_PASS")
    integrity = evidence.get("integrity")
    if not isinstance(integrity, Mapping):
        raise RuntimeError("IMPROVEMENT_INTEGRITY_MISSING")
    for key in ("source_parity", "ledger_parity", "cost_parity", "paper_only", "no_live_orders"):
        if integrity.get(key) is not True:
            raise RuntimeError(f"IMPROVEMENT_INTEGRITY_FAIL:{key}")
    errors = _int(integrity.get("error_count", 0), "integrity.error_count")
    if errors < 0:
        raise RuntimeError("IMPROVEMENT_ERROR_COUNT_INVALID")
    return errors


def validate_metrics(metrics: Mapping[str, Any], thresholds: Mapping[str, float], *, error_count: int) -> dict[str, float]:
    out = {
        "trade_count": float(_int(metrics.get("trade_count"), "trade_count")),
        "net_expectancy": _float(metrics.get("net_expectancy"), "net_expectancy"),
        "profit_factor": _float(metrics.get("profit_factor"), "profit_factor"),
        "net_pnl": _float(metrics.get("net_pnl"), "net_pnl"),
        "max_dd_pct": _float(metrics.get("max_dd_pct"), "max_dd_pct"),
        "score": _float(metrics.get("score"), "score"),
    }
    if out["trade_count"] < thresholds["min_trades"]:
        raise RuntimeError("IMPROVEMENT_GATE_MIN_TRADES")
    if out["net_expectancy"] < thresholds["min_expectancy"]:
        raise RuntimeError("IMPROVEMENT_GATE_EXPECTANCY")
    if out["profit_factor"] < thresholds["min_profit_factor"]:
        raise RuntimeError("IMPROVEMENT_GATE_PROFIT_FACTOR")
    if out["net_pnl"] < thresholds["min_net_pnl"]:
        raise RuntimeError("IMPROVEMENT_GATE_NET_PNL")
    if out["max_dd_pct"] > thresholds["max_dd_pct"]:
        raise RuntimeError("IMPROVEMENT_GATE_DD")
    if error_count > int(thresholds["error_budget"]):
        raise RuntimeError("IMPROVEMENT_GATE_ERROR_BUDGET")
    return out


def validate_authority_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    required = ("strategy_id", "alpha_id", "symbol", "cost_model_id", "risk_request", "source_hashes")
    for key in required:
        if key not in candidate:
            raise RuntimeError(f"IMPROVEMENT_AUTHORITY_FIELD_MISSING:{key}")
    symbol = str(candidate.get("symbol") or "").replace("-", "").upper()
    if symbol not in {"BTCUSDT", "ETHUSDT"}:
        raise RuntimeError("IMPROVEMENT_AUTHORITY_SYMBOL_INVALID")
    risk = candidate.get("risk_request")
    if not isinstance(risk, Mapping) or set(risk) != {"leverage_x", "position_pct"}:
        raise RuntimeError("IMPROVEMENT_AUTHORITY_RISK_REQUEST_INVALID")
    if _int(risk.get("leverage_x"), "risk_request.leverage_x") not in {10, 15, 20}:
        raise RuntimeError("IMPROVEMENT_AUTHORITY_LEVERAGE_INVALID")
    if _float(risk.get("position_pct"), "risk_request.position_pct") not in {5.0, 10.0, 15.0, 20.0}:
        raise RuntimeError("IMPROVEMENT_AUTHORITY_POSITION_PCT_INVALID")
    hashes = candidate.get("source_hashes")
    if not isinstance(hashes, list) or not hashes or any(not str(v).strip() for v in hashes):
        raise RuntimeError("IMPROVEMENT_AUTHORITY_SOURCE_HASHES_INVALID")
    knobs = candidate.get("knobs") or {}
    tunable = candidate.get("tunable_axes") or []
    values = candidate.get("candidate_values") or {}
    if not isinstance(knobs, Mapping) or not isinstance(tunable, list) or not isinstance(values, Mapping):
        raise RuntimeError("IMPROVEMENT_TUNABLE_CONTRACT_INVALID")
    if any(str(axis) not in knobs or str(axis) not in values for axis in tunable):
        raise RuntimeError("IMPROVEMENT_TUNABLE_AXIS_UNBOUND")
    if any(not isinstance(values.get(str(axis)), list) or not values.get(str(axis)) for axis in tunable):
        raise RuntimeError("IMPROVEMENT_CANDIDATE_VALUES_EMPTY")
    result = dict(candidate)
    result["symbol"] = symbol
    result["knobs"] = dict(knobs)
    result["tunable_axes"] = [str(v) for v in tunable]
    result["candidate_values"] = {str(k): list(v) for k, v in values.items()}
    return result


def executable_authority(candidate: Mapping[str, Any], *, evidence_sha: str, promoted_at_ms: int) -> dict[str, Any]:
    base = validate_authority_candidate(candidate)
    base.update({
        "schema_version": "zel.production_alpha_authority.v1",
        "state": "PASS_PRODUCTION_ALPHA_AUTHORITY",
        "alpha_state": "SURVIVOR_ACTIVE",
        "research_only": False,
        "promotion_authority": True,
        "execution_allowed": True,
        "runtime_bound": True,
        "promoted_at_ms": promoted_at_ms,
        "promotion_evidence_sha256": evidence_sha,
        "runtime_authority": {
            "execution_authority": "PAPER_SIM_ONLY",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
    })
    base["receipt_sha256"] = stable_sha(base)
    return base


def hard_gate_result(metrics: Mapping[str, Any], thresholds: Mapping[str, float], error_count: int) -> tuple[bool, str, dict[str, float] | None]:
    try:
        parsed = validate_metrics(metrics, thresholds, error_count=error_count)
    except RuntimeError as exc:
        return False, str(exc), None
    return True, "ECONOMIC_GATE_PASS", parsed


def generate_candidates(authority: Mapping[str, Any], *, budget: int = 2) -> list[dict[str, Any]]:
    incumbent = validate_authority_candidate(authority)
    knobs = dict(incumbent.get("knobs") or {})
    values = dict(incumbent.get("candidate_values") or {})
    rows: list[dict[str, Any]] = []
    for axis in incumbent.get("tunable_axes") or []:
        current = knobs.get(axis)
        for value in values.get(axis) or []:
            if value == current:
                continue
            material = {
                "incumbent_receipt_sha256": incumbent.get("receipt_sha256"),
                "strategy_id": incumbent.get("strategy_id"),
                "alpha_id": incumbent.get("alpha_id"),
                "changed_axis": axis,
                "value": value,
            }
            candidate_id = "cfg." + stable_sha(material)[:16]
            candidate_knobs = dict(knobs)
            candidate_knobs[axis] = value
            rows.append({
                "candidate_id": candidate_id,
                "incumbent_id": incumbent.get("alpha_id"),
                "incumbent_hash": incumbent.get("receipt_sha256"),
                "changed_axis": axis,
                "knob_changes": {axis: value},
                "knobs": candidate_knobs,
                "mutation_class": "CONFIG_ONLY",
                "strategy_id": incumbent.get("strategy_id"),
                "symbol": incumbent.get("symbol"),
                "evaluation_state": "PENDING_PAPER_EVIDENCE",
            })
            if len(rows) >= budget:
                return rows
    return rows


def candidate_queue(authority: Mapping[str, Any], *, budget: int = 2) -> dict[str, Any]:
    candidates = generate_candidates(authority, budget=budget)
    queue = {
        "schema_version": QUEUE_SCHEMA,
        "state": "PASS_CANDIDATE_QUEUE" if candidates else "HOLD_NO_CONFIG_CANDIDATE",
        "incumbent_id": authority.get("alpha_id"),
        "incumbent_hash": authority.get("receipt_sha256"),
        "candidate_budget": budget,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "required_evidence_schema": EVIDENCE_SCHEMA,
        "mutation_class": "CONFIG_ONLY",
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
        "exchange_order_submitted": False,
    }
    queue["receipt_sha256"] = stable_sha(queue)
    return queue


def _registry(authority: Mapping[str, Any], metrics: Mapping[str, Any], evidence_sha: str, now_ms: int, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    row = {
        "schema_version": REGISTRY_SCHEMA,
        "state": "PASS_INCUMBENT_REGISTRY",
        "updated_at_ms": now_ms,
        "current_authority": dict(authority),
        "current_metrics": dict(metrics),
        "history": list(history or []),
        "last_evidence_receipt_sha256": evidence_sha,
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def _paths(policy: Mapping[str, Any]) -> dict[str, Path]:
    return {key: Path(str(policy[key])) for key in ("registry_path", "authority_path", "evidence_path", "candidate_queue_path")}


def _write_registry_then_authority(registry_path: Path, authority_path: Path, registry: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
    # Safe ordering: registry may briefly lead authority after a crash, but the
    # trading source can never observe a newly promoted authority without a
    # durable registry record. The next tick repairs an authority lag.
    atomic_json_write(registry_path, registry)
    atomic_json_write(authority_path, authority)


def controller_tick(policy: Mapping[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
    cfg = validate_policy_shape(policy)
    paths = _paths(cfg)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    registry = read_json(paths["registry_path"])
    evidence = read_json(paths["evidence_path"])

    if registry is not None and registry.get("schema_version") != REGISTRY_SCHEMA:
        raise RuntimeError("IMPROVEMENT_REGISTRY_SCHEMA_INVALID")
    current = dict(registry.get("current_authority") or {}) if isinstance(registry, Mapping) else {}

    if evidence is None:
        if not current:
            return {
                "schema_version": SCHEMA,
                "state": "HOLD_NO_SEED_SURVIVOR",
                "action": "hold",
                "reason": "NO_IMPROVEMENT_EVIDENCE_AND_NO_INCUMBENT",
                "exchange_order_submitted": False,
                "source_code_mutation_applied": False,
                "self_modification_applied": False,
            }
        queue = candidate_queue(current, budget=int(cfg["candidate_budget"]))
        atomic_json_write(paths["candidate_queue_path"], queue)
        return {
            "schema_version": SCHEMA,
            "state": queue["state"],
            "action": "hold",
            "reason": "CANDIDATE_QUEUE_REFRESHED",
            "candidate_queue_receipt_sha256": queue["receipt_sha256"],
            "exchange_order_submitted": False,
            "source_code_mutation_applied": False,
            "self_modification_applied": False,
        }

    errors = validate_integrity(evidence)
    evidence_sha = str(evidence.get("receipt_sha256") or stable_sha({k: v for k, v in evidence.items() if k != "receipt_sha256"}))
    if registry is not None and registry.get("last_evidence_receipt_sha256") == evidence_sha:
        if current:
            # Repair an authority file that may lag a durable registry after a crash.
            existing_authority = read_json(paths["authority_path"])
            if existing_authority is None or existing_authority.get("receipt_sha256") != current.get("receipt_sha256"):
                atomic_json_write(paths["authority_path"], current)
        return {
            "schema_version": SCHEMA,
            "state": "HOLD_EVIDENCE_ALREADY_APPLIED",
            "action": "hold",
            "reason": "IDEMPOTENT_EVIDENCE_REPLAY",
            "exchange_order_submitted": False,
            "source_code_mutation_applied": False,
            "self_modification_applied": False,
        }

    thresholds = resolved_thresholds(cfg)
    kind = str(evidence.get("kind") or "").upper()

    if kind == "SEED_SURVIVOR":
        if current:
            raise RuntimeError("IMPROVEMENT_SEED_FORBIDDEN_WITH_INCUMBENT")
        metrics = evidence.get("metrics")
        candidate = evidence.get("authority_candidate")
        if not isinstance(metrics, Mapping) or not isinstance(candidate, Mapping):
            raise RuntimeError("IMPROVEMENT_SEED_FIELDS_MISSING")
        passed, reason, parsed = hard_gate_result(metrics, thresholds, errors)
        if not passed or parsed is None:
            return {"schema_version": SCHEMA, "state": "HOLD", "action": "hold", "reason": reason, "exchange_order_submitted": False, "source_code_mutation_applied": False, "self_modification_applied": False}
        authority = executable_authority(candidate, evidence_sha=evidence_sha, promoted_at_ms=now)
        reg = _registry(authority, parsed, evidence_sha, now)
        _write_registry_then_authority(paths["registry_path"], paths["authority_path"], reg, authority)
        queue = candidate_queue(authority, budget=int(cfg["candidate_budget"]))
        atomic_json_write(paths["candidate_queue_path"], queue)
        return {"schema_version": SCHEMA, "state": "PROMOTED_SEED_INCUMBENT", "action": "hold", "reason": "SEED_ECONOMIC_GATE_PASS", "incumbent_id": authority["alpha_id"], "registry_receipt_sha256": reg["receipt_sha256"], "candidate_queue_receipt_sha256": queue["receipt_sha256"], "exchange_order_submitted": False, "source_code_mutation_applied": False, "self_modification_applied": False}

    if not current:
        raise RuntimeError("IMPROVEMENT_INCUMBENT_REQUIRED")

    if kind == "CANDIDATE_COMPARISON":
        queue = read_json(paths["candidate_queue_path"], required=True)
        candidate = evidence.get("candidate")
        incumbent_metrics = evidence.get("incumbent_metrics")
        candidate_metrics = evidence.get("candidate_metrics")
        if not isinstance(candidate, Mapping) or not isinstance(incumbent_metrics, Mapping) or not isinstance(candidate_metrics, Mapping):
            raise RuntimeError("IMPROVEMENT_COMPARISON_FIELDS_MISSING")
        expected = None
        for row in queue.get("candidates") or []:
            if isinstance(row, Mapping) and row.get("candidate_id") == candidate.get("candidate_id"):
                expected = dict(row)
                break
        if expected is None or stable_sha(expected) != stable_sha(dict(candidate)):
            raise RuntimeError("IMPROVEMENT_CANDIDATE_NOT_IN_QUEUE")
        if queue.get("incumbent_hash") != current.get("receipt_sha256"):
            raise RuntimeError("IMPROVEMENT_QUEUE_INCUMBENT_STALE")

        cand_ok, cand_reason, cand_parsed = hard_gate_result(candidate_metrics, thresholds, errors)
        inc_ok, _inc_reason, inc_parsed = hard_gate_result(incumbent_metrics, thresholds, errors)
        if not inc_ok or inc_parsed is None:
            raise RuntimeError("IMPROVEMENT_INCUMBENT_EVIDENCE_INVALID")
        if not cand_ok or cand_parsed is None:
            return {"schema_version": SCHEMA, "state": "HOLD", "action": "hold", "reason": cand_reason, "candidate_id": candidate.get("candidate_id"), "exchange_order_submitted": False, "source_code_mutation_applied": False, "self_modification_applied": False}

        supervisor_policy = SupervisorPolicy(
            min_evidence_samples=int(thresholds["min_trades"]),
            min_score_gain=thresholds["min_score_gain"],
            max_dd_regression_pct=thresholds["max_dd_regression_pct"],
            error_budget=int(thresholds["error_budget"]),
            allowlisted_knobs=tuple(str(v) for v in current.get("tunable_axes") or []),
        )
        comparison = evaluate_improvement(
            {
                "candidate": {"candidate_id": candidate["candidate_id"], "knobs": dict(candidate.get("knob_changes") or {})},
                "incumbent_id": current.get("alpha_id"),
                "incumbent_hash": current.get("receipt_sha256"),
                "sample_count": int(cand_parsed["trade_count"]),
                "candidate_score": cand_parsed["score"],
                "incumbent_score": inc_parsed["score"],
                "candidate_max_dd_pct": cand_parsed["max_dd_pct"],
                "incumbent_max_dd_pct": inc_parsed["max_dd_pct"],
                "error_count": errors,
            },
            supervisor_policy,
        )
        if comparison.get("promotion_allowed") is not True:
            return {"schema_version": SCHEMA, "state": "HOLD", "action": "hold", "reason": comparison.get("reason"), "comparison": comparison, "exchange_order_submitted": False, "source_code_mutation_applied": False, "self_modification_applied": False}

        previous = {"authority": current, "metrics": dict(registry.get("current_metrics") or {}), "replaced_at_ms": now}
        next_candidate = dict(current)
        next_candidate["knobs"] = dict(candidate.get("knobs") or {})
        next_candidate["alpha_id"] = f"{current.get('alpha_id')}.cfg.{str(candidate.get('candidate_id')).split('.')[-1]}"
        next_candidate["source_hashes"] = sorted(set([str(v) for v in current.get("source_hashes") or []] + [evidence_sha]))
        next_authority = executable_authority(next_candidate, evidence_sha=evidence_sha, promoted_at_ms=now)
        history = list(registry.get("history") or []) + [previous]
        reg = _registry(next_authority, cand_parsed, evidence_sha, now, history=history)
        _write_registry_then_authority(paths["registry_path"], paths["authority_path"], reg, next_authority)
        next_queue = candidate_queue(next_authority, budget=int(cfg["candidate_budget"]))
        atomic_json_write(paths["candidate_queue_path"], next_queue)
        return {"schema_version": SCHEMA, "state": "PROMOTED_NEW_INCUMBENT", "action": "hold", "reason": "CANDIDATE_BEATS_INCUMBENT", "incumbent_id": next_authority["alpha_id"], "comparison": comparison, "registry_receipt_sha256": reg["receipt_sha256"], "candidate_queue_receipt_sha256": next_queue["receipt_sha256"], "exchange_order_submitted": False, "source_code_mutation_applied": False, "self_modification_applied": False}

    if kind == "INCUMBENT_HEALTH":
        metrics = evidence.get("metrics")
        if not isinstance(metrics, Mapping):
            raise RuntimeError("IMPROVEMENT_HEALTH_METRICS_MISSING")
        passed, reason, parsed = hard_gate_result(metrics, thresholds, errors)
        if passed and parsed is not None:
            reg = _registry(current, parsed, evidence_sha, now, history=list(registry.get("history") or []))
            _write_registry_then_authority(paths["registry_path"], paths["authority_path"], reg, current)
            return {"schema_version": SCHEMA, "state": "INCUMBENT_HEALTH_PASS", "action": "hold", "reason": "INCUMBENT_REMAINS_VALID", "exchange_order_submitted": False, "source_code_mutation_applied": False, "self_modification_applied": False}
        history = list(registry.get("history") or [])
        if not history:
            return {"schema_version": SCHEMA, "state": "HOLD_ROLLBACK_UNAVAILABLE", "action": "hold", "reason": reason, "exchange_order_submitted": False, "source_code_mutation_applied": False, "self_modification_applied": False}
        previous = history[-1]
        previous_authority = previous.get("authority")
        previous_metrics = previous.get("metrics")
        if not isinstance(previous_authority, Mapping) or not isinstance(previous_metrics, Mapping):
            raise RuntimeError("IMPROVEMENT_ROLLBACK_HISTORY_INVALID")
        rollback_authority = dict(previous_authority)
        rollback_authority["rollback_from_alpha_id"] = current.get("alpha_id")
        rollback_authority["rollback_evidence_sha256"] = evidence_sha
        rollback_authority["receipt_sha256"] = stable_sha({k: v for k, v in rollback_authority.items() if k != "receipt_sha256"})
        reg = _registry(rollback_authority, previous_metrics, evidence_sha, now, history=history[:-1])
        _write_registry_then_authority(paths["registry_path"], paths["authority_path"], reg, rollback_authority)
        queue = candidate_queue(rollback_authority, budget=int(cfg["candidate_budget"]))
        atomic_json_write(paths["candidate_queue_path"], queue)
        return {"schema_version": SCHEMA, "state": "ROLLED_BACK_TO_PREVIOUS_INCUMBENT", "action": "rollback", "reason": reason, "incumbent_id": rollback_authority.get("alpha_id"), "registry_receipt_sha256": reg["receipt_sha256"], "candidate_queue_receipt_sha256": queue["receipt_sha256"], "exchange_order_submitted": False, "source_code_mutation_applied": False, "self_modification_applied": False}

    raise RuntimeError(f"IMPROVEMENT_EVIDENCE_KIND_UNSUPPORTED:{kind or 'MISSING'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL production cumulative improvement controller")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--tick", action="store_true")
    args = parser.parse_args(argv)
    policy = read_json(args.policy, required=True)
    assert policy is not None
    result = controller_tick(policy)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
