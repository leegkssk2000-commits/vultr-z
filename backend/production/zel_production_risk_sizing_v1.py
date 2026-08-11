from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.production_risk_sizing.v1"
POLICY_SCHEMA = "zel.production_risk_sizing_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_risk_sizing_v1.json")
DEFAULT_ACCOUNT_STATE = Path("/home/zel/apps/zel/ledger/production_paper_account_state_v1.json")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _float(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"INVALID_NUMERIC:{name}") from exc
    if not math.isfinite(out):
        raise ValueError(f"NONFINITE_NUMERIC:{name}")
    return out


def _int(value: Any, name: str) -> int:
    number = _float(value, name)
    if not number.is_integer():
        raise ValueError(f"NON_INTEGER:{name}")
    return int(number)


def _load_json(path: str | Path, label: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"{label}_MISSING:{p}")
    try:
        row = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"{label}_INVALID_JSON:{type(exc).__name__}") from exc
    if not isinstance(row, dict):
        raise RuntimeError(f"{label}_MUST_BE_OBJECT")
    return row


def _policy_value(policy: Mapping[str, Any], key: str) -> float:
    value = policy.get(key)
    if value is not None:
        return _float(value, key)
    env_map = policy.get("required_env_when_null")
    env_name = env_map.get(key) if isinstance(env_map, Mapping) else None
    if not env_name:
        raise RuntimeError(f"RISK_POLICY_VALUE_UNBOUND:{key}")
    raw = os.environ.get(str(env_name))
    if raw is None or not raw.strip():
        raise RuntimeError(f"RISK_POLICY_ENV_UNBOUND:{key}:{env_name}")
    return _float(raw, key)


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("RISK_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("RISK_POLICY_NON_PAPER_FORBIDDEN")
    if policy.get("execution_authority") != "PAPER_SIM_ONLY":
        raise RuntimeError("RISK_POLICY_EXECUTION_AUTHORITY_INVALID")
    if policy.get("order_authority") != "BLOCKED" or policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("RISK_POLICY_LIVE_AUTHORITY_FORBIDDEN")
    if policy.get("conditional_25x_enabled") is not False:
        raise RuntimeError("RISK_POLICY_25X_MUST_REMAIN_DISABLED")
    allowed_lev = tuple(_int(v, "allowed_leverage_x") for v in (policy.get("allowed_leverage_x") or []))
    allowed_pos = tuple(_float(v, "allowed_position_pct") for v in (policy.get("allowed_position_pct") or []))
    if allowed_lev != (10, 15, 20):
        raise RuntimeError("RISK_POLICY_LEVERAGE_ALLOWLIST_INVALID")
    if allowed_pos != (5.0, 10.0, 15.0, 20.0):
        raise RuntimeError("RISK_POLICY_POSITION_ALLOWLIST_INVALID")
    symbols = tuple(str(v).upper() for v in (policy.get("allowed_symbols") or []))
    if not symbols:
        raise RuntimeError("RISK_POLICY_SYMBOL_ALLOWLIST_EMPTY")
    return {
        "allowed_leverage_x": allowed_lev,
        "allowed_position_pct": allowed_pos,
        "allowed_symbols": symbols,
        "market_data_stale_ms": _policy_value(policy, "market_data_stale_ms"),
        "account_state_stale_ms": _policy_value(policy, "account_state_stale_ms"),
        "max_dd_day_pct": _policy_value(policy, "max_dd_day_pct"),
        "max_dd_total_pct": _policy_value(policy, "max_dd_total_pct"),
    }


def validate_account_state(account: Mapping[str, Any], *, now_ms: int, max_stale_ms: float) -> dict[str, float]:
    if str(account.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("ACCOUNT_STATE_NON_PAPER_FORBIDDEN")
    if str(account.get("state") or "").upper() not in {"PASS", "PASS_PAPER_ACCOUNT_STATE"}:
        raise RuntimeError("ACCOUNT_STATE_NOT_PASS")
    updated_at_ms = _int(account.get("updated_at_ms"), "account.updated_at_ms")
    age_ms = now_ms - updated_at_ms
    if age_ms < 0:
        raise RuntimeError("ACCOUNT_STATE_FUTURE_TIMESTAMP")
    if age_ms > max_stale_ms:
        raise RuntimeError(f"ACCOUNT_STATE_STALE:{age_ms}")
    equity = _float(account.get("equity_usdt"), "account.equity_usdt")
    available = _float(account.get("available_balance_usdt"), "account.available_balance_usdt")
    dd_day = _float(account.get("dd_day_pct"), "account.dd_day_pct")
    dd_total = _float(account.get("dd_total_pct"), "account.dd_total_pct")
    if equity <= 0 or available < 0:
        raise RuntimeError("ACCOUNT_STATE_BALANCE_INVALID")
    if dd_day < 0 or dd_total < 0:
        raise RuntimeError("ACCOUNT_STATE_DD_INVALID")
    return {
        "equity_usdt": equity,
        "available_balance_usdt": available,
        "dd_day_pct": dd_day,
        "dd_total_pct": dd_total,
        "updated_at_ms": float(updated_at_ms),
        "age_ms": float(age_ms),
    }


def build_risk_sizing(
    authority: Mapping[str, Any],
    market: Mapping[str, Any],
    account: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Create PAPER-only sizing from explicit active-alpha request and fresh state.

    No leverage or position-size default is selected. Missing authority/policy/account
    inputs fail closed rather than silently borrowing research parameters.
    """

    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    cfg = validate_policy(policy)
    if str(authority.get("alpha_state") or "").upper() != "SURVIVOR_ACTIVE":
        raise RuntimeError("RISK_SIZING_REQUIRES_SURVIVOR_ACTIVE")
    if authority.get("research_only") is not False or authority.get("promotion_authority") is not True:
        raise RuntimeError("RISK_SIZING_ALPHA_AUTHORITY_INVALID")
    if authority.get("execution_allowed") is not True or authority.get("runtime_bound") is not True:
        raise RuntimeError("RISK_SIZING_ALPHA_RUNTIME_NOT_BOUND")

    symbol = str(authority.get("symbol") or "").upper()
    signal = str(authority.get("signal") or "").upper()
    if symbol not in cfg["allowed_symbols"]:
        raise RuntimeError(f"RISK_SIZING_SYMBOL_NOT_ALLOWED:{symbol}")
    if signal not in {"LONG", "SHORT", "EXIT", "FLAT"}:
        raise RuntimeError(f"RISK_SIZING_SIGNAL_INVALID:{signal}")

    market_state = str(market.get("state") or "").upper()
    if market_state != "PASS_BINGX_FRESH":
        raise RuntimeError("RISK_SIZING_MARKET_NOT_FRESH")
    if str(market.get("symbol") or "").upper() != symbol:
        raise RuntimeError("RISK_SIZING_MARKET_SYMBOL_MISMATCH")
    market_age_ms = _float(market.get("age_ms"), "market.age_ms")
    if market_age_ms < 0 or market_age_ms > cfg["market_data_stale_ms"]:
        raise RuntimeError("RISK_SIZING_MARKET_STALE")
    reference_price = _float(market.get("reference_price"), "market.reference_price")
    if reference_price <= 0:
        raise RuntimeError("RISK_SIZING_MARKET_PRICE_INVALID")

    account_state = validate_account_state(account, now_ms=now, max_stale_ms=cfg["account_state_stale_ms"])
    if account_state["dd_day_pct"] > cfg["max_dd_day_pct"]:
        raise RuntimeError("RISK_SIZING_DD_DAY_EXCEEDED")
    if account_state["dd_total_pct"] > cfg["max_dd_total_pct"]:
        raise RuntimeError("RISK_SIZING_DD_TOTAL_EXCEEDED")

    request = authority.get("risk_request")
    if not isinstance(request, Mapping):
        raise RuntimeError("RISK_SIZING_REQUEST_MISSING")
    leverage_x = _int(request.get("leverage_x"), "risk_request.leverage_x")
    position_pct = _float(request.get("position_pct"), "risk_request.position_pct")
    if leverage_x not in cfg["allowed_leverage_x"]:
        raise RuntimeError(f"RISK_SIZING_LEVERAGE_NOT_ALLOWED:{leverage_x}")
    if position_pct not in cfg["allowed_position_pct"]:
        raise RuntimeError(f"RISK_SIZING_POSITION_NOT_ALLOWED:{position_pct}")

    # EXIT/FLAT do not create a new exposure. The owner-binding ledger resolves
    # actual close quantity from the open position; no synthetic close qty is made.
    if signal in {"EXIT", "FLAT"}:
        notional = 0.0
        qty = 0.0
    else:
        margin_usdt = account_state["equity_usdt"] * position_pct / 100.0
        if margin_usdt > account_state["available_balance_usdt"] + 1e-12:
            raise RuntimeError("RISK_SIZING_MARGIN_EXCEEDS_AVAILABLE")
        notional = margin_usdt * leverage_x
        qty = notional / reference_price
        if qty <= 0 or not math.isfinite(qty):
            raise RuntimeError("RISK_SIZING_QTY_INVALID")

    receipt = {
        "schema_version": SCHEMA,
        "state": "PASS_PRODUCTION_RISK_SIZING",
        "mode": "PAPER",
        "symbol": symbol,
        "signal": signal,
        "reference_price": reference_price,
        "qty": qty,
        "notional_usdt": notional,
        "leverage_x": leverage_x,
        "position_pct": position_pct,
        "exposure_pct": leverage_x * position_pct,
        "account_state": account_state,
        "market_receipt_sha256": market.get("receipt_sha256"),
        "alpha_authority_receipt_sha256": authority.get("receipt_sha256"),
        "paper_simulated_qty": True,
        "qty_step_live_binding": "NOT_AUTHORIZED_PAPER_SIM_ONLY",
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL canonical PAPER risk+sizing producer")
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--account", type=Path, default=Path(os.environ.get("ZEL_PAPER_ACCOUNT_STATE_PATH", DEFAULT_ACCOUNT_STATE)))
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    authority = _load_json(args.authority, "ALPHA_AUTHORITY")
    market = _load_json(args.market, "MARKET_FRESHNESS")
    account = _load_json(args.account, "ACCOUNT_STATE")
    policy = _load_json(args.policy, "RISK_POLICY")
    receipt = build_risk_sizing(authority, market, account, policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
