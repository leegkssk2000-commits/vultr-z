from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production import zel_production_survivor_authority_activation_v1 as v1
from backend.production.zel_production_active_alpha_adapter_v1 import authority_is_executable
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = v1.SCHEMA
DEFAULT_POLICY = v1.DEFAULT_POLICY


def _verified_authority(row: Mapping[str, Any]) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError("SURVIVOR_ACTIVATION_V2_EXISTING_AUTHORITY_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError("SURVIVOR_ACTIVATION_V2_EXISTING_AUTHORITY_RECEIPT_MISMATCH")
    return claimed


def activate_tick(
    policy: Mapping[str, Any],
    *,
    pool: Mapping[str, Any] | None,
    canary_state: Mapping[str, Any] | None,
    existing_authority: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = v1.validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if isinstance(existing_authority, Mapping) and authority_is_executable(existing_authority):
        receipt = _verified_authority(existing_authority)
        state = {
            "schema_version": SCHEMA,
            "state": "HOLD_SURVIVOR_AUTHORITY_ALREADY_EXECUTABLE",
            "action": "hold",
            "reason": "KEEP_CURRENT_EXECUTABLE_AUTHORITY_UNTIL_RUNTIME_HEALTH_ROTATION",
            "authority_written": False,
            "family_id": existing_authority.get("family_id"),
            "strategy_id": existing_authority.get("strategy_id"),
            "alpha_id": existing_authority.get("alpha_id"),
            "runtime_symbol": str(existing_authority.get("runtime_symbol") or existing_authority.get("symbol") or "").replace("-", "").upper(),
            "authority_receipt_sha256": receipt,
            "selection_authority": False,
            "promotion_authority": True,
            "execution_authority": "PAPER_SIM_ONLY",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "updated_at_ms": now,
        }
        state["receipt_sha256"] = stable_sha(state)
        return state, None
    return v1.activate_tick(cfg, pool=pool, canary_state=canary_state, now_ms=now)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Idempotent survivor activation; runtime rotation owns replacement of healthy authorities")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    policy = read_json(ns.policy, required=True)
    assert policy is not None
    cfg = v1.validate_policy(policy)
    authority_path = Path(str(cfg["authority_path"]))
    state, authority = activate_tick(
        cfg,
        pool=read_json(Path(str(cfg["pool_path"]))),
        canary_state=read_json(Path(str(cfg["canary_state_path"]))),
        existing_authority=read_json(authority_path),
    )
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if authority is not None:
        atomic_json_write(authority_path, authority)
    print(json.dumps({
        "state": state["state"],
        "authority_written": state["authority_written"],
        "strategy_id": state.get("strategy_id"),
        "runtime_symbol": state.get("runtime_symbol"),
        "receipt_sha256": state["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
