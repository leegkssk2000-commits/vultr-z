#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import breakout_policy_batch_v1 as breakout
from backend.research.rebuild import trend_policy_batch_v1 as trend
from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
LATEST = ROOT / "backend/research/rebuild/a1_finalist_sample_stall_no_idle_latest.json"
MIN_TRADES = 25
LOSS_STREAK_TRIGGER = 3
STALL_LAST_TRADE_HOURS = 12.0
MIN_ELAPSED_HOURS_FOR_STALL = 24.0
PROJECTED_REMAINING_HOURS_ALERT = 168.0

TARGETS = {
    "supertrend_pullback": {
        "child_policy": "backend/research/rebuild/supertrend_pullback_touch_reclaim_child_policy_v1.py",
        "child_id": "supertrend_pullback__touch_reclaim_v1",
        "changed_axis": "PULLBACK_EVENT_CLOSE_BAND_TO_INTRABAR_EMA_TOUCH_RECLAIM",
    },
    "trend_ma_macd": {
        "child_policy": "backend/research/rebuild/trend_ma_macd_reaccel_child_policy_v1.py",
        "child_id": "trend_ma_macd__same_sign_reaccel_v1",
        "changed_axis": "MACD_EVENT_ZERO_CROSS_TO_SAME_SIGN_REACCELERATION",
    },
    "break_and_continue": {
        "child_policy": "backend/research/rebuild/break_and_continue_box_break_child_policy_v1.py",
        "child_id": "break_and_continue__box_break_v1",
        "changed_axis": "BREAKOUT_REFERENCE_PRIOR20_RANGE_TO_EXISTING_8BAR_BOX",
    },
}

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "exchange_order_submitted": False,
}


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def metric(row: Mapping[str, Any], name: str) -> float | None:
    m = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
    value = m.get(name, row.get(name))
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def tail_loss_streak(trades: list[dict[str, Any]]) -> int:
    streak = 0
    for trade in sorted(trades, key=lambda x: (int(x.get("exit_ts") or 0), int(x.get("entry_ts") or 0)), reverse=True):
        if float(trade.get("net_bps") or 0.0) < 0.0:
            streak += 1
        else:
            break
    return streak


def max_loss_streak(trades: list[dict[str, Any]]) -> int:
    best = current = 0
    for trade in sorted(trades, key=lambda x: (int(x.get("exit_ts") or 0), int(x.get("entry_ts") or 0))):
        if float(trade.get("net_bps") or 0.0) < 0.0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def source_frontier(receipt: Mapping[str, Any]) -> tuple[int | None, int, str]:
    source = receipt.get("source") if isinstance(receipt.get("source"), Mapping) else {}
    rows = [x for x in (source.get("symbols") or []) if isinstance(x, Mapping)]
    latest = max((int(x["last_post_boundary_ts"]) for x in rows if x.get("last_post_boundary_ts") is not None), default=None)
    bars = sum(int(x.get("bars_post_boundary") or 0) for x in rows)
    return latest, bars, str(source.get("interval") or "")


def next_full_hour_iso(ts_ms: int) -> str:
    hour = 3_600_000
    nxt = ((int(ts_ms) // hour) + 1) * hour
    return datetime.fromtimestamp(nxt / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parent_policy_path(strategy_id: str, inventory: Mapping[str, Any]) -> Path:
    return ROOT / str(inventory["strategies"][strategy_id]["policy_owner"])


def run_receipt(strategy_id: str, policy_path: Path, boundary: str, out: Path) -> dict[str, Any]:
    receipt, shadow = run_terminal_shadow(
        strategy_id=strategy_id,
        policy_path=policy_path,
        fresh_boundary_utc=boundary,
        out=out,
    )
    receipt["shadow_replay_meta"] = shadow
    return receipt


def feature_funnel(strategy_id: str, boundary: str, symbols: tuple[str, ...] = ("BTC-USDT", "ETH-USDT")) -> dict[str, Any]:
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    stages: list[tuple[str, int]] = []
    counts: dict[str, int] = {}
    total = 0
    for symbol in symbols:
        bars = ev.fetch_bars(symbol, "1h", 1000)
        for i in range(64, len(bars) - 1):
            if int(bars[i]["ts_ms"]) < boundary_ms:
                continue
            total += 1
            prefix = bars[: i + 1]
            if strategy_id == "trend_ma_macd":
                f = trend.compute_trend_ma_macd_feature(prefix, symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=trend.TrendPolicyConfig())
                v = f.values
                align = (float(f.close) > float(v["ema_fast"]) > float(v["ema_slow"])) or (float(f.close) < float(v["ema_fast"]) < float(v["ema_slow"]))
                cross = bool(v["long_cross"] or v["short_cross"])
                chase = cross and float(v["chase_atr"]) <= 1.5
                counts["ema_alignment"] = counts.get("ema_alignment", 0) + int(align)
                counts["ema_plus_macd_zero_cross"] = counts.get("ema_plus_macd_zero_cross", 0) + int(cross)
                counts["plus_anti_chase"] = counts.get("plus_anti_chase", 0) + int(chase)
            elif strategy_id == "supertrend_pullback":
                f = trend.compute_supertrend_pullback_feature(prefix, symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=trend.TrendPolicyConfig())
                v = f.values
                reclaim = bool(v["long_reclaim"] or v["short_reclaim"])
                depth = reclaim and 0.15 <= float(v["pullback_depth_atr"]) <= 2.0
                chase = depth and float(v["chase_atr"]) <= 1.5
                counts["aligned_reclaim_event"] = counts.get("aligned_reclaim_event", 0) + int(reclaim)
                counts["plus_pullback_depth"] = counts.get("plus_pullback_depth", 0) + int(depth)
                counts["plus_anti_chase"] = counts.get("plus_anti_chase", 0) + int(chase)
            elif strategy_id == "break_and_continue":
                f = breakout.compute_break_and_continue_feature(prefix, symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=breakout.BreakoutPolicyConfig())
                v = f.values
                close = float(f.close)
                raw = close > float(v["prior_high"]) or close < float(v["prior_low"])
                combined = bool(v["long_break"] or v["short_break"])
                box = combined and float(v["box_height_atr"]) <= 4.0
                chase = box and float(v["chase_atr"]) <= 1.0
                counts["prior20_range_break"] = counts.get("prior20_range_break", 0) + int(raw)
                counts["plus_ema_alignment"] = counts.get("plus_ema_alignment", 0) + int(combined)
                counts["plus_box_geometry"] = counts.get("plus_box_geometry", 0) + int(box)
                counts["plus_anti_chase"] = counts.get("plus_anti_chase", 0) + int(chase)
            else:
                raise RuntimeError(f"UNKNOWN_TARGET:{strategy_id}")
    previous = total
    bottleneck = None
    largest_drop = -1.0
    for name, passed in counts.items():
        ratio = passed / max(1, previous)
        drop = 1.0 - ratio
        stages.append((name, passed))
        if drop > largest_drop:
            largest_drop = drop
            bottleneck = name
        previous = passed
    return {
        "eligible_bar_opportunities": total,
        "stages": [{"stage": name, "passed": count} for name, count in stages],
        "largest_sequential_drop_stage": bottleneck,
        "largest_sequential_drop_fraction": largest_drop if bottleneck else None,
    }


def pace_diagnostic(receipt: Mapping[str, Any], funnel: Mapping[str, Any]) -> dict[str, Any]:
    boundary = str(receipt.get("boundary_utc") or "")
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    latest, post_bars, interval = source_frontier(receipt)
    trades = [dict(x) for x in (receipt.get("trades") or [])]
    completed = len(trades)
    intents = int(receipt.get("intent_count") or 0)
    elapsed_h = max(0.0, ((latest or boundary_ms) - boundary_ms) / 3_600_000.0)
    last_exit = max((int(x.get("exit_ts") or 0) for x in trades), default=boundary_ms)
    last_trade_age_h = max(0.0, ((latest or boundary_ms) - last_exit) / 3_600_000.0)
    throughput = completed / elapsed_h if elapsed_h > 0 else 0.0
    projected = (MIN_TRADES - completed) / throughput if completed < MIN_TRADES and throughput > 0 else (0.0 if completed >= MIN_TRADES else None)
    closure_gap = max(0, intents - completed)
    closure_lag = closure_gap >= max(2, math.ceil(max(1, intents) * 0.25))
    stall = bool(
        completed < MIN_TRADES
        and elapsed_h >= MIN_ELAPSED_HOURS_FOR_STALL
        and (last_trade_age_h >= STALL_LAST_TRADE_HOURS or projected is None or projected > PROJECTED_REMAINING_HOURS_ALERT)
    )
    tail = tail_loss_streak(trades)
    if tail >= LOSS_STREAK_TRIGGER:
        root = "LOSS_CLUSTER"
        route = "USE_INSTALLED_A1_RECENT_LOSS_CLUSTER_ACTIONABLE_V2_IN_PARALLEL"
    elif closure_lag:
        root = "EXIT_CLOSURE_LAG"
        route = "DIAGNOSE_OPEN_TO_CLOSE_LIFECYCLE_BEFORE_ADMISSION_EXPANSION"
    elif stall:
        root = "ADMISSION_SAMPLE_STALL"
        route = "RUN_ONE_AXIS_SAMPLE_EXPANSION_COMPARATOR_NOW"
    else:
        root = "NORMAL_ACCUMULATION"
        route = "KEEP_COLLECTING_AND_RECHECK_HOURLY"
    return {
        "completed_trades": completed,
        "intent_count": intents,
        "intent_minus_completed": closure_gap,
        "post_boundary_bars_total": post_bars,
        "source_interval": interval,
        "elapsed_hours": elapsed_h,
        "last_completed_trade_age_hours": last_trade_age_h,
        "completed_trades_per_hour": throughput,
        "projected_remaining_hours_to_25": projected,
        "tail_loss_streak": tail,
        "max_loss_streak": max_loss_streak(trades),
        "sample_stall_triggered": stall,
        "closure_lag_triggered": closure_lag,
        "root_cause_class": root,
        "recommended_route": route,
        "feature_funnel": funnel,
        "monitor_thresholds_are_research_sla_not_strategy_parameters": True,
    }


def comparison(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    pm = {
        "trades": int(parent.get("completed_trades") or 0),
        "win_rate": metric(parent, "win_rate"),
        "net_pnl_bps": metric(parent, "net_pnl_bps"),
        "net_expectancy_bps": metric(parent, "net_expectancy_bps"),
        "profit_factor": metric(parent, "net_profit_factor") or metric(parent, "profit_factor"),
        "max_drawdown_bps": metric(parent, "max_drawdown_bps"),
    }
    cm = {
        "trades": int(child.get("completed_trades") or 0),
        "win_rate": metric(child, "win_rate"),
        "net_pnl_bps": metric(child, "net_pnl_bps"),
        "net_expectancy_bps": metric(child, "net_expectancy_bps"),
        "profit_factor": metric(child, "net_profit_factor") or metric(child, "profit_factor"),
        "max_drawdown_bps": metric(child, "max_drawdown_bps"),
    }
    def better(name: str) -> bool:
        return cm[name] is not None and pm[name] is not None and float(cm[name]) > float(pm[name])
    economics_positive = bool((cm["net_pnl_bps"] or 0.0) > 0.0 and (cm["net_expectancy_bps"] or 0.0) > 0.0 and (cm["profit_factor"] is None or cm["profit_factor"] >= 1.0))
    sample_growth = cm["trades"] > pm["trades"]
    quality_gain = any(better(x) for x in ("win_rate", "net_pnl_bps", "net_expectancy_bps"))
    return {
        "parent": pm,
        "child": cm,
        "trade_growth": cm["trades"] - pm["trades"],
        "win_rate_delta": None if cm["win_rate"] is None or pm["win_rate"] is None else cm["win_rate"] - pm["win_rate"],
        "net_pnl_delta_bps": None if cm["net_pnl_bps"] is None or pm["net_pnl_bps"] is None else cm["net_pnl_bps"] - pm["net_pnl_bps"],
        "expectancy_delta_bps": None if cm["net_expectancy_bps"] is None or pm["net_expectancy_bps"] is None else cm["net_expectancy_bps"] - pm["net_expectancy_bps"],
        "sample_growth_improved": sample_growth,
        "child_economics_positive": economics_positive,
        "at_least_one_quality_metric_improved": quality_gain,
        "development_prereg_eligible": bool(sample_growth and economics_positive and quality_gain),
        "promotion_claim": False,
    }


def run(out: Path) -> dict[str, Any]:
    ledger, inventory = read(LEDGER), read(INVENTORY)
    previous = read(LATEST) if LATEST.exists() else {}
    previous_targets = {str(x.get("strategy_id")): x for x in previous.get("targets", []) if isinstance(x, Mapping)}
    targets: list[dict[str, Any]] = []
    for strategy_id, spec in TARGETS.items():
        canonical = (ledger.get("strategies") or {}).get(strategy_id) or {}
        boundary = str(canonical.get("prospective_boundary_utc") or "")
        if not boundary:
            raise RuntimeError(f"BOUNDARY_MISSING:{strategy_id}")
        child_path = ROOT / str(spec["child_policy"])
        prior = previous_targets.get(strategy_id) or {}
        frozen = str(prior.get("frozen_child_fresh_boundary_utc") or "")
        row: dict[str, Any] = {
            "strategy_id": strategy_id,
            "child_id": spec["child_id"],
            "changed_axis": spec["changed_axis"],
            "canonical_boundary_utc": boundary,
            "frozen_child_fresh_boundary_utc": frozen or None,
            "incumbent_mutated": False,
            "numeric_threshold_sweep": False,
            "post_outcome_threshold_rescue": False,
            **AUTH,
        }
        if frozen:
            child = run_receipt(strategy_id, child_path, frozen, out.parent / f".{strategy_id}.child_fresh.json")
            row["mode"] = "FROZEN_CHILD_FRESH_COLLECTION"
            row["child_fresh"] = {
                "completed_trades": int(child.get("completed_trades") or 0),
                "sample_gap_to_25": max(0, MIN_TRADES - int(child.get("completed_trades") or 0)),
                "win_rate": metric(child, "win_rate"),
                "net_pnl_bps": metric(child, "net_pnl_bps"),
                "net_expectancy_bps": metric(child, "net_expectancy_bps"),
                "profit_factor": metric(child, "net_profit_factor") or metric(child, "profit_factor"),
                "source_quality_state": str((child.get("source_quality_gate") or {}).get("state") or ""),
                "integrity_defects": list(child.get("integrity_defects") or []),
                "leakage_lookahead": int(child.get("leakage_lookahead") or 0),
            }
            row["state"] = "READY_CHILD_FRESH_25_FOR_IDENTITY_HARDENING" if int(child.get("completed_trades") or 0) >= MIN_TRADES else "COLLECT_CHILD_FRESH_TO_25"
            row["next"] = "BUILD_IDENTITY_SPECIFIC_H4_H5" if int(child.get("completed_trades") or 0) >= MIN_TRADES else "CONTINUE_HOURLY_CHILD_FRESH_COLLECTION"
        else:
            parent = run_receipt(strategy_id, parent_policy_path(strategy_id, inventory), boundary, out.parent / f".{strategy_id}.parent.json")
            funnel = feature_funnel(strategy_id, boundary)
            diag = pace_diagnostic(parent, funnel)
            row["parent_diagnostic"] = diag
            row["parent_metrics"] = {
                "completed_trades": int(parent.get("completed_trades") or 0),
                "win_rate": metric(parent, "win_rate"),
                "net_pnl_bps": metric(parent, "net_pnl_bps"),
                "net_expectancy_bps": metric(parent, "net_expectancy_bps"),
            }
            if diag["root_cause_class"] == "ADMISSION_SAMPLE_STALL":
                child = run_receipt(strategy_id, child_path, boundary, out.parent / f".{strategy_id}.child_discovery.json")
                comp = comparison(parent, child)
                row["sample_expansion_comparison"] = comp
                if comp["development_prereg_eligible"]:
                    latest, _, _ = source_frontier(parent)
                    if latest is None:
                        raise RuntimeError(f"SOURCE_FRONTIER_MISSING:{strategy_id}")
                    frozen = next_full_hour_iso(latest)
                    row["frozen_child_fresh_boundary_utc"] = frozen
                    row["state"] = "PASS_SAMPLE_STALL_CHILD_PREREG_FROZEN"
                    row["next"] = "START_HOURLY_CHILD_FRESH_COLLECTION_FROM_FROZEN_BOUNDARY"
                else:
                    row["state"] = "HOLD_SAMPLE_EXPANSION_CHILD_NOT_PARETO_USEFUL"
                    row["next"] = "ROTATE_TO_NEXT_DISTINCT_MECHANISM_AXIS_NOT_THRESHOLD_TUNING"
            elif diag["root_cause_class"] == "LOSS_CLUSTER":
                row["state"] = "ROUTE_EXISTING_LOSS_CLUSTER_REPAIR"
                row["next"] = "A1_RECENT_LOSS_CLUSTER_ACTIONABLE_V2"
            elif diag["root_cause_class"] == "EXIT_CLOSURE_LAG":
                row["state"] = "HOLD_EXIT_LIFECYCLE_DIAGNOSIS_REQUIRED"
                row["next"] = "OPEN_TO_CLOSE_LIFECYCLE_DIAGNOSTIC_NO_ENTRY_RELAXATION"
            else:
                row["state"] = "PASS_ACCUMULATION_WITH_ACTIVE_HOURLY_RECHECK"
                row["next"] = "RECHECK_STALL_AND_LOSS_CLUSTER_HOURLY"
        row["receipt_sha256"] = stable({k: v for k, v in row.items() if k != "receipt_sha256"})
        targets.append(row)

    states = [x["state"] for x in targets]
    result = {
        "schema_version": "zel.a1.finalist.sample_stall.no_idle.v1",
        "state": "PASS_NO_IDLE_RESEARCH_ACTIVE",
        "purpose": "Treat slow sample growth as a research failure mode instead of passively waiting; diagnose stall/loss/closure causes, test one-axis mechanism-preserving sample-expansion children, freeze successful development children prospectively, and continue fresh evidence hourly.",
        "targets": targets,
        "frozen_child_count": sum(bool(x.get("frozen_child_fresh_boundary_utc")) for x in targets),
        "fresh25_ready_count": sum(x["state"] == "READY_CHILD_FRESH_25_FOR_IDENTITY_HARDENING" for x in targets),
        "loss_cluster_routed_count": sum(x["state"] == "ROUTE_EXISTING_LOSS_CLUSTER_REPAIR" for x in targets),
        "sample_stall_hold_count": sum(x["state"] == "HOLD_SAMPLE_EXPANSION_CHILD_NOT_PARETO_USEFUL" for x in targets),
        "strategy_parameters_changed": False,
        "thresholds_changed": False,
        "canonical_ledger_mutation": False,
        "canonical_inventory_mutation": False,
        "research_monitor_sla": {
            "minimum_elapsed_hours_before_stall_check": MIN_ELAPSED_HOURS_FOR_STALL,
            "last_completed_trade_stall_hours": STALL_LAST_TRADE_HOURS,
            "projected_remaining_hours_alert": PROJECTED_REMAINING_HOURS_ALERT,
            "loss_streak_trigger": LOSS_STREAK_TRIGGER,
            "not_strategy_parameters": True,
        },
        "next": "KEEP_ALL_PARENT_COLLECTORS_RUNNING_AND_RUN_THIS_ROUTER_HOURLY",
        **AUTH,
    }
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    for p in out.parent.glob(".*.parent.json"):
        p.unlink(missing_ok=True)
    for p in out.parent.glob(".*.child_discovery.json"):
        p.unlink(missing_ok=True)
    for p in out.parent.glob(".*.child_fresh.json"):
        p.unlink(missing_ok=True)
    return result


def self_test() -> int:
    assert set(TARGETS) == {"supertrend_pullback", "trend_ma_macd", "break_and_continue"}
    assert LOSS_STREAK_TRIGGER == 3
    assert STALL_LAST_TRADE_HOURS > 0 and MIN_ELAPSED_HOURS_FOR_STALL > 0
    assert AUTH["selection_authority"] is False and AUTH["promotion_authority"] is False
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_FINALIST_SAMPLE_STALL_NO_IDLE_ROUTER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_finalist_sample_stall_no_idle_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "frozen_child_count": r["frozen_child_count"],
        "fresh25_ready_count": r["fresh25_ready_count"],
        "routes": {x["strategy_id"]: x["state"] for x in r["targets"]},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
