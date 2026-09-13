#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = ROOT / "research/development_evidence/G4_SCALP_INTRADAY_REBASE_V1"
CONTRACT_PATH = EVIDENCE_ROOT / "ROUND1_CONTRACT.json"
FAST_CHILD_PATH = EVIDENCE_ROOT / "FAST_CHILD_FREEZE_V1.json"
ROUND0_PATH = EVIDENCE_ROOT / "ROUND0_RESULT.json"
DEFAULT_LANES = EVIDENCE_ROOT / "ROUND1_NATIVE/LANES"
DEFAULT_AGG = EVIDENCE_ROOT / "ROUND1_NATIVE/RESULT.json"
KLINE_API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
TF_MS = 300_000
WARMUP_BARS = 320
POST_WINDOW_BARS = 48
MAX_PAGES = 80
POLICY_COST_BPS = 14.0
COST2_BPS = 28.0
SCHEMA = "zel.g4_scalp_intraday_rebase.round1_native_lane.v1"
AGG_SCHEMA = "zel.g4_scalp_intraday_rebase.round1_native_result.v1"

GROUPS: dict[str, dict[str, Any]] = {
    "microstructure": {
        "module": "backend.research.rebuild.microstructure_policy_batch_v1",
        "config": "MicroPolicyConfig",
        "strategies": ["liquidity_sweep", "scalp_snap", "vol_spike_fade"],
        "context_bars": 80,
    },
    "reversal_range": {
        "module": "backend.research.rebuild.reversal_range_policy_batch_v1",
        "config": "ReversalRangeConfig",
        "strategies": ["range_fade", "fvg_revert", "pivot_reversal", "rsi_swing_fail"],
        "context_bars": 80,
    },
    "indicator_core": {
        "module": "backend.research.rebuild.indicator_core_policy_batch_v1",
        "config": "IndicatorCoreConfig",
        "strategies": ["alpha_combo", "ema_ribbon_scalp", "mfi_rsi_div", "obv_trend"],
        "context_bars": 256,
    },
    "final_four": {
        "module": "backend.research.rebuild.final_four_policy_batch_v1",
        "config": "FinalFourConfig",
        "strategies": ["grid_rebalance", "rbreaker_like", "session_bias", "sr_levels"],
        "context_bars": 180,
    },
}

LANE_ORDER = [
    "liquidity_sweep", "scalp_snap", "vol_spike_fade", "ema_ribbon_scalp",
    "session_bias", "sr_levels", "rbreaker_like", "pivot_reversal",
    "range_fade", "fvg_revert", "rsi_swing_fail", "alpha_combo",
    "obv_trend", "mfi_rsi_div", "grid_rebalance",
]


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(float(x) for x in values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * float(p)
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    w = pos - lo
    return xs[lo] * (1.0 - w) + xs[hi] * w


def request_json(params: Mapping[str, Any]) -> Any:
    url = KLINE_API + "?" + urllib.parse.urlencode(dict(params))
    last: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                value = json.loads(response.read().decode("utf-8"))
            if isinstance(value, dict) and value.get("code") not in (None, 0):
                raise RuntimeError(f"BINGX:{value.get('code')}:{value.get('msg')}")
            return value
        except Exception as exc:
            last = exc
            if attempt >= 4:
                break
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"BINGX_REQUEST_FAILED:{last}")


def decode(value: Any) -> list[dict[str, float | int]]:
    rows = value.get("data", value if isinstance(value, list) else []) if isinstance(value, (dict, list)) else []
    out: list[dict[str, float | int]] = []
    for row in rows:
        try:
            if isinstance(row, dict):
                ts = int(row.get("time") or row.get("openTime") or row.get("timestamp"))
                out.append({
                    "ts_ms": ts,
                    "open": float(row["open"]), "high": float(row["high"]),
                    "low": float(row["low"]), "close": float(row["close"]),
                    "volume": float(row.get("volume") or row.get("vol") or row.get("baseVolume") or 0.0),
                })
            else:
                out.append({
                    "ts_ms": int(row[0]), "open": float(row[1]), "high": float(row[2]),
                    "low": float(row[3]), "close": float(row[4]),
                    "volume": float(row[5] if len(row) > 5 else 0.0),
                })
        except Exception:
            continue
    return out


def validate_source(rows: Sequence[Mapping[str, Any]], *, required_start: int, required_end: int) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("SOURCE_EMPTY")
    seen: set[int] = set()
    duplicate = 0
    ohlc_fail = 0
    negative_volume = 0
    gaps: list[list[int]] = []
    prev: int | None = None
    for row in rows:
        ts = int(row["ts_ms"])
        if ts in seen:
            duplicate += 1
        seen.add(ts)
        o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        v = float(row.get("volume", 0.0))
        if o <= 0 or h <= 0 or l <= 0 or c <= 0 or h < max(o, c) or l > min(o, c) or h < l:
            ohlc_fail += 1
        if v < 0:
            negative_volume += 1
        if prev is not None and ts - prev != TF_MS:
            gaps.append([prev, ts])
        prev = ts
    first = int(rows[0]["ts_ms"]); last = int(rows[-1]["ts_ms"])
    coverage_ok = first <= required_start and last >= required_end - TF_MS
    ok = duplicate == 0 and ohlc_fail == 0 and negative_volume == 0 and not gaps and coverage_ok
    return {
        "pass": ok, "bars": len(rows), "first_ts": first, "last_ts": last,
        "duplicates": duplicate, "ohlc_failures": ohlc_fail,
        "negative_volume": negative_volume, "gap_count": len(gaps),
        "first_gaps": gaps[:5], "coverage_ok": coverage_ok,
    }


def fetch_symbol(symbol: str, start_ms: int, end_ms: int) -> list[dict[str, float | int]]:
    all_rows: dict[int, dict[str, float | int]] = {}
    cursor = int(end_ms)
    for _ in range(MAX_PAGES):
        page = sorted(decode(request_json({"symbol": symbol, "interval": "5m", "limit": 1000, "endTime": cursor})), key=lambda x: int(x["ts_ms"]))
        if not page:
            break
        for row in page:
            ts = int(row["ts_ms"])
            if start_ms <= ts < end_ms:
                all_rows[ts] = row
        oldest = int(page[0]["ts_ms"])
        if oldest <= start_ms:
            break
        if oldest >= cursor:
            break
        cursor = oldest - 1
        time.sleep(0.04)
    return [all_rows[k] for k in sorted(all_rows)]


def prepare_cache(cache_dir: Path) -> dict[str, Any]:
    contract = read_json(CONTRACT_PATH)
    start = int(__import__("datetime").datetime.fromisoformat(contract["window"]["start_utc_inclusive"].replace("Z", "+00:00")).timestamp() * 1000)
    end = int(__import__("datetime").datetime.fromisoformat(contract["window"]["end_utc_exclusive"].replace("Z", "+00:00")).timestamp() * 1000)
    fetch_start = start - WARMUP_BARS * TF_MS
    fetch_end = end + POST_WINDOW_BARS * TF_MS
    cache_dir.mkdir(parents=True, exist_ok=True)
    receipts: dict[str, Any] = {}
    for symbol in contract["universe"]["symbols"]:
        path = cache_dir / f"{symbol.replace('-', '_')}_5m.json.gz"
        rows: list[dict[str, float | int]]
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                rows = json.load(fh)
        else:
            rows = fetch_symbol(symbol, fetch_start, fetch_end)
            with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as fh:
                json.dump(rows, fh, separators=(",", ":"), allow_nan=False)
        integrity = validate_source(rows, required_start=fetch_start, required_end=fetch_end)
        if not integrity["pass"]:
            raise RuntimeError(f"SOURCE_INTEGRITY_FAIL:{symbol}:{json.dumps(integrity, sort_keys=True)}")
        receipts[symbol] = {
            **integrity,
            "sha256": stable(rows),
            "cache_file": path.name,
        }
    manifest = {
        "schema_version": "zel.g4_scalp_round1.source_cache.v1",
        "window_start_ms": start, "window_end_ms": end,
        "fetch_start_ms": fetch_start, "fetch_end_ms": fetch_end,
        "timeframe_ms": TF_MS, "symbols": receipts,
        "contract_sha256": file_sha256(CONTRACT_PATH),
    }
    manifest["manifest_sha256"] = stable(manifest)
    (cache_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_cache(cache_dir: Path, symbol: str) -> list[dict[str, float | int]]:
    path = cache_dir / f"{symbol.replace('-', '_')}_5m.json.gz"
    if not path.exists():
        raise RuntimeError(f"CACHE_MISSING:{symbol}")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, list):
        raise RuntimeError(f"CACHE_LIST_REQUIRED:{symbol}")
    return value


def group_for(strategy_id: str) -> tuple[str, dict[str, Any]]:
    for name, spec in GROUPS.items():
        if strategy_id in spec["strategies"]:
            return name, spec
    raise RuntimeError(f"NATIVE_STRATEGY_UNMAPPED:{strategy_id}")


def policy_adapter(strategy_id: str) -> tuple[Any, Any, Any, Path, int]:
    group, spec = group_for(strategy_id)
    module = importlib.import_module(str(spec["module"]))
    cfg = getattr(module, str(spec["config"]))()
    if int(getattr(cfg, "timeframe_ms")) != TF_MS:
        raise RuntimeError(f"NATIVE_TIMEFRAME_DRIFT:{strategy_id}")
    if group == "microstructure":
        compute = getattr(module, f"compute_{strategy_id}_feature")
        build = getattr(module, f"build_{strategy_id}_intent")
        def feature_fn(bars: Sequence[Mapping[str, Any]], symbol: str, now: int) -> Any:
            return compute(bars, symbol=symbol, now_ts_ms=now, config=cfg)
        def intent_fn(feature: Any) -> Any:
            return build(feature, policy_source_sha=file_sha256(Path(module.__file__).resolve()), verified_round_trip_cost_bps=POLICY_COST_BPS, config=cfg)
    elif group in {"reversal_range", "indicator_core"}:
        def feature_fn(bars: Sequence[Mapping[str, Any]], symbol: str, now: int) -> Any:
            return module.compute_feature(strategy_id, bars, symbol=symbol, now_ts_ms=now, config=cfg)
        def intent_fn(feature: Any) -> Any:
            return module.build_intent(feature, policy_source_sha=file_sha256(Path(module.__file__).resolve()), verified_round_trip_cost_bps=POLICY_COST_BPS, config=cfg)
    else:
        def feature_fn(bars: Sequence[Mapping[str, Any]], symbol: str, now: int) -> Any:
            return module.features(strategy_id, bars, symbol=symbol, now_ms=now, config=cfg)
        def intent_fn(feature: Any) -> Any:
            return module.intent_from_snapshot(feature, policy_source_sha=file_sha256(Path(module.__file__).resolve()), verified_round_trip_cost_bps=POLICY_COST_BPS, config=cfg)
    return feature_fn, intent_fn, cfg, Path(module.__file__).resolve(), int(spec["context_bars"])


def lifecycle_is_supported(intent: Any) -> bool:
    partial = getattr(intent, "partial", {}) or {}
    trailing = getattr(intent, "trailing", {}) or {}
    runner = getattr(intent, "runner", {}) or {}
    return not bool(partial.get("enabled")) and not bool(trailing.get("enabled")) and not bool(runner.get("enabled"))


def simulate_exit(rows: Sequence[Mapping[str, Any]], *, entry_i: int, timeout_bars: int, side: str,
                  sl: float, tp: float | None) -> tuple[float, int, str, int]:
    if timeout_bars <= 0:
        raise RuntimeError("TIMEOUT_BARS_REQUIRED")
    last_j = min(len(rows) - 1, entry_i + timeout_bars - 1)
    for j in range(entry_i, last_j + 1):
        bar = rows[j]
        low, high = float(bar["low"]), float(bar["high"])
        sl_hit = low <= sl if side == "long" else high >= sl
        tp_hit = False if tp is None else (high >= tp if side == "long" else low <= tp)
        # Pessimistic and deterministic when a bar touches both boundaries.
        if sl_hit:
            return float(sl), int(bar["ts_ms"]) + TF_MS, "SL", j
        if tp_hit:
            return float(tp), int(bar["ts_ms"]) + TF_MS, "TP", j
    bar = rows[last_j]
    return float(bar["close"]), int(bar["ts_ms"]) + TF_MS, "TIMEOUT", last_j


def max_drawdown(values: Sequence[float]) -> float:
    eq = peak = dd = 0.0
    for value in values:
        eq += float(value); peak = max(peak, eq); dd = max(dd, peak - eq)
    return dd


def summarize_trades(trades: Sequence[Mapping[str, Any]], window_days: float) -> dict[str, Any]:
    tr = sorted((dict(x) for x in trades), key=lambda x: (int(x["exit_ts"]), int(x["signal_ts"]), str(x["symbol"])))
    net = [float(x["net_bps"]) for x in tr]
    gross = [float(x["gross_bps"]) for x in tr]
    rvals = [float(x["net_R"]) for x in tr]
    wins = [x for x in net if x > 0]; losses_abs = [-x for x in net if x < 0]
    holds = [float(x["hold_minutes"]) for x in tr]
    sym = Counter(str(x["symbol"]) for x in tr)
    top_symbol, top_n = sym.most_common(1)[0] if sym else (None, 0)
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses_abs) / len(losses_abs) if losses_abs else None
    pf_unbounded = bool(wins and not losses_abs)
    pf = (sum(wins) / sum(losses_abs)) if losses_abs else None
    payoff = (avg_win / avg_loss) if avg_win is not None and avg_loss not in (None, 0) else None
    negative = sorted(x for x in net if x < 0)
    tail_n = max(1, math.ceil(len(negative) * 0.05)) if negative else 0
    loss_tail = statistics.mean(negative[:tail_n]) if tail_n else None
    largest_win = max(wins) if wins else None
    win_sum = sum(wins)
    return {
        "closed_T": len(tr),
        "T_per_day": len(tr) / window_days if window_days > 0 else None,
        "hold_minutes_mean": statistics.mean(holds) if holds else None,
        "hold_minutes_median": statistics.median(holds) if holds else None,
        "hold_minutes_p95": percentile(holds, 0.95),
        "gross_pnl_bps": sum(gross),
        "net_pnl_bps": sum(net),
        "net_R_per_day": sum(rvals) / window_days if window_days > 0 else None,
        "net_R_total": sum(rvals),
        "net_expectancy_bps_per_T": sum(net) / len(net) if net else None,
        "payoff": payoff,
        "profit_factor": pf,
        "profit_factor_unbounded": pf_unbounded,
        "win_rate": len(wins) / len(net) if net else None,
        "drawdown_bps": max_drawdown(net),
        "drawdown_R": max_drawdown(rvals),
        "worst_loss_bps": min(net) if net else None,
        "loss_tail_mean_worst_5pct_bps": loss_tail,
        "cost2_net_bps": sum(gross) - COST2_BPS * len(tr),
        "symbol_counts": dict(sorted(sym.items())),
        "top_symbol": top_symbol,
        "top_symbol_share": top_n / len(tr) if tr else None,
        "largest_winner_bps": largest_win,
        "largest_winner_contribution": (largest_win / win_sum) if largest_win is not None and win_sum > 0 else None,
        "trades_sha256": stable(tr),
    }


def terminal_state(metrics: Mapping[str, Any], minimum_t: int = 30) -> str:
    n = int(metrics.get("closed_T") or 0)
    if n == 0:
        return "ROUND1_NO_TRADES"
    if n < minimum_t:
        return "ROUND1_SPARSE_DESCRIPTIVE"
    net = float(metrics.get("net_pnl_bps") or 0.0)
    nr = float(metrics.get("net_R_per_day") or 0.0)
    pf = metrics.get("profit_factor")
    unbounded = bool(metrics.get("profit_factor_unbounded"))
    pf_ok = unbounded or (pf is not None and float(pf) >= 1.0)
    if net <= 0 or nr <= 0 or not pf_ok:
        return "ROUND1_ECONOMIC_FAIL"
    return "ROUND1_POSITIVE_ECONOMICS"


def run_lane(strategy_id: str, cache_dir: Path) -> dict[str, Any]:
    contract = read_json(CONTRACT_PATH)
    if strategy_id not in contract["native_round1"]:
        raise RuntimeError(f"ROUND1_NATIVE_NOT_AUTHORIZED:{strategy_id}")
    manifest = read_json(cache_dir / "MANIFEST.json")
    start = int(manifest["window_start_ms"]); end = int(manifest["window_end_ms"])
    window_days = (end - start) / 86_400_000.0
    feature_fn, intent_fn, cfg, policy_path, context_bars = policy_adapter(strategy_id)
    all_trades: list[dict[str, Any]] = []
    diagnostics = Counter()
    for symbol in contract["universe"]["symbols"]:
        rows = load_cache(cache_dir, symbol)
        blocked_until = -1
        for i, bar in enumerate(rows[:-1]):
            signal_ts = int(bar["ts_ms"])
            if signal_ts < start:
                continue
            if signal_ts >= end:
                break
            lo = max(0, i - context_bars + 1)
            context = rows[lo:i + 1]
            try:
                feature = feature_fn(context, symbol, signal_ts)
                intent = intent_fn(feature)
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_", "RSI_WARMUP_", "VWAP_VOLUME_")):
                    diagnostics["warmup_or_volume_hold"] += 1
                    continue
                diagnostics[f"policy_value_error:{str(exc)}"] += 1
                continue
            except Exception as exc:
                diagnostics[f"policy_error:{type(exc).__name__}:{str(exc)[:80]}"] += 1
                continue
            if bool(getattr(intent, "no_trade", True)):
                continue
            diagnostics["signals"] += 1
            if not lifecycle_is_supported(intent):
                raise RuntimeError(f"UNSUPPORTED_NATIVE_LIFECYCLE:{strategy_id}")
            entry_i = i + 1
            entry_ts = int(rows[entry_i]["ts_ms"])
            if entry_ts < blocked_until:
                diagnostics["overlap_blocked"] += 1
                continue
            side = str(getattr(intent, "side"))
            if side not in {"long", "short"}:
                diagnostics["invalid_side"] += 1
                continue
            entry = float(rows[entry_i]["open"])
            sl = getattr(intent, "sl", None)
            tp = getattr(intent, "tp", None)
            if sl is None:
                diagnostics["execution_reject_missing_sl"] += 1
                continue
            sl = float(sl); tp = None if tp is None else float(tp)
            if (side == "long" and sl >= entry) or (side == "short" and sl <= entry):
                diagnostics["execution_reject_gap_through_sl"] += 1
                continue
            if tp is not None and ((side == "long" and tp <= entry) or (side == "short" and tp >= entry)):
                diagnostics["execution_reject_gap_through_tp"] += 1
                continue
            risk_bps = abs(entry - sl) / entry * 10_000.0
            if risk_bps <= 0 or not math.isfinite(risk_bps):
                diagnostics["execution_reject_invalid_risk"] += 1
                continue
            timeout = int((getattr(intent, "timeout", {}) or {}).get("bars", getattr(cfg, "timeout_bars", 0)))
            exit_px, exit_ts, reason, exit_i = simulate_exit(rows, entry_i=entry_i, timeout_bars=timeout, side=side, sl=sl, tp=tp)
            sgn = 1.0 if side == "long" else -1.0
            gross_bps = sgn * (exit_px - entry) / entry * 10_000.0
            net_bps = gross_bps - POLICY_COST_BPS
            hold_minutes = (exit_i - entry_i + 1) * (TF_MS / 60_000.0)
            trade = {
                "strategy_id": strategy_id,
                "symbol": symbol,
                "signal_ts": signal_ts,
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "side": side,
                "entry_px": entry,
                "exit_px": exit_px,
                "sl": sl,
                "tp": tp,
                "exit_reason": reason,
                "gross_bps": gross_bps,
                "net_bps": net_bps,
                "risk_bps": risk_bps,
                "net_R": net_bps / risk_bps,
                "hold_minutes": hold_minutes,
            }
            trade["trade_id"] = stable({k: trade[k] for k in ("strategy_id", "symbol", "signal_ts", "entry_ts", "exit_ts", "side")})
            all_trades.append(trade)
            diagnostics["opens"] += 1
            cooldown = getattr(intent, "cooldown", {}) or {}
            cooldown_bars = int(cooldown.get("bars", 0)) if isinstance(cooldown, Mapping) else 0
            blocked_until = exit_ts + max(0, cooldown_bars) * TF_MS
    ids = [x["trade_id"] for x in all_trades]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"DUPLICATE_TRADE_ID:{strategy_id}")
    metrics = summarize_trades(all_trades, window_days)
    state = terminal_state(metrics, int(contract["terminal_readback"]["minimum_closed_T_for_terminal_economic_fail_or_positive"]))
    return {
        "schema_version": SCHEMA,
        "scope_key": contract["scope_key"],
        "issue": contract["issue"],
        "strategy_id": strategy_id,
        "state": state,
        "window": contract["window"],
        "universe": contract["universe"],
        "policy": {
            "path": str(policy_path.relative_to(ROOT)),
            "sha256": file_sha256(policy_path),
            "config_sha": str(getattr(cfg, "sha", "")),
            "context_bars": context_bars,
            "timeframe_ms": int(getattr(cfg, "timeframe_ms")),
            "timeout_bars": int(getattr(cfg, "timeout_bars")),
            "unmodified_native_parent": True,
        },
        "execution": contract["execution"],
        "cost": contract["cost"],
        "metrics": metrics,
        "diagnostics": dict(sorted(diagnostics.items())),
        "source": {
            "manifest_sha256": manifest["manifest_sha256"],
            "symbols": manifest["symbols"],
            "fresh_or_post_boundary_rows_used": False,
        },
        "trades": sorted(all_trades, key=lambda x: (int(x["exit_ts"]), int(x["signal_ts"]), str(x["symbol"]))),
        "authority": contract["authority"],
    }


def aggregate(lanes_dir: Path, out: Path) -> dict[str, Any]:
    contract = read_json(CONTRACT_PATH)
    rows = []
    for sid in contract["native_round1"]:
        p = lanes_dir / f"{sid}.json"
        if not p.exists():
            raise RuntimeError(f"LANE_RESULT_MISSING:{sid}")
        lane = read_json(p)
        if lane.get("strategy_id") != sid:
            raise RuntimeError(f"LANE_IDENTITY_MISMATCH:{sid}")
        m = dict(lane["metrics"])
        rows.append({"strategy_id": sid, "state": lane["state"], **m})
    def pf_sort(row: Mapping[str, Any]) -> float:
        if row.get("profit_factor_unbounded"):
            return float("inf")
        return float(row.get("profit_factor") or -1e99)
    ranking = sorted(rows, key=lambda r: (
        float(r.get("net_R_per_day") or -1e99),
        float(r.get("net_pnl_bps") or -1e99),
        pf_sort(r),
        float(r.get("payoff") or -1e99),
        float(r.get("win_rate") or -1e99),
    ), reverse=True)
    state_counts = dict(Counter(str(x["state"]) for x in rows))
    result = {
        "schema_version": AGG_SCHEMA,
        "scope_key": contract["scope_key"],
        "issue": contract["issue"],
        "state": "ROUND1_NATIVE_15_COMPLETE_DESCRIPTIVE_NO_SELECTION",
        "lane_count": len(rows),
        "state_counts": state_counts,
        "descriptive_ranking": ranking,
        "ranking_note": "Descriptive lexicographic ordering only: Net R/day then Net PnL then PF/payoff/WR. No weighted score and no Top5 selection authority.",
        "portfolio_target_closed_T_per_day": contract["selection"]["portfolio_closed_T_per_day_target"],
        "fast_child_freeze_sha256": file_sha256(FAST_CHILD_PATH),
        "contract_sha256": file_sha256(CONTRACT_PATH),
        "authority": contract["authority"],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare-cache", action="store_true")
    ap.add_argument("--cache-dir", default="/tmp/g4_scalp_round1_cache")
    ap.add_argument("--strategy-id")
    ap.add_argument("--out")
    ap.add_argument("--aggregate", action="store_true")
    ap.add_argument("--lanes-dir", default=str(DEFAULT_LANES))
    args = ap.parse_args()
    cache_dir = Path(args.cache_dir)
    if args.prepare_cache:
        result = prepare_cache(cache_dir)
        print(json.dumps({"state": "ROUND1_SOURCE_CACHE_READY", "manifest_sha256": result["manifest_sha256"], "symbols": list(result["symbols"])}))
        return 0
    if args.aggregate:
        out = Path(args.out) if args.out else DEFAULT_AGG
        result = aggregate(Path(args.lanes_dir), out)
        print(json.dumps({"state": result["state"], "lane_count": result["lane_count"], "state_counts": result["state_counts"]}, sort_keys=True))
        return 0
    if not args.strategy_id:
        raise SystemExit("--strategy-id required unless --prepare-cache or --aggregate")
    if args.strategy_id not in LANE_ORDER:
        raise SystemExit(f"unsupported native lane: {args.strategy_id}")
    result = run_lane(args.strategy_id, cache_dir)
    out = Path(args.out) if args.out else DEFAULT_LANES / f"{args.strategy_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"strategy_id": args.strategy_id, "state": result["state"], "metrics": result["metrics"], "out": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
