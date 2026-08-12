from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.engine.market_data_service import BingXPublicAdapter
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_ai_admission_executor.v1"
POLICY_SCHEMA = "zel.production_ai_admission_executor_policy.v1"
CONTRACT_SCHEMA = "zel.production_ai_admission_contract.v1"
MATERIALIZER_SCHEMA = "zel.production_ai_admission_materializer.v1"
L2_SCHEMA = "zel.production_l2_order_book_data.v1"
CARRY_SCHEMA = "zel.production_carry_flow_data.v1"
OBS_SCHEMA = "zel.production_ai_admission_observation.v1"
DEFAULT_POLICY = Path("config/zel_production_ai_admission_executor_v1.json")
L2_TEMPLATE = "l2_inventory_pressure_v1"
L2_CONTEXT_RULE = "REQUIRE_BASIS_SIGN_MATCH_PRIMARY_IMBALANCE_SIGN"
EXPECTED_CONTROLS = ["DIRECTION_REVERSAL", "PLUS_ONE_EVENT_DELAY", "NO_SIGNAL_PLACEBO"]


def _authority_guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")


def _finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"AI_ADMISSION_EXECUTOR_NUMERIC_INVALID:{label}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"AI_ADMISSION_EXECUTOR_NUMERIC_NONFINITE:{label}")
    return out


def _timestamp_ms(value: Any, label: str) -> int:
    try:
        out = int(float(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"AI_ADMISSION_EXECUTOR_TIMESTAMP_INVALID:{label}") from exc
    if out < 10_000_000_000:
        out *= 1000
    if out <= 0:
        raise RuntimeError(f"AI_ADMISSION_EXECUTOR_TIMESTAMP_INVALID:{label}")
    return out


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("AI_ADMISSION_EXECUTOR_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("AI_ADMISSION_EXECUTOR_NON_PAPER_FORBIDDEN")
    for key in (
        "contract_state_path", "template_registry_path", "l2_snapshot_path",
        "carry_snapshot_path", "observation_history_path", "output_path",
        "execution_cost_authority_path",
    ):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"AI_ADMISSION_EXECUTOR_PATH_MISSING:{key}")
    symbols = list(map(str, policy.get("symbols") or []))
    if symbols != ["BTC-USDT", "ETH-USDT"]:
        raise RuntimeError("AI_ADMISSION_EXECUTOR_SYMBOLS_DRIFT")
    if str(policy.get("outcome_timeframe") or "") != "1h":
        raise RuntimeError("AI_ADMISSION_EXECUTOR_TIMEFRAME_DRIFT")
    if policy.get("numeric_signal_thresholds") != [] or policy.get("parameter_search") is not False:
        raise RuntimeError("AI_ADMISSION_EXECUTOR_SEARCH_FORBIDDEN")
    _authority_guard(policy, "AI_ADMISSION_EXECUTOR_POLICY")
    return dict(policy)


def validate_contract(contract: Mapping[str, Any], template_registry: Mapping[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        raise RuntimeError("AI_ADMISSION_EXECUTOR_CONTRACT_SCHEMA_INVALID")
    _authority_guard(contract, "AI_ADMISSION_EXECUTOR_CONTRACT")
    if contract.get("numeric_signal_thresholds") != [] or contract.get("parameter_search") is not False:
        raise RuntimeError("AI_ADMISSION_EXECUTOR_CONTRACT_SEARCH_FORBIDDEN")
    template_id = str(contract.get("template_id") or "")
    templates = template_registry.get("templates") if isinstance(template_registry, Mapping) else None
    if not isinstance(templates, Mapping) or template_id not in templates or not isinstance(templates[template_id], Mapping):
        raise RuntimeError("AI_ADMISSION_EXECUTOR_TEMPLATE_MISSING")
    template = dict(templates[template_id])
    if stable_sha(template) != str(contract.get("template_sha256") or ""):
        raise RuntimeError("AI_ADMISSION_EXECUTOR_TEMPLATE_SHA_MISMATCH")
    if template_id == L2_TEMPLATE:
        if sorted(map(str, contract.get("required_sources") or [])) != ["basis", "l2_order_book"]:
            raise RuntimeError("AI_ADMISSION_EXECUTOR_L2_SOURCE_SIGNATURE_DRIFT")
        if contract.get("event_anchor") != "NATIVE_ORDER_BOOK_UPDATE":
            raise RuntimeError("AI_ADMISSION_EXECUTOR_L2_EVENT_ANCHOR_DRIFT")
        if contract.get("direction_rule") != "FOLLOW_PRIMARY_IMBALANCE_SIGN":
            raise RuntimeError("AI_ADMISSION_EXECUTOR_L2_DIRECTION_DRIFT")
        if contract.get("horizon_rule") != "NEXT_CANONICAL_OUTCOME_OBSERVATION":
            raise RuntimeError("AI_ADMISSION_EXECUTOR_L2_HORIZON_DRIFT")
        if contract.get("temporal_durability_split") != "FIRST_HALF_VS_SECOND_HALF_BY_ORDERED_EVENT":
            raise RuntimeError("AI_ADMISSION_EXECUTOR_L2_SPLIT_DRIFT")
        if list(contract.get("negative_controls") or []) != EXPECTED_CONTROLS:
            raise RuntimeError("AI_ADMISSION_EXECUTOR_L2_CONTROLS_DRIFT")
        if contract.get("context_rule") != L2_CONTEXT_RULE:
            raise RuntimeError("AI_ADMISSION_EXECUTOR_L2_CONTEXT_RULE_MISSING")
    return dict(contract)


def _execution_cost_bps(cost_authority: Mapping[str, Any]) -> float:
    if cost_authority.get("schema_version") != "zel.production_carry_positioning.v1":
        raise RuntimeError("AI_ADMISSION_EXECUTOR_COST_AUTHORITY_SCHEMA")
    cost = cost_authority.get("execution_cost_authority")
    if not isinstance(cost, Mapping) or int(cost.get("source_pull_request") or 0) != 570:
        raise RuntimeError("AI_ADMISSION_EXECUTOR_COST_AUTHORITY_MISSING")
    declared = _finite(cost.get("round_trip_execution_cost_bps"), "round_trip_execution_cost_bps")
    derived = 2.0 * _finite(cost.get("taker_fee_pct_one_way"), "taker_fee_pct_one_way") * 100.0 + 2.0 * _finite(cost.get("slippage_floor_bps_one_way"), "slippage_floor_bps_one_way")
    if abs(declared - derived) > 1e-9 or declared <= 0.0:
        raise RuntimeError("AI_ADMISSION_EXECUTOR_COST_AUTHORITY_DRIFT")
    return declared


def _latest_closed_candle(candles: Sequence[Mapping[str, Any]], observed_at_ms: int, timeframe_ms: int = 3_600_000) -> dict[str, Any] | None:
    eligible: list[tuple[int, float]] = []
    for row in candles:
        if not isinstance(row, Mapping):
            continue
        try:
            ts = _timestamp_ms(row.get("ts"), "candle.ts")
            close = _finite(row.get("cl"), "candle.close")
        except RuntimeError:
            continue
        if close > 0.0 and ts + timeframe_ms <= observed_at_ms:
            eligible.append((ts, close))
    if not eligible:
        return None
    ts, close = max(eligible, key=lambda x: x[0])
    return {"candle_ts_ms": ts, "close": close}


def _l2_rows(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if snapshot.get("schema_version") != L2_SCHEMA or snapshot.get("state") != "PASS_L2_ORDER_BOOK_NATIVE_SNAPSHOT":
        raise RuntimeError("AI_ADMISSION_EXECUTOR_L2_SNAPSHOT_INVALID")
    _authority_guard(snapshot, "AI_ADMISSION_EXECUTOR_L2")
    rows = snapshot.get("records")
    if not isinstance(rows, list):
        raise RuntimeError("AI_ADMISSION_EXECUTOR_L2_ROWS_MISSING")
    return {str(x.get("symbol")): dict(x) for x in rows if isinstance(x, Mapping)}


def _basis_rows(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if snapshot.get("schema_version") != CARRY_SCHEMA or snapshot.get("state") != "PASS_CARRY_POSITIONING_RAW_DATA":
        raise RuntimeError("AI_ADMISSION_EXECUTOR_BASIS_SNAPSHOT_INVALID")
    _authority_guard(snapshot, "AI_ADMISSION_EXECUTOR_CARRY")
    out: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("records") or []:
        if isinstance(row, Mapping) and row.get("feature") == "premium_index":
            out[str(row.get("symbol"))] = dict(row)
    return out


def build_observations(
    contract: Mapping[str, Any], l2_snapshot: Mapping[str, Any], carry_snapshot: Mapping[str, Any],
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]], symbols: Sequence[str],
) -> list[dict[str, Any]]:
    if contract.get("template_id") != L2_TEMPLATE:
        return []
    l2 = _l2_rows(l2_snapshot)
    basis = _basis_rows(carry_snapshot)
    observed_at = int(l2_snapshot.get("observed_at_ms") or 0)
    if observed_at <= 0:
        raise RuntimeError("AI_ADMISSION_EXECUTOR_OBSERVED_AT_INVALID")
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        if symbol not in l2 or symbol not in basis:
            continue
        candle = _latest_closed_candle(candles_by_symbol.get(symbol) or [], observed_at)
        if candle is None:
            continue
        lr = l2[symbol]
        br = basis[symbol]
        imbalance = _finite(lr.get("imbalance_returned_book"), f"{symbol}.imbalance")
        primary_sign = int(lr.get("primary_imbalance_sign") or 0)
        derived = br.get("derived_observation")
        if not isinstance(derived, Mapping):
            raise RuntimeError(f"AI_ADMISSION_EXECUTOR_BASIS_DERIVED_MISSING:{symbol}")
        basis_bps = _finite(derived.get("basis_bps"), f"{symbol}.basis_bps")
        basis_sign = _sign(basis_bps)
        context_pass = primary_sign != 0 and basis_sign == primary_sign
        row: dict[str, Any] = {
            "schema_version": OBS_SCHEMA,
            "contract_id": str(contract.get("contract_id") or ""),
            "family_id": str(contract.get("family_id") or ""),
            "template_id": L2_TEMPLATE,
            "symbol": symbol,
            "observed_at_ms": observed_at,
            "outcome_candle_ts_ms": int(candle["candle_ts_ms"]),
            "outcome_close": float(candle["close"]),
            "primary_imbalance_sign": primary_sign,
            "imbalance_returned_book": imbalance,
            "basis_bps": basis_bps,
            "basis_sign": basis_sign,
            "context_rule": L2_CONTEXT_RULE,
            "context_pass": context_pass,
            "l2_source_payload_sha256": str(lr.get("source_payload_sha256") or ""),
            "basis_source_payload_sha256": str(br.get("source_payload_sha256") or ""),
            "l2_receipt_sha256": str(l2_snapshot.get("receipt_sha256") or ""),
            "carry_receipt_sha256": str(carry_snapshot.get("receipt_sha256") or ""),
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }
        for key in ("l2_source_payload_sha256", "basis_source_payload_sha256", "l2_receipt_sha256", "carry_receipt_sha256"):
            if len(row[key]) != 64:
                raise RuntimeError(f"AI_ADMISSION_EXECUTOR_SOURCE_SHA_INVALID:{symbol}:{key}")
        row["receipt_sha256"] = stable_sha(row)
        out.append(row)
    return out


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except Exception as exc:
            raise RuntimeError(f"AI_ADMISSION_EXECUTOR_HISTORY_JSON_INVALID:{line_no}") from exc
        if not isinstance(row, dict) or row.get("schema_version") != OBS_SCHEMA:
            raise RuntimeError(f"AI_ADMISSION_EXECUTOR_HISTORY_ROW_INVALID:{line_no}")
        _authority_guard(row, "AI_ADMISSION_EXECUTOR_HISTORY")
        out.append(row)
    return out


def append_observations(path: Path, rows: Sequence[Mapping[str, Any]]) -> int:
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_history(path)
    keys = {(str(x.get("contract_id")), str(x.get("symbol")), int(x.get("outcome_candle_ts_ms") or 0)) for x in existing}
    added = 0
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        for raw in rows:
            row = dict(raw)
            key = (str(row.get("contract_id")), str(row.get("symbol")), int(row.get("outcome_candle_ts_ms") or 0))
            if key in keys:
                continue
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
            keys.add(key)
            added += 1
        fh.flush()
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    path.chmod(0o600)
    return added


def _metrics(values: Sequence[float]) -> dict[str, Any]:
    vals = [float(x) for x in values]
    wins = [x for x in vals if x > 0]
    losses = [x for x in vals if x < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    return {
        "trade_count": len(vals),
        "net_return_sum_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else 0.0,
        "profit_factor": gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0),
    }


def _positive(m: Mapping[str, Any]) -> bool:
    return int(m.get("trade_count") or 0) > 0 and float(m.get("net_return_sum_bps") or 0.0) > 0.0 and float(m.get("net_expectancy_bps") or 0.0) > 0.0 and float(m.get("profit_factor") or 0.0) >= 1.0


def evaluate_contract(contract: Mapping[str, Any], history: Sequence[Mapping[str, Any]], cost_bps: float) -> dict[str, Any]:
    cid = str(contract.get("contract_id") or "")
    rows = [dict(x) for x in history if str(x.get("contract_id") or "") == cid]
    rows.sort(key=lambda x: (str(x.get("symbol")), int(x.get("outcome_candle_ts_ms") or 0)))
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row.get("symbol")), []).append(row)
    main: list[tuple[int, float]] = []
    reversal: list[float] = []
    delayed: list[float] = []
    for symbol, xs in sorted(by_symbol.items()):
        for cur, nxt in zip(xs, xs[1:]):
            if cur.get("context_pass") is not True:
                continue
            side = int(cur.get("primary_imbalance_sign") or 0)
            if side == 0:
                continue
            gross = side * (_finite(nxt.get("outcome_close"), f"{symbol}.next_close") / _finite(cur.get("outcome_close"), f"{symbol}.entry_close") - 1.0) * 10000.0
            main.append((int(cur.get("outcome_candle_ts_ms") or 0), gross - cost_bps))
            reversal.append(-gross - cost_bps)
        for first, delayed_entry, delayed_exit in zip(xs, xs[1:], xs[2:]):
            if first.get("context_pass") is not True:
                continue
            side = int(first.get("primary_imbalance_sign") or 0)
            if side == 0:
                continue
            gross = side * (_finite(delayed_exit.get("outcome_close"), f"{symbol}.delay_exit") / _finite(delayed_entry.get("outcome_close"), f"{symbol}.delay_entry") - 1.0) * 10000.0
            delayed.append(gross - cost_bps)
    main.sort(key=lambda x: x[0])
    base = {
        "schema_version": SCHEMA,
        "family_id": str(contract.get("family_id") or ""),
        "contract_id": cid,
        "template_id": str(contract.get("template_id") or ""),
        "observation_count": len(rows),
        "parameter_search_performed": False,
        "numeric_signal_threshold_count": 0,
        "execution_cost_bps": cost_bps,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
    }
    if len(main) < 2 or not delayed:
        base.update({"state": "HOLD_AI_ADMISSION_HISTORY_INSUFFICIENT", "next": "CONTINUE_PROSPECTIVE_SOURCE_HISTORY", "economic_candidate": False})
        base["receipt_sha256"] = stable_sha(base)
        return base
    split = len(main) // 2
    first_vals = [x[1] for x in main[:split]]
    second_vals = [x[1] for x in main[split:]]
    aggregate_vals = [x[1] for x in main]
    first_m, second_m, aggregate_m = _metrics(first_vals), _metrics(second_vals), _metrics(aggregate_vals)
    reverse_m, delayed_m = _metrics(reversal), _metrics(delayed)
    controls_pass = aggregate_m["net_expectancy_bps"] > 0.0 and aggregate_m["net_expectancy_bps"] > reverse_m["net_expectancy_bps"] and aggregate_m["net_expectancy_bps"] > delayed_m["net_expectancy_bps"]
    candidate = _positive(first_m) and _positive(second_m) and _positive(aggregate_m) and controls_pass
    base.update({
        "state": "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE" if candidate else "REJECT_AI_ADMISSION_ECONOMIC_EDGE",
        "next": "BUILD_INDEPENDENT_FAMILY_PAPER_CANARY" if candidate else "RETURN_TO_EDGE_ACQUISITION",
        "economic_candidate": candidate,
        "first_half": first_m,
        "second_half": second_m,
        "aggregate": aggregate_m,
        "negative_controls": {
            "DIRECTION_REVERSAL": reverse_m,
            "PLUS_ONE_EVENT_DELAY": delayed_m,
            "NO_SIGNAL_PLACEBO": {"trade_count": 0, "net_return_sum_bps": 0.0, "net_expectancy_bps": 0.0, "profit_factor": 0.0},
            "pass": controls_pass,
        },
    })
    base["receipt_sha256"] = stable_sha(base)
    return base


async def _fetch_candles(symbols: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    adapter = BingXPublicAdapter()
    pairs = await asyncio.gather(*(adapter.fetch_candles(symbol, "1h", limit=7) for symbol in symbols))
    return {symbol: list(rows) for symbol, rows in zip(symbols, pairs)}


def executor_tick(policy: Mapping[str, Any], *, contract_state: Mapping[str, Any] | None, template_registry: Mapping[str, Any] | None, l2_snapshot: Mapping[str, Any] | None, carry_snapshot: Mapping[str, Any] | None, cost_authority: Mapping[str, Any] | None, candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]] | None = None, history: Sequence[Mapping[str, Any]] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cfg = validate_policy(policy)
    out = {
        "schema_version": SCHEMA,
        "state": "HOLD_AI_ADMISSION_NO_FROZEN_CONTRACT",
        "results": [],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
        "updated_at_ms": int(time.time() * 1000),
    }
    if not isinstance(contract_state, Mapping) or contract_state.get("schema_version") != MATERIALIZER_SCHEMA:
        out["receipt_sha256"] = stable_sha(out)
        return out, []
    _authority_guard(contract_state, "AI_ADMISSION_EXECUTOR_MATERIALIZER")
    contracts = contract_state.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        out["receipt_sha256"] = stable_sha(out)
        return out, []
    if not isinstance(template_registry, Mapping) or not isinstance(cost_authority, Mapping):
        out["state"] = "HOLD_AI_ADMISSION_EXECUTOR_AUTHORITY_MISSING"
        out["receipt_sha256"] = stable_sha(out)
        return out, []
    cost_bps = _execution_cost_bps(cost_authority)
    observations: list[dict[str, Any]] = []
    validated: list[dict[str, Any]] = []
    for raw in contracts:
        if not isinstance(raw, Mapping):
            raise RuntimeError("AI_ADMISSION_EXECUTOR_CONTRACT_ROW_INVALID")
        contract = validate_contract(raw, template_registry)
        if contract.get("template_id") != L2_TEMPLATE:
            out["results"].append({"family_id": contract.get("family_id"), "state": "HOLD_AI_ADMISSION_EXECUTOR_TEMPLATE_NOT_YET_SOURCE_BOUND", "economic_candidate": False})
            continue
        validated.append(contract)
    if validated:
        if not isinstance(l2_snapshot, Mapping) or not isinstance(carry_snapshot, Mapping):
            out["state"] = "HOLD_AI_ADMISSION_EXECUTOR_SOURCE_SNAPSHOT_MISSING"
            out["receipt_sha256"] = stable_sha(out)
            return out, []
        cbs = candles_by_symbol
        if cbs is None:
            cbs = asyncio.run(_fetch_candles(cfg["symbols"]))
        for contract in validated:
            observations.extend(build_observations(contract, l2_snapshot, carry_snapshot, cbs, cfg["symbols"]))
    merged_history = list(history or []) + observations
    for contract in validated:
        out["results"].append(evaluate_contract(contract, merged_history, cost_bps))
    if out["results"]:
        if any(x.get("state") == "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE" for x in out["results"] if isinstance(x, Mapping)):
            out["state"] = "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE"
            out["next"] = "BUILD_INDEPENDENT_FAMILY_PAPER_CANARY"
        elif any(str(x.get("state") or "").startswith("HOLD_") for x in out["results"] if isinstance(x, Mapping)):
            out["state"] = "HOLD_AI_ADMISSION_HISTORY_ACCUMULATING"
            out["next"] = "CONTINUE_PROSPECTIVE_SOURCE_HISTORY"
        else:
            out["state"] = "REJECT_AI_ADMISSION_ECONOMIC_EDGE"
            out["next"] = "RETURN_TO_EDGE_ACQUISITION"
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, observations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Execute frozen authority-free AI admission contracts")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    history_path = Path(str(cfg["observation_history_path"]))
    result, observations = executor_tick(
        cfg,
        contract_state=read_json(Path(str(cfg["contract_state_path"]))),
        template_registry=read_json(Path(str(cfg["template_registry_path"]))),
        l2_snapshot=read_json(Path(str(cfg["l2_snapshot_path"]))),
        carry_snapshot=read_json(Path(str(cfg["carry_snapshot_path"]))),
        cost_authority=read_json(Path(str(cfg["execution_cost_authority_path"]))),
        history=read_history(history_path),
    )
    added = append_observations(history_path, observations)
    # Re-evaluate against the persisted deduplicated history so repeated Explore ticks are idempotent.
    if observations:
        result, _ = executor_tick(
            cfg,
            contract_state=read_json(Path(str(cfg["contract_state_path"]))),
            template_registry=read_json(Path(str(cfg["template_registry_path"]))),
            l2_snapshot=read_json(Path(str(cfg["l2_snapshot_path"]))),
            carry_snapshot=read_json(Path(str(cfg["carry_snapshot_path"]))),
            cost_authority=read_json(Path(str(cfg["execution_cost_authority_path"]))),
            candles_by_symbol={s: [] for s in cfg["symbols"]},
            history=read_history(history_path),
        )
    result["observation_history_appended"] = added
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    atomic_json_write(Path(str(cfg["output_path"])), result)
    print(json.dumps({"state": result["state"], "next": result.get("next"), "observation_history_appended": added, "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
