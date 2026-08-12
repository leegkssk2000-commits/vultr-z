from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production.zel_production_ai_admission_executor_v1 import (
    CARRY_SCHEMA,
    EXPECTED_CONTROLS,
    L2_TEMPLATE,
    OBS_SCHEMA,
    SCHEMA,
    _authority_guard,
    _basis_rows,
    _execution_cost_bps,
    _fetch_candles,
    _finite,
    _l2_rows,
    _latest_closed_candle,
    _metrics,
    _positive,
    _sign,
    append_observations,
    build_observations as build_l2_basis_observations,
    read_history,
    validate_contract as validate_contract_v1,
    validate_policy,
)
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

BASIS_OI_TEMPLATE = "basis_oi_deleveraging_v1"
FUNDING_L2_TEMPLATE = "funding_l2_inventory_exhaustion_v1"
SUPPORTED_TEMPLATES = {L2_TEMPLATE, BASIS_OI_TEMPLATE, FUNDING_L2_TEMPLATE}

BASIS_OI_CONTEXT = "REQUIRE_OPEN_INTEREST_INCREASE_AND_NONZERO_BASIS_CHANGE"
FUNDING_L2_CONTEXT = "REQUIRE_FUNDING_SIGN_MATCH_PRIMARY_IMBALANCE_SIGN"


def validate_contract(contract: Mapping[str, Any], template_registry: Mapping[str, Any]) -> dict[str, Any]:
    row = validate_contract_v1(contract, template_registry)
    template_id = str(row.get("template_id") or "")
    if template_id == BASIS_OI_TEMPLATE:
        if sorted(map(str, row.get("required_sources") or [])) != ["basis", "open_interest"]:
            raise RuntimeError("AI_ADMISSION_V2_BASIS_OI_SOURCE_SIGNATURE_DRIFT")
        expected = {
            "event_anchor": "NATIVE_CARRY_SNAPSHOT_CHANGE",
            "direction_rule": "FADE_BASIS_CHANGE_SIGN_WHEN_OI_EXPANDS",
            "context_rule": BASIS_OI_CONTEXT,
            "horizon_rule": "NEXT_CANONICAL_OUTCOME_OBSERVATION",
            "temporal_durability_split": "FIRST_HALF_VS_SECOND_HALF_BY_ORDERED_EVENT",
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise RuntimeError(f"AI_ADMISSION_V2_BASIS_OI_{key.upper()}_DRIFT")
        if list(row.get("negative_controls") or []) != EXPECTED_CONTROLS:
            raise RuntimeError("AI_ADMISSION_V2_BASIS_OI_CONTROLS_DRIFT")
    elif template_id == FUNDING_L2_TEMPLATE:
        if sorted(map(str, row.get("required_sources") or [])) != ["funding", "l2_order_book"]:
            raise RuntimeError("AI_ADMISSION_V2_FUNDING_L2_SOURCE_SIGNATURE_DRIFT")
        expected = {
            "event_anchor": "NATIVE_ORDER_BOOK_UPDATE",
            "direction_rule": "FADE_FUNDING_SIGN",
            "context_rule": FUNDING_L2_CONTEXT,
            "horizon_rule": "NEXT_CANONICAL_OUTCOME_OBSERVATION",
            "temporal_durability_split": "FIRST_HALF_VS_SECOND_HALF_BY_ORDERED_EVENT",
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise RuntimeError(f"AI_ADMISSION_V2_FUNDING_L2_{key.upper()}_DRIFT")
        if list(row.get("negative_controls") or []) != EXPECTED_CONTROLS:
            raise RuntimeError("AI_ADMISSION_V2_FUNDING_L2_CONTROLS_DRIFT")
    return row


def _carry_maps(snapshot: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if snapshot.get("schema_version") != CARRY_SCHEMA or snapshot.get("state") != "PASS_CARRY_POSITIONING_RAW_DATA":
        raise RuntimeError("AI_ADMISSION_V2_CARRY_SNAPSHOT_INVALID")
    _authority_guard(snapshot, "AI_ADMISSION_V2_CARRY")
    premium: dict[str, dict[str, Any]] = {}
    oi: dict[str, dict[str, Any]] = {}
    for raw in snapshot.get("records") or []:
        if not isinstance(raw, Mapping):
            continue
        symbol = str(raw.get("symbol") or "")
        feature = str(raw.get("feature") or "")
        if feature == "premium_index":
            premium[symbol] = dict(raw)
        elif feature == "open_interest":
            oi[symbol] = dict(raw)
    return premium, oi


def _history_last(history: Sequence[Mapping[str, Any]], contract_id: str, symbol: str) -> dict[str, Any] | None:
    rows = [
        dict(x)
        for x in history
        if isinstance(x, Mapping)
        and str(x.get("contract_id") or "") == contract_id
        and str(x.get("symbol") or "") == symbol
    ]
    if not rows:
        return None
    rows.sort(key=lambda x: (int(x.get("observed_at_ms") or 0), int(x.get("outcome_candle_ts_ms") or 0)))
    return rows[-1]


def _base_observation(contract: Mapping[str, Any], symbol: str, observed_at: int, candle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": OBS_SCHEMA,
        "contract_id": str(contract.get("contract_id") or ""),
        "family_id": str(contract.get("family_id") or ""),
        "template_id": str(contract.get("template_id") or ""),
        "symbol": symbol,
        "observed_at_ms": observed_at,
        "outcome_candle_ts_ms": int(candle["candle_ts_ms"]),
        "outcome_close": float(candle["close"]),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def build_basis_oi_observations(
    contract: Mapping[str, Any],
    carry_snapshot: Mapping[str, Any],
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    symbols: Sequence[str],
    history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    premium, oi = _carry_maps(carry_snapshot)
    observed_at = int(carry_snapshot.get("observed_at_ms") or 0)
    if observed_at <= 0:
        raise RuntimeError("AI_ADMISSION_V2_CARRY_OBSERVED_AT_INVALID")
    cid = str(contract.get("contract_id") or "")
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        if symbol not in premium or symbol not in oi:
            continue
        candle = _latest_closed_candle(candles_by_symbol.get(symbol) or [], observed_at)
        if candle is None:
            continue
        pr = premium[symbol]
        orow = oi[symbol]
        derived = pr.get("derived_observation")
        raw_oi = orow.get("raw")
        if not isinstance(derived, Mapping) or not isinstance(raw_oi, Mapping):
            raise RuntimeError(f"AI_ADMISSION_V2_BASIS_OI_FIELDS_MISSING:{symbol}")
        basis_bps = _finite(derived.get("basis_bps"), f"{symbol}.basis_bps")
        open_interest = _finite(raw_oi.get("openInterest"), f"{symbol}.openInterest")
        prev = _history_last(history, cid, symbol)
        basis_delta = 0.0
        oi_delta = 0.0
        context_pass = False
        signal_side = 0
        if prev is not None and prev.get("template_id") == BASIS_OI_TEMPLATE:
            basis_delta = basis_bps - _finite(prev.get("basis_bps"), f"{symbol}.prev_basis_bps")
            oi_delta = open_interest - _finite(prev.get("open_interest"), f"{symbol}.prev_open_interest")
            basis_change_sign = _sign(basis_delta)
            context_pass = oi_delta > 0.0 and basis_change_sign != 0
            signal_side = -basis_change_sign if context_pass else 0
        row = _base_observation(contract, symbol, observed_at, candle)
        row.update(
            {
                "basis_bps": basis_bps,
                "open_interest": open_interest,
                "basis_delta_bps": basis_delta,
                "open_interest_delta": oi_delta,
                "signal_side": signal_side,
                "context_rule": BASIS_OI_CONTEXT,
                "context_pass": context_pass,
                "basis_source_payload_sha256": str(pr.get("source_payload_sha256") or ""),
                "open_interest_source_payload_sha256": str(orow.get("source_payload_sha256") or ""),
                "carry_receipt_sha256": str(carry_snapshot.get("receipt_sha256") or ""),
            }
        )
        for key in ("basis_source_payload_sha256", "open_interest_source_payload_sha256", "carry_receipt_sha256"):
            if len(str(row[key])) != 64:
                raise RuntimeError(f"AI_ADMISSION_V2_SOURCE_SHA_INVALID:{symbol}:{key}")
        row["receipt_sha256"] = stable_sha(row)
        out.append(row)
    return out


def build_funding_l2_observations(
    contract: Mapping[str, Any],
    l2_snapshot: Mapping[str, Any],
    carry_snapshot: Mapping[str, Any],
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    symbols: Sequence[str],
) -> list[dict[str, Any]]:
    l2 = _l2_rows(l2_snapshot)
    premium, _ = _carry_maps(carry_snapshot)
    observed_at = int(l2_snapshot.get("observed_at_ms") or 0)
    if observed_at <= 0:
        raise RuntimeError("AI_ADMISSION_V2_L2_OBSERVED_AT_INVALID")
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        if symbol not in l2 or symbol not in premium:
            continue
        candle = _latest_closed_candle(candles_by_symbol.get(symbol) or [], observed_at)
        if candle is None:
            continue
        lr = l2[symbol]
        pr = premium[symbol]
        raw = pr.get("raw")
        if not isinstance(raw, Mapping):
            raise RuntimeError(f"AI_ADMISSION_V2_FUNDING_RAW_MISSING:{symbol}")
        funding_rate = _finite(raw.get("lastFundingRate"), f"{symbol}.funding")
        funding_sign = _sign(funding_rate)
        imbalance = _finite(lr.get("imbalance_returned_book"), f"{symbol}.imbalance")
        imbalance_sign = int(lr.get("primary_imbalance_sign") or 0)
        context_pass = funding_sign != 0 and imbalance_sign == funding_sign
        signal_side = -funding_sign if context_pass else 0
        row = _base_observation(contract, symbol, observed_at, candle)
        row.update(
            {
                "funding_rate": funding_rate,
                "funding_sign": funding_sign,
                "imbalance_returned_book": imbalance,
                "primary_imbalance_sign": imbalance_sign,
                "signal_side": signal_side,
                "context_rule": FUNDING_L2_CONTEXT,
                "context_pass": context_pass,
                "funding_source_payload_sha256": str(pr.get("source_payload_sha256") or ""),
                "l2_source_payload_sha256": str(lr.get("source_payload_sha256") or ""),
                "carry_receipt_sha256": str(carry_snapshot.get("receipt_sha256") or ""),
                "l2_receipt_sha256": str(l2_snapshot.get("receipt_sha256") or ""),
            }
        )
        for key in ("funding_source_payload_sha256", "l2_source_payload_sha256", "carry_receipt_sha256", "l2_receipt_sha256"):
            if len(str(row[key])) != 64:
                raise RuntimeError(f"AI_ADMISSION_V2_SOURCE_SHA_INVALID:{symbol}:{key}")
        row["receipt_sha256"] = stable_sha(row)
        out.append(row)
    return out


def build_observations(
    contract: Mapping[str, Any],
    l2_snapshot: Mapping[str, Any] | None,
    carry_snapshot: Mapping[str, Any] | None,
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    symbols: Sequence[str],
    history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    template_id = str(contract.get("template_id") or "")
    if template_id == L2_TEMPLATE:
        if not isinstance(l2_snapshot, Mapping) or not isinstance(carry_snapshot, Mapping):
            return []
        return build_l2_basis_observations(contract, l2_snapshot, carry_snapshot, candles_by_symbol, symbols)
    if template_id == BASIS_OI_TEMPLATE:
        if not isinstance(carry_snapshot, Mapping):
            return []
        return build_basis_oi_observations(contract, carry_snapshot, candles_by_symbol, symbols, history)
    if template_id == FUNDING_L2_TEMPLATE:
        if not isinstance(l2_snapshot, Mapping) or not isinstance(carry_snapshot, Mapping):
            return []
        return build_funding_l2_observations(contract, l2_snapshot, carry_snapshot, candles_by_symbol, symbols)
    return []


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
    for symbol_rows in by_symbol.values():
        xs = sorted(symbol_rows, key=lambda x: int(x.get("outcome_candle_ts_ms") or 0))
        for cur, nxt in zip(xs, xs[1:]):
            if cur.get("context_pass") is not True:
                continue
            side = int(cur.get("signal_side") or cur.get("primary_imbalance_sign") or 0)
            if side == 0:
                continue
            gross = side * (
                _finite(nxt.get("outcome_close"), "next_close") / _finite(cur.get("outcome_close"), "entry_close") - 1.0
            ) * 10_000.0
            main.append((int(cur.get("outcome_candle_ts_ms") or 0), gross - cost_bps))
            reversal.append(-gross - cost_bps)
        for first, delayed_entry, delayed_exit in zip(xs, xs[1:], xs[2:]):
            if first.get("context_pass") is not True:
                continue
            side = int(first.get("signal_side") or first.get("primary_imbalance_sign") or 0)
            if side == 0:
                continue
            gross = side * (
                _finite(delayed_exit.get("outcome_close"), "delay_exit")
                / _finite(delayed_entry.get("outcome_close"), "delay_entry")
                - 1.0
            ) * 10_000.0
            delayed.append(gross - cost_bps)
    main.sort(key=lambda x: x[0])
    base: dict[str, Any] = {
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
        base.update(
            {
                "state": "HOLD_AI_ADMISSION_HISTORY_INSUFFICIENT",
                "next": "CONTINUE_PROSPECTIVE_SOURCE_HISTORY",
                "economic_candidate": False,
            }
        )
        base["receipt_sha256"] = stable_sha(base)
        return base
    split = len(main) // 2
    first_m = _metrics([x[1] for x in main[:split]])
    second_m = _metrics([x[1] for x in main[split:]])
    aggregate_m = _metrics([x[1] for x in main])
    reverse_m = _metrics(reversal)
    delayed_m = _metrics(delayed)
    controls_pass = (
        aggregate_m["net_expectancy_bps"] > 0.0
        and aggregate_m["net_expectancy_bps"] > reverse_m["net_expectancy_bps"]
        and aggregate_m["net_expectancy_bps"] > delayed_m["net_expectancy_bps"]
    )
    candidate = _positive(first_m) and _positive(second_m) and _positive(aggregate_m) and controls_pass
    base.update(
        {
            "state": "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE" if candidate else "REJECT_AI_ADMISSION_ECONOMIC_EDGE",
            "next": "BUILD_INDEPENDENT_FAMILY_PAPER_CANARY" if candidate else "RETURN_TO_EDGE_ACQUISITION",
            "economic_candidate": candidate,
            "first_half": first_m,
            "second_half": second_m,
            "aggregate": aggregate_m,
            "negative_controls": {
                "DIRECTION_REVERSAL": reverse_m,
                "PLUS_ONE_EVENT_DELAY": delayed_m,
                "NO_SIGNAL_PLACEBO": {
                    "trade_count": 0,
                    "net_return_sum_bps": 0.0,
                    "net_expectancy_bps": 0.0,
                    "profit_factor": 0.0,
                },
                "pass": controls_pass,
            },
        }
    )
    base["receipt_sha256"] = stable_sha(base)
    return base


def executor_tick(
    policy: Mapping[str, Any],
    *,
    contract_state: Mapping[str, Any] | None,
    template_registry: Mapping[str, Any] | None,
    l2_snapshot: Mapping[str, Any] | None,
    carry_snapshot: Mapping[str, Any] | None,
    cost_authority: Mapping[str, Any] | None,
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    history: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cfg = validate_policy(policy)
    out: dict[str, Any] = {
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
    if not isinstance(contract_state, Mapping) or contract_state.get("schema_version") != "zel.production_ai_admission_materializer.v1":
        out["receipt_sha256"] = stable_sha(out)
        return out, []
    _authority_guard(contract_state, "AI_ADMISSION_V2_MATERIALIZER")
    contracts = contract_state.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        out["receipt_sha256"] = stable_sha(out)
        return out, []
    if not isinstance(template_registry, Mapping) or not isinstance(cost_authority, Mapping):
        out["state"] = "HOLD_AI_ADMISSION_EXECUTOR_AUTHORITY_MISSING"
        out["receipt_sha256"] = stable_sha(out)
        return out, []
    cost_bps = _execution_cost_bps(cost_authority)
    supported: list[dict[str, Any]] = []
    for raw in contracts:
        if not isinstance(raw, Mapping):
            raise RuntimeError("AI_ADMISSION_V2_CONTRACT_ROW_INVALID")
        contract = validate_contract(raw, template_registry)
        if str(contract.get("template_id") or "") in SUPPORTED_TEMPLATES:
            supported.append(contract)
        else:
            out["results"].append(
                {
                    "family_id": contract.get("family_id"),
                    "template_id": contract.get("template_id"),
                    "state": "HOLD_AI_ADMISSION_EXECUTOR_TEMPLATE_NOT_YET_SOURCE_BOUND",
                    "economic_candidate": False,
                }
            )
    if not supported:
        if out["results"]:
            out["state"] = "HOLD_AI_ADMISSION_HISTORY_ACCUMULATING"
            out["next"] = "WAIT_SUPPORTED_FROZEN_TEMPLATE_EXECUTOR"
        out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
        return out, []
    if not isinstance(carry_snapshot, Mapping):
        out["state"] = "HOLD_AI_ADMISSION_EXECUTOR_SOURCE_SNAPSHOT_MISSING"
        out["receipt_sha256"] = stable_sha(out)
        return out, []
    if any(str(x.get("template_id") or "") in {L2_TEMPLATE, FUNDING_L2_TEMPLATE} for x in supported) and not isinstance(l2_snapshot, Mapping):
        out["state"] = "HOLD_AI_ADMISSION_EXECUTOR_SOURCE_SNAPSHOT_MISSING"
        out["receipt_sha256"] = stable_sha(out)
        return out, []
    cbs = candles_by_symbol
    if cbs is None:
        cbs = asyncio.run(_fetch_candles(cfg["symbols"]))
    existing_history = list(history or [])
    observations: list[dict[str, Any]] = []
    for contract in supported:
        observations.extend(
            build_observations(contract, l2_snapshot, carry_snapshot, cbs, cfg["symbols"], existing_history + observations)
        )
    merged_history = existing_history + observations
    for contract in supported:
        out["results"].append(evaluate_contract(contract, merged_history, cost_bps))
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
    ap = argparse.ArgumentParser(description="Execute frozen authority-free AI admission contracts V2")
    ap.add_argument("--policy", type=Path, default=Path("config/zel_production_ai_admission_executor_v1.json"))
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    history_path = Path(str(cfg["observation_history_path"]))
    kwargs = {
        "contract_state": read_json(Path(str(cfg["contract_state_path"]))),
        "template_registry": read_json(Path(str(cfg["template_registry_path"]))),
        "l2_snapshot": read_json(Path(str(cfg["l2_snapshot_path"]))),
        "carry_snapshot": read_json(Path(str(cfg["carry_snapshot_path"]))),
        "cost_authority": read_json(Path(str(cfg["execution_cost_authority_path"]))),
    }
    result, observations = executor_tick(cfg, history=read_history(history_path), **kwargs)
    added = append_observations(history_path, observations)
    if observations:
        result, _ = executor_tick(
            cfg,
            candles_by_symbol={s: [] for s in cfg["symbols"]},
            history=read_history(history_path),
            **kwargs,
        )
    result["observation_history_appended"] = added
    result["executor_version"] = "V2"
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    atomic_json_write(Path(str(cfg["output_path"])), result)
    print(
        json.dumps(
            {
                "state": result["state"],
                "next": result.get("next"),
                "result_count": len(result.get("results") or []),
                "observation_history_appended": added,
                "receipt_sha256": result["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
