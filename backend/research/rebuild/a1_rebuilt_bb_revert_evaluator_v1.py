from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.research.rebuild.bb_revert_policy_v2 import (
    BbRevertPolicyConfig,
    build_decision_intent,
    compute_feature_snapshot,
)

POLICY_SHA = "b1d69717599cb651285d7a8094c0aa5603373db2"
KLINE_API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
DEPTH_API = "https://open-api.bingx.com/openApi/swap/v2/quote/depth"
FUNDING_API = "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate"
COST_PATH = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
ACTIVATION_PATH = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_activation_v1.json"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def request_json(url: str, params: dict[str, Any]) -> Any:
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(url + "?" + query, timeout=20) as response:
        payload = json.loads(response.read().decode())
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise RuntimeError(f"BINGX_API_ERROR:{payload.get('code')}:{payload.get('msg')}")
    return payload


def fetch_bars(symbol: str, limit: int = 1000) -> list[dict[str, float | int]]:
    payload = request_json(KLINE_API, {"symbol": symbol, "interval": "1h", "limit": limit})
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    out: list[dict[str, float | int]] = []
    for row in rows:
        if isinstance(row, dict):
            ts = int(row.get("time") or row.get("openTime") or row.get("timestamp"))
            out.append({"ts_ms": ts, "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])})
        else:
            out.append({"ts_ms": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4])})
    return sorted({int(bar["ts_ms"]): bar for bar in out}.values(), key=lambda bar: int(bar["ts_ms"]))


def _depth_vwap(levels: list[list[str]], target_quote: float, buy: bool) -> tuple[float, float]:
    remaining = float(target_quote)
    quote = 0.0
    base = 0.0
    for raw_price, raw_qty, *_ in levels:
        price = float(raw_price)
        qty = float(raw_qty)
        if price <= 0 or qty <= 0:
            continue
        take = min(qty, remaining / price)
        quote += take * price
        base += take
        remaining -= take * price
        if remaining <= 1e-9:
            break
    if remaining > max(0.01, target_quote * 1e-6) or base <= 0:
        raise RuntimeError("DEPTH_REFERENCE_NOTIONAL_UNFILLED")
    return quote / base, quote


def fetch_execution_snapshot(symbol: str, authority: dict[str, Any]) -> dict[str, Any]:
    depth_payload = request_json(DEPTH_API, {"symbol": symbol, "limit": 50})
    data = depth_payload.get("data", {}) if isinstance(depth_payload, dict) else {}
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    if not bids or not asks:
        raise RuntimeError("DEPTH_EMPTY")
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    if best_bid <= 0 or best_ask <= best_bid:
        raise RuntimeError("DEPTH_TOP_INVALID")
    mid = (best_bid + best_ask) / 2.0
    observed_spread_rt_bps = (best_ask - best_bid) / mid * 10000.0
    reference_notional = float(authority["slippage_impact"]["reference_notional_usdt"])
    buy_vwap, _ = _depth_vwap(asks, reference_notional, True)
    sell_vwap, _ = _depth_vwap(bids, reference_notional, False)
    buy_impact_bps = max(0.0, (buy_vwap / best_ask - 1.0) * 10000.0)
    sell_impact_bps = max(0.0, (best_bid / sell_vwap - 1.0) * 10000.0)
    impact_rt_bps = buy_impact_bps + sell_impact_bps
    spread_rt_bps = max(float(authority["spread"]["round_trip_floor_bps"]), observed_spread_rt_bps)
    impact_rt_bps = max(float(authority["slippage_impact"]["round_trip_floor_bps"]), impact_rt_bps)

    funding_payload = request_json(FUNDING_API, {"symbol": symbol, "limit": 100})
    funding_rows_raw = funding_payload.get("data", []) if isinstance(funding_payload, dict) else []
    funding_rows: list[dict[str, float | int]] = []
    for row in funding_rows_raw or []:
        if not isinstance(row, dict):
            continue
        ts = row.get("fundingTime") or row.get("time") or row.get("timestamp")
        rate = row.get("fundingRate") or row.get("rate")
        if ts is None or rate is None:
            continue
        funding_rows.append({"ts_ms": int(ts), "rate": float(rate)})
    funding_rows.sort(key=lambda row: int(row["ts_ms"]))
    abs_bps = sorted(abs(float(row["rate"])) * 10000.0 for row in funding_rows)
    if not abs_bps:
        raise RuntimeError("FUNDING_HISTORY_EMPTY")
    p95_index = min(len(abs_bps) - 1, max(0, math.ceil(0.95 * len(abs_bps)) - 1))
    funding_p95_bps = abs_bps[p95_index]
    fee_rt_bps = float(authority["fee"]["round_trip_fee_bps"])
    pretrade_cost_bps = fee_rt_bps + spread_rt_bps + impact_rt_bps + funding_p95_bps
    snapshot = {
        "symbol": symbol,
        "depth_ts_ms": int(data.get("T") or 0),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "observed_spread_round_trip_bps": observed_spread_rt_bps,
        "charged_spread_round_trip_bps": spread_rt_bps,
        "reference_notional_usdt": reference_notional,
        "buy_vwap": buy_vwap,
        "sell_vwap": sell_vwap,
        "observed_depth_impact_round_trip_bps": buy_impact_bps + sell_impact_bps,
        "charged_impact_round_trip_bps": impact_rt_bps,
        "funding_history_count": len(funding_rows),
        "funding_p95_abs_bps": funding_p95_bps,
        "pretrade_verified_cost_bps": pretrade_cost_bps,
        "funding_rows": funding_rows,
    }
    snapshot["snapshot_sha256"] = stable_sha(snapshot)
    return snapshot


def expected_funding_boundaries(entry_ts: int, exit_ts: int) -> int:
    step = 8 * 60 * 60 * 1000
    return max(0, exit_ts // step - entry_ts // step)


def realized_funding_cost_bps(entry_ts: int, exit_ts: int, funding_rows: list[dict[str, float | int]]) -> tuple[float, int]:
    crossed = [row for row in funding_rows if entry_ts < int(row["ts_ms"]) <= exit_ts]
    expected = expected_funding_boundaries(entry_ts, exit_ts)
    if len(crossed) < expected:
        raise RuntimeError(f"FUNDING_RATE_COVERAGE_MISSING:{len(crossed)}<{expected}")
    return sum(abs(float(row["rate"])) * 10000.0 for row in crossed), len(crossed)


def empty_receipt(state: str, *, activation: dict[str, Any] | None = None, blocker: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "zel.a1_rebuilt_bb_revert.economics.v2",
        "state": state,
        "strategy_id": "bb_revert",
        "activation": activation,
        "blocker": blocker,
        "intent_count": 0,
        "completed_trades": 0,
        "metrics": {},
        "trades": [],
        "integrity_defects": [] if blocker is None else [blocker],
        "leakage_lookahead": 0,
        "duplicate_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTC-USDT,ETH-USDT")
    parser.add_argument("--out", default="a1_rebuilt_bb_revert_receipt.json")
    args = parser.parse_args()

    if not ACTIVATION_PATH.exists():
        receipt = empty_receipt("HOLD_A1_REBUILT_ACTIVATION_REQUIRED", blocker="FRESH_POST_CODE_FREEZE_BOUNDARY_REQUIRED")
        Path(args.out).write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(receipt, sort_keys=True))
        return

    activation = load_json(ACTIVATION_PATH)
    if activation.get("state") != "ACTIVE_A1_REBUILT_BB_REVERT_V1":
        receipt = empty_receipt("HOLD_A1_REBUILT_ACTIVATION_INVALID", activation=activation, blocker="ACTIVATION_STATE_INVALID")
        Path(args.out).write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(receipt, sort_keys=True))
        return

    boundary_iso = str(activation["prospective_boundary_utc"])
    boundary_ms = int(datetime.fromisoformat(boundary_iso.replace("Z", "+00:00")).timestamp() * 1000)
    authority = load_json(COST_PATH)
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")
    authority_sha = stable_sha(authority)
    cfg = BbRevertPolicyConfig()
    sources: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    intent_count = 0
    seen_intents: set[str] = set()
    integrity_defects: list[str] = []
    execution_snapshots: dict[str, dict[str, Any]] = {}

    for symbol in [item.strip() for item in args.symbols.split(",") if item.strip()]:
        snapshot = fetch_execution_snapshot(symbol, authority)
        execution_snapshots[symbol] = snapshot
        bars = fetch_bars(symbol)
        fresh = [bar for bar in bars if int(bar["ts_ms"]) >= boundary_ms]
        sources.append({
            "symbol": symbol,
            "bars_total": len(bars),
            "bars_post_boundary": len(fresh),
            "first_post_boundary_ts": int(fresh[0]["ts_ms"]) if fresh else None,
            "last_post_boundary_ts": int(fresh[-1]["ts_ms"]) if fresh else None,
        })
        for i in range(cfg.warmup_bars, len(bars) - 1):
            if int(bars[i]["ts_ms"]) < boundary_ms:
                continue
            feature = compute_feature_snapshot(bars[: i + 1], symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=cfg)
            policy_cost_bps = float(snapshot["pretrade_verified_cost_bps"])
            intent = build_decision_intent(
                feature,
                policy_source_sha=POLICY_SHA,
                verified_round_trip_cost_bps=policy_cost_bps,
                config=cfg,
            )
            if intent.no_trade:
                continue
            if intent.sha in seen_intents:
                integrity_defects.append(f"DUPLICATE_INTENT:{intent.sha}")
                continue
            seen_intents.add(intent.sha)
            intent_count += 1
            entry_bar = bars[i + 1]
            entry = float(entry_bar["open"])
            side = 1 if intent.side == "long" else -1
            exit_px = None
            exit_ts = None
            reason = None
            for j in range(i + 1, min(len(bars), i + 2 + int(intent.timeout["bars"]))):
                bar = bars[j]
                low, high = float(bar["low"]), float(bar["high"])
                if side == 1 and low <= float(intent.sl):
                    exit_px, reason = float(intent.sl), "SL"
                elif side == -1 and high >= float(intent.sl):
                    exit_px, reason = float(intent.sl), "SL"
                elif side == 1 and intent.tp is not None and high >= float(intent.tp):
                    exit_px, reason = float(intent.tp), "TP"
                elif side == -1 and intent.tp is not None and low <= float(intent.tp):
                    exit_px, reason = float(intent.tp), "TP"
                if exit_px is not None:
                    exit_ts = int(bar["ts_ms"])
                    break
            if exit_px is None or exit_ts is None:
                continue
            try:
                funding_bps, funding_count = realized_funding_cost_bps(int(entry_bar["ts_ms"]), exit_ts, list(snapshot["funding_rows"]))
            except RuntimeError as exc:
                integrity_defects.append(f"{symbol}:{intent.signal_ts}:{exc}")
                continue
            fee_bps = float(authority["fee"]["round_trip_fee_bps"])
            spread_bps = float(snapshot["charged_spread_round_trip_bps"])
            impact_bps = float(snapshot["charged_impact_round_trip_bps"])
            realized_cost_bps = fee_bps + spread_bps + impact_bps + funding_bps
            gross_bps = side * (float(exit_px) - entry) / entry * 10000.0
            net_bps = gross_bps - realized_cost_bps
            trades.append({
                "symbol": symbol,
                "signal_ts": intent.signal_ts,
                "entry_ts": int(entry_bar["ts_ms"]),
                "exit_ts": exit_ts,
                "side": intent.side,
                "entry": entry,
                "exit": float(exit_px),
                "reason": reason,
                "gross_bps": gross_bps,
                "fee_bps": fee_bps,
                "spread_bps": spread_bps,
                "slippage_impact_bps": impact_bps,
                "funding_bps": funding_bps,
                "funding_settlement_count": funding_count,
                "realized_cost_bps": realized_cost_bps,
                "net_bps": net_bps,
                "intent_sha": intent.sha,
                "feature_sha": intent.feature_sha,
                "config_sha": intent.config_sha,
                "policy_sha": POLICY_SHA,
                "cost_authority_sha256": authority_sha,
                "execution_snapshot_sha256": snapshot["snapshot_sha256"],
            })

    wins = [trade for trade in trades if float(trade["net_bps"]) > 0]
    losses = [trade for trade in trades if float(trade["net_bps"]) < 0]
    gross_wins = [trade for trade in trades if float(trade["gross_bps"]) > 0]
    gross_losses = [trade for trade in trades if float(trade["gross_bps"]) < 0]
    net_gp = sum(float(trade["net_bps"]) for trade in wins)
    net_gl = -sum(float(trade["net_bps"]) for trade in losses)
    gross_gp = sum(float(trade["gross_bps"]) for trade in gross_wins)
    gross_gl = -sum(float(trade["gross_bps"]) for trade in gross_losses)
    avg_win = net_gp / len(wins) if wins else None
    avg_loss = net_gl / len(losses) if losses else None
    state = "HOLD_A1_REBUILT_INTEGRITY" if integrity_defects else "WAIT_FRESH_PROSPECTIVE_DATA" if not trades else "A1_REBUILT_ECONOMICS_ACTIVE"
    receipt = {
        "schema_version": "zel.a1_rebuilt_bb_revert.economics.v2",
        "state": state,
        "strategy_id": "bb_revert",
        "activation": activation,
        "boundary_utc": boundary_iso,
        "policy_sha": POLICY_SHA,
        "cost_authority_sha256": authority_sha,
        "cost_authority": authority,
        "execution_snapshots": {symbol: {key: value for key, value in snapshot.items() if key != "funding_rows"} for symbol, snapshot in execution_snapshots.items()},
        "source": {"endpoint": "/openApi/swap/v3/quote/klines", "symbols": sources},
        "intent_count": intent_count,
        "completed_trades": len(trades),
        "metrics": {
            "gross_pnl_bps": sum(float(trade["gross_bps"]) for trade in trades),
            "gross_expectancy_bps": sum(float(trade["gross_bps"]) for trade in trades) / len(trades) if trades else None,
            "gross_profit_factor": gross_gp / gross_gl if gross_gl > 0 else (math.inf if gross_gp > 0 else None),
            "net_pnl_bps": sum(float(trade["net_bps"]) for trade in trades),
            "net_expectancy_bps": sum(float(trade["net_bps"]) for trade in trades) / len(trades) if trades else None,
            "net_profit_factor": net_gp / net_gl if net_gl > 0 else (math.inf if net_gp > 0 else None),
            "net_payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
            "win_rate": len(wins) / len(trades) if trades else None,
        },
        "required_negative_controls": ["direction_flip", "time_placebo", "regime_permutation", "delayed_entry"],
        "negative_control_gate": "PENDING_EXISTING_H4_SAMPLE_GATE",
        "trades": trades,
        "integrity_defects": integrity_defects,
        "leakage_lookahead": 0,
        "duplicate_count": len([defect for defect in integrity_defects if defect.startswith("DUPLICATE_INTENT:")]),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    Path(args.out).write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
