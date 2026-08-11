from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.production_active_alpha_adapter.v1"
POLICY_SCHEMA = "zel.production_active_alpha_policy.v1"
SIGNAL_SCHEMA = "zel.production_alpha_signal.v1"
DEFAULT_POLICY = Path("config/zel_production_active_alpha_v1.json")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _float(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"ACTIVE_ALPHA_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"ACTIVE_ALPHA_NUMERIC_NONFINITE:{name}")
    return out


def _policy_stale_ms(policy: Mapping[str, Any]) -> float:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("ACTIVE_ALPHA_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("ACTIVE_ALPHA_POLICY_NON_PAPER_FORBIDDEN")
    if policy.get("execution_authority") != "PAPER_SIM_ONLY":
        raise RuntimeError("ACTIVE_ALPHA_POLICY_EXECUTION_INVALID")
    if policy.get("order_authority") != "BLOCKED" or policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("ACTIVE_ALPHA_POLICY_LIVE_AUTHORITY_FORBIDDEN")
    raw = policy.get("signal_stale_ms")
    if raw is None:
        env_map = policy.get("required_env_when_null")
        env_name = env_map.get("signal_stale_ms") if isinstance(env_map, Mapping) else None
        if not env_name:
            raise RuntimeError("ACTIVE_ALPHA_SIGNAL_STALE_UNBOUND")
        raw = os.environ.get(str(env_name))
        if raw is None or not str(raw).strip():
            raise RuntimeError(f"ACTIVE_ALPHA_SIGNAL_STALE_ENV_UNBOUND:{env_name}")
    value = _float(raw, "signal_stale_ms")
    if value <= 0:
        raise RuntimeError("ACTIVE_ALPHA_SIGNAL_STALE_NONPOSITIVE")
    return value


def authority_is_executable(authority: Mapping[str, Any]) -> bool:
    return (
        str(authority.get("alpha_state") or "").upper() == "SURVIVOR_ACTIVE"
        and authority.get("research_only") is False
        and authority.get("promotion_authority") is True
        and authority.get("execution_allowed") is True
        and authority.get("runtime_bound") is True
        and str((authority.get("runtime_authority") or {}).get("execution_authority") or "") == "PAPER_SIM_ONLY"
        and str((authority.get("runtime_authority") or {}).get("order_authority") or "") == "BLOCKED"
        and str((authority.get("runtime_authority") or {}).get("live_trade_authority") or "") == "BLOCKED"
    )


def bind_active_alpha(
    authority: Mapping[str, Any],
    signal: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    if not authority_is_executable(authority):
        raise RuntimeError("ACTIVE_ALPHA_AUTHORITY_NOT_EXECUTABLE")
    max_stale_ms = _policy_stale_ms(policy)
    if signal.get("schema_version") != SIGNAL_SCHEMA:
        raise RuntimeError("ACTIVE_ALPHA_SIGNAL_SCHEMA_INVALID")
    if str(signal.get("state") or "").upper() != "PASS_ACTIVE_ALPHA_SIGNAL":
        raise RuntimeError("ACTIVE_ALPHA_SIGNAL_NOT_PASS")

    strategy_id = str(authority.get("strategy_id") or "")
    alpha_id = str(authority.get("alpha_id") or "")
    symbol = str(authority.get("symbol") or "").replace("-", "").upper()
    if not strategy_id or not alpha_id or symbol not in {"BTCUSDT", "ETHUSDT"}:
        raise RuntimeError("ACTIVE_ALPHA_AUTHORITY_IDENTITY_INCOMPLETE")
    if str(signal.get("strategy_id") or "") != strategy_id:
        raise RuntimeError("ACTIVE_ALPHA_SIGNAL_STRATEGY_MISMATCH")
    if str(signal.get("alpha_id") or "") != alpha_id:
        raise RuntimeError("ACTIVE_ALPHA_SIGNAL_ALPHA_MISMATCH")
    if str(signal.get("symbol") or "").replace("-", "").upper() != symbol:
        raise RuntimeError("ACTIVE_ALPHA_SIGNAL_SYMBOL_MISMATCH")

    signal_name = str(signal.get("signal") or "").upper()
    allowed = {str(v).upper() for v in (policy.get("allowed_signals") or [])}
    if signal_name not in allowed or signal_name not in {"LONG", "SHORT", "EXIT", "FLAT"}:
        raise RuntimeError(f"ACTIVE_ALPHA_SIGNAL_INVALID:{signal_name}")
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    signal_ts = int(_float(signal.get("signal_ts"), "signal_ts"))
    age_ms = now - signal_ts
    if age_ms < 0:
        raise RuntimeError("ACTIVE_ALPHA_SIGNAL_FUTURE_TIMESTAMP")
    if age_ms > max_stale_ms:
        raise RuntimeError(f"ACTIVE_ALPHA_SIGNAL_STALE:{age_ms}")

    source_hashes = signal.get("source_hashes")
    if not isinstance(source_hashes, list) or not source_hashes or any(not str(v).strip() for v in source_hashes):
        raise RuntimeError("ACTIVE_ALPHA_SIGNAL_SOURCE_HASHES_MISSING")
    risk_request = authority.get("risk_request")
    if not isinstance(risk_request, Mapping):
        raise RuntimeError("ACTIVE_ALPHA_RISK_REQUEST_MISSING")

    bound = dict(authority)
    bound.update(
        {
            "schema_version": SCHEMA,
            "state": "PASS_ACTIVE_ALPHA_BOUND",
            "symbol": symbol,
            "signal": signal_name,
            "signal_ts": signal_ts,
            "signal_age_ms": age_ms,
            "signal_source_hashes": list(source_hashes),
            "source_hashes": sorted(set([str(v) for v in (authority.get("source_hashes") or [])] + [str(v) for v in source_hashes])),
            "exchange_order_submitted": False,
        }
    )
    bound["receipt_sha256"] = stable_sha(bound)
    return bound


def read_json(path: str | Path, label: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"{label}_MISSING:{p}")
    row = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"{label}_NOT_OBJECT")
    return row


def build_from_paths(
    authority_path: str | Path,
    *,
    policy_path: str | Path = DEFAULT_POLICY,
    signal_path: str | Path | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    authority = read_json(authority_path, "ACTIVE_ALPHA_AUTHORITY")
    policy = read_json(policy_path, "ACTIVE_ALPHA_POLICY")
    configured_signal = signal_path or policy.get("signal_path")
    if not configured_signal:
        raise RuntimeError("ACTIVE_ALPHA_SIGNAL_PATH_UNBOUND")
    signal = read_json(configured_signal, "ACTIVE_ALPHA_SIGNAL")
    return bind_active_alpha(authority, signal, policy, now_ms=now_ms)
