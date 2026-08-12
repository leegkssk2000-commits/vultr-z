from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_family_paper_evidence_producer.v1"
INPUT_SCHEMA = "zel.production_family_paper_canary_result.v1"
OUTPUT_SCHEMA = "zel.production_family_paper_evidence.v1"
POLICY_SCHEMA = "zel.production_family_paper_evidence_producer_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_family_paper_evidence_producer_v1.json")


def _f(v: Any, name: str) -> float:
    try:
        out = float(v)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"FAMILY_PAPER_EVIDENCE_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"FAMILY_PAPER_EVIDENCE_NUMERIC_NONFINITE:{name}")
    return out


def _hold(state: str, reason: str, *, missing: list[str] | None = None) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "reason": reason,
        "missing": list(missing or []),
        "write_evidence": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": int(time.time() * 1000),
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_NON_PAPER_FORBIDDEN")
    for key in ("canary_result_path", "evidence_path", "state_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"FAMILY_PAPER_EVIDENCE_PATH_MISSING:{key}")
    envs = policy.get("required_ssot_env")
    if not isinstance(envs, list) or not envs:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_SSOT_ENV_MISSING")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_LIVE_FORBIDDEN")
    return dict(policy)


def _ssot_bound(policy: Mapping[str, Any]) -> tuple[dict[str, float], list[str]]:
    values: dict[str, float] = {}
    missing: list[str] = []
    for env_name in policy["required_ssot_env"]:
        name = str(env_name)
        raw = os.environ.get(name, "").strip()
        if not raw:
            missing.append(name)
        else:
            values[name] = _f(raw, name)
    return values, sorted(missing)


def _normalize_canary(row: Mapping[str, Any], ssot: Mapping[str, float]) -> dict[str, Any]:
    if row.get("schema_version") != INPUT_SCHEMA or row.get("state") != "PASS_FAMILY_PAPER_CANARY":
        raise RuntimeError("FAMILY_PAPER_CANARY_NOT_PASS")
    if row.get("economic_gate_pass") is not True or row.get("durability_gate_pass") is not True or row.get("integrity_pass") is not True:
        raise RuntimeError("FAMILY_PAPER_CANARY_GATE_FAIL")
    family_id = str(row.get("family_id") or "").strip()
    strategy_id = str(row.get("strategy_id") or "").strip()
    alpha_id = str(row.get("alpha_id") or "").strip()
    if not family_id or not strategy_id or not alpha_id:
        raise RuntimeError("FAMILY_PAPER_CANARY_IDENTITY_MISSING")
    hashes = row.get("source_hashes")
    if not isinstance(hashes, list) or not hashes or any(not str(x).strip() for x in hashes):
        raise RuntimeError("FAMILY_PAPER_CANARY_SOURCE_HASHES_INVALID")
    risk = row.get("risk_request")
    if not isinstance(risk, Mapping):
        raise RuntimeError("FAMILY_PAPER_CANARY_RISK_REQUEST_MISSING")
    lev = int(_f(risk.get("leverage_x"), "risk_request.leverage_x"))
    pos = _f(risk.get("position_pct"), "risk_request.position_pct")
    if lev not in (10, 15, 20) or pos not in (5.0, 10.0, 15.0, 20.0):
        raise RuntimeError("FAMILY_PAPER_CANARY_RISK_REQUEST_NOT_ALLOWED")
    windows = row.get("windows")
    if not isinstance(windows, Mapping) or set(windows) != {"W1", "W2", "W3"}:
        raise RuntimeError("FAMILY_PAPER_CANARY_WINDOWS_INVALID")
    out_windows: dict[str, dict[str, float]] = {}
    for name in ("W1", "W2", "W3"):
        w = windows[name]
        if not isinstance(w, Mapping):
            raise RuntimeError(f"FAMILY_PAPER_CANARY_WINDOW_INVALID:{name}")
        out_windows[name] = {
            "net_pnl": _f(w.get("net_pnl"), f"{name}.net_pnl"),
            "profit_factor": _f(w.get("profit_factor"), f"{name}.profit_factor"),
            "expectancy": _f(w.get("expectancy"), f"{name}.expectancy"),
            "payoff_ratio": _f(w.get("payoff_ratio"), f"{name}.payoff_ratio"),
            "retention": _f(w.get("retention"), f"{name}.retention"),
        }
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        raise RuntimeError("FAMILY_PAPER_CANARY_METRICS_MISSING")
    out_metrics = {k: _f(metrics.get(k), k) for k in ("trade_count", "net_expectancy", "profit_factor", "net_pnl", "max_dd_pct")}
    out = {
        "schema_version": OUTPUT_SCHEMA,
        "state": "PASS_FAMILY_PAPER_EVIDENCE",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "family_id": family_id,
        "strategy_id": strategy_id,
        "alpha_id": alpha_id,
        "source_hashes": sorted(set(map(str, hashes))),
        "risk_request": {"leverage_x": lev, "position_pct": pos},
        "windows": out_windows,
        "metrics": out_metrics,
        "ssot_binding": {"bound": True, "env_names": sorted(ssot), "values_sha256": stable_sha(dict(sorted(ssot.items())))},
        "canary_receipt_sha256": str(row.get("receipt_sha256") or stable_sha(row)),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "produced_at_ms": int(time.time() * 1000),
    }
    out["receipt_sha256"] = stable_sha(out)
    return out


def tick(policy: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    ssot, missing = _ssot_bound(cfg)
    if missing:
        return _hold("HOLD_FAMILY_PAPER_EVIDENCE_SSOT_UNBOUND", "REQUIRED_Z_POLICY_SSOT_ENV_UNBOUND", missing=missing), None
    canary = read_json(Path(str(cfg["canary_result_path"])))
    if canary is None:
        return _hold("HOLD_FAMILY_PAPER_CANARY_MISSING", "NORMALIZED_FAMILY_PAPER_CANARY_NOT_AVAILABLE"), None
    evidence = _normalize_canary(canary, ssot)
    state = {
        "schema_version": SCHEMA,
        "state": "PASS_FAMILY_PAPER_EVIDENCE_READY",
        "action": "hold",
        "write_evidence": True,
        "family_id": evidence["family_id"],
        "strategy_id": evidence["strategy_id"],
        "evidence_receipt_sha256": evidence["receipt_sha256"],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": int(time.time() * 1000),
    }
    state["receipt_sha256"] = stable_sha(state)
    return state, evidence


def main() -> int:
    policy = read_json(DEFAULT_POLICY, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    state, evidence = tick(cfg)
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if evidence is not None:
        atomic_json_write(Path(str(cfg["evidence_path"])), evidence)
    print(json.dumps({"state": state["state"], "write_evidence": state["write_evidence"], "receipt_sha256": state["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
