from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_family_survivor_verifier.v1"
POLICY_SCHEMA = "zel.production_family_survivor_verifier_policy.v1"
EVIDENCE_SCHEMA = "zel.production_family_paper_evidence.v1"
INTAKE_SCHEMA = "zel.production_verified_survivor_receipt.v1"
DEFAULT_POLICY = Path("config/zel_production_family_survivor_verifier_v1.json")


def _f(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"FAMILY_SURVIVOR_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"FAMILY_SURVIVOR_NUMERIC_NONFINITE:{name}")
    return out


def _required_thresholds(policy: Mapping[str, Any]) -> tuple[dict[str, float], list[str]]:
    env_map = policy.get("required_env")
    if not isinstance(env_map, Mapping) or not env_map:
        raise RuntimeError("FAMILY_SURVIVOR_REQUIRED_ENV_MISSING")
    values: dict[str, float] = {}
    missing: list[str] = []
    for key, env_name in env_map.items():
        raw = os.environ.get(str(env_name), "").strip()
        if not raw:
            missing.append(str(env_name))
            continue
        values[str(key)] = _f(raw, str(key))
    return values, sorted(missing)


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("FAMILY_SURVIVOR_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("FAMILY_SURVIVOR_NON_PAPER_FORBIDDEN")
    for key in ("evidence_path", "verified_survivor_intake_path", "state_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"FAMILY_SURVIVOR_PATH_MISSING:{key}")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("FAMILY_SURVIVOR_POLICY_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("FAMILY_SURVIVOR_POLICY_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("FAMILY_SURVIVOR_POLICY_LIVE_FORBIDDEN")
    return dict(policy)


def _hold(state: str, reason: str, *, missing: list[str] | None = None, now_ms: int) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "reason": reason,
        "missing": list(missing or []),
        "write_verified_intake": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now_ms,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def _validate_evidence(e: Mapping[str, Any]) -> dict[str, Any]:
    if e.get("schema_version") != EVIDENCE_SCHEMA:
        raise RuntimeError("FAMILY_SURVIVOR_EVIDENCE_SCHEMA_INVALID")
    if e.get("state") != "PASS_FAMILY_PAPER_EVIDENCE":
        raise RuntimeError("FAMILY_SURVIVOR_EVIDENCE_NOT_PASS")
    if e.get("economic_gate_pass") is not True or e.get("durability_gate_pass") is not True or e.get("integrity_pass") is not True:
        raise RuntimeError("FAMILY_SURVIVOR_REQUIRED_GATE_FAIL")
    family_id = str(e.get("family_id") or "").strip()
    strategy_id = str(e.get("strategy_id") or "").strip()
    alpha_id = str(e.get("alpha_id") or "").strip()
    if not family_id or not strategy_id or not alpha_id:
        raise RuntimeError("FAMILY_SURVIVOR_IDENTITY_MISSING")
    hashes = e.get("source_hashes")
    if not isinstance(hashes, list) or not hashes or any(not str(v).strip() for v in hashes):
        raise RuntimeError("FAMILY_SURVIVOR_SOURCE_HASHES_INVALID")
    risk = e.get("risk_request")
    if not isinstance(risk, Mapping):
        raise RuntimeError("FAMILY_SURVIVOR_RISK_REQUEST_MISSING")
    lev = int(_f(risk.get("leverage_x"), "risk_request.leverage_x"))
    pos = _f(risk.get("position_pct"), "risk_request.position_pct")
    if lev not in (10, 15, 20) or pos not in (5.0, 10.0, 15.0, 20.0):
        raise RuntimeError("FAMILY_SURVIVOR_RISK_REQUEST_NOT_ALLOWED")
    windows = e.get("windows")
    if not isinstance(windows, Mapping) or set(windows) != {"W1", "W2", "W3"}:
        raise RuntimeError("FAMILY_SURVIVOR_WINDOWS_INVALID")
    for name in ("W1", "W2", "W3"):
        row = windows[name]
        if not isinstance(row, Mapping):
            raise RuntimeError(f"FAMILY_SURVIVOR_WINDOW_INVALID:{name}")
        if _f(row.get("net_pnl"), f"{name}.net_pnl") <= 0:
            raise RuntimeError(f"FAMILY_SURVIVOR_WINDOW_NET_FAIL:{name}")
        if _f(row.get("profit_factor"), f"{name}.profit_factor") < 1.0:
            raise RuntimeError(f"FAMILY_SURVIVOR_WINDOW_PF_FAIL:{name}")
        if _f(row.get("expectancy"), f"{name}.expectancy") <= 0:
            raise RuntimeError(f"FAMILY_SURVIVOR_WINDOW_EXPECTANCY_FAIL:{name}")
        if _f(row.get("payoff_ratio"), f"{name}.payoff_ratio") < 1.0:
            raise RuntimeError(f"FAMILY_SURVIVOR_WINDOW_PAYOFF_FAIL:{name}")
        if _f(row.get("retention"), f"{name}.retention") < 0.60:
            raise RuntimeError(f"FAMILY_SURVIVOR_WINDOW_RETENTION_FAIL:{name}")
    metrics = e.get("metrics")
    if not isinstance(metrics, Mapping):
        raise RuntimeError("FAMILY_SURVIVOR_METRICS_MISSING")
    parsed = {
        "trade_count": _f(metrics.get("trade_count"), "trade_count"),
        "net_expectancy": _f(metrics.get("net_expectancy"), "net_expectancy"),
        "profit_factor": _f(metrics.get("profit_factor"), "profit_factor"),
        "net_pnl": _f(metrics.get("net_pnl"), "net_pnl"),
        "max_dd_pct": _f(metrics.get("max_dd_pct"), "max_dd_pct"),
    }
    if parsed["trade_count"] <= 0:
        raise RuntimeError("FAMILY_SURVIVOR_TRADE_COUNT_NONPOSITIVE")
    return {"family_id": family_id, "strategy_id": strategy_id, "alpha_id": alpha_id, "source_hashes": sorted(set(map(str, hashes))), "risk_request": {"leverage_x": lev, "position_pct": pos}, "metrics": parsed}


def verify(policy: Mapping[str, Any], evidence: Mapping[str, Any] | None, *, now_ms: int | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    thresholds, missing = _required_thresholds(cfg)
    if missing:
        return _hold("HOLD_FAMILY_SURVIVOR_SSOT_UNBOUND", "REQUIRED_Z_POLICY_SSOT_ENV_UNBOUND", missing=missing, now_ms=now), None
    if evidence is None:
        return _hold("HOLD_FAMILY_SURVIVOR_EVIDENCE_MISSING", "NORMALIZED_PAPER_EVIDENCE_NOT_AVAILABLE", now_ms=now), None
    parsed = _validate_evidence(evidence)
    m = parsed["metrics"]
    if m["trade_count"] < thresholds["min_trades"]:
        raise RuntimeError("FAMILY_SURVIVOR_MIN_TRADES_FAIL")
    if m["net_expectancy"] < thresholds["min_expectancy"]:
        raise RuntimeError("FAMILY_SURVIVOR_MIN_EXPECTANCY_FAIL")
    if m["profit_factor"] < thresholds["min_profit_factor"]:
        raise RuntimeError("FAMILY_SURVIVOR_MIN_PF_FAIL")
    if m["net_pnl"] < thresholds["min_net_pnl"]:
        raise RuntimeError("FAMILY_SURVIVOR_MIN_NET_PNL_FAIL")
    if m["max_dd_pct"] > thresholds["max_dd_pct"]:
        raise RuntimeError("FAMILY_SURVIVOR_MAX_DD_FAIL")
    intake = {
        "schema_version": INTAKE_SCHEMA,
        "state": "PASS_ECONOMIC_SURVIVOR",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "family_id": parsed["family_id"],
        "strategy_id": parsed["strategy_id"],
        "alpha_id": parsed["alpha_id"],
        "authority_receipt_sha256": str(evidence.get("receipt_sha256") or stable_sha(evidence)),
        "source_hashes": parsed["source_hashes"],
        "risk_request": parsed["risk_request"],
        "metrics": m,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "verified_at_ms": now,
    }
    intake["receipt_sha256"] = stable_sha(intake)
    state = {
        "schema_version": SCHEMA,
        "state": "PASS_FAMILY_VERIFIED_SURVIVOR_INTAKE_READY",
        "action": "hold",
        "write_verified_intake": True,
        "family_id": parsed["family_id"],
        "strategy_id": parsed["strategy_id"],
        "intake_receipt_sha256": intake["receipt_sha256"],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now,
    }
    state["receipt_sha256"] = stable_sha(state)
    return state, intake


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify normalized independent-family PAPER evidence before survivor catalog intake")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args()
    policy = read_json(ns.policy, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    state, intake = verify(cfg, read_json(Path(str(cfg["evidence_path"]))))
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if intake is not None:
        atomic_json_write(Path(str(cfg["verified_survivor_intake_path"])), intake)
    print(json.dumps({"state": state["state"], "write_verified_intake": state["write_verified_intake"], "receipt_sha256": state["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
