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
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import _side, _validate_side
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as child_eval
from backend.research.rebuild import trend_rider_wr80_us_chase_cooling_child_policy_v1 as primary_policy

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_g4_recent_historical_accelerator_v1.json"
V2_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
V2_FRESH = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
BREAK_FRESH = ROOT / "backend/research/rebuild/a1_break_reclaim_breakout_g4_fresh_latest.json"
LATEST = ROOT / "backend/research/rebuild/a1_top5_g4_recent_historical_accelerator_latest.json"
ESCROW_LATEST = ROOT / "backend/research/prep/a1_top5_g5_prep_escrow_latest.json"
KLINE_API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
SCHEMA = "zel.a1.top5.g4.recent_historical_accelerator.receipt.v1"
ESCROW_SCHEMA = "zel.a1.top5.g5.prep_escrow.v1"
INTERVAL_MS = {"1h": 3_600_000, "4h": 14_400_000}
WARMUP_BARS = 240
MAX_PAGES = 8
COST_BPS = 20.0
EPS = 1e-12

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


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def req(params: Mapping[str, Any]) -> Any:
    url = KLINE_API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    if isinstance(value, dict) and value.get("code") not in (None, 0):
        raise RuntimeError(f"BINGX:{value.get('code')}:{value.get('msg')}")
    return value


def decode(value: Any) -> list[dict[str, float]]:
    rows = value.get("data", value if isinstance(value, list) else []) if isinstance(value, (dict, list)) else []
    out: list[dict[str, float]] = []
    for row in rows:
        try:
            if isinstance(row, dict):
                ts = int(row.get("time") or row.get("openTime") or row.get("timestamp"))
                out.append({
                    "ts": ts,
                    "ts_ms": ts,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or row.get("vol") or 0.0),
                })
            else:
                ts = int(row[0])
                out.append({
                    "ts": ts,
                    "ts_ms": ts,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5] if len(row) > 5 else 0.0),
                })
        except Exception:
            continue
    return out


def paged_bars(symbol: str, interval: str, start_ms: int, evaluation_end_ms: int) -> list[dict[str, float]]:
    if interval not in INTERVAL_MS:
        raise RuntimeError(f"INTERVAL_UNSUPPORTED:{interval}")
    tf_ms = INTERVAL_MS[interval]
    warmup_floor = start_ms - WARMUP_BARS * tf_ms
    all_rows: dict[int, dict[str, float]] = {}
    end = evaluation_end_ms
    for _ in range(MAX_PAGES):
        page = sorted(decode(req({"symbol": symbol, "interval": interval, "limit": 1000, "endTime": end})), key=lambda x: int(x["ts"]))
        if not page:
            break
        for row in page:
            ts = int(row["ts"])
            if ts < evaluation_end_ms:
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
    return [x for x in rows if int(x["ts"]) >= warmup_floor]


def metrics(trades: Sequence[Mapping[str, Any]], calendar_days: float) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in trades]
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    gp, gl = sum(wins), sum(losses)
    eq = peak = dd = 0.0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    return {
        "closed_T": len(vals),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(vals) if vals else None,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "profit_factor_unbounded": bool(gp > 0 and gl == 0),
        "payoff": (avg_win / avg_loss) if avg_win is not None and avg_loss not in (None, 0) else None,
        "drawdown_bps": dd,
        "net_bps_per_calendar_day": sum(vals) / calendar_days if calendar_days > 0 else None,
        "fixed_cost_bps_per_trade": COST_BPS,
    }


def window_rows(trades: Sequence[Mapping[str, Any]], start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    return [dict(x) for x in trades if start_ms <= int(x["signal_ts"]) < end_ms]


def primary_trades(start_ms: int, end_ms: int, symbols: Sequence[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = primary_policy.TrendRiderWR80USChaseCoolingConfig()
    interval = ev.interval_for_ms(int(cfg.timeframe_ms))
    if interval != "1h":
        raise RuntimeError(f"PRIMARY_INTERVAL_DRIFT:{interval}")
    policy_path = ROOT / "backend/research/rebuild/trend_rider_wr80_us_chase_cooling_child_policy_v1.py"
    policy_sha = ev.git_blob_sha(policy_path)
    max_hold = int(getattr(cfg, "timeout_bars", 48))
    evaluation_end = end_ms + (max_hold + 2) * INTERVAL_MS[interval]
    out: list[dict[str, Any]] = []
    source: dict[str, Any] = {}
    for symbol in symbols:
        bars = paged_bars(symbol, interval, start_ms, evaluation_end)
        source[symbol] = {
            "bars": len(bars),
            "first_ts": int(bars[0]["ts"]) if bars else None,
            "last_ts": int(bars[-1]["ts"]) if bars else None,
        }
        blocked_until_ts = -1
        warmup = int(getattr(cfg, "warmup_bars", max(64, int(getattr(cfg, "lookback", 20)) + 10)))
        for i in range(max(1, warmup), len(bars) - 1):
            signal_ts = int(bars[i]["ts"])
            if signal_ts < start_ms:
                continue
            if signal_ts >= end_ms:
                break
            try:
                feature = primary_policy.compute_trend_rider_feature(
                    bars[: i + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg
                )
                intent = primary_policy.build_trend_rider_intent(
                    feature, policy_source_sha=policy_sha, verified_round_trip_cost_bps=COST_BPS, config=cfg
                )
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_", "WINDOW_", "ATR_")):
                    continue
                raise
            if bool(getattr(intent, "no_trade")):
                continue
            side_name = str(getattr(intent, "side"))
            if side_name not in {"long", "short"}:
                raise RuntimeError(f"PRIMARY_SIDE_UNSUPPORTED:{side_name}")
            entry_i = i + 1
            entry_ts = int(bars[entry_i]["ts"])
            owns, cooldown_bars = ev.execution_ownership_policy(intent)
            if owns and ev.ownership_blocked(entry_ts, blocked_until_ts):
                continue
            entry_px = float(bars[entry_i]["open"])
            side = 1.0 if side_name == "long" else -1.0
            timeout = getattr(intent, "timeout", {}) or {}
            timeout_bars = int(timeout.get("bars", getattr(cfg, "timeout_bars", 1)))
            sl, tp = getattr(intent, "sl", None), getattr(intent, "tp", None)
            if sl is None and tp is None:
                raise RuntimeError("PRIMARY_EXIT_GEOMETRY_MISSING")
            last_j = min(len(bars) - 1, entry_i + max(1, timeout_bars))
            exit_px: float | None = None
            exit_ts: int | None = None
            reason: str | None = None
            for j in range(entry_i, last_j + 1):
                bar = bars[j]
                low, high = float(bar["low"]), float(bar["high"])
                if sl is not None and ((side > 0 and low <= float(sl)) or (side < 0 and high >= float(sl))):
                    exit_px, exit_ts, reason = float(sl), int(bar["ts"]), "SL"
                    break
                if tp is not None and ((side > 0 and high >= float(tp)) or (side < 0 and low <= float(tp))):
                    exit_px, exit_ts, reason = float(tp), int(bar["ts"]), "TP"
                    break
            if exit_px is None:
                if last_j >= len(bars) - 1:
                    continue
                exit_px, exit_ts, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts"]), "TIMEOUT"
            if owns:
                blocked_until_ts = max(
                    blocked_until_ts,
                    ev.reserve_position_ownership(
                        exit_ts=int(exit_ts), open_horizon_ts=None,
                        cooldown_bars=cooldown_bars, timeframe_ms=INTERVAL_MS[interval]
                    ),
                )
            gross = side * (float(exit_px) - entry_px) / entry_px * 10_000.0
            net = gross - COST_BPS
            identity = {
                "lane_id": "trend_rider_primary_wr8125",
                "symbol": symbol,
                "signal_ts": signal_ts,
                "entry_ts": entry_ts,
                "exit_ts": int(exit_ts),
                "side": side_name,
            }
            out.append({
                "trade_id": stable(identity), **identity,
                "entry_px": entry_px, "exit_px": float(exit_px), "reason": reason,
                "gross_bps": gross, "net_bps": net, "cost_bps": COST_BPS,
            })
    out.sort(key=lambda x: (int(x["exit_ts"]), int(x["signal_ts"]), str(x["symbol"]), str(x["trade_id"])))
    if len({x["trade_id"] for x in out}) != len(out):
        raise RuntimeError("PRIMARY_DUPLICATE_TRADE")
    return out, source


def v2_trades(child: Mapping[str, Any], start_ms: int, end_ms: int, symbols: Sequence[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    child_id = str(child.get("child_id") or "")
    spec = child.get("executable_spec")
    if not child_id or not isinstance(spec, Mapping):
        raise RuntimeError("V2_SPEC_REQUIRED")
    interval = str(spec.get("bar_interval") or "")
    if interval != "4h":
        raise RuntimeError(f"V2_INTERVAL_DRIFT:{child_id}:{interval}")
    hold = int(spec.get("max_hold_bars") or 0)
    if hold <= 0:
        raise RuntimeError("V2_HOLD_REQUIRED")
    if abs(float(spec.get("cost_bps_per_trade") or 0.0) - COST_BPS) > EPS:
        raise RuntimeError(f"V2_COST_DRIFT:{child_id}")
    evaluation_end = end_ms + (hold + 2) * INTERVAL_MS[interval]
    entry_rule = str(spec.get("entry_rule") or "")
    side_rule = str(spec.get("side_rule") or "")
    out: list[dict[str, Any]] = []
    source: dict[str, Any] = {}
    for symbol in symbols:
        bars = paged_bars(symbol, interval, start_ms, evaluation_end)
        source[symbol] = {
            "bars": len(bars),
            "first_ts": int(bars[0]["ts"]) if bars else None,
            "last_ts": int(bars[-1]["ts"]) if bars else None,
        }
        if len(bars) < 60:
            continue
        _, engine = child_eval._features(bars, spec)
        engine.validate(entry_rule)
        _validate_side(side_rule, engine)
        i = 50
        while i < len(bars) - 1:
            signal_ts = int(bars[i]["ts"])
            if signal_ts < start_ms:
                i += 1
                continue
            if signal_ts >= end_ms:
                break
            try:
                fire = bool(engine.eval(entry_rule, i))
            except (TypeError, ZeroDivisionError, ValueError):
                fire = False
            if not fire:
                i += 1
                continue
            side_name = _side(side_rule, engine, i)
            entry_i = i + 1
            exit_i = entry_i + hold - 1
            if exit_i >= len(bars):
                break
            entry_px = float(bars[entry_i]["open"])
            exit_px = float(bars[exit_i]["close"])
            gross = (exit_px / entry_px - 1.0) * 10_000.0 * (1.0 if side_name == "long" else -1.0)
            net = gross - COST_BPS
            identity = {
                "lane_id": str(child.get("lane_id") or ""),
                "child_id": child_id,
                "symbol": symbol,
                "signal_ts": signal_ts,
                "entry_ts": int(bars[entry_i]["ts"]),
                "exit_ts": int(bars[exit_i]["ts"]),
                "side": side_name,
            }
            out.append({
                "trade_id": stable(identity), **identity,
                "entry_px": entry_px, "exit_px": exit_px, "reason": "TIME_STOP",
                "gross_bps": gross, "net_bps": net, "cost_bps": COST_BPS,
            })
            i = exit_i + 1
    out.sort(key=lambda x: (int(x["exit_ts"]), int(x["signal_ts"]), str(x["symbol"]), str(x["trade_id"])))
    if len({x["trade_id"] for x in out}) != len(out):
        raise RuntimeError(f"V2_DUPLICATE_TRADE:{child_id}")
    return out, source


def classify(contract: Mapping[str, Any], window_metrics: list[Mapping[str, Any]], aggregate: Mapping[str, Any]) -> str:
    gate = contract["economic_gate"]
    n = int(aggregate["closed_T"])
    if n < int(gate["minimum_aggregate_closed_T"]):
        return str(gate["states"]["inconclusive"])
    pf = aggregate.get("profit_factor")
    pf_ok = bool(aggregate.get("profit_factor_unbounded")) or (pf is not None and float(pf) > float(gate["aggregate_profit_factor_gt"]))
    econ_ok = (
        float(aggregate["net_pnl_bps"]) > float(gate["aggregate_net_pnl_bps_gt"])
        and aggregate.get("net_expectancy_bps") is not None
        and float(aggregate["net_expectancy_bps"]) > float(gate["aggregate_net_expectancy_bps_gt"])
        and pf_ok
    )
    if not econ_ok:
        return str(gate["states"]["fail"])
    both_positive = True
    for row in window_metrics:
        if int(row["closed_T"]) <= 0 or row.get("net_expectancy_bps") is None or float(row["net_expectancy_bps"]) <= float(gate["each_window_net_expectancy_bps_gt_for_strong_pass"]):
            both_positive = False
    return str(gate["states"]["strong_pass"] if both_positive else gate["states"]["mixed"])


def assert_contract(contract: Mapping[str, Any], top5: Mapping[str, Any], freeze: Mapping[str, Any], break_fresh: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != "zel.a1.top5.g4.recent_historical_accelerator.contract.v1":
        raise RuntimeError("CONTRACT_SCHEMA_DRIFT")
    if contract.get("state") != "PREREGISTERED_BEFORE_RECENT_HISTORICAL_RESULTS":
        raise RuntimeError("CONTRACT_NOT_PREREGISTERED")
    sem = contract["evidence_semantics"]
    for key in ("historical_result_is_formal_g4_pass", "historical_result_is_formal_g5_pass", "old_history_union_into_fresh_cohort", "post_result_retune", "threshold_sweep", "window_sweep"):
        if sem.get(key) is not False:
            raise RuntimeError(f"HISTORICAL_CONTAMINATION_GUARD_DRIFT:{key}")
    if int(sem.get("historical_trade_credit_to_fresh_g4_T", -1)) != 0 or int(sem.get("historical_trade_credit_to_g5_T", -1)) != 0:
        raise RuntimeError("HISTORICAL_CREDIT_MUST_BE_ZERO")
    if top5.get("state") != "CURRENT_TOP5_ONLY":
        raise RuntimeError("TOP5_SSOT_STATE_DRIFT")
    broad = next(x for x in top5["top5"] if x["lane_id"] == "trend_rider_broad_wr7000")
    if broad.get("terminal_state") != "G4_PASS_SURVIVOR_READY":
        raise RuntimeError("BROAD_G4_SURVIVOR_DRIFT")
    if freeze.get("schema_version") != "zel.a1.top5.replacement_child_freeze.v2":
        raise RuntimeError("V2_FREEZE_SCHEMA_DRIFT")
    guard = contract["fresh_authority_guards"]
    if break_fresh.get("activation_id") != guard["break_salvage_activation_id"] or break_fresh.get("cohort_id") != guard["break_salvage_cohort_id"]:
        raise RuntimeError("BREAK_SALVAGE_ACTIVATION_DRIFT")
    if break_fresh.get("prospective_boundary_utc") != guard["break_salvage_boundary_utc"]:
        raise RuntimeError("BREAK_SALVAGE_BOUNDARY_DRIFT")
    if int(break_fresh.get("minimum_fresh_T_before_gate") or 0) != int(guard["break_salvage_minimum_fresh_T"]):
        raise RuntimeError("BREAK_SALVAGE_FRESH6_DRIFT")


def run(out: Path, escrow_out: Path) -> dict[str, Any]:
    contract, top5, freeze, v2fresh, break_fresh = read(CONTRACT), read(TOP5), read(V2_FREEZE), read(V2_FRESH), read(BREAK_FRESH)
    assert_contract(contract, top5, freeze, break_fresh)
    before_hashes = {str(p.relative_to(ROOT)): file_sha(p) for p in (TOP5, V2_FRESH, BREAK_FRESH)}
    windows = contract["historical_windows"]
    starts = [utc_ms(x["start_utc"]) for x in windows]
    ends = [utc_ms(x["end_utc"]) for x in windows]
    global_start, global_end = min(starts), max(ends)
    calendar_days = (global_end - global_start) / 86_400_000.0
    freeze_children = {str(x["lane_id"]): x for x in freeze["children"]}
    lane_results: dict[str, Any] = {}
    for lane_id in contract["scope"]["include_lane_ids"]:
        lane_contract = contract["lanes"][lane_id]
        if lane_id == "trend_rider_primary_wr8125":
            trades, source = primary_trades(global_start, global_end, lane_contract["symbols"])
            architecture = "CURRENT_PRIMARY_WR80_US_CHASE_COOLING_POLICY"
        else:
            child = freeze_children.get(lane_id)
            if not isinstance(child, Mapping):
                raise RuntimeError(f"V2_CHILD_LANE_MISSING:{lane_id}")
            if child.get("child_id") != lane_contract["child_id"]:
                raise RuntimeError(f"V2_CHILD_ID_DRIFT:{lane_id}")
            trades, source = v2_trades(child, global_start, global_end, freeze["frozen_symbol_universe"])
            architecture = str(child["architecture_family"])
        per_window: list[dict[str, Any]] = []
        for raw, start_ms, end_ms in zip(windows, starts, ends):
            rows = window_rows(trades, start_ms, end_ms)
            days = (end_ms - start_ms) / 86_400_000.0
            per_window.append({
                "window_id": raw["window_id"], "start_utc": raw["start_utc"], "end_utc": raw["end_utc"],
                **metrics(rows, days), "trade_ids": [x["trade_id"] for x in rows],
            })
        aggregate = metrics(trades, calendar_days)
        state = classify(contract, per_window, aggregate)
        lane_results[lane_id] = {
            "lane_id": lane_id,
            "strategy_id": lane_contract.get("strategy_id") or freeze_children[lane_id]["parent_strategy_id"],
            "architecture": architecture,
            "state": state,
            "historical_label": contract["evidence_semantics"]["label"],
            "historical_credit_to_fresh_g4_T": 0,
            "historical_credit_to_g5_T": 0,
            "formal_g4_pass": False,
            "formal_g5_pass": False,
            "aggregate": aggregate,
            "windows": per_window,
            "source_summary": source,
            "trade_identity_sha256": stable([x["trade_id"] for x in trades]),
            "trades": trades,
            "g5_prep_escrow_eligible": state == contract["economic_gate"]["states"]["strong_pass"],
        }
    after_hashes = {str(p.relative_to(ROOT)): file_sha(p) for p in (TOP5, V2_FRESH, BREAK_FRESH)}
    if before_hashes != after_hashes:
        raise RuntimeError("FRESH_AUTHORITY_MUTATED_BY_HISTORICAL_ACCELERATOR")
    strong = [k for k, v in lane_results.items() if v["g5_prep_escrow_eligible"]]
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_RECENT_HISTORICAL_ACCELERATOR_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": file_sha(CONTRACT),
        "base_master_sha": contract["base_master_sha"],
        "lane_count": len(lane_results),
        "strong_pass_count": len(strong),
        "strong_pass_lane_ids": strong,
        "lanes": lane_results,
        "historical_trade_credit_to_fresh_g4_T": 0,
        "historical_trade_credit_to_g5_T": 0,
        "g5_prep_escrow_is_contingent_only": True,
        "fresh_authority_hashes_before": before_hashes,
        "fresh_authority_hashes_after": after_hashes,
        "fresh_authority_unchanged": before_hashes == after_hashes,
        "break_salvage_fresh6": {
            "activation_id": break_fresh["activation_id"],
            "cohort_id": break_fresh["cohort_id"],
            "boundary_utc": break_fresh["prospective_boundary_utc"],
            "fresh_g4_T": break_fresh["fresh_g4_T"],
            "minimum_fresh_T_before_gate": break_fresh["minimum_fresh_T_before_gate"],
            "unchanged": True,
        },
        "broad_g5_mutated": False,
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        **AUTH,
    }
    result["deterministic_result_sha256"] = stable({k: v for k, v in result.items() if k not in {"observed_at_utc", "receipt_sha256", "deterministic_result_sha256"}})
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    escrow_entries = {
        lane_id: {
            "state": "G5_PREP_ESCROW_READY_CONTINGENT_ON_FRESH_G4_PASS",
            "lane_id": lane_id,
            "historical_accelerator_receipt_sha256": result["receipt_sha256"],
            "historical_state": lane_results[lane_id]["state"],
            "historical_metrics": lane_results[lane_id]["aggregate"],
            "formal_g4_pass_required_before_activation": True,
            "formal_g5_T": 0,
            "g4_credit_T": 0,
            "g5_credit_T": 0,
            "activation_id": None,
            "cohort_id": None,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "invalid_if_fresh_g4_fails": True,
        }
        for lane_id in strong
    }
    escrow = {
        "schema_version": ESCROW_SCHEMA,
        "state": "CONTINGENT_G5_PREP_ESCROW_READY" if escrow_entries else "NO_HISTORICAL_STRONG_PASS_NO_ESCROW",
        "source_accelerator_receipt_sha256": result["receipt_sha256"],
        "entries": escrow_entries,
        "formal_g5_T": 0,
        "historical_credit_to_g4_T": 0,
        "historical_credit_to_g5_T": 0,
        "broad_g5_mutated": False,
        **AUTH,
    }
    escrow["receipt_sha256"] = stable(escrow)
    out.parent.mkdir(parents=True, exist_ok=True)
    escrow_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    escrow_out.write_text(json.dumps(escrow, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = read(CONTRACT)
    assert c["state"] == "PREREGISTERED_BEFORE_RECENT_HISTORICAL_RESULTS"
    assert c["scope"]["exclude_lane_ids"] == ["trend_rider_broad_wr7000"]
    assert len(c["scope"]["include_lane_ids"]) == 4
    assert c["evidence_semantics"]["historical_trade_credit_to_fresh_g4_T"] == 0
    assert c["evidence_semantics"]["historical_trade_credit_to_g5_T"] == 0
    assert c["fresh_authority_guards"]["break_salvage_minimum_fresh_T"] == 6
    assert COST_BPS == 20.0
    print("PASS_A1_TOP5_G4_RECENT_HISTORICAL_ACCELERATOR_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_g4_recent_historical_accelerator_v1.json"))
    ap.add_argument("--escrow-out", type=Path, default=Path("out/a1_top5_g5_prep_escrow_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out, args.escrow_out)
    print(json.dumps({
        "state": r["state"],
        "strong_pass_lane_ids": r["strong_pass_lane_ids"],
        "lane_states": {k: v["state"] for k, v in r["lanes"].items()},
        "aggregate": {k: v["aggregate"] for k, v in r["lanes"].items()},
        "break_salvage_fresh6": r["break_salvage_fresh6"],
        "receipt_sha256": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
