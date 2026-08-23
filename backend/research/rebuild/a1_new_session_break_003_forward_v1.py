from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "backend/research/rebuild/new_session_break_003_prereg_v1.json"
SOURCE = ROOT / "backend/research/prep/a1_external_research_exact8_forward_state_v1.json"
LATEST = ROOT / "backend/research/rebuild/a1_new_session_break_003_forward_latest.json"
TF_MS = 300_000
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "exchange_order_submitted": False,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def verify_prereg(p: Mapping[str, Any]) -> None:
    if p.get("state") != "PREREGISTERED_COMMON_SOURCE_FRESH_ONLY":
        raise RuntimeError("PREREG_STATE_INVALID")
    if p.get("candidate_id") != "NEW_session_break_003":
        raise RuntimeError("CANDIDATE_ID_INVALID")
    if p.get("candidate_sha256") != "a6f4c6ed88eda3d5091da1f73359689f2976760b669d30c896b5003a25286db3":
        raise RuntimeError("CANDIDATE_SHA_INVALID")
    if p.get("common_source_semantic_guard_pass") is not True:
        raise RuntimeError("COMMON_SOURCE_SEMANTIC_GUARD_NOT_PASS")
    if list(p.get("required_sources") or []) != ["ohlcv", "volume"]:
        raise RuntimeError("REQUIRED_SOURCES_INVALID")
    if int(p.get("timeframe_ms") or 0) != TF_MS:
        raise RuntimeError("TIMEFRAME_INVALID")
    a1 = p.get("a1_gate") or {}
    if int(a1.get("minimum_completed_trades") or 0) != 25:
        raise RuntimeError("A1_MIN_SAMPLE_NOT_25")
    if set(a1.get("hard_controls") or []) != {"same_count_random_entry", "direction_inversion", "timestamp_shuffle"}:
        raise RuntimeError("A1_HARD_CONTROLS_INVALID")
    f = p.get("falsification_rule") or {}
    if int(float(f.get("expected_move_cost_multiple") or 0)) != 2:
        raise RuntimeError("FALSIFICATION_COST_MULTIPLE_INVALID")
    body = dict(p)
    claimed = str(body.pop("prereg_sha256", ""))
    if not claimed or stable_sha(body) != claimed:
        raise RuntimeError("PREREG_SHA_MISMATCH")


def stream_bars(source: Mapping[str, Any], symbol: str) -> list[dict[str, Any]]:
    key = f"{symbol}|{TF_MS}"
    raw = (source.get("streams") or {}).get(key)
    if not isinstance(raw, list):
        raise RuntimeError(f"SOURCE_STREAM_MISSING:{key}")
    bars: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        bars.append({
            "ts_ms": int(row["ts_ms"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume") or 0.0),
        })
    bars = sorted({int(x["ts_ms"]): x for x in bars}.values(), key=lambda x: int(x["ts_ms"]))
    if len(bars) < 8:
        raise RuntimeError(f"SOURCE_STREAM_TOO_SHORT:{key}:{len(bars)}")
    return bars


def overlap_bounds(day: date) -> tuple[datetime, datetime]:
    lon = ZoneInfo("Europe/London")
    ny = ZoneInfo("America/New_York")
    lon_open = datetime.combine(day, time(8, 0), tzinfo=lon)
    lon_close = datetime.combine(day, time(16, 30), tzinfo=lon)
    ny_open = datetime.combine(day, time(9, 30), tzinfo=ny)
    ny_close = datetime.combine(day, time(16, 0), tzinfo=ny)
    start = max(lon_open.astimezone(timezone.utc), ny_open.astimezone(timezone.utc))
    end = min(lon_close.astimezone(timezone.utc), ny_close.astimezone(timezone.utc))
    return start, end


def max_drawdown(values: list[float]) -> float:
    equity = peak = dd = 0.0
    for x in values:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def profit_factor(values: list[float]) -> float | None:
    gp = sum(x for x in values if x > 0)
    gl = -sum(x for x in values if x < 0)
    if gl <= 0:
        return None
    value = gp / gl
    return value if math.isfinite(value) else None


def payoff(values: list[float]) -> float | None:
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    if not wins or not losses:
        return None
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def metrics(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    gross = [float(x["gross_bps"]) for x in trades]
    net = [float(x["net_bps"]) for x in trades]
    return {
        "trade_count": len(net),
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": sum(net) / len(net) if net else None,
        "net_profit_factor": profit_factor(net),
        "net_payoff": payoff(net),
        "win_rate": sum(1 for x in net if x > 0) / len(net) if net else None,
        "max_drawdown_bps": max_drawdown(net),
    }


def paired_stats(candidate: list[float], control: list[float], seed: int, bootstrap_n: int = 10000) -> tuple[float, float]:
    if len(candidate) != len(control) or not candidate:
        raise RuntimeError("PAIRED_CONTROL_BUDGET_INVALID")
    diffs = [a - b for a, b in zip(candidate, control)]
    rng = random.Random(seed)
    obs = sum(diffs) / len(diffs)
    ge = 1
    for _ in range(bootstrap_n):
        perm = sum(x if rng.random() < 0.5 else -x for x in diffs) / len(diffs)
        if perm >= obs:
            ge += 1
    p = ge / (bootstrap_n + 1)
    boots = [sum(diffs[rng.randrange(len(diffs))] for __ in range(len(diffs))) for _ in range(bootstrap_n)]
    boots.sort()
    ci = boots[max(0, int(0.05 * bootstrap_n) - 1)]
    return ci, p


def source_costs(source: Mapping[str, Any], prereg: Mapping[str, Any]) -> dict[str, float]:
    expected = ((prereg.get("cost_rule") or {}).get("expected_pretrade_verified_cost_bps_by_symbol") or {})
    snaps = source.get("cost_snapshot_by_symbol") or {}
    out: dict[str, float] = {}
    for symbol in prereg["symbols"]:
        snap = snaps.get(symbol)
        if not isinstance(snap, Mapping):
            raise RuntimeError(f"COST_SNAPSHOT_MISSING:{symbol}")
        actual = float(snap.get("pretrade_verified_cost_bps"))
        exp = float(expected[symbol])
        if abs(actual - exp) > 1e-9:
            raise RuntimeError(f"COST_DRIFT_FAIL_CLOSED:{symbol}:{actual}!={exp}")
        out[symbol] = actual
    return out


def common_frontier(bars_by: Mapping[str, list[dict[str, Any]]]) -> int:
    return min(int(rows[-1]["ts_ms"]) for rows in bars_by.values())


def seal_or_reuse_boundary(prereg: Mapping[str, Any], frontier: int) -> tuple[int, str, bool]:
    prereg_sha = str(prereg["prereg_sha256"])
    if LATEST.exists():
        prev = read(LATEST)
        if prev.get("candidate_id") != prereg["candidate_id"] or prev.get("prereg_sha256") != prereg_sha:
            raise RuntimeError("LATEST_IDENTITY_MISMATCH")
        boundary = int(prev.get("boundary_ms") or 0)
        if boundary <= 0:
            raise RuntimeError("LATEST_BOUNDARY_INVALID")
        return boundary, str(prev["boundary_utc"]), False
    boundary = frontier + TF_MS
    boundary_utc = datetime.fromtimestamp(boundary / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return boundary, boundary_utc, True


def exact_bar(mp: Mapping[int, dict[str, Any]], ts: int) -> dict[str, Any] | None:
    return mp.get(ts)


def collect_trades(
    prereg: Mapping[str, Any],
    bars_by: Mapping[str, list[dict[str, Any]]],
    boundary_ms: int,
    frontier_ms: int,
    costs: Mapping[str, float],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    defects: list[str] = []
    trades: list[dict[str, Any]] = []
    sessions_seen = sessions_complete = signals = 0
    prereg_sha = str(prereg["prereg_sha256"])
    multiple = float((prereg.get("falsification_rule") or {}).get("expected_move_cost_multiple") or 2.0)

    for symbol in prereg["symbols"]:
        rows = bars_by[symbol]
        mp = {int(x["ts_ms"]): x for x in rows}
        first_date = datetime.fromtimestamp(rows[0]["ts_ms"] / 1000, timezone.utc).date() - timedelta(days=1)
        last_date = datetime.fromtimestamp(frontier_ms / 1000, timezone.utc).date() + timedelta(days=1)
        day = first_date
        while day <= last_date:
            if day.weekday() >= 5:
                day += timedelta(days=1)
                continue
            start_dt, end_dt = overlap_bounds(day)
            start_ms = int(start_dt.timestamp() * 1000)
            end_ms = int(end_dt.timestamp() * 1000)
            if end_ms <= boundary_ms or start_ms > frontier_ms:
                day += timedelta(days=1)
                continue
            sessions_seen += 1
            if frontier_ms < end_ms:
                day += timedelta(days=1)
                continue
            sessions_complete += 1
            pre_ts = [start_ms - TF_MS * i for i in range(6, 0, -1)]
            pre = [exact_bar(mp, ts) for ts in pre_ts]
            if any(x is None for x in pre):
                if rows[0]["ts_ms"] <= pre_ts[0] <= rows[-1]["ts_ms"]:
                    defects.append(f"{symbol}:{day.isoformat()}:PRE_SESSION_5M_GAP")
                day += timedelta(days=1)
                continue
            pre2 = [x for x in pre if x is not None]
            direction = 1 if float(pre2[-1]["close"]) > float(pre2[0]["open"]) else (-1 if float(pre2[-1]["close"]) < float(pre2[0]["open"]) else 0)
            if direction == 0:
                day += timedelta(days=1)
                continue
            pre_high = max(float(x["high"]) for x in pre2)
            pre_low = min(float(x["low"]) for x in pre2)
            pre_vol_median = statistics.median(float(x["volume"]) for x in pre2)
            if pre_vol_median <= 0:
                defects.append(f"{symbol}:{day.isoformat()}:PRE_SESSION_VOLUME_NONPOSITIVE")
                day += timedelta(days=1)
                continue

            session_ts = list(range(start_ms, end_ms, TF_MS))
            session = [exact_bar(mp, ts) for ts in session_ts]
            if any(x is None for x in session):
                defects.append(f"{symbol}:{day.isoformat()}:OVERLAP_5M_GAP")
                day += timedelta(days=1)
                continue
            srows = [x for x in session if x is not None]
            signal_i = None
            for i, bar in enumerate(srows[:-1]):
                ts = int(bar["ts_ms"])
                if ts < boundary_ms:
                    continue
                breakout = float(bar["close"]) > pre_high if direction == 1 else float(bar["close"]) < pre_low
                elevated_volume = float(bar["volume"]) >= pre_vol_median
                if breakout and elevated_volume:
                    signal_i = i
                    break
            if signal_i is None:
                day += timedelta(days=1)
                continue
            signals += 1
            entry_i = signal_i + 1
            if entry_i >= len(srows):
                day += timedelta(days=1)
                continue
            entry_bar = srows[entry_i]
            entry_ts = int(entry_bar["ts_ms"])
            if entry_ts < boundary_ms:
                defects.append(f"{symbol}:{day.isoformat()}:ENTRY_PREBOUNDARY")
                day += timedelta(days=1)
                continue
            entry_px = float(entry_bar["open"])
            exit_px = None
            exit_ts = None
            exit_reason = None
            prev_close = float(srows[signal_i]["close"])
            horizon_prices = [float(x["high"]) if direction == 1 else float(x["low"]) for x in srows[entry_i:]]
            if direction == 1:
                mfe_bps = (max(horizon_prices) / entry_px - 1.0) * 10_000.0
            else:
                mfe_bps = (entry_px / min(horizon_prices) - 1.0) * 10_000.0

            for j in range(entry_i, len(srows)):
                bar = srows[j]
                close = float(bar["close"])
                range_return = close <= pre_high if direction == 1 else close >= pre_low
                signed_ret = direction * (close / prev_close - 1.0)
                momentum_collapse = signed_ret <= 0.0
                if range_return:
                    exit_px, exit_ts, exit_reason = close, int(bar["ts_ms"]), "RANGE_RETURN"
                    break
                if momentum_collapse:
                    exit_px, exit_ts, exit_reason = close, int(bar["ts_ms"]), "MOMENTUM_COLLAPSE"
                    break
                prev_close = close
            if exit_px is None:
                last = srows[-1]
                exit_px, exit_ts, exit_reason = float(last["close"]), int(last["ts_ms"]), "SESSION_END"

            gross_bps = direction * (float(exit_px) / entry_px - 1.0) * 10_000.0
            cost_bps = float(costs[symbol])
            net_bps = gross_bps - cost_bps
            side = "long" if direction == 1 else "short"
            intent = {
                "candidate_id": prereg["candidate_id"],
                "candidate_sha256": prereg["candidate_sha256"],
                "prereg_sha256": prereg_sha,
                "symbol": symbol,
                "session_date": day.isoformat(),
                "side": side,
                "signal_ts": int(srows[signal_i]["ts_ms"]),
                "entry_ts": entry_ts,
            }
            trades.append({
                "strategy_id": prereg["candidate_id"],
                "symbol": symbol,
                "session_date": day.isoformat(),
                "side": side,
                "signal_ts": int(srows[signal_i]["ts_ms"]),
                "entry_ts": entry_ts,
                "exit_ts": int(exit_ts),
                "entry_price": entry_px,
                "exit_price": float(exit_px),
                "exit_reason": exit_reason,
                "gross_bps": gross_bps,
                "realized_cost_bps": cost_bps,
                "net_bps": net_bps,
                "mfe_bps_to_session_end": mfe_bps,
                "mechanism_move_gt_2x_cost": mfe_bps > multiple * cost_bps,
                "intent_sha": stable_sha(intent),
            })
            day += timedelta(days=1)

    unique: dict[str, dict[str, Any]] = {}
    for trade in trades:
        sha = str(trade["intent_sha"])
        if sha in unique:
            defects.append(f"DUPLICATE_INTENT:{sha}")
        else:
            unique[sha] = trade
    ordered = sorted(unique.values(), key=lambda x: (int(x["entry_ts"]), str(x["symbol"]), str(x["intent_sha"])))
    stats = {"sessions_seen": sessions_seen, "sessions_complete": sessions_complete, "signals": signals}
    return ordered, defects, stats


def _bar_maps(bars_by: Mapping[str, list[dict[str, Any]]]) -> dict[str, dict[int, int]]:
    return {symbol: {int(x["ts_ms"]): i for i, x in enumerate(rows)} for symbol, rows in bars_by.items()}


def random_entry_control(
    cohort: list[dict[str, Any]], bars_by: Mapping[str, list[dict[str, Any]]], boundary_ms: int, frontier_ms: int, seed: int
) -> list[float]:
    maps = _bar_maps(bars_by)
    rng = random.Random(seed)
    used: set[tuple[str, int]] = set()
    out: list[float] = []
    for trade in cohort:
        symbol = str(trade["symbol"])
        rows = bars_by[symbol]
        mp = maps[symbol]
        if int(trade["entry_ts"]) not in mp or int(trade["exit_ts"]) not in mp:
            raise RuntimeError(f"CONTROL_TRADE_BAR_MISSING:{symbol}")
        duration = max(1, mp[int(trade["exit_ts"])] - mp[int(trade["entry_ts"])])
        pool = [
            j for j, bar in enumerate(rows)
            if boundary_ms <= int(bar["ts_ms"]) <= frontier_ms
            and j + duration < len(rows)
            and int(rows[j + duration]["ts_ms"]) <= frontier_ms
            and (symbol, int(bar["ts_ms"])) not in used
        ]
        if not pool:
            raise RuntimeError(f"RANDOM_ENTRY_POOL_EXHAUSTED:{symbol}")
        j = pool[rng.randrange(len(pool))]
        used.add((symbol, int(rows[j]["ts_ms"])))
        entry = float(rows[j]["open"])
        exit_px = float(rows[j + duration]["close"])
        side = 1 if str(trade["side"]) == "long" else -1
        out.append((side * (exit_px / entry - 1.0) * 10_000.0 - float(trade["realized_cost_bps"])) / 100.0)
    return out


def timestamp_shuffle_control(
    cohort: list[dict[str, Any]], bars_by: Mapping[str, list[dict[str, Any]]], seed: int
) -> list[float]:
    maps = _bar_maps(bars_by)
    rng = random.Random(seed)
    starts_by_symbol = {
        symbol: [int(x["entry_ts"]) for x in cohort if str(x["symbol"]) == symbol]
        for symbol in bars_by
    }
    for starts in starts_by_symbol.values():
        rng.shuffle(starts)
    cursor = {symbol: 0 for symbol in bars_by}
    out: list[float] = []
    for trade in cohort:
        symbol = str(trade["symbol"])
        rows = bars_by[symbol]
        mp = maps[symbol]
        if int(trade["entry_ts"]) not in mp or int(trade["exit_ts"]) not in mp:
            raise RuntimeError(f"TIMESTAMP_CONTROL_TRADE_BAR_MISSING:{symbol}")
        duration = max(1, mp[int(trade["exit_ts"])] - mp[int(trade["entry_ts"])])
        starts = starts_by_symbol[symbol]
        replacement = starts[cursor[symbol] % len(starts)]
        cursor[symbol] += 1
        entry_i = mp[replacement]
        if entry_i + duration >= len(rows):
            raise RuntimeError(f"TIMESTAMP_CONTROL_FUTURE_BAR_MISSING:{symbol}")
        entry = float(rows[entry_i]["open"])
        exit_px = float(rows[entry_i + duration]["close"])
        side = 1 if str(trade["side"]) == "long" else -1
        out.append((side * (exit_px / entry - 1.0) * 10_000.0 - float(trade["realized_cost_bps"])) / 100.0)
    return out


def a1_controls(
    prereg: Mapping[str, Any],
    trades: list[dict[str, Any]],
    bars_by: Mapping[str, list[dict[str, Any]]],
    boundary_ms: int,
    frontier_ms: int,
) -> dict[str, Any]:
    if len(trades) < 25:
        return {"state": "WAIT_FRESH_25", "frozen_trade_count": 0, "hard_control_states": {}}
    cohort = trades[:25]
    candidate = [float(x["net_bps"]) / 100.0 for x in cohort]
    direction = [(-float(x["gross_bps"]) - float(x["realized_cost_bps"])) / 100.0 for x in cohort]
    seed_base = {
        "candidate_id": prereg["candidate_id"],
        "candidate_sha256": prereg["candidate_sha256"],
        "prereg_sha256": prereg["prereg_sha256"],
        "boundary_ms": boundary_ms,
        "cohort": "FIRST_25_BY_ENTRY_TS_SYMBOL_INTENT_SHA",
    }
    controls: dict[str, Any] = {}
    control_values: dict[str, list[float]] = {
        "direction_inversion": direction,
        "same_count_random_entry": random_entry_control(
            cohort, bars_by, boundary_ms, frontier_ms,
            int(stable_sha({**seed_base, "control": "same_count_random_entry"})[:16], 16),
        ),
        "timestamp_shuffle": timestamp_shuffle_control(
            cohort, bars_by,
            int(stable_sha({**seed_base, "control": "timestamp_shuffle"})[:16], 16),
        ),
    }
    pmax = float((prereg.get("a1_gate") or {}).get("paired_p_value_max") or 0.05)
    for name in ["same_count_random_entry", "direction_inversion", "timestamp_shuffle"]:
        vals = control_values[name]
        seed = int(stable_sha({**seed_base, "control": name, "stats": 1})[:16], 16)
        ci, p = paired_stats(candidate, vals, seed)
        passed = p <= pmax and ci > 0.0
        controls[name] = {
            "state": "PASS" if passed else "FAIL",
            "p_value": p,
            "candidate_minus_control_ci_low_R": ci,
            "candidate_net_R": sum(candidate),
            "control_net_R": sum(vals),
            "candidate_minus_control_net_R": sum(candidate) - sum(vals),
            "equal_trade_budget": True,
            "trade_count": 25,
        }
    states = {k: str(v["state"]) for k, v in controls.items()}
    result = {
        "state": "PASS" if all(x == "PASS" for x in states.values()) else "FAIL",
        "frozen_trade_count": 25,
        "cohort_rule": "FIRST_25_BY_ENTRY_TS_SYMBOL_INTENT_SHA",
        "cohort_sha256": stable_sha([
            {k: x.get(k) for k in ("symbol", "entry_ts", "exit_ts", "intent_sha", "net_bps", "realized_cost_bps")}
            for x in cohort
        ]),
        "hard_control_states": states,
        "controls": controls,
        "one_bar_delay": {"state": "NOT_RUN", "owner": "A2_EXECUTION_STRESS"},
        "indicator_removal": {"state": "NOT_RUN", "owner": "MECHANISM_SPECIFIC_DIAGNOSTIC"},
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def evaluate() -> dict[str, Any]:
    prereg = read(PREREG)
    verify_prereg(prereg)
    source = read(SOURCE)
    source_defects = [str(x) for x in source.get("integrity_defects") or []]
    if source_defects:
        raise RuntimeError(f"SOURCE_INTEGRITY_DEFECT:{source_defects}")
    if source.get("state") != "COLLECTING":
        raise RuntimeError(f"SOURCE_STATE_NOT_COLLECTING:{source.get('state')}")
    bars_by = {symbol: stream_bars(source, symbol) for symbol in prereg["symbols"]}
    frontier = common_frontier(bars_by)
    costs = source_costs(source, prereg)
    boundary_ms, boundary_utc, boundary_created = seal_or_reuse_boundary(prereg, frontier)
    trades, defects, collection = collect_trades(prereg, bars_by, boundary_ms, frontier, costs)
    controls = a1_controls(prereg, trades, bars_by, boundary_ms, frontier)
    first10 = trades[:10]
    mechanism_falsified = len(first10) == 10 and all(not bool(x["mechanism_move_gt_2x_cost"]) for x in first10)
    first25 = trades[:25]
    first25_metrics = metrics(first25)
    economic_nonfail = (
        len(first25) == 25
        and float(first25_metrics.get("net_pnl_bps") or 0.0) > 0.0
        and float(first25_metrics.get("net_expectancy_bps") or 0.0) > 0.0
    )

    if defects:
        state, next_step = "HOLD_SOURCE_OR_INTEGRITY", "FIX_SOURCE_INTEGRITY_ONLY"
    elif mechanism_falsified:
        state, next_step = "HOLD_A1_MECHANISM_FALSIFIED", "ROUTE_TO_NEXT_DISTINCT_ARCHITECTURE"
    elif len(trades) < 25:
        state, next_step = "WAIT_FRESH_25", "CONTINUE_HOURLY_FRESH_COLLECTION"
    elif controls.get("state") == "PASS" and economic_nonfail:
        state, next_step = "PASS_A1_CAUSAL_READY_FOR_A2", "A2_COST_EXECUTION_STRESS"
    else:
        state, next_step = "HOLD_A1_CAUSAL_FAIL", "ROUTE_TO_NEXT_DISTINCT_ARCHITECTURE"

    result = {
        "schema_version": "zel.a1.new_session_break_003.forward.v1",
        "state": state,
        "next": next_step,
        "candidate_id": prereg["candidate_id"],
        "candidate_sha256": prereg["candidate_sha256"],
        "prereg_sha256": prereg["prereg_sha256"],
        "boundary_ms": boundary_ms,
        "boundary_utc": boundary_utc,
        "boundary_created_this_run": boundary_created,
        "preboundary_outcomes_counted": False,
        "preboundary_bars_are_feature_warmup_only": True,
        "common_source_frontier_ms": frontier,
        "common_source_frontier_utc": datetime.fromtimestamp(frontier / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_receipt_sha256": source.get("receipt_sha256"),
        "source_updated_at_utc": source.get("updated_at_utc"),
        "source_quality_state": "PASS" if not source_defects else "HOLD",
        "source_integrity_defects": source_defects,
        "cost_bps_by_symbol": costs,
        "collection": collection,
        "completed_trades": len(trades),
        "sample_gap_to_25": max(0, 25 - len(trades)),
        "metrics_all_fresh": metrics(trades),
        "first_25_metrics": first25_metrics,
        "a1_economic_nonfail": economic_nonfail,
        "a1_controls": controls,
        "mechanism_falsification": {
            "evaluated": len(first10) == 10,
            "first_10_trade_count": len(first10),
            "all_first_10_failed_2x_cost_mfe": mechanism_falsified,
            "first_10_move_pass_count": sum(1 for x in first10 if bool(x["mechanism_move_gt_2x_cost"])),
        },
        "trades": trades,
        "integrity_defects": defects,
        "leakage_lookahead": 0,
        "thresholds_changed": False,
        "strategy_parameters_changed": False,
        "canonical_exact25_ledger_mutation": False,
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    p = read(PREREG)
    verify_prereg(p)
    assert int(p["entry_rule"]["pre_session_range_bars"]) == 6
    assert p["entry_rule"]["entry_fill"] == "next_5m_bar_open"
    assert int(p["a1_gate"]["minimum_completed_trades"]) == 25
    assert float(p["a1_gate"]["paired_p_value_max"]) == 0.05
    assert p["cost_rule"]["cost_drift_allowed"] is False
    assert p["selection_authority"] is False and p["promotion_authority"] is False
    assert p["execution_authority"] == "NONE" and p["order_authority"] == "BLOCKED" and p["live_trade_authority"] == "BLOCKED"
    start, end = overlap_bounds(date(2026, 8, 21))
    assert start < end
    vals = [{"net_bps": 10.0, "gross_bps": 24.0}] * 25
    m = metrics(vals)
    assert m["trade_count"] == 25 and m["net_pnl_bps"] == 250.0
    print("PASS_A1_NEW_SESSION_BREAK_003_FORWARD_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_new_session_break_003_forward_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = evaluate()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "candidate_id": result["candidate_id"],
        "boundary_utc": result["boundary_utc"],
        "completed_trades": result["completed_trades"],
        "sample_gap_to_25": result["sample_gap_to_25"],
        "a1_controls": result["a1_controls"].get("hard_control_states"),
        "falsified": result["mechanism_falsification"]["all_first_10_failed_2x_cost_mfe"],
        "next": result["next"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
