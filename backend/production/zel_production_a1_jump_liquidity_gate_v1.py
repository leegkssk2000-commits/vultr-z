from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production.zel_production_improvement_controller_v1 import stable_sha

SCHEMA = "zel.production_a1_jump_liquidity_gate.v1"
POLICY_SCHEMA = "zel.production_a1_jump_liquidity_autopsy_policy.v1"
HISTORY_SCHEMA = "zel.production_bingx_l2_prospective.v1"
SUMMARY_SCHEMA = "zel.production_bingx_l2_prospective_summary.v1"
DEFAULT_POLICY = Path("config/zel_production_a1_jump_liquidity_autopsy_v1.json")
EXPECTED_SOURCES = ["l2_order_book", "ohlcv", "volume"]


def _authority_guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")
    if row.get("exchange_order_submitted") not in (None, False):
        raise RuntimeError(f"{prefix}_EXCHANGE_ORDER_FORBIDDEN")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("A1_JUMP_LIQUIDITY_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("A1_JUMP_LIQUIDITY_NON_PAPER_FORBIDDEN")
    if policy.get("role") != "A1_STRATEGY_AUTOPSY_AND_SOURCE_GATE_NOT_STRATEGY_ROUTE":
        raise RuntimeError("A1_JUMP_LIQUIDITY_ROLE_DRIFT")
    if policy.get("family_id") != "jump_liquidity_state_switch":
        raise RuntimeError("A1_JUMP_LIQUIDITY_FAMILY_DRIFT")
    if policy.get("architecture_result") != "PRE_REGISTERED_NOT_EVALUATED":
        raise RuntimeError("A1_JUMP_LIQUIDITY_ARCHITECTURE_RESULT_INVALID")
    if sorted(map(str, policy.get("required_sources_exact") or [])) != EXPECTED_SOURCES:
        raise RuntimeError("A1_JUMP_LIQUIDITY_REQUIRED_SOURCES_INVALID")
    required_text = (
        "mechanism", "entry_event", "direction_rule", "horizon", "regime_owner",
        "invalidation", "exit_logic", "time_stop", "turnover_cost_budget",
        "symbol_side_scope", "risk_geometry", "execution_assumptions", "falsification_test",
    )
    for key in required_text:
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"A1_JUMP_LIQUIDITY_AUTOPSY_FIELD_MISSING:{key}")
    evidence = policy.get("evidence_ids")
    failures = policy.get("failure_modes")
    if not isinstance(evidence, list) or len(evidence) < 2:
        raise RuntimeError("A1_JUMP_LIQUIDITY_EVIDENCE_MISSING")
    if not isinstance(failures, list) or not failures:
        raise RuntimeError("A1_JUMP_LIQUIDITY_FAILURE_MODES_MISSING")
    for key in ("history_path", "history_summary_path", "output_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"A1_JUMP_LIQUIDITY_PATH_MISSING:{key}")
    if policy.get("admission_state") != "HOLD_ADMISSION_TEMPLATE_REQUIRED" or policy.get("admission_template_id") is not None:
        raise RuntimeError("A1_JUMP_LIQUIDITY_ADMISSION_PREMATURE")
    if policy.get("numeric_signal_thresholds") != [] or policy.get("parameter_search") is not False:
        raise RuntimeError("A1_JUMP_LIQUIDITY_PARAMETER_SEARCH_FORBIDDEN")
    if policy.get("economic_replay_allowed") is not False or policy.get("economic_signal_enabled") is not False:
        raise RuntimeError("A1_JUMP_LIQUIDITY_ECONOMIC_REPLAY_FORBIDDEN")
    _authority_guard(policy, "A1_JUMP_LIQUIDITY_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("A1_JUMP_LIQUIDITY_MUTATION_FORBIDDEN")
    return dict(policy)


def _load_recent_jsonl(path: Path, max_lines: int = 512) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, Mapping):
            rows.append(dict(raw))
    return rows


def _book_valid(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for row in value:
        if not isinstance(row, list) or len(row) < 2:
            return False
        try:
            price, qty = float(row[0]), float(row[1])
        except (TypeError, ValueError, OverflowError):
            return False
        if price <= 0 or qty < 0:
            return False
    return True


def _row_valid(row: Mapping[str, Any]) -> bool:
    if row.get("schema_version") != HISTORY_SCHEMA:
        return False
    if row.get("provider") != "BINGX_PUBLIC_USDT_PERPETUAL":
        return False
    if row.get("economic_signal_enabled") is not False or row.get("history_gate_decision") != "UNSET_BY_COLLECTOR":
        return False
    try:
        _authority_guard(row, "A1_JUMP_LIQUIDITY_HISTORY")
    except RuntimeError:
        return False
    klines = row.get("klines")
    if not isinstance(klines, list) or not klines:
        return False
    latest = klines[-1]
    if not isinstance(latest, Mapping) or not {"time_ms", "open", "high", "low", "close", "volume"}.issubset(latest):
        return False
    l2 = row.get("l2")
    if not isinstance(l2, Mapping) or not _book_valid(l2.get("bids")) or not _book_valid(l2.get("asks")):
        return False
    try:
        best_bid = float(l2["bids"][0][0])
        best_ask = float(l2["asks"][0][0])
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return False
    return best_bid > 0 and best_ask >= best_bid


def evaluate_gate(
    policy: Mapping[str, Any],
    *,
    history_rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    base = {
        "schema_version": SCHEMA,
        "family_id": cfg["family_id"],
        "role": cfg["role"],
        "action": "hold",
        "architecture_result": "PRE_REGISTERED_NOT_EVALUATED",
        "required_sources_exact": list(cfg["required_sources_exact"]),
        "evidence_ids": list(cfg["evidence_ids"]),
        "falsification_test": cfg["falsification_test"],
        "admission_state": "HOLD_ADMISSION_TEMPLATE_REQUIRED",
        "admission_template_id": None,
        "source_ready": False,
        "template_ready": False,
        "economic_replay_allowed": False,
        "economic_signal_enabled": False,
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
    if not isinstance(summary, Mapping) or summary.get("schema_version") != SUMMARY_SCHEMA:
        out = dict(base)
        out.update({"state": "HOLD_A1_JUMP_LIQUIDITY_HISTORY_SUMMARY_MISSING", "blockers": ["PROSPECTIVE_HISTORY_SUMMARY_MISSING"]})
        out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
        return out
    try:
        _authority_guard(summary, "A1_JUMP_LIQUIDITY_SUMMARY")
    except RuntimeError:
        out = dict(base)
        out.update({"state": "HOLD_A1_JUMP_LIQUIDITY_HISTORY_SUMMARY_UNSAFE", "blockers": ["PROSPECTIVE_HISTORY_SUMMARY_AUTHORITY_DRIFT"]})
        out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
        return out
    buckets = [int(row.get("capture_bucket_ms") or 0) for row in history_rows if isinstance(row, Mapping)]
    latest_bucket = max(buckets, default=0)
    latest_rows = [dict(row) for row in history_rows if isinstance(row, Mapping) and int(row.get("capture_bucket_ms") or 0) == latest_bucket]
    by_symbol = {str(row.get("symbol") or ""): row for row in latest_rows if _row_valid(row)}
    required_symbols = {"BTC-USDT", "ETH-USDT"}
    transport_ready = required_symbols.issubset(by_symbol)
    source_context = {
        "schema_version": "zel.production_a1_jump_liquidity_source_context.v1",
        "family_id": cfg["family_id"],
        "ohlcv_transport_bound": transport_ready,
        "volume_transport_bound": transport_ready,
        "l2_order_book_transport_bound": transport_ready,
        "ohlcv_source_bound": transport_ready,
        "volume_source_bound": transport_ready,
        "l2_order_book_source_bound": False,
        "history_coverage_bound": False,
        "prospective_history_started": bool(summary.get("prospective_history_started")) and latest_bucket > 0,
        "history_gate_decision": str(summary.get("history_gate_decision") or "UNSET_BY_COLLECTOR"),
        "latest_capture_bucket_ms": latest_bucket or None,
        "latest_symbols": sorted(by_symbol),
        "observation_count_by_symbol": dict(summary.get("observation_count_by_symbol") or {}),
        "total_observation_count": int(summary.get("total_observation_count") or 0),
        "economic_signal_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    out = dict(base)
    out["source_context"] = source_context
    if not transport_ready:
        out.update({"state": "HOLD_A1_JUMP_LIQUIDITY_LATEST_SOURCE_INCOMPLETE", "blockers": ["LATEST_SYNCHRONIZED_OHLCV_VOLUME_L2_INCOMPLETE"]})
    elif source_context["history_gate_decision"] != "UNSET_BY_COLLECTOR":
        out.update({"state": "HOLD_A1_JUMP_LIQUIDITY_UNRECOGNIZED_HISTORY_GATE", "blockers": ["HISTORY_GATE_MUST_BE_DEFINED_BY_SEPARATE_FROZEN_POLICY"]})
    else:
        out.update({
            "state": "HOLD_A1_JUMP_LIQUIDITY_HISTORY_ACCUMULATING",
            "blockers": ["PROSPECTIVE_L2_HISTORY_GATE_UNSET", "ADMISSION_TEMPLATE_REQUIRED"],
            "next": "CONTINUE_PROSPECTIVE_L2_HISTORY_THEN_FREEZE_SEPARATE_HISTORY_GATE_BEFORE_ECONOMIC_REPLAY",
        })
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(value), handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the preregistered A1 jump-liquidity source gate without economic replay")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    history_rows = _load_recent_jsonl(Path(str(cfg["history_path"])))
    summary_path = Path(str(cfg["history_summary_path"]))
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else None
    result = evaluate_gate(cfg, history_rows=history_rows, summary=summary)
    _atomic_json(Path(str(cfg["output_path"])), result)
    print(json.dumps({
        "state": result["state"],
        "family_id": result["family_id"],
        "architecture_result": result["architecture_result"],
        "source_ready": result["source_ready"],
        "template_ready": result["template_ready"],
        "admission_state": result["admission_state"],
        "economic_replay_allowed": result["economic_replay_allowed"],
        "selection_authority": result["selection_authority"],
        "promotion_authority": result["promotion_authority"],
        "execution_authority": result["execution_authority"],
        "order_authority": result["order_authority"],
        "live_trade_authority": result["live_trade_authority"],
        "exchange_order_submitted": result["exchange_order_submitted"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
