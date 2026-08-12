from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production import zel_production_ai_admission_executor_v2 as v2
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

FUNDING_VOLUME_TEMPLATE = "funding_volume_elasticity_v1"
FUNDING_VOLUME_CONTEXT = "REQUIRE_CURRENT_VOLUME_GT_PREVIOUS_OBSERVED_VOLUME_AND_CURRENT_FUNDING_EQ_PREVIOUS_OBSERVED_FUNDING"


def validate_funding_volume_contract(contract: Mapping[str, Any], template_registry: Mapping[str, Any]) -> dict[str, Any]:
    row = v2.validate_contract(contract, template_registry)
    if str(row.get("template_id") or "") != FUNDING_VOLUME_TEMPLATE:
        return row
    if sorted(map(str, row.get("required_sources") or [])) != ["funding", "ohlcv", "volume"]:
        raise RuntimeError("AI_ADMISSION_V3_FUNDING_VOLUME_SOURCE_SIGNATURE_DRIFT")
    expected = {
        "event_anchor": "VERIFIED_NATIVE_FUNDING_AND_CLOSED_OHLCV_UPDATE",
        "direction_rule": "FOLLOW_CLOSED_CANDLE_SIGN_WHEN_VOLUME_EXPANDS_AND_FUNDING_UNCHANGED",
        "context_rule": FUNDING_VOLUME_CONTEXT,
        "horizon_rule": "NEXT_CANONICAL_OUTCOME_OBSERVATION",
        "temporal_durability_split": "FIRST_HALF_VS_SECOND_HALF_BY_ORDERED_EVENT",
    }
    for key, value in expected.items():
        if row.get(key) != value:
            raise RuntimeError(f"AI_ADMISSION_V3_FUNDING_VOLUME_{key.upper()}_DRIFT")
    if list(row.get("negative_controls") or []) != v2.EXPECTED_CONTROLS:
        raise RuntimeError("AI_ADMISSION_V3_FUNDING_VOLUME_CONTROLS_DRIFT")
    if row.get("numeric_signal_thresholds") != [] or row.get("parameter_search") is not False:
        raise RuntimeError("AI_ADMISSION_V3_FUNDING_VOLUME_SEARCH_FORBIDDEN")
    return row


def _latest_closed_ohlcv(candles: Sequence[Mapping[str, Any]], observed_at_ms: int, timeframe_ms: int = 3_600_000) -> dict[str, Any] | None:
    eligible: list[dict[str, Any]] = []
    for raw in candles:
        if not isinstance(raw, Mapping):
            continue
        try:
            ts = int(float(raw.get("ts")))
            if ts < 10_000_000_000:
                ts *= 1000
            op = v2._finite(raw.get("op"), "candle.open")
            cl = v2._finite(raw.get("cl"), "candle.close")
            vol = v2._finite(raw.get("vol"), "candle.volume")
        except (RuntimeError, TypeError, ValueError):
            continue
        if ts > 0 and op > 0.0 and cl > 0.0 and vol >= 0.0 and ts + timeframe_ms <= observed_at_ms:
            eligible.append({"candle_ts_ms": ts, "open": op, "close": cl, "volume": vol})
    if not eligible:
        return None
    return max(eligible, key=lambda x: int(x["candle_ts_ms"]))


def build_funding_volume_observations(
    contract: Mapping[str, Any],
    carry_snapshot: Mapping[str, Any],
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    symbols: Sequence[str],
    history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    premium, _ = v2._carry_maps(carry_snapshot)
    observed_at = int(carry_snapshot.get("observed_at_ms") or 0)
    if observed_at <= 0:
        raise RuntimeError("AI_ADMISSION_V3_CARRY_OBSERVED_AT_INVALID")
    cid = str(contract.get("contract_id") or "")
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        pr = premium.get(symbol)
        if not isinstance(pr, Mapping):
            continue
        candle = _latest_closed_ohlcv(candles_by_symbol.get(symbol) or [], observed_at)
        if candle is None:
            continue
        raw = pr.get("raw")
        if not isinstance(raw, Mapping):
            raise RuntimeError(f"AI_ADMISSION_V3_FUNDING_RAW_MISSING:{symbol}")
        funding_rate = v2._finite(raw.get("lastFundingRate"), f"{symbol}.funding")
        volume = v2._finite(candle.get("volume"), f"{symbol}.volume")
        candle_open = v2._finite(candle.get("open"), f"{symbol}.open")
        candle_close = v2._finite(candle.get("close"), f"{symbol}.close")
        prev = v2._history_last(history, cid, symbol)
        context_pass = False
        signal_side = 0
        volume_delta = 0.0
        funding_delta = 0.0
        if prev is not None and prev.get("template_id") == FUNDING_VOLUME_TEMPLATE:
            prev_volume = v2._finite(prev.get("volume"), f"{symbol}.prev_volume")
            prev_funding = v2._finite(prev.get("funding_rate"), f"{symbol}.prev_funding")
            volume_delta = volume - prev_volume
            funding_delta = funding_rate - prev_funding
            context_pass = volume_delta > 0.0 and funding_delta == 0.0
            signal_side = v2._sign(candle_close - candle_open) if context_pass else 0
        row = v2._base_observation(contract, symbol, observed_at, candle)
        row.update(
            {
                "funding_rate": funding_rate,
                "funding_delta": funding_delta,
                "volume": volume,
                "volume_delta": volume_delta,
                "candle_open": candle_open,
                "candle_close": candle_close,
                "signal_side": signal_side,
                "context_rule": FUNDING_VOLUME_CONTEXT,
                "context_pass": context_pass,
                "funding_source_payload_sha256": str(pr.get("source_payload_sha256") or ""),
                "ohlcv_volume_payload_sha256": stable_sha(
                    {
                        "symbol": symbol,
                        "candle_ts_ms": int(candle["candle_ts_ms"]),
                        "open": candle_open,
                        "close": candle_close,
                        "volume": volume,
                    }
                ),
                "carry_receipt_sha256": str(carry_snapshot.get("receipt_sha256") or ""),
            }
        )
        for key in ("funding_source_payload_sha256", "ohlcv_volume_payload_sha256", "carry_receipt_sha256"):
            if len(str(row[key])) != 64:
                raise RuntimeError(f"AI_ADMISSION_V3_SOURCE_SHA_INVALID:{symbol}:{key}")
        row["receipt_sha256"] = stable_sha(row)
        out.append(row)
    return out


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
    cfg = v2.validate_policy(policy)
    if not isinstance(contract_state, Mapping) or not isinstance(contract_state.get("contracts"), list):
        return v2.executor_tick(
            cfg,
            contract_state=contract_state,
            template_registry=template_registry,
            l2_snapshot=l2_snapshot,
            carry_snapshot=carry_snapshot,
            cost_authority=cost_authority,
            candles_by_symbol=candles_by_symbol,
            history=history,
        )
    contracts = [x for x in contract_state.get("contracts") or [] if isinstance(x, Mapping)]
    target = [x for x in contracts if str(x.get("template_id") or "") == FUNDING_VOLUME_TEMPLATE]
    other = [x for x in contracts if str(x.get("template_id") or "") != FUNDING_VOLUME_TEMPLATE]
    if not target:
        return v2.executor_tick(
            cfg,
            contract_state=contract_state,
            template_registry=template_registry,
            l2_snapshot=l2_snapshot,
            carry_snapshot=carry_snapshot,
            cost_authority=cost_authority,
            candles_by_symbol=candles_by_symbol,
            history=history,
        )
    if not isinstance(template_registry, Mapping) or not isinstance(cost_authority, Mapping):
        raise RuntimeError("AI_ADMISSION_V3_AUTHORITY_MISSING")
    if not isinstance(carry_snapshot, Mapping):
        return ({
            "schema_version": v2.SCHEMA,
            "state": "HOLD_AI_ADMISSION_EXECUTOR_SOURCE_SNAPSHOT_MISSING",
            "results": [],
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "action": "hold",
            "receipt_sha256": stable_sha({"state":"HOLD_AI_ADMISSION_EXECUTOR_SOURCE_SNAPSHOT_MISSING"}),
        }, [])
    cost_bps = v2._execution_cost_bps(cost_authority)
    cbs = candles_by_symbol if candles_by_symbol is not None else asyncio.run(v2._fetch_candles(cfg["symbols"]))
    existing = list(history or [])
    observations: list[dict[str, Any]] = []
    validated_target: list[dict[str, Any]] = []
    for raw in target:
        contract = validate_funding_volume_contract(raw, template_registry)
        validated_target.append(contract)
        observations.extend(build_funding_volume_observations(contract, carry_snapshot, cbs, cfg["symbols"], existing + observations))
    results: list[dict[str, Any]] = []
    if other:
        other_state = dict(contract_state)
        other_state["contracts"] = other
        base_result, base_obs = v2.executor_tick(
            cfg,
            contract_state=other_state,
            template_registry=template_registry,
            l2_snapshot=l2_snapshot,
            carry_snapshot=carry_snapshot,
            cost_authority=cost_authority,
            candles_by_symbol=cbs,
            history=existing,
        )
        observations.extend(base_obs)
        results.extend([dict(x) for x in base_result.get("results") or [] if isinstance(x, Mapping)])
    merged = existing + observations
    for contract in validated_target:
        results.append(v2.evaluate_contract(contract, merged, cost_bps))
    out: dict[str, Any] = {
        "schema_version": v2.SCHEMA,
        "results": results,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
    }
    if any(x.get("state") == "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE" for x in results):
        out["state"] = "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE"
        out["next"] = "BUILD_INDEPENDENT_FAMILY_PAPER_CANARY"
    elif any(str(x.get("state") or "").startswith("HOLD_") for x in results):
        out["state"] = "HOLD_AI_ADMISSION_HISTORY_ACCUMULATING"
        out["next"] = "CONTINUE_PROSPECTIVE_SOURCE_HISTORY"
    else:
        out["state"] = "REJECT_AI_ADMISSION_ECONOMIC_EDGE"
        out["next"] = "RETURN_TO_EDGE_ACQUISITION"
    out["receipt_sha256"] = stable_sha(out)
    return out, observations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Execute frozen authority-free AI admission contracts V3")
    ap.add_argument("--policy", type=Path, default=Path("config/zel_production_ai_admission_executor_v1.json"))
    ns = ap.parse_args(argv)
    cfg = v2.validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    history_path = Path(str(cfg["observation_history_path"]))
    kwargs = {
        "contract_state": read_json(Path(str(cfg["contract_state_path"]))),
        "template_registry": read_json(Path(str(cfg["template_registry_path"]))),
        "l2_snapshot": read_json(Path(str(cfg["l2_snapshot_path"]))),
        "carry_snapshot": read_json(Path(str(cfg["carry_snapshot_path"]))),
        "cost_authority": read_json(Path(str(cfg["execution_cost_authority_path"]))),
    }
    result, observations = executor_tick(cfg, history=v2.read_history(history_path), **kwargs)
    added = v2.append_observations(history_path, observations)
    if observations:
        result, _ = executor_tick(
            cfg,
            candles_by_symbol={s: [] for s in cfg["symbols"]},
            history=v2.read_history(history_path),
            **kwargs,
        )
    result["observation_history_appended"] = added
    result["executor_version"] = "V3"
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    atomic_json_write(Path(str(cfg["output_path"])), result)
    print(json.dumps({
        "state": result["state"],
        "next": result.get("next"),
        "result_count": len(result.get("results") or []),
        "observation_history_appended": added,
        "executor_version": "V3",
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
