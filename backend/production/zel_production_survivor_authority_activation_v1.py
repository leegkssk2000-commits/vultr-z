from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_ai_admission_executor_v2 import SUPPORTED_TEMPLATES
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_survivor_authority_activation.v1"
POLICY_SCHEMA = "zel.production_survivor_authority_activation_policy.v1"
POOL_SCHEMA = "zel.production_survivor_pool.v1"
CANARY_STATE_SCHEMA = "zel.production_family_paper_canary_runner.v1"
CANARY_RESULT_SCHEMA = "zel.production_family_paper_canary_result.v1"
AUTHORITY_SCHEMA = "zel.production_alpha_authority.v1"
DEFAULT_POLICY = Path("config/zel_production_survivor_authority_activation_v1.json")
RUNTIME_SYMBOLS = {"BTCUSDT", "ETHUSDT"}


def _verified_receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"SURVIVOR_ACTIVATION_{label}_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError(f"SURVIVOR_ACTIVATION_{label}_RECEIPT_MISMATCH")
    return claimed


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("SURVIVOR_ACTIVATION_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("SURVIVOR_ACTIVATION_NON_PAPER_FORBIDDEN")
    for key in ("pool_path", "canary_state_path", "authority_path", "state_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"SURVIVOR_ACTIVATION_PATH_MISSING:{key}")
    if policy.get("required_pool_state") != "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2":
        raise RuntimeError("SURVIVOR_ACTIVATION_POOL_GATE_DRIFT")
    if policy.get("active_slot_index") != 0:
        raise RuntimeError("SURVIVOR_ACTIVATION_SLOT_DRIFT")
    if policy.get("selection_rule") != "POOL_RANKED_ACTIVE_SLOT_0_NO_RESELECTION":
        raise RuntimeError("SURVIVOR_ACTIVATION_SELECTION_RULE_DRIFT")
    if policy.get("require_symbol_qualified") is not True:
        raise RuntimeError("SURVIVOR_ACTIVATION_SYMBOL_QUALIFICATION_REQUIRED")
    if policy.get("risk_request") != {"leverage_x": 10, "position_pct": 5.0}:
        raise RuntimeError("SURVIVOR_ACTIVATION_RISK_REQUEST_DRIFT")
    if policy.get("execution_authority") != "PAPER_SIM_ONLY":
        raise RuntimeError("SURVIVOR_ACTIVATION_EXECUTION_AUTHORITY_INVALID")
    if policy.get("order_authority") != "BLOCKED" or policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_ACTIVATION_LIVE_AUTHORITY_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("SURVIVOR_ACTIVATION_MUTATION_FORBIDDEN")
    return dict(policy)


def _hold(reason: str, now_ms: int) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA,
        "state": "HOLD_SURVIVOR_AUTHORITY_NOT_READY",
        "action": "hold",
        "reason": reason,
        "authority_written": False,
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


def _active_candidate(pool: Mapping[str, Any], cfg: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if pool.get("schema_version") != POOL_SCHEMA:
        raise RuntimeError("SURVIVOR_ACTIVATION_POOL_SCHEMA_INVALID")
    pool_receipt = _verified_receipt(pool, "POOL")
    if pool.get("state") != cfg["required_pool_state"]:
        raise RuntimeError("SURVIVOR_ACTIVATION_POOL_NOT_TARGET_READY")
    if int(pool.get("active_count") or 0) != 3 or int(pool.get("reserve_count") or 0) != 2:
        raise RuntimeError("SURVIVOR_ACTIVATION_POOL_3_PLUS_2_INVALID")
    active = pool.get("active")
    reserve = pool.get("reserve")
    if not isinstance(active, list) or len(active) != 3 or not isinstance(reserve, list) or len(reserve) != 2:
        raise RuntimeError("SURVIVOR_ACTIVATION_POOL_ROWS_INVALID")
    families = [str(x.get("family_id") or "") for x in active + reserve if isinstance(x, Mapping)]
    if len(families) != 5 or len(set(families)) != 5 or any(not x for x in families):
        raise RuntimeError("SURVIVOR_ACTIVATION_POOL_FAMILY_DIVERSITY_INVALID")
    raw = active[int(cfg["active_slot_index"])]
    if not isinstance(raw, Mapping):
        raise RuntimeError("SURVIVOR_ACTIVATION_PRIMARY_ROW_INVALID")
    row = dict(raw)
    if row.get("symbol_qualified") is not True:
        raise RuntimeError("SURVIVOR_ACTIVATION_PRIMARY_NOT_SYMBOL_QUALIFIED")
    symbol = str(row.get("runtime_symbol") or "").replace("-", "").upper()
    if symbol not in RUNTIME_SYMBOLS:
        raise RuntimeError("SURVIVOR_ACTIVATION_PRIMARY_SYMBOL_INVALID")
    if str(row.get("strategy_id") or "") not in SUPPORTED_TEMPLATES:
        raise RuntimeError("SURVIVOR_ACTIVATION_PRIMARY_STRATEGY_UNSUPPORTED")
    for key in ("family_id", "strategy_id", "alpha_id", "canary_key", "contract_id"):
        if not str(row.get(key) or "").strip():
            raise RuntimeError(f"SURVIVOR_ACTIVATION_PRIMARY_IDENTITY_MISSING:{key}")
    for key in ("contract_receipt_sha256", "canary_receipt_sha256"):
        if len(str(row.get(key) or "")) != 64:
            raise RuntimeError(f"SURVIVOR_ACTIVATION_PRIMARY_LINEAGE_INVALID:{key}")
    hashes = row.get("source_hashes")
    if not isinstance(hashes, list) or not hashes or any(not str(x).strip() for x in hashes):
        raise RuntimeError("SURVIVOR_ACTIVATION_PRIMARY_SOURCE_HASHES_INVALID")
    if row.get("risk_request") != cfg["risk_request"]:
        raise RuntimeError("SURVIVOR_ACTIVATION_PRIMARY_RISK_REQUEST_MISMATCH")
    return row, pool_receipt


def _verify_canary(candidate: Mapping[str, Any], canary_state: Mapping[str, Any]) -> str:
    if canary_state.get("schema_version") != CANARY_STATE_SCHEMA:
        raise RuntimeError("SURVIVOR_ACTIVATION_CANARY_STATE_SCHEMA_INVALID")
    _verified_receipt(canary_state, "CANARY_STATE")
    rows = canary_state.get("canaries")
    raw = rows.get(str(candidate["canary_key"])) if isinstance(rows, Mapping) else None
    if not isinstance(raw, Mapping) or str(raw.get("status") or "") != "PASS":
        raise RuntimeError("SURVIVOR_ACTIVATION_CANARY_NOT_PASS")
    result = raw.get("result")
    if not isinstance(result, Mapping) or result.get("schema_version") != CANARY_RESULT_SCHEMA or result.get("state") != "PASS_FAMILY_PAPER_CANARY":
        raise RuntimeError("SURVIVOR_ACTIVATION_CANARY_RESULT_INVALID")
    receipt = _verified_receipt(result, "CANARY_RESULT")
    expected = {
        "family_id": candidate["family_id"],
        "strategy_id": candidate["strategy_id"],
        "alpha_id": candidate["alpha_id"],
        "runtime_symbol": candidate["runtime_symbol"],
        "canary_key": candidate["canary_key"],
        "contract_id": candidate["contract_id"],
        "contract_receipt_sha256": candidate["contract_receipt_sha256"],
    }
    for key, value in expected.items():
        left = str(result.get(key) or "").replace("-", "").upper() if key == "runtime_symbol" else str(result.get(key) or "")
        right = str(value or "").replace("-", "").upper() if key == "runtime_symbol" else str(value or "")
        if left != right:
            raise RuntimeError(f"SURVIVOR_ACTIVATION_CANARY_LINEAGE_MISMATCH:{key}")
    if receipt != str(candidate["canary_receipt_sha256"]):
        raise RuntimeError("SURVIVOR_ACTIVATION_CANARY_RECEIPT_MISMATCH")
    if result.get("symbol_qualified") is not True or result.get("prospective_only") is not True or result.get("admission_history_reuse_allowed") is not False:
        raise RuntimeError("SURVIVOR_ACTIVATION_CANARY_QUALIFICATION_INVALID")
    return receipt


def activate_tick(
    policy: Mapping[str, Any],
    *,
    pool: Mapping[str, Any] | None,
    canary_state: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(pool, Mapping):
        return _hold("SURVIVOR_POOL_MISSING", now), None
    if str(pool.get("state") or "") != cfg["required_pool_state"]:
        return _hold(str(pool.get("state") or "SURVIVOR_POOL_NOT_READY"), now), None
    if not isinstance(canary_state, Mapping):
        return _hold("FAMILY_CANARY_STATE_MISSING", now), None

    candidate, pool_receipt = _active_candidate(pool, cfg)
    canary_receipt = _verify_canary(candidate, canary_state)
    symbol = str(candidate["runtime_symbol"]).replace("-", "").upper()
    authority: dict[str, Any] = {
        "schema_version": AUTHORITY_SCHEMA,
        "state": "PASS_SURVIVOR_ACTIVE_AUTHORITY",
        "alpha_state": "SURVIVOR_ACTIVE",
        "family_id": str(candidate["family_id"]),
        "strategy_id": str(candidate["strategy_id"]),
        "alpha_id": str(candidate["alpha_id"]),
        "symbol": symbol,
        "runtime_symbol": symbol,
        "symbol_qualified": True,
        "canary_key": str(candidate["canary_key"]),
        "contract_id": str(candidate["contract_id"]),
        "contract_receipt_sha256": str(candidate["contract_receipt_sha256"]),
        "canary_receipt_sha256": canary_receipt,
        "pool_receipt_sha256": pool_receipt,
        "pool_rank": 0,
        "selection_rule": cfg["selection_rule"],
        "source_hashes": sorted(set(map(str, candidate["source_hashes"]))),
        "risk_request": dict(cfg["risk_request"]),
        "metrics": dict(candidate.get("metrics") or {}),
        "research_only": False,
        "selection_authority": False,
        "promotion_authority": True,
        "execution_allowed": True,
        "runtime_bound": True,
        "runtime_authority": {
            "execution_authority": "PAPER_SIM_ONLY",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "activated_at_ms": now,
    }
    authority["receipt_sha256"] = stable_sha(authority)
    state = {
        "schema_version": SCHEMA,
        "state": "PASS_SURVIVOR_PAPER_AUTHORITY_READY",
        "action": "hold",
        "authority_written": True,
        "family_id": authority["family_id"],
        "strategy_id": authority["strategy_id"],
        "alpha_id": authority["alpha_id"],
        "runtime_symbol": symbol,
        "authority_receipt_sha256": authority["receipt_sha256"],
        "pool_receipt_sha256": pool_receipt,
        "selection_authority": False,
        "promotion_authority": True,
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now,
    }
    state["receipt_sha256"] = stable_sha(state)
    return state, authority


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Activate the frozen primary symbol-qualified survivor into PAPER-only runtime authority")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    policy = read_json(ns.policy, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    state, authority = activate_tick(
        cfg,
        pool=read_json(Path(str(cfg["pool_path"]))),
        canary_state=read_json(Path(str(cfg["canary_state_path"]))),
    )
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if authority is not None:
        atomic_json_write(Path(str(cfg["authority_path"])), authority)
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
