from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production import zel_production_family_paper_canary_runner_v1 as canary_v1
from backend.production import zel_production_family_paper_canary_runner_v2 as canary_v2
from backend.production.zel_production_active_alpha_adapter_v1 import authority_is_executable
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha
from backend.production.zel_production_survivor_authority_activation_v1 import _verify_canary

SCHEMA = "zel.production_survivor_runtime_health.v1"
RESULT_SCHEMA = "zel.production_survivor_runtime_health_result.v1"
POLICY_SCHEMA = "zel.production_survivor_runtime_health_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_survivor_runtime_health_v1.json")
RUNTIME_SYMBOLS = {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT"}


def _receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"SURVIVOR_HEALTH_{label}_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError(f"SURVIVOR_HEALTH_{label}_RECEIPT_MISMATCH")
    return claimed


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("SURVIVOR_HEALTH_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("SURVIVOR_HEALTH_NON_PAPER_FORBIDDEN")
    for key in (
        "authority_path",
        "canary_state_path",
        "l2_snapshot_path",
        "carry_snapshot_path",
        "history_dir",
        "state_path",
        "result_path",
    ):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"SURVIVOR_HEALTH_PATH_MISSING:{key}")
    if list(map(str, policy.get("windows") or [])) != ["W1", "W2", "W3"]:
        raise RuntimeError("SURVIVOR_HEALTH_WINDOWS_DRIFT")
    if int(policy.get("trades_per_window") or 0) != 60:
        raise RuntimeError("SURVIVOR_HEALTH_TRADES_PER_WINDOW_DRIFT")
    if policy.get("contract_source") != "ORIGINAL_SYMBOL_QUALIFIED_CANARY_SURVIVOR_CONTRACT":
        raise RuntimeError("SURVIVOR_HEALTH_CONTRACT_SOURCE_DRIFT")
    if policy.get("prospective_only") is not True:
        raise RuntimeError("SURVIVOR_HEALTH_PROSPECTIVE_ONLY_REQUIRED")
    if policy.get("canary_history_reuse_allowed") is not False or policy.get("admission_history_reuse_allowed") is not False:
        raise RuntimeError("SURVIVOR_HEALTH_HISTORY_REUSE_FORBIDDEN")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("SURVIVOR_HEALTH_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_HEALTH_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_HEALTH_LIVE_FORBIDDEN")
    return dict(policy)


def _hold(reason: str, now_ms: int) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA,
        "state": "HOLD_SURVIVOR_RUNTIME_HEALTH",
        "status": "HOLD",
        "action": "hold",
        "reason": reason,
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


def _authority_start_ms(authority: Mapping[str, Any]) -> int:
    for key in ("activated_at_ms", "promoted_at_ms"):
        try:
            value = int(authority.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    raise RuntimeError("SURVIVOR_HEALTH_AUTHORITY_START_MISSING")


def _authority_identity(authority: Mapping[str, Any]) -> dict[str, str]:
    if not authority_is_executable(authority):
        raise RuntimeError("SURVIVOR_HEALTH_AUTHORITY_NOT_EXECUTABLE")
    receipt = _receipt(authority, "AUTHORITY")
    symbol = str(authority.get("runtime_symbol") or authority.get("symbol") or "").replace("-", "").upper()
    if symbol not in RUNTIME_SYMBOLS:
        raise RuntimeError("SURVIVOR_HEALTH_SYMBOL_INVALID")
    out = {
        "authority_receipt_sha256": receipt,
        "family_id": str(authority.get("family_id") or ""),
        "strategy_id": str(authority.get("strategy_id") or ""),
        "alpha_id": str(authority.get("alpha_id") or ""),
        "runtime_symbol": symbol,
        "canary_key": str(authority.get("canary_key") or ""),
        "contract_id": str(authority.get("contract_id") or ""),
        "contract_receipt_sha256": str(authority.get("contract_receipt_sha256") or ""),
    }
    if any(not value for key, value in out.items() if key != "authority_receipt_sha256"):
        raise RuntimeError("SURVIVOR_HEALTH_AUTHORITY_LINEAGE_INCOMPLETE")
    if len(out["contract_receipt_sha256"]) != 64:
        raise RuntimeError("SURVIVOR_HEALTH_CONTRACT_RECEIPT_INVALID")
    return out


def _state_valid(state: Mapping[str, Any]) -> None:
    if state.get("schema_version") != SCHEMA:
        raise RuntimeError("SURVIVOR_HEALTH_STATE_SCHEMA_INVALID")
    _receipt(state, "STATE")
    if state.get("order_authority") != "BLOCKED" or state.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_HEALTH_STATE_LIVE_FORBIDDEN")


def _epoch_state(
    identity: Mapping[str, str],
    *,
    epoch_index: int,
    not_before_ms: int,
    history_dir: Path,
    now_ms: int,
) -> dict[str, Any]:
    health_key = stable_sha({
        "authority_receipt_sha256": identity["authority_receipt_sha256"],
        "epoch_index": epoch_index,
        "not_before_ms": not_before_ms,
    })[:32]
    row = {
        "schema_version": SCHEMA,
        "state": "HOLD_SURVIVOR_RUNTIME_HEALTH_ACCUMULATING",
        "status": "ACCUMULATING",
        "action": "hold",
        "health_key": health_key,
        "epoch_index": epoch_index,
        "epoch_not_before_ms": not_before_ms,
        "history_path": str(history_dir / f"{health_key}.ndjson"),
        **dict(identity),
        "trade_count": 0,
        "required_trade_count": 180,
        "observation_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "created_at_ms": now_ms,
        "updated_at_ms": now_ms,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def _resolve_epoch(
    authority: Mapping[str, Any],
    identity: Mapping[str, str],
    existing_state: Mapping[str, Any] | None,
    history_dir: Path,
    now_ms: int,
) -> dict[str, Any]:
    start = _authority_start_ms(authority)
    if not isinstance(existing_state, Mapping):
        return _epoch_state(identity, epoch_index=0, not_before_ms=start, history_dir=history_dir, now_ms=now_ms)
    _state_valid(existing_state)
    if str(existing_state.get("authority_receipt_sha256") or "") != identity["authority_receipt_sha256"]:
        return _epoch_state(identity, epoch_index=0, not_before_ms=start, history_dir=history_dir, now_ms=now_ms)
    status = str(existing_state.get("status") or "")
    if status == "REJECT":
        return dict(existing_state)
    if status == "PASS":
        last_observed = int(existing_state.get("last_observed_at_ms") or existing_state.get("completed_at_ms") or now_ms)
        return _epoch_state(
            identity,
            epoch_index=int(existing_state.get("epoch_index") or 0) + 1,
            not_before_ms=last_observed + 1,
            history_dir=history_dir,
            now_ms=now_ms,
        )
    if status != "ACCUMULATING":
        raise RuntimeError("SURVIVOR_HEALTH_STATE_STATUS_INVALID")
    return dict(existing_state)


def _health_meta(
    epoch: Mapping[str, Any],
    authority: Mapping[str, Any],
    canary_state: Mapping[str, Any],
) -> dict[str, Any]:
    _verify_canary(authority, canary_state)
    rows = canary_state.get("canaries")
    source = rows.get(str(authority.get("canary_key") or "")) if isinstance(rows, Mapping) else None
    if not isinstance(source, Mapping) or str(source.get("status") or "") != "PASS":
        raise RuntimeError("SURVIVOR_HEALTH_CANARY_META_NOT_PASS")
    meta = dict(source)
    for key in ("contract", "template", "survivor_contract", "risk_request"):
        if not isinstance(meta.get(key), Mapping):
            raise RuntimeError(f"SURVIVOR_HEALTH_CANARY_META_MISSING:{key}")
    meta["canary_key"] = str(epoch["health_key"])
    meta["first_not_before_ms"] = int(epoch["epoch_not_before_ms"])
    meta["first_request_id"] = f"runtime-health:{epoch['health_key']}"
    meta["history_path"] = str(epoch["history_path"])
    meta["initial_lineage"] = {
        "authority_receipt_sha256": str(epoch["authority_receipt_sha256"]),
        "original_canary_receipt_sha256": str(authority.get("canary_receipt_sha256") or ""),
        "contract_receipt_sha256": str(authority.get("contract_receipt_sha256") or ""),
    }
    return meta


def tick(
    policy: Mapping[str, Any],
    *,
    authority: Mapping[str, Any] | None,
    canary_state: Mapping[str, Any] | None,
    l2_snapshot: Mapping[str, Any] | None,
    carry_snapshot: Mapping[str, Any] | None,
    existing_state: Mapping[str, Any] | None,
    history: Sequence[Mapping[str, Any]],
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    now_ms: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(authority, Mapping) or not authority_is_executable(authority):
        return _hold("NO_EXECUTABLE_SURVIVOR_AUTHORITY", now), [], None
    if not isinstance(canary_state, Mapping):
        return _hold("SYMBOL_QUALIFIED_CANARY_STATE_MISSING", now), [], None

    identity = _authority_identity(authority)
    epoch = _resolve_epoch(authority, identity, existing_state, Path(str(cfg["history_dir"])), now)
    if str(epoch.get("status") or "") == "REJECT":
        return epoch, [], None
    meta = _health_meta(epoch, authority, canary_state)
    verified = canary_v1._verify_history(list(history), meta)
    native_symbol = RUNTIME_SYMBOLS[identity["runtime_symbol"]]
    new_rows = canary_v1._new_observations(
        meta,
        verified,
        l2_snapshot,
        carry_snapshot,
        candles_by_symbol,
        [native_symbol],
    )
    merged = canary_v1._verify_history(verified + new_rows, meta)
    trades = canary_v1._trade_rows(
        merged,
        canary_v1._f(meta.get("execution_cost_bps"), "execution_cost_bps"),
        meta["risk_request"],
    )
    symbol_trades = [row for row in trades if str(row.get("symbol") or "") == native_symbol]
    survivor_contract = canary_v1._survivor_contract(meta["survivor_contract"])
    evaluation = canary_v2._symbol_eval(
        symbol_trades,
        trades_per_window=int(cfg["trades_per_window"]),
        frozen_contract=survivor_contract,
    )
    state = dict(epoch)
    state.update({
        "trade_count": int(evaluation["trade_count"]),
        "required_trade_count": int(evaluation["required_trade_count"]),
        "observation_count": len(merged),
        "last_observed_at_ms": max([int(x.get("observed_at_ms") or 0) for x in merged] or [int(state["epoch_not_before_ms"])]),
        "updated_at_ms": now,
    })
    if evaluation["state"] == "PENDING_SYMBOL_SAMPLE":
        state["state"] = "HOLD_SURVIVOR_RUNTIME_HEALTH_ACCUMULATING"
        state["status"] = "ACCUMULATING"
        state["receipt_sha256"] = stable_sha({k: v for k, v in state.items() if k != "receipt_sha256"})
        return state, new_rows, None

    passed = evaluation["state"] == "PASS_SYMBOL_PAPER_CANARY"
    result = {
        "schema_version": RESULT_SCHEMA,
        "state": "PASS_SURVIVOR_RUNTIME_HEALTH" if passed else "REJECT_SURVIVOR_RUNTIME_HEALTH",
        "health_key": state["health_key"],
        "epoch_index": state["epoch_index"],
        "epoch_not_before_ms": state["epoch_not_before_ms"],
        **identity,
        "original_canary_receipt_sha256": str(authority.get("canary_receipt_sha256") or ""),
        "symbol_qualified": True,
        "economic_gate_pass": bool(evaluation.get("economic_gate_pass")),
        "durability_gate_pass": bool(evaluation.get("durability_gate_pass")),
        "integrity_pass": bool(evaluation.get("integrity_pass")),
        "windows": evaluation.get("windows"),
        "metrics": evaluation.get("metrics"),
        "source_hashes": canary_v1._source_hashes(merged, meta),
        "prospective_only": True,
        "canary_history_reuse_allowed": False,
        "admission_history_reuse_allowed": False,
        "contract_source": cfg["contract_source"],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "completed_at_ms": now,
    }
    result["receipt_sha256"] = stable_sha(result)
    state.update({
        "state": result["state"],
        "status": "PASS" if passed else "REJECT",
        "terminal_result_receipt_sha256": result["receipt_sha256"],
        "completed_at_ms": now,
    })
    state["receipt_sha256"] = stable_sha({k: v for k, v in state.items() if k != "receipt_sha256"})
    return state, new_rows, result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Post-activation prospective runtime health monitor for symbol-qualified survivors")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    policy = read_json(ns.policy, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    authority = read_json(Path(str(cfg["authority_path"])))
    existing = read_json(Path(str(cfg["state_path"])))
    history: list[dict[str, Any]] = []
    candles: dict[str, list[dict[str, Any]]] = {}
    if isinstance(authority, Mapping) and authority_is_executable(authority):
        identity = _authority_identity(authority)
        epoch = _resolve_epoch(authority, identity, existing, Path(str(cfg["history_dir"])), int(time.time() * 1000))
        history = canary_v1.read_history(Path(str(epoch["history_path"])))
        candles = asyncio.run(canary_v1._fetch_candles([RUNTIME_SYMBOLS[identity["runtime_symbol"]]]))
    state, appends, result = tick(
        cfg,
        authority=authority,
        canary_state=read_json(Path(str(cfg["canary_state_path"]))),
        l2_snapshot=read_json(Path(str(cfg["l2_snapshot_path"]))),
        carry_snapshot=read_json(Path(str(cfg["carry_snapshot_path"]))),
        existing_state=existing,
        history=history,
        candles_by_symbol=candles,
    )
    if appends:
        canary_v1.append_observations(Path(str(state["history_path"])), appends)
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if result is not None:
        atomic_json_write(Path(str(cfg["result_path"])), result)
    print(json.dumps({
        "state": state["state"],
        "status": state["status"],
        "trade_count": state.get("trade_count"),
        "required_trade_count": state.get("required_trade_count"),
        "runtime_symbol": state.get("runtime_symbol"),
        "receipt_sha256": state["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
