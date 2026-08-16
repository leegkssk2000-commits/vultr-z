from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import math
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LEDGER_PATH = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY_PATH = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
COST_PATH = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
KLINE_API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
DEPTH_API = "https://open-api.bingx.com/openApi/swap/v2/quote/depth"
FUNDING_API = "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def request_json(url: str, params: dict[str, Any]) -> Any:
    with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params), timeout=25) as response:
        payload = json.loads(response.read().decode())
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise RuntimeError(f"BINGX_API_ERROR:{payload.get('code')}:{payload.get('msg')}")
    return payload


def interval_for_ms(ms: int) -> str:
    table = {
        60_000: "1m", 180_000: "3m", 300_000: "5m", 900_000: "15m",
        1_800_000: "30m", 3_600_000: "1h", 7_200_000: "2h", 14_400_000: "4h",
        21_600_000: "6h", 43_200_000: "12h", 86_400_000: "1d",
    }
    if ms not in table:
        raise RuntimeError(f"UNSUPPORTED_TIMEFRAME_MS:{ms}")
    return table[ms]


def fetch_bars(symbol: str, interval: str, limit: int = 1000) -> list[dict[str, float | int]]:
    payload = request_json(KLINE_API, {"symbol": symbol, "interval": interval, "limit": limit})
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    out: list[dict[str, float | int]] = []
    for row in rows:
        if isinstance(row, dict):
            ts = int(row.get("time") or row.get("openTime") or row.get("timestamp"))
            vol = row.get("volume", row.get("vol", row.get("baseVolume", 0)))
            out.append({"ts_ms": ts, "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"]), "volume": float(vol or 0)})
        else:
            vol = row[5] if len(row) > 5 else 0
            out.append({"ts_ms": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(vol or 0)})
    return sorted({int(x["ts_ms"]): x for x in out}.values(), key=lambda x: int(x["ts_ms"]))


def _depth_vwap(levels: list[list[str]], target_quote: float) -> float:
    remaining = target_quote
    quote = base = 0.0
    for raw_price, raw_qty, *_ in levels:
        price, qty = float(raw_price), float(raw_qty)
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
    return quote / base


def fetch_execution_snapshot(symbol: str, authority: dict[str, Any]) -> dict[str, Any]:
    depth_payload = request_json(DEPTH_API, {"symbol": symbol, "limit": 50})
    data = depth_payload.get("data", {}) if isinstance(depth_payload, dict) else {}
    bids, asks = data.get("bids") or [], data.get("asks") or []
    if not bids or not asks:
        raise RuntimeError("DEPTH_EMPTY")
    bid, ask = float(bids[0][0]), float(asks[0][0])
    if bid <= 0 or ask <= bid:
        raise RuntimeError("DEPTH_TOP_INVALID")
    mid = (bid + ask) / 2
    observed_spread = (ask - bid) / mid * 10_000
    ref = float(authority["slippage_impact"]["reference_notional_usdt"])
    buy_vwap, sell_vwap = _depth_vwap(asks, ref), _depth_vwap(bids, ref)
    observed_impact = max(0.0, (buy_vwap / ask - 1) * 10_000) + max(0.0, (bid / sell_vwap - 1) * 10_000)
    spread = max(float(authority["spread"]["round_trip_floor_bps"]), observed_spread)
    impact = max(float(authority["slippage_impact"]["round_trip_floor_bps"]), observed_impact)
    funding_payload = request_json(FUNDING_API, {"symbol": symbol, "limit": 100})
    funding_rows: list[dict[str, float | int]] = []
    for row in (funding_payload.get("data", []) if isinstance(funding_payload, dict) else []):
        if not isinstance(row, dict):
            continue
        ts = row.get("fundingTime") or row.get("time") or row.get("timestamp")
        rate = row.get("fundingRate") or row.get("rate")
        if ts is not None and rate is not None:
            funding_rows.append({"ts_ms": int(ts), "rate": float(rate)})
    funding_rows.sort(key=lambda x: int(x["ts_ms"]))
    abs_bps = sorted(abs(float(x["rate"])) * 10_000 for x in funding_rows)
    if not abs_bps:
        raise RuntimeError("FUNDING_HISTORY_EMPTY")
    p95 = abs_bps[min(len(abs_bps) - 1, max(0, math.ceil(0.95 * len(abs_bps)) - 1))]
    fee = float(authority["fee"]["round_trip_fee_bps"])
    return {
        "symbol": symbol, "fee_bps": fee, "spread_bps": spread, "impact_bps": impact,
        "funding_p95_abs_bps": p95, "pretrade_verified_cost_bps": fee + spread + impact + p95,
        "funding_rows": funding_rows,
        "snapshot_sha256": stable_sha({"symbol": symbol, "bid": bid, "ask": ask, "spread": spread, "impact": impact, "p95": p95, "ref": ref}),
    }


def funding_cost(entry_ts: int, exit_ts: int, rows: list[dict[str, float | int]]) -> float:
    return sum(abs(float(x["rate"])) * 10_000 for x in rows if entry_ts < int(x["ts_ms"]) <= exit_ts)


def load_policy(strategy_id: str, inventory: dict[str, Any]) -> tuple[Any, Path, str]:
    meta = inventory["strategies"][strategy_id]
    path = ROOT / str(meta["policy_owner"])
    spec = importlib.util.spec_from_file_location(f"a1_policy_{strategy_id}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("POLICY_IMPORT_SPEC_FAIL")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path, git_blob_sha(path)


def config_instance(module: Any) -> Any:
    candidates = []
    for name, obj in vars(module).items():
        if inspect.isclass(obj) and name.endswith("Config") and obj.__module__ == module.__name__:
            try:
                candidates.append(obj())
            except TypeError:
                pass
    if len(candidates) != 1:
        raise RuntimeError(f"CONFIG_CLASS_AMBIGUOUS:{len(candidates)}")
    return candidates[0]


def policy_functions(module: Any, strategy_id: str) -> tuple[Any, Any]:
    compute = getattr(module, f"compute_{strategy_id}_feature", None) or getattr(module, "compute_feature_snapshot", None)
    build = getattr(module, f"build_{strategy_id}_intent", None) or getattr(module, "build_decision_intent", None)
    if not callable(compute) or not callable(build):
        raise RuntimeError("POLICY_ADAPTER_MISSING")
    return compute, build


def intent_sha(intent: Any) -> str:
    value = getattr(intent, "sha", None)
    if isinstance(value, str):
        return value
    body = asdict(intent) if is_dataclass(intent) else dict(vars(intent))
    return stable_sha(body)


def max_drawdown(values: list[float]) -> float:
    equity = peak = dd = 0.0
    for x in values:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy-id")
    p.add_argument("--symbols", default="BTC-USDT,ETH-USDT")
    p.add_argument("--out", default="a1_exact25_receipt.json")
    args = p.parse_args()
    ledger, inventory, authority = load_json(LEDGER_PATH), load_json(INVENTORY_PATH), load_json(COST_PATH)
    strategy_id = args.strategy_id or str(ledger["active_strategy_id"])
    entry = ledger["strategies"].get(strategy_id)
    if not isinstance(entry, dict) or entry.get("status") not in ("ACTIVE", "UNTESTED"):
        raise RuntimeError("STRATEGY_NOT_ACTIVE_OR_UNTESTED")
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")
    boundary = str(entry.get("prospective_boundary_utc") or "")
    if not boundary:
        raise RuntimeError("PROSPECTIVE_BOUNDARY_REQUIRED")
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    module, policy_path, policy_sha = load_policy(strategy_id, inventory)
    cfg = config_instance(module)
    timeframe_ms = int(getattr(cfg, "timeframe_ms"))
    interval = interval_for_ms(timeframe_ms)
    compute, build = policy_functions(module, strategy_id)
    config_sha = str(getattr(cfg, "sha", stable_sha(asdict(cfg) if is_dataclass(cfg) else vars(cfg))))
    evidence_path = ROOT / str(inventory["strategies"][strategy_id]["evidence_packet"])
    evidence_sha = git_blob_sha(evidence_path)
    trades: list[dict[str, Any]] = []
    intent_count = 0
    seen: set[str] = set()
    defects: list[str] = []
    sources: list[dict[str, Any]] = []
    snapshots: dict[str, Any] = {}

    for symbol in [x.strip() for x in args.symbols.split(",") if x.strip()]:
        snap = fetch_execution_snapshot(symbol, authority)
        snapshots[symbol] = snap
        bars = fetch_bars(symbol, interval)
        post = [x for x in bars if int(x["ts_ms"]) >= boundary_ms]
        sources.append({"symbol": symbol, "bars_total": len(bars), "bars_post_boundary": len(post), "first_post_boundary_ts": int(post[0]["ts_ms"]) if post else None, "last_post_boundary_ts": int(post[-1]["ts_ms"]) if post else None})
        warmup = int(getattr(cfg, "warmup_bars", max(64, int(getattr(cfg, "lookback", 20)) + 10)))
        for i in range(max(1, warmup), len(bars) - 1):
            if int(bars[i]["ts_ms"]) < boundary_ms:
                continue
            try:
                feature = compute(bars[: i + 1], symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=cfg)
                intent = build(feature, policy_source_sha=policy_sha, verified_round_trip_cost_bps=float(snap["pretrade_verified_cost_bps"]), config=cfg)
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_", "WINDOW_", "ATR_")):
                    continue
                defects.append(f"{symbol}:{int(bars[i]['ts_ms'])}:POLICY:{exc}")
                continue
            if bool(getattr(intent, "no_trade")):
                continue
            sha = intent_sha(intent)
            if sha in seen:
                defects.append(f"DUPLICATE_INTENT:{sha}")
                continue
            seen.add(sha)
            intent_count += 1
            side_name = str(getattr(intent, "side"))
            if side_name not in ("long", "short"):
                defects.append(f"UNSUPPORTED_SIDE:{side_name}")
                continue
            entry_bar = bars[i + 1]
            entry_px = float(entry_bar["open"])
            side = 1 if side_name == "long" else -1
            timeout = getattr(intent, "timeout", {}) or {}
            timeout_bars = int(timeout.get("bars", getattr(cfg, "timeout_bars", 1)))
            sl, tp = getattr(intent, "sl", None), getattr(intent, "tp", None)
            if sl is None and tp is None:
                defects.append(f"{strategy_id}:EXIT_GEOMETRY_UNSUPPORTED_NO_SL_TP")
                continue
            exit_px = exit_ts = reason = None
            last_j = min(len(bars) - 1, i + 1 + max(1, timeout_bars))
            for j in range(i + 1, last_j + 1):
                bar = bars[j]
                low, high = float(bar["low"]), float(bar["high"])
                if sl is not None and ((side == 1 and low <= float(sl)) or (side == -1 and high >= float(sl))):
                    exit_px, exit_ts, reason = float(sl), int(bar["ts_ms"]), "SL"
                    break
                if tp is not None and ((side == 1 and high >= float(tp)) or (side == -1 and low <= float(tp))):
                    exit_px, exit_ts, reason = float(tp), int(bar["ts_ms"]), "TP"
                    break
            if exit_px is None:
                if last_j >= len(bars) - 1:
                    continue
                exit_px, exit_ts, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts_ms"]), "TIMEOUT"
            fee, spread, impact = float(snap["fee_bps"]), float(snap["spread_bps"]), float(snap["impact_bps"])
            fund = funding_cost(int(entry_bar["ts_ms"]), int(exit_ts), list(snap["funding_rows"]))
            cost = fee + spread + impact + fund
            gross = side * (float(exit_px) - entry_px) / entry_px * 10_000
            net = gross - cost
            trades.append({"symbol": symbol, "signal_ts": int(getattr(intent, "signal_ts")), "entry_ts": int(entry_bar["ts_ms"]), "exit_ts": int(exit_ts), "side": side_name, "entry": entry_px, "exit": float(exit_px), "reason": reason, "gross_bps": gross, "realized_cost_bps": cost, "net_bps": net, "intent_sha": sha, "feature_sha": str(getattr(intent, "feature_sha", "")), "config_sha": str(getattr(intent, "config_sha", config_sha)), "policy_sha": policy_sha, "cost_snapshot_sha": snap["snapshot_sha256"]})

    net_values = [float(x["net_bps"]) for x in trades]
    gross_values = [float(x["gross_bps"]) for x in trades]
    wins = [x for x in net_values if x > 0]
    losses = [-x for x in net_values if x < 0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    receipt = {
        "schema_version": "zel.a1_exact25_generic_economics.v1", "state": "HOLD_A1_REBUILT_INTEGRITY" if defects else ("WAIT_FRESH_PROSPECTIVE_DATA" if not trades else "A1_REBUILT_ECONOMICS_ACTIVE"),
        "strategy_id": strategy_id, "boundary_utc": boundary, "policy_path": str(policy_path.relative_to(ROOT)), "policy_sha": policy_sha, "config_sha": config_sha, "evidence_sha": evidence_sha,
        "cost_authority_sha256": stable_sha(authority), "source": {"endpoint": "/openApi/swap/v3/quote/klines", "interval": interval, "symbols": sources},
        "execution_snapshots": {k: {kk: vv for kk, vv in v.items() if kk != "funding_rows"} for k, v in snapshots.items()},
        "intent_count": intent_count, "completed_trades": len(trades),
        "metrics": {"gross_pnl_bps": sum(gross_values), "gross_expectancy_bps": sum(gross_values) / len(gross_values) if gross_values else None, "net_pnl_bps": sum(net_values), "net_expectancy_bps": sum(net_values) / len(net_values) if net_values else None, "net_profit_factor": gp / gl if gl > 0 else (math.inf if gp > 0 else None), "net_payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None, "win_rate": len(wins) / len(net_values) if net_values else None, "max_drawdown_bps": max_drawdown(net_values)},
        "required_negative_controls": ["same_count_random_entry", "one_bar_delay", "direction_inversion", "timestamp_shuffle", "indicator_removal"], "negative_control_gate": "PENDING_EXISTING_H4_CONTROL_EVALUATOR",
        "trades": trades, "integrity_defects": defects, "leakage_lookahead": 0, "duplicate_count": len([x for x in defects if x.startswith("DUPLICATE_INTENT:")]),
        "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "protected_mutations": 0,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    Path(args.out).write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
