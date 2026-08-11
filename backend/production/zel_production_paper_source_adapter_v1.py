from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_active_alpha_adapter_v1 import (
    DEFAULT_POLICY as DEFAULT_ACTIVE_ALPHA_POLICY,
    authority_is_executable,
    bind_active_alpha,
    read_json as read_active_json,
)
from backend.production.zel_production_bingx_freshness_v1 import fetch_fresh_bingx_quote
from backend.production.zel_production_paper_account_state_v1 import (
    DEFAULT_POLICY as DEFAULT_ACCOUNT_POLICY,
    build_account_state,
    read_json_if_exists,
)
from backend.production.zel_production_risk_sizing_v1 import (
    DEFAULT_POLICY as DEFAULT_RISK_POLICY,
    build_risk_sizing,
    validate_policy as validate_risk_policy,
)

SCHEMA = "zel.production_paper_source_adapter.v2"
INPUT_SCHEMA = "zel.production_paper_input.v1"
DEFAULT_OUTPUT = "/home/zel/apps/zel/ledger/production_paper_input_v1.json"
DEFAULT_ALPHA_AUTHORITY = "/home/zel/apps/zel/ledger/production_alpha_authority_v1.json"

MARKET_DATA_OWNER = {
    "path": "backend/production/zel_production_bingx_freshness_v1.py",
    "symbol": "fetch_fresh_bingx_quote/BingXPublicAdapter",
    "dummy_fallback_allowed": False,
}
RISK_OWNER = {
    "path": "backend/production/zel_production_risk_sizing_v1.py",
    "symbol": "build_risk_sizing",
}
ACCOUNT_OWNER = {
    "path": "backend/production/zel_production_paper_account_state_v1.py",
    "symbol": "build_account_state",
}
ACTIVE_ALPHA_OWNER = {
    "path": "backend/production/zel_production_active_alpha_adapter_v1.py",
    "symbol": "bind_active_alpha",
}


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
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


def _read_authority(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise ValueError("ALPHA_AUTHORITY_MUST_BE_JSON_OBJECT")
    return row


def build_no_validated_alpha_payload(
    *,
    symbol: str = "BTCUSDT",
    authority_state: str = "ALPHA_AUTHORITY_MISSING",
) -> dict[str, Any]:
    """Build a PAPER no-order payload without synthetic market/sizing values."""

    return {
        "schema_version": INPUT_SCHEMA,
        "source_adapter_schema_version": SCHEMA,
        "mode": "PAPER",
        "symbol": symbol,
        "strategy_id": "production.no_validated_alpha",
        "alpha_id": "alpha.none",
        "alpha_state": "NONE",
        "signal": "FLAT",
        "risk_state": "HOLD",
        "market_data_ok": False,
        "cost_model_id": "UNBOUND",
        "source_state": "NO_VALIDATED_ALPHA",
        "authority_state": authority_state,
        "source_owners": {
            "market_data": dict(MARKET_DATA_OWNER),
            "risk_gate": dict(RISK_OWNER),
            "account_state": dict(ACCOUNT_OWNER),
            "active_alpha": dict(ACTIVE_ALPHA_OWNER),
        },
        "exchange_order_submitted": False,
    }


def _load_policy(path: str | Path, label: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"{label}_MISSING:{p}")
    row = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"{label}_NOT_OBJECT")
    return row


def build_payload(
    authority: Mapping[str, Any] | None,
    *,
    symbol: str = "BTCUSDT",
    active_signal: Mapping[str, Any] | None = None,
    market_receipt: Mapping[str, Any] | None = None,
    account_state: Mapping[str, Any] | None = None,
    prior_account_state: Mapping[str, Any] | None = None,
    canonical_snapshot: Mapping[str, Any] | None = None,
    active_policy: Mapping[str, Any] | None = None,
    risk_policy: Mapping[str, Any] | None = None,
    account_policy: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    if authority is None:
        return build_no_validated_alpha_payload(symbol=symbol, authority_state="ALPHA_AUTHORITY_MISSING")

    if not authority_is_executable(authority):
        return build_no_validated_alpha_payload(symbol=symbol, authority_state="ALPHA_AUTHORITY_NON_EXECUTABLE")

    if active_signal is None or active_policy is None or risk_policy is None or account_policy is None:
        raise RuntimeError("ACTIVE_ALPHA_RUNTIME_INPUTS_REQUIRED")
    bound_alpha = bind_active_alpha(authority, active_signal, active_policy, now_ms=now_ms)
    active_symbol = str(bound_alpha["symbol"])

    risk_cfg = validate_risk_policy(risk_policy)
    if market_receipt is None:
        market_receipt = fetch_fresh_bingx_quote(
            active_symbol,
            max_stale_ms=float(risk_cfg["market_data_stale_ms"]),
            now_ms=now_ms,
        )
    if account_state is None:
        account_state = build_account_state(
            policy=account_policy,
            snapshot=canonical_snapshot,
            prior=prior_account_state,
            now_ms=now_ms,
        )
    sizing = build_risk_sizing(
        bound_alpha,
        market_receipt,
        account_state,
        risk_policy,
        now_ms=now_ms,
    )

    cost_model_id = str(bound_alpha.get("cost_model_id") or "").strip()
    if not cost_model_id:
        raise RuntimeError("ACTIVE_ALPHA_COST_MODEL_ID_MISSING")
    strategy_id = str(bound_alpha.get("strategy_id") or "").strip()
    alpha_id = str(bound_alpha.get("alpha_id") or "").strip()
    if not strategy_id or not alpha_id:
        raise RuntimeError("ACTIVE_ALPHA_IDENTITY_MISSING")

    payload = {
        "schema_version": INPUT_SCHEMA,
        "source_adapter_schema_version": SCHEMA,
        "mode": "PAPER",
        "symbol": active_symbol,
        "strategy_id": strategy_id,
        "alpha_id": alpha_id,
        "alpha_state": "SURVIVOR_ACTIVE",
        "signal": str(bound_alpha["signal"]),
        "signal_ts": int(bound_alpha["signal_ts"]),
        "price": float(sizing["reference_price"]),
        "qty": float(sizing["qty"]),
        "risk_state": "PASS",
        "market_data_ok": True,
        "cost_model_id": cost_model_id,
        "source_state": "PROMOTED_ACTIVE_ALPHA",
        "authority_state": "SURVIVOR_ACTIVE_RUNTIME_BOUND",
        "event_id": str(bound_alpha.get("receipt_sha256") or ""),
        "decision_id": str(sizing.get("receipt_sha256") or ""),
        "alpha": {
            "allowed": True,
            "source_hashes": list(bound_alpha.get("source_hashes") or []),
            "authority_receipt_sha256": bound_alpha.get("receipt_sha256"),
        },
        "risk": {
            "leverage_x": int(sizing["leverage_x"]),
            "position_pct": float(sizing["position_pct"]),
            "notional_usdt": float(sizing["notional_usdt"]),
            "exposure_pct": float(sizing["exposure_pct"]),
            "receipt_sha256": sizing.get("receipt_sha256"),
        },
        "market": {
            "provider": market_receipt.get("provider"),
            "source_timestamp_ms": market_receipt.get("source_timestamp_ms"),
            "age_ms": market_receipt.get("age_ms"),
            "spread_bps": market_receipt.get("spread_bps"),
            "receipt_sha256": market_receipt.get("receipt_sha256"),
        },
        "account": {
            "equity_usdt": account_state.get("equity_usdt"),
            "dd_day_pct": account_state.get("dd_day_pct"),
            "dd_total_pct": account_state.get("dd_total_pct"),
            "receipt_sha256": account_state.get("receipt_sha256"),
        },
        "source_owners": {
            "market_data": dict(MARKET_DATA_OWNER),
            "risk_gate": dict(RISK_OWNER),
            "account_state": dict(ACCOUNT_OWNER),
            "active_alpha": dict(ACTIVE_ALPHA_OWNER),
        },
        "exchange_order_submitted": False,
    }
    return payload


class CanonicalPaperSourceAdapter:
    def __init__(
        self,
        authority_path: str | Path = DEFAULT_ALPHA_AUTHORITY,
        output_path: str | Path = DEFAULT_OUTPUT,
        *,
        symbol: str = "BTCUSDT",
        active_policy_path: str | Path = DEFAULT_ACTIVE_ALPHA_POLICY,
        risk_policy_path: str | Path = DEFAULT_RISK_POLICY,
        account_policy_path: str | Path = DEFAULT_ACCOUNT_POLICY,
    ) -> None:
        self.authority_path = Path(authority_path)
        self.output_path = Path(output_path)
        self.symbol = symbol
        self.active_policy_path = Path(active_policy_path)
        self.risk_policy_path = Path(risk_policy_path)
        self.account_policy_path = Path(account_policy_path)

    def build(self) -> dict[str, Any]:
        authority = _read_authority(self.authority_path)
        if authority is None or not authority_is_executable(authority):
            return build_payload(authority, symbol=self.symbol)

        active_policy = _load_policy(self.active_policy_path, "ACTIVE_ALPHA_POLICY")
        risk_policy = _load_policy(self.risk_policy_path, "RISK_POLICY")
        account_policy = _load_policy(self.account_policy_path, "ACCOUNT_POLICY")
        signal_path = active_policy.get("signal_path")
        if not signal_path:
            raise RuntimeError("ACTIVE_ALPHA_SIGNAL_PATH_UNBOUND")
        active_signal = read_active_json(signal_path, "ACTIVE_ALPHA_SIGNAL")
        snapshot_path = Path(str(account_policy.get("canonical_snapshot_path")))
        state_path = Path(str(account_policy.get("account_state_path")))
        canonical_snapshot = read_json_if_exists(snapshot_path)
        prior_account = read_json_if_exists(state_path)
        account_state = build_account_state(
            policy=account_policy,
            snapshot=canonical_snapshot,
            prior=prior_account,
        )
        _atomic_json_write(state_path, account_state)
        return build_payload(
            authority,
            symbol=self.symbol,
            active_signal=active_signal,
            account_state=account_state,
            active_policy=active_policy,
            risk_policy=risk_policy,
            account_policy=account_policy,
        )

    def write(self) -> dict[str, Any]:
        payload = self.build()
        _atomic_json_write(self.output_path, payload)
        return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL fail-closed PAPER source adapter")
    parser.add_argument("--authority", type=Path, default=Path(os.environ.get("ZEL_PRODUCTION_ALPHA_AUTHORITY_PATH", DEFAULT_ALPHA_AUTHORITY)))
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("ZEL_PRODUCTION_PAPER_INPUT_PATH", DEFAULT_OUTPUT)))
    parser.add_argument("--symbol", default=os.environ.get("ZEL_PRODUCTION_IDLE_SYMBOL", "BTCUSDT"))
    parser.add_argument("--active-policy", type=Path, default=DEFAULT_ACTIVE_ALPHA_POLICY)
    parser.add_argument("--risk-policy", type=Path, default=DEFAULT_RISK_POLICY)
    parser.add_argument("--account-policy", type=Path, default=DEFAULT_ACCOUNT_POLICY)
    args = parser.parse_args(argv)

    payload = CanonicalPaperSourceAdapter(
        args.authority,
        args.output,
        symbol=args.symbol,
        active_policy_path=args.active_policy,
        risk_policy_path=args.risk_policy,
        account_policy_path=args.account_policy,
    ).write()
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
