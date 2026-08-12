from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_survivor_pool_refill_bridge.v1"
BOOTSTRAP_SCHEMA = "zel.production_performance_bootstrap.v1"
POOL_SCHEMA = "zel.production_survivor_pool.v1"
ORIGINAL_BOOTSTRAP_PATH = Path("/home/z/z/ledger/production_performance_bootstrap_state_v1.json")
POOL_PATH = Path("/home/z/z/ledger/production_survivor_pool_v1.json")
EFFECTIVE_BOOTSTRAP_PATH = Path("/home/z/z/ledger/production_edge_bootstrap_demand_v1.json")
STATE_PATH = Path("/home/z/z/ledger/production_survivor_pool_refill_bridge_v1.json")
ACTIVE_TARGET = 3
RESERVE_TARGET = 2


def _receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"SURVIVOR_REFILL_{label}_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError(f"SURVIVOR_REFILL_{label}_RECEIPT_MISMATCH")
    return claimed


def _validate_bootstrap(row: Mapping[str, Any]) -> dict[str, Any]:
    if row.get("schema_version") != BOOTSTRAP_SCHEMA:
        raise RuntimeError("SURVIVOR_REFILL_BOOTSTRAP_SCHEMA_INVALID")
    if row.get("order_authority") != "BLOCKED" or row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_REFILL_BOOTSTRAP_LIVE_AUTHORITY_INVALID")
    if row.get("exchange_order_submitted") is not False:
        raise RuntimeError("SURVIVOR_REFILL_BOOTSTRAP_ORDER_STATE_INVALID")
    return dict(row)


def _pool_deficit(pool: Mapping[str, Any]) -> dict[str, Any]:
    if pool.get("schema_version") != POOL_SCHEMA:
        raise RuntimeError("SURVIVOR_REFILL_POOL_SCHEMA_INVALID")
    pool_receipt = _receipt(pool, "POOL")
    if pool.get("order_authority") != "BLOCKED" or pool.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_REFILL_POOL_LIVE_AUTHORITY_INVALID")
    if pool.get("exchange_order_submitted") is not False:
        raise RuntimeError("SURVIVOR_REFILL_POOL_ORDER_STATE_INVALID")
    active_target = int(pool.get("active_target") or 0)
    reserve_target = int(pool.get("reserve_target") or 0)
    active_count = int(pool.get("active_count") or 0)
    reserve_count = int(pool.get("reserve_count") or 0)
    if active_target != ACTIVE_TARGET or reserve_target != RESERVE_TARGET:
        raise RuntimeError("SURVIVOR_REFILL_POOL_TARGET_DRIFT")
    if not 0 <= active_count <= active_target or not 0 <= reserve_count <= reserve_target:
        raise RuntimeError("SURVIVOR_REFILL_POOL_COUNT_INVALID")
    deficit = (active_target - active_count) + (reserve_target - reserve_count)
    state = str(pool.get("state") or "")
    if state == "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2" and deficit != 0:
        raise RuntimeError("SURVIVOR_REFILL_POOL_PASS_COUNT_MISMATCH")
    if state == "HOLD_SURVIVOR_POOL_BUILDING" and deficit == 0:
        raise RuntimeError("SURVIVOR_REFILL_POOL_HOLD_COUNT_MISMATCH")
    if state not in {"PASS_SURVIVOR_POOL_TARGET_3_PLUS_2", "HOLD_SURVIVOR_POOL_BUILDING"}:
        raise RuntimeError(f"SURVIVOR_REFILL_POOL_STATE_INVALID:{state or 'MISSING'}")
    return {
        "required": deficit > 0,
        "deficit_count": deficit,
        "active_target": active_target,
        "reserve_target": reserve_target,
        "active_count": active_count,
        "reserve_count": reserve_count,
        "pool_state": state,
        "pool_receipt_sha256": pool_receipt,
        "quarantine_receipt_sha256": pool.get("quarantine_receipt_sha256"),
    }


def _effective_missing(now_ms: int) -> dict[str, Any]:
    row = {
        "schema_version": BOOTSTRAP_SCHEMA,
        "state": "HOLD_BOOTSTRAP_EFFECTIVE_INPUT_MISSING",
        "action": "hold",
        "reason": "ORIGINAL_BOOTSTRAP_STATE_NOT_AVAILABLE",
        "pool_refill_required": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now_ms,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def bridge_tick(
    bootstrap: Mapping[str, Any] | None,
    pool: Mapping[str, Any] | None,
    *,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(bootstrap, Mapping):
        effective = _effective_missing(now)
        state = {
            "schema_version": SCHEMA,
            "state": "HOLD_SURVIVOR_POOL_REFILL_BOOTSTRAP_MISSING",
            "action": "hold",
            "reason": "ORIGINAL_BOOTSTRAP_STATE_NOT_AVAILABLE",
            "refill_required": False,
            "effective_bootstrap_state": effective["state"],
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "updated_at_ms": now,
        }
        state["receipt_sha256"] = stable_sha(state)
        return state, effective

    original = _validate_bootstrap(bootstrap)
    if not isinstance(pool, Mapping):
        effective = dict(original)
        state = {
            "schema_version": SCHEMA,
            "state": "HOLD_SURVIVOR_POOL_REFILL_POOL_NOT_MATERIALIZED",
            "action": "hold",
            "reason": "SURVIVOR_POOL_NOT_AVAILABLE_KEEP_ORIGINAL_BOOTSTRAP_DEMAND",
            "refill_required": False,
            "original_bootstrap_state": original.get("state"),
            "effective_bootstrap_state": effective.get("state"),
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "updated_at_ms": now,
        }
        state["receipt_sha256"] = stable_sha(state)
        return state, effective

    deficit = _pool_deficit(pool)
    if not deficit["required"]:
        effective = dict(original)
        state_name = "PASS_SURVIVOR_POOL_REFILL_TARGET_SATISFIED"
        reason = "SURVIVOR_POOL_3_PLUS_2_COMPLETE_KEEP_ORIGINAL_BOOTSTRAP_DEMAND"
    else:
        effective = {
            "schema_version": BOOTSTRAP_SCHEMA,
            "state": "HOLD_BOOTSTRAP_ROUTE_CHANGE",
            "action": "route_change",
            "reason": "SURVIVOR_POOL_REFILL_REQUIRED",
            "pool_refill_required": True,
            "pool_refill_deficit_count": deficit["deficit_count"],
            "pool_active_count": deficit["active_count"],
            "pool_reserve_count": deficit["reserve_count"],
            "pool_active_target": deficit["active_target"],
            "pool_reserve_target": deficit["reserve_target"],
            "pool_receipt_sha256": deficit["pool_receipt_sha256"],
            "quarantine_receipt_sha256": deficit["quarantine_receipt_sha256"],
            "original_bootstrap_state": original.get("state"),
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "updated_at_ms": now,
        }
        effective["receipt_sha256"] = stable_sha(effective)
        state_name = "PASS_SURVIVOR_POOL_REFILL_DEMAND_ROUTED"
        reason = "POOL_DEFICIT_FORCES_EXISTING_BOUNDED_EDGE_ACQUISITION"

    state = {
        "schema_version": SCHEMA,
        "state": state_name,
        "action": "route_change" if deficit["required"] else "hold",
        "reason": reason,
        "refill_required": bool(deficit["required"]),
        "deficit_count": int(deficit["deficit_count"]),
        "active_count": int(deficit["active_count"]),
        "reserve_count": int(deficit["reserve_count"]),
        "active_target": int(deficit["active_target"]),
        "reserve_target": int(deficit["reserve_target"]),
        "pool_receipt_sha256": deficit["pool_receipt_sha256"],
        "quarantine_receipt_sha256": deficit["quarantine_receipt_sha256"],
        "original_bootstrap_state": original.get("state"),
        "effective_bootstrap_state": effective.get("state"),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "updated_at_ms": now,
    }
    state["receipt_sha256"] = stable_sha(state)
    return state, effective


def main() -> int:
    state, effective = bridge_tick(
        read_json(ORIGINAL_BOOTSTRAP_PATH),
        read_json(POOL_PATH),
    )
    atomic_json_write(EFFECTIVE_BOOTSTRAP_PATH, effective)
    atomic_json_write(STATE_PATH, state)
    print(json.dumps({
        "state": state["state"],
        "refill_required": state["refill_required"],
        "deficit_count": state.get("deficit_count"),
        "original_bootstrap_state": state.get("original_bootstrap_state"),
        "effective_bootstrap_state": state["effective_bootstrap_state"],
        "receipt_sha256": state["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
