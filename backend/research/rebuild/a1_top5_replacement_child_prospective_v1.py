#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import Expr, _feature_formula, _side, _validate_side

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v1.json"
LATEST = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_latest.json"
KLINE_API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
SYMBOLS = ("BTC-USDT", "ETH-USDT")
INTERVAL_MS = {"4h": 4 * 60 * 60 * 1000}
SCHEMA = "zel.a1.top5.replacement_child.prospective.receipt.v1"
WARMUP_BARS = 240
MAX_PAGES = 6

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _req(params: Mapping[str, Any]) -> Any:
    url = KLINE_API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    if isinstance(value, dict) and value.get("code") not in (None, 0):
        raise RuntimeError(f"BINGX:{value.get('code')}:{value.get('msg')}")
    return value


def _decode(value: Any) -> list[dict[str, float]]:
    rows = value.get("data", value if isinstance(value, list) else []) if isinstance(value, (dict, list)) else []
    out: list[dict[str, float]] = []
    for row in rows:
        try:
            if isinstance(row, dict):
                ts = int(row.get("time") or row.get("openTime") or row.get("timestamp"))
                out.append({
                    "ts": ts,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or row.get("vol") or 0.0),
                })
            else:
                out.append({
                    "ts": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5] if len(row) > 5 else 0.0),
                })
        except Exception:
            continue
    return out


def _bars(symbol: str, interval: str, boundary_ms: int, now_ms: int) -> list[dict[str, float]]:
    interval_ms = INTERVAL_MS[interval]
    warmup_floor = boundary_ms - WARMUP_BARS * interval_ms
    all_rows: dict[int, dict[str, float]] = {}
    end = now_ms
    for _ in range(MAX_PAGES):
        page = sorted(_decode(_req({"symbol": symbol, "interval": interval, "limit": 1000, "endTime": end})), key=lambda x: x["ts"])
        if not page:
            break
        for row in page:
            ts = int(row["ts"])
            if ts + interval_ms <= now_ms:
                all_rows[ts] = row
        oldest = int(page[0]["ts"])
        if oldest <= warmup_floor:
            break
        if oldest >= end:
            break
        end = oldest - 1
        if len(page) < 900:
            break
    rows = [all_rows[k] for k in sorted(all_rows)]
    return [row for row in rows if int(row["ts"]) >= warmup_floor]


def _features(rows: list[dict[str, float]], spec: Mapping[str, Any]) -> tuple[dict[str, list[float | None]], Expr]:
    features: dict[str, list[float | None]] = {}
    engine = Expr(rows, features)
    for raw in spec.get("features") or []:
        if not isinstance(raw, Mapping):
            raise RuntimeError("FEATURE_OBJECT_REQUIRED")
        name = str(raw.get("name") or "").strip()
        formula = _feature_formula(str(raw.get("formula") or ""))
        if not name or not formula:
            raise RuntimeError("FEATURE_EMPTY")
        engine.validate(formula)
        arr: list[float | None] = []
        features[name] = arr
        for i in range(len(rows)):
            try:
                value = engine.eval(formula, i)
                arr.append(float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None)
            except (TypeError, ZeroDivisionError, ValueError):
                arr.append(None)
    return features, Expr(rows, features)


def _closed_trades(child: Mapping[str, Any], boundary_ms: int, now_ms: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    child_id = str(child.get("child_id") or "")
    spec = child.get("executable_spec")
    if not child_id or not isinstance(spec, Mapping):
        raise RuntimeError("CHILD_SPEC_REQUIRED")
    interval = str(spec.get("bar_interval") or "")
    if interval not in INTERVAL_MS:
        raise RuntimeError(f"UNSUPPORTED_INTERVAL:{interval}")
    hold = int(spec.get("max_hold_bars") or 0)
    if hold <= 0:
        raise RuntimeError("HOLD_REQUIRED")
    entry_rule = str(spec.get("entry_rule") or "")
    side_rule = str(spec.get("side_rule") or "")
    cost_bps = float(spec.get("cost_bps_per_trade") or 0.0)
    if abs(cost_bps - 14.0) > 1e-12:
        raise RuntimeError("COST_DRIFT")

    trades: list[dict[str, Any]] = []
    source: dict[str, Any] = {}
    for symbol in SYMBOLS:
        rows = _bars(symbol, interval, boundary_ms, now_ms)
        source[symbol] = {
            "closed_bars": len(rows),
            "first_bar_ts": int(rows[0]["ts"]) if rows else None,
            "last_bar_ts": int(rows[-1]["ts"]) if rows else None,
        }
        if len(rows) < 60:
            continue
        _, engine = _features(rows, spec)
        engine.validate(entry_rule)
        _validate_side(side_rule, engine)
        i = 50
        while i < len(rows) - 1:
            signal_ts = int(rows[i]["ts"])
            if signal_ts < boundary_ms:
                i += 1
                continue
            try:
                fire = bool(engine.eval(entry_rule, i))
            except (TypeError, ZeroDivisionError, ValueError):
                fire = False
            if not fire:
                i += 1
                continue
            side = _side(side_rule, engine, i)
            if side not in {"long", "short"}:
                raise RuntimeError("SIDE_RULE_UNSUPPORTED")
            entry_i = i + 1
            exit_i = entry_i + hold - 1
            if exit_i >= len(rows):
                break
            entry_px = float(rows[entry_i]["open"])
            exit_px = float(rows[exit_i]["close"])
            gross = (exit_px / entry_px - 1.0) * 10000.0 * (1.0 if side == "long" else -1.0)
            net = gross - cost_bps
            payload = {
                "child_id": child_id,
                "symbol": symbol,
                "side": side,
                "signal_ts": signal_ts,
                "entry_ts": int(rows[entry_i]["ts"]),
                "exit_ts": int(rows[exit_i]["ts"]),
            }
            trade_id = _sha(payload)
            trades.append({
                "closed_trade_id": trade_id,
                **payload,
                "entry_px": entry_px,
                "exit_px": exit_px,
                "gross_bps": gross,
                "net_bps": net,
                "cost_bps": cost_bps,
            })
            i = exit_i + 1
    trades.sort(key=lambda x: (x["exit_ts"], x["signal_ts"], x["symbol"], x["closed_trade_id"]))
    ids = [x["closed_trade_id"] for x in trades]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"DUPLICATE_CHILD_TRADE_ID:{child_id}")
    return trades, source


def _metrics(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    net = [float(x["net_bps"]) for x in trades]
    gp = sum(x for x in net if x > 0)
    gl = -sum(x for x in net if x < 0)
    eq = peak = dd = 0.0
    for value in net:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "closed_T": len(net),
        "win_rate": (sum(1 for x in net if x > 0) / len(net)) if net else None,
        "net_expectancy_bps": (sum(net) / len(net)) if net else None,
        "net_pnl_bps": sum(net),
        "profit_factor": (gp / gl) if gl > 0 else None,
        "drawdown_bps": dd,
        "cost_bps_per_trade": 14.0,
    }


def _previous_ids(previous: Mapping[str, Any] | None, lane_id: str) -> set[str]:
    if not isinstance(previous, Mapping) or previous.get("schema_version") != SCHEMA:
        return set()
    lane = (previous.get("lanes") or {}).get(lane_id)
    if not isinstance(lane, Mapping):
        return set()
    return {str(x.get("closed_trade_id")) for x in lane.get("closed_trades") or [] if isinstance(x, Mapping) and x.get("closed_trade_id")}


def run(output: Path, previous_path: Path | None = None, now_ms: int | None = None) -> dict[str, Any]:
    contract = _read(CONTRACT)
    if contract.get("schema_version") != "zel.a1.top5.replacement_child_freeze.v1":
        raise RuntimeError("FREEZE_CONTRACT_SCHEMA_DRIFT")
    if contract.get("state") != "FROZEN_REPLACEMENT_CHILDREN_PRE_PROSPECTIVE":
        raise RuntimeError("FREEZE_CONTRACT_STATE_DRIFT")
    boundary = contract.get("prospective_boundary")
    if not isinstance(boundary, Mapping):
        raise RuntimeError("BOUNDARY_REQUIRED")
    boundary_ms = int(boundary.get("ms") or 0)
    if boundary_ms <= 0:
        raise RuntimeError("BOUNDARY_MS_REQUIRED")
    rules = contract.get("global_rules") or {}
    for key in ("child_T_starts_at_zero", "old_parent_raw_observer_is_burned_non_consumable", "architecture_mutation_after_freeze", "same_trade_parent_and_child_reuse"):
        expected = key in {"child_T_starts_at_zero", "old_parent_raw_observer_is_burned_non_consumable"}
        if bool(rules.get(key)) is not expected:
            raise RuntimeError(f"FREEZE_RULE_DRIFT:{key}")
    if rules.get("old_history_union") is not False or rules.get("post_result_retune") is not False or rules.get("threshold_sweep") is not False:
        raise RuntimeError("CONTAMINATION_RULE_DRIFT")

    children = contract.get("children") or []
    if not isinstance(children, list) or len(children) != 3:
        raise RuntimeError("EXACT_THREE_CHILDREN_REQUIRED")
    if len({str(x.get("lane_id")) for x in children if isinstance(x, Mapping)}) != 3:
        raise RuntimeError("DISTINCT_CHILD_LANES_REQUIRED")
    if any(int((x or {}).get("prospective_child_T_at_freeze") or -1) != 0 for x in children if isinstance(x, Mapping)):
        raise RuntimeError("CHILD_MUST_START_AT_ZERO")

    current_ms = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    previous = _read(previous_path) if previous_path and previous_path.is_file() else (_read(LATEST) if LATEST.is_file() else None)
    lanes: dict[str, Any] = {}
    total_new = 0
    for child in children:
        if not isinstance(child, Mapping):
            raise RuntimeError("CHILD_OBJECT_REQUIRED")
        lane_id = str(child.get("lane_id") or "")
        burned = {str(x) for x in child.get("burned_parent_raw_observer_closed_trade_ids") or [] if str(x)}
        if len(burned) != int(child.get("burned_parent_raw_observer_T") or 0):
            raise RuntimeError(f"BURNED_PARENT_COUNT_DRIFT:{lane_id}")
        trades, source = _closed_trades(child, boundary_ms, current_ms) if current_ms >= boundary_ms else ([], {})
        child_ids = {str(x["closed_trade_id"]) for x in trades}
        if child_ids & burned:
            raise RuntimeError(f"PARENT_CHILD_TRADE_ID_REUSE:{lane_id}")
        if any(int(x["signal_ts"]) < boundary_ms for x in trades):
            raise RuntimeError(f"PREBOUNDARY_CHILD_TRADE:{lane_id}")
        prior = _previous_ids(previous, lane_id)
        if not prior.issubset(child_ids):
            raise RuntimeError(f"APPEND_ONLY_CHILD_HISTORY_REGRESSION:{lane_id}")
        new_ids = sorted(child_ids - prior)
        total_new += len(new_ids)
        lanes[lane_id] = {
            "parent_strategy_id": child.get("parent_strategy_id"),
            "child_id": child.get("child_id"),
            "architecture_family": child.get("architecture_family"),
            "boundary_ms": boundary_ms,
            "boundary_utc": boundary.get("utc"),
            "replacement_child_frozen": True,
            "old_parent_raw_observer_burned_T": len(burned),
            "old_parent_raw_observer_consumed_T": 0,
            "closed_trades": trades,
            "closed_T": len(trades),
            "new_closed_trade_ids": new_ids,
            "new_closed_T": len(new_ids),
            "metrics": _metrics(trades),
            "source_summary": source,
            "next": "ACCUMULATE_FRESH_PROSPECTIVE_CHILD_T_ONLY",
        }

    state = "WAIT_PROSPECTIVE_BOUNDARY" if current_ms < boundary_ms else "PASS_PROSPECTIVE_CHILD_COLLECTION_ACTIVE"
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.fromtimestamp(current_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "boundary_ms": boundary_ms,
        "boundary_utc": boundary.get("utc"),
        "boundary_reached": current_ms >= boundary_ms,
        "lane_count": 3,
        "total_closed_T": sum(int(x["closed_T"]) for x in lanes.values()),
        "total_new_closed_T": total_new,
        "parent_observer_consumed_T": 0,
        "old_history_union": False,
        "post_result_retune": False,
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        "lanes": lanes,
        **AUTH,
    }
    result["receipt_sha256"] = _sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    contract = _read(CONTRACT)
    children = contract["children"]
    assert len(children) == 3
    assert int(contract["prospective_boundary"]["ms"]) == 1788030000000
    assert sum(int(x["burned_parent_raw_observer_T"]) for x in children) == 15
    assert all(int(x["prospective_child_T_at_freeze"]) == 0 for x in children)
    assert all(float(x["executable_spec"]["cost_bps_per_trade"]) == 14.0 for x in children)
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED" and AUTH["live_trade_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_REPLACEMENT_CHILD_PROSPECTIVE_V1_SELF_TEST")
    print("PASS_15_PARENT_RAW_OBSERVERS_BURNED_AND_CHILD_T_ZERO_AT_FREEZE")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("out/a1_top5_replacement_child_prospective_latest.json"))
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output, args.previous)
    print(json.dumps({
        "state": result["state"],
        "boundary_reached": result["boundary_reached"],
        "total_closed_T": result["total_closed_T"],
        "total_new_closed_T": result["total_new_closed_T"],
        "lane_T": {k: v["closed_T"] for k, v in result["lanes"].items()},
        "paid_provider_calls": result["paid_provider_calls"],
        "receipt": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
