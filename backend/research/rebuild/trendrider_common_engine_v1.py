"""Offline common DEV replay of the two immutable executable TrendRider policies.

This module never loads market files, fetches data, or writes economic results.
The caller owns the frozen inputs, serial execution budget and durable receipts.
Native generic stop fills (including their gap optimism) are preserved. All
prices and performance here are a unit-notional DEV model, not account returns.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import math
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence
from unittest.mock import patch

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as generic
from backend.research.rebuild import policy_kernel_v1 as kernel
from backend.research.rebuild import trend_policy_batch_v1 as broad
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as primary
from backend.research.rebuild.top5_development_native_v1 import NativeFeatureCache

HOUR = 3_600_000
WARMUP = 64
LANES = ("B_COMMON", "P_COMMON")
COST_FIELDS = ("fee_bps", "spread_bps", "impact_bps", "funding_proxy_bps")


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False, ensure_ascii=False).encode()).hexdigest()


def validate_cost(cost_tuple: Mapping[str, Any]) -> float:
    values = [float(cost_tuple[key]) for key in COST_FIELDS]
    if any(not math.isfinite(x) or x < 0 for x in values) or math.fsum(values) <= 0:
        raise ValueError("COMMON_COST_INVALID")
    if cost_tuple.get("actual_funding", False) is not False:
        raise ValueError("COMMON_COST_IS_DEV_PROXY_ONLY")
    return math.fsum(values)


def validate_bars(bars_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    if not bars_by_symbol:
        raise ValueError("COMMON_SYMBOLS_EMPTY")
    first_clock = None
    for symbol, rows in sorted(bars_by_symbol.items()):
        if not symbol:
            raise ValueError("COMMON_SYMBOL_EMPTY")
        kernel.validate_bars(rows, minimum=WARMUP + 1)
        clock = [kernel.ts(row) for row in rows]
        if any(t % HOUR for t in clock) or any(b - a != HOUR for a, b in zip(clock, clock[1:])):
            raise ValueError("COMMON_GAP_OR_CLOCK")
        if any("volume" in row and float(row["volume"]) < 0 for row in rows):
            raise ValueError("COMMON_VOLUME_NEGATIVE")
        if first_clock is not None and clock != first_clock:
            raise ValueError("COMMON_SYMBOL_CLOCK_MISMATCH")
        first_clock = clock


def build_signals(bars_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
                  cost_tuple: Mapping[str, Any], policy_shas: Mapping[str, str]) -> list[dict[str, Any]]:
    """Return both policies' full causal intent snapshots, without any trade path.

    Cached B features use the existing exact NativeFeatureCache. P runs its
    original source with only its parent's feature compute bound to that cache.
    Every cached array is a causal prefix recurrence; future values do not enter
    a snapshot or its hashes. Source timestamps remain bar-open identifiers;
    decision_ts explicitly records when the full signal bar is available.
    """
    validate_bars(bars_by_symbol)
    cost = validate_cost(cost_tuple)
    if any(not policy_shas.get(lane) for lane in LANES):
        raise ValueError("COMMON_POLICY_SHA_REQUIRED")
    output = []
    bcfg, pcfg = broad.TrendPolicyConfig(), primary.TrendRiderTransitionFreshnessConfig()
    if bcfg.sha != pcfg.sha:
        raise ValueError("COMMON_POLICY_CONFIG_MISMATCH")
    for symbol, rows in sorted(bars_by_symbol.items()):
        cache = NativeFeatureCache(rows, bcfg)
        for i in range(WARMUP, len(rows)):
            prefix = rows[:i + 1]
            stamp = kernel.ts(rows[i])
            bfeature = cache.feature(prefix, symbol=symbol, now_ts_ms=stamp, config=bcfg)
            prior_feature = cache.feature(rows[:i], symbol=symbol,
                                          now_ts_ms=kernel.ts(rows[i - 1]), config=bcfg)
            with patch.object(broad, "compute_trend_rider_feature", cache.feature):
                pfeature = primary.compute_trend_rider_feature(
                    prefix, symbol=symbol, now_ts_ms=stamp, config=pcfg)
            bintent = broad.build_trend_rider_intent(
                bfeature, policy_source_sha=policy_shas["B_COMMON"],
                verified_round_trip_cost_bps=cost, config=bcfg)
            pintent = primary.build_trend_rider_intent(
                pfeature, policy_source_sha=policy_shas["P_COMMON"],
                verified_round_trip_cost_bps=cost, config=pcfg)
            if not pintent.no_trade and (bintent.no_trade or pintent.side != bintent.side):
                raise ValueError("COMMON_P_NOT_SUBSET_B")
            lane_views = {}
            for lane, feature, intent in (("B_COMMON", bfeature, bintent), ("P_COMMON", pfeature, pintent)):
                lane_views[lane] = {"feature": asdict(feature), "feature_sha": feature.feature_sha,
                                    "intent": asdict(intent), "intent_sha": intent.sha}
            body = {"symbol": symbol, "signal_index": i, "signal_ts": stamp,
                    "decision_ts": stamp + HOUR, "side": bintent.side,
                    "key": [symbol, stamp, bintent.side],
                    "b_actionable": not bintent.no_trade, "p_actionable": not pintent.no_trade,
                    "b_only": not bintent.no_trade and pintent.no_trade,
                    "current_features": asdict(bfeature), "prior_features": asdict(prior_feature),
                    "input_prefix_sha": digest(prefix), "cost_sha": digest(dict(cost_tuple)),
                    "lanes": lane_views}
            body["snapshot_sha"] = digest(body)
            output.append(body)
    return sorted(output, key=lambda row: (row["signal_ts"], row["symbol"]))


def _drawdown(values: Sequence[float]) -> float:
    peak = dd = 0.0
    for value in values:
        peak = max(peak, value)
        dd = max(dd, peak - value)
    return dd


def summarize_campaigns(campaigns: Sequence[Mapping[str, Any]],
                        equity: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Arithmetic on already executed paths only; does not replay a policy."""
    closed = sorted((x for x in campaigns if x["status"] == "COMPLETED"),
                    key=lambda x: (x["exit_available_ts"], x["symbol"], x["entry_ts"]))
    opens = [x for x in campaigns if x["status"] == "OPEN_CENSORED"]
    values = [float(x["net_bps"]) for x in closed]
    wins, losses = [x for x in values if x > 0], [x for x in values if x < 0]
    gp, gl = math.fsum(wins), -math.fsum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = math.fsum(losses) / len(losses) if losses else None
    payoff = avg_win / -avg_loss if avg_win is not None and avg_loss is not None else None
    closed_curve, streak, maximum_streak = [], 0, 0
    for index, value in enumerate(values):
        closed_curve.append(math.fsum(values[:index + 1]))
        streak = streak + 1 if value < 0 else 0
        maximum_streak = max(maximum_streak, streak)
    all_positive = [float(x["terminal_net_bps"]) for x in campaigns if x["terminal_net_bps"] > 0]
    tail_n = max(1, math.ceil(len(losses) * 0.1))
    return {"completed_T": len(closed), "open_censored_T": len(opens),
            "wins_T": len(wins), "losses_T": len(losses), "flat_T": len(values)-len(wins)-len(losses),
            "WR": len(wins) / len(values) if values else None,
            "closed_net_bps": math.fsum(values),
            "terminal_net_bps": math.fsum(float(x["terminal_net_bps"]) for x in campaigns),
            "expectancy_bps": math.fsum(values) / len(values) if values else None,
            "PF": gp / gl if gl > 0 else None, "PF_infinite": gp > 0 and gl == 0,
            "payoff": payoff, "payoff_infinite": bool(wins) and not losses,
            "avg_win_bps": avg_win, "avg_loss_bps": avg_loss,
            "worst_loss_bps": min(losses) if losses else None,
            "loss_tail_10pct_mean_bps": math.fsum(sorted(losses)[:tail_n]) / tail_n if losses else None,
            "max_loss_streak": maximum_streak,
            "closed_DD_bps": _drawdown(closed_curve),
            "marked_DD_bps": _drawdown([float(x["equity_net_bps"]) for x in equity]) if equity else None,
            "closed_cost2_net_bps": math.fsum(float(x["cost2_net_bps"]) for x in closed),
            "cost2_terminal_net_bps": math.fsum(float(x["cost2_terminal_net_bps"]) for x in campaigns),
            "symbol_hours": math.fsum(float(x["hold_hours"]) for x in campaigns),
            "intent_notional_fraction_hours": math.fsum(float(x["intent_exposure"]["notional_fraction_of_equity"]) * float(x["hold_hours"]) for x in campaigns),
            "max_concurrent_symbols": max((int(x.get("held_symbols", x["open_symbols"])) for x in equity), default=0),
            "top1_positive_contribution_fraction": max(all_positive) / math.fsum(all_positive) if all_positive else None,
            "gap_optimism_T": sum(bool(x["native_stop_gap_optimism"]) for x in campaigns),
            "performance_unit": "UNIT_NOTIONAL_TRADE_BPS_NOT_ACCOUNT_RETURN",
            "actual_funding": False, "production_grade": False}


def replay(signals: Sequence[Mapping[str, Any]],
           bars_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
           partition: str, start_index: int, end_exclusive: int,
           lane_or_admission: str | Callable[[Mapping[str, Any]], str | None],
           cost_tuple: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one lane/union in one frozen partition, starting flat.

    A union callback receives only a previously frozen signal snapshot and must
    return P_COMMON, B_COMMON or None. It cannot receive campaign outcomes.
    Native expiry reaches entry_index+48 inclusive; if that is the final
    available bar and no stop/target occurred the campaign remains censored.
    """
    validate_bars(bars_by_symbol)
    cost = validate_cost(cost_tuple)
    count = len(next(iter(bars_by_symbol.values())))
    if not (WARMUP <= start_index < end_exclusive <= count):
        raise ValueError("COMMON_PARTITION_INVALID")
    if isinstance(lane_or_admission, str) and lane_or_admission not in LANES:
        raise ValueError("COMMON_LANE_INVALID")
    ordered = sorted(signals, key=lambda row: (row["signal_ts"], row["symbol"]))
    seen = set()
    for snap in ordered:
        key = (snap["symbol"], snap["signal_ts"])
        if key in seen:
            raise ValueError("COMMON_DUPLICATE_SIGNAL")
        seen.add(key)
        rows = bars_by_symbol[snap["symbol"]]
        i = int(snap["signal_index"])
        if not (0 <= i < len(rows)) or int(snap["signal_ts"]) != kernel.ts(rows[i]) or int(snap["decision_ts"]) != kernel.ts(rows[i]) + HOUR:
            raise ValueError("COMMON_SIGNAL_CLOCK_BINDING")
        if snap["snapshot_sha"] != digest({key: value for key, value in snap.items() if key != "snapshot_sha"}):
            raise ValueError("COMMON_SNAPSHOT_SHA_MISMATCH")
        if snap["input_prefix_sha"] != digest(rows[:i + 1]):
            raise ValueError("COMMON_INPUT_PREFIX_SHA_MISMATCH")
        for lane in LANES:
            view = snap["lanes"][lane]
            intent, feature = view["intent"], view["feature"]
            if view["intent_sha"] != digest(intent):
                raise ValueError("COMMON_INTENT_SHA_MISMATCH")
            feature_body = {key: feature[key] for key in
                            ("strategy_id", "symbol", "signal_ts", "close", "atr", "values")}
            if lane == "P_COMMON":
                feature_body.update(changed_axis=primary.AXIS, context_transform=primary.CONTEXT_TRANSFORM)
            if view["feature_sha"] != digest(feature_body) or feature["feature_sha"] != view["feature_sha"]:
                raise ValueError("COMMON_FEATURE_SHA_MISMATCH")
            if intent["feature_sha"] != view["feature_sha"]:
                raise ValueError("COMMON_INTENT_FEATURE_BINDING")
            if (intent["symbol"] != snap["symbol"] or feature["symbol"] != snap["symbol"]
                    or intent["signal_ts"] != snap["signal_ts"] or feature["signal_ts"] != snap["signal_ts"]
                    or intent["strategy_id"] != "trend_rider" or feature["strategy_id"] != "trend_rider"):
                raise ValueError("COMMON_LANE_IDENTITY_BINDING")
        bintent, pintent = (snap["lanes"][lane]["intent"] for lane in LANES)
        if (type(snap["b_actionable"]) is not bool or type(snap["p_actionable"]) is not bool
                or type(snap["b_only"]) is not bool or type(bintent["no_trade"]) is not bool
                or type(pintent["no_trade"]) is not bool
                or snap["b_actionable"] != (not bintent["no_trade"])
                or snap["p_actionable"] != (not pintent["no_trade"])
                or snap["b_only"] != (not bintent["no_trade"] and pintent["no_trade"])
                or snap["side"] != bintent["side"]
                or (snap["p_actionable"] and (not snap["b_actionable"] or bintent["side"] != pintent["side"]))):
            raise ValueError("COMMON_ACTIONABLE_IDENTITY_BINDING")
    campaigns, events = [], []
    blocked_until = {symbol: -1 for symbol in bars_by_symbol}
    for snap in ordered:
        i, symbol = int(snap["signal_index"]), str(snap["symbol"])
        if not start_index <= i < end_exclusive:
            continue
        selected = lane_or_admission(snap) if callable(lane_or_admission) else lane_or_admission
        if selected is not None and selected not in LANES:
            raise ValueError("COMMON_ADMISSION_LANE_INVALID")
        event = {"symbol": symbol, "signal_index": i, "signal_ts": snap["signal_ts"],
                 "decision_ts": snap["decision_ts"], "snapshot_sha": snap["snapshot_sha"],
                 "b_actionable": snap["b_actionable"], "p_actionable": snap["p_actionable"],
                 "b_only": snap["b_only"], "selected_lane": selected}
        if selected is None:
            event["status"] = "QUALITY_GATE_REJECTED" if snap["b_actionable"] else "NO_SIGNAL"
            events.append(event)
            continue
        view = snap["lanes"][selected]
        intent = view["intent"]
        if intent["no_trade"]:
            event["status"] = "NO_SIGNAL"
            events.append(event)
            continue
        if intent["side"] not in ("long", "short"):
            raise ValueError("COMMON_SIDE_INVALID")
        if float(intent["verified_round_trip_cost_bps"]) != cost:
            raise ValueError("COMMON_INTENT_COST_DRIFT")
        if int(intent["timeout"]["bars"]) != 48:
            raise ValueError("COMMON_NATIVE_TIMEOUT_DRIFT")
        event.update(intent_sha=view["intent_sha"], side=intent["side"])
        if i + 1 >= end_exclusive:
            event["status"] = "UNFILLED_BOUNDARY_SIGNAL"
            events.append(event)
            continue
        rows = bars_by_symbol[symbol]
        entry_i = i + 1
        entry_ts = kernel.ts(rows[entry_i])
        owns, cooldown = generic.execution_ownership_policy(SimpleNamespace(**intent))
        if not owns or cooldown != 2:
            raise ValueError("COMMON_NATIVE_OWNERSHIP_DRIFT")
        if generic.ownership_blocked(entry_ts, blocked_until[symbol]):
            event.update(status="OWNERSHIP_REJECTED", blocked_until_ts=blocked_until[symbol])
            events.append(event)
            continue
        entry = float(rows[entry_i]["open"])
        sign = 1 if intent["side"] == "long" else -1
        sl, tp = intent["sl"], intent["tp"]
        if sl is None and tp is None:
            raise ValueError("COMMON_NATIVE_GEOMETRY_MISSING")
        last_i = min(end_exclusive - 1, entry_i + 48)
        exit_i = exit_price = exit_reason = None
        gap_optimism = False
        for j in range(entry_i, last_i + 1):
            row = rows[j]
            if sl is not None and ((sign > 0 and row["low"] <= sl) or (sign < 0 and row["high"] >= sl)):
                exit_i, exit_price, exit_reason = j, float(sl), "SL"
                gap_optimism = sign * (float(row["open"]) - float(sl)) < 0
                break
            if tp is not None and ((sign > 0 and row["high"] >= tp) or (sign < 0 and row["low"] <= tp)):
                exit_i, exit_price, exit_reason = j, float(tp), "TP"
                break
        if exit_i is None and last_i < end_exclusive - 1:
            exit_i, exit_price, exit_reason = last_i, float(rows[last_i]["close"]), "TIMEOUT"
        completed = exit_i is not None
        mark_i = int(exit_i) if completed else end_exclusive - 1
        terminal_price = float(exit_price) if completed else float(rows[mark_i]["close"])
        terminal_ts = kernel.ts(rows[mark_i]) + HOUR
        native_exit_ts = kernel.ts(rows[mark_i]) if completed else None
        blocked_until[symbol] = generic.reserve_position_ownership(
            exit_ts=native_exit_ts, open_horizon_ts=kernel.ts(rows[end_exclusive - 1]),
            cooldown_bars=cooldown, timeframe_ms=HOUR)
        gross = sign * (terminal_price - entry) / entry * 10_000
        campaign = {"campaign_id": digest([partition, symbol, snap["signal_ts"], intent["side"]]),
                    "partition": partition, "symbol": symbol, "signal_index": i,
                    "signal_ts": snap["signal_ts"], "decision_ts": snap["decision_ts"],
                    "key": [symbol, snap["signal_ts"], intent["side"]],
                    "selected_lane": selected, "b_only": snap["b_only"], "p_core": snap["p_actionable"],
                    "side": intent["side"], "entry_index": entry_i, "entry_ts": entry_ts, "entry": entry,
                    "status": "COMPLETED" if completed else "OPEN_CENSORED",
                    "exit_index": exit_i, "exit_ts": native_exit_ts,
                    "exit_available_ts": terminal_ts if completed else None,
                    "exit": exit_price, "exit_reason": exit_reason,
                    "mark_index": mark_i, "mark_ts": terminal_ts, "mark_price": terminal_price,
                    "gross_bps": gross if completed else None, "terminal_gross_bps": gross,
                    "net_bps": gross - cost if completed else None,
                    "terminal_net_bps": gross - cost,
                    "cost2_net_bps": gross - 2 * cost if completed else None,
                    "cost2_terminal_net_bps": gross - 2 * cost,
                    "cost_bps": cost, "cost_components": {key: float(cost_tuple[key]) for key in COST_FIELDS},
                    "terminal_reserve_bps": 0.0 if completed else cost,
                    "hold_hours": (terminal_ts - entry_ts) / HOUR,
                    "quantity_normalized": 1.0, "intent_risk_size": intent["risk_size"],
                    "intent_exposure": intent["exposure"], "intent_geometry": intent,
                    "intent_sha": view["intent_sha"], "feature_sha": view["feature_sha"],
                    "policy_sha": intent.get("source_sha"),
                    "input_prefix_sha": snap.get("input_prefix_sha"), "snapshot_sha": snap["snapshot_sha"],
                    "native_stop_gap_optimism": gap_optimism,
                    "native_exit_timestamp_semantics": "BAR_OPEN_ID; INTRABAR_FILL_AVAILABLE_BY_CLOSE",
                    "actual_funding": False, "production_grade": False}
        campaign["mark_path"] = []
        for j in range(entry_i, mark_i + 1):
            price = terminal_price if completed and j == mark_i else float(rows[j]["close"])
            mark_gross = sign * (price - entry) / entry * 10_000
            campaign["mark_path"].append({"ts": kernel.ts(rows[j]) + HOUR,
                                           "net_bps": mark_gross - cost,
                                           "cost2_net_bps": mark_gross - 2 * cost})
        campaigns.append(campaign)
        event.update(status=campaign["status"], campaign_id=campaign["campaign_id"])
        events.append(event)
    equity = []
    reference = next(iter(bars_by_symbol.values()))
    for j in range(start_index, end_exclusive):
        contributions, contributions2 = [], []
        open_symbols = set()
        held_symbols = set()
        for campaign in campaigns:
            if campaign["entry_index"] > j:
                continue
            if campaign["mark_index"] >= j:
                held_symbols.add(campaign["symbol"])
            if campaign["status"] == "COMPLETED" and campaign["exit_index"] <= j:
                contributions.append(campaign["net_bps"])
                contributions2.append(campaign["cost2_net_bps"])
            else:
                sign = 1 if campaign["side"] == "long" else -1
                mark = float(bars_by_symbol[campaign["symbol"]][j]["close"])
                gross = sign * (mark - campaign["entry"]) / campaign["entry"] * 10_000
                contributions.append(gross - cost)
                contributions2.append(gross - 2 * cost)
                open_symbols.add(campaign["symbol"])
        equity.append({"bar_index": j, "ts": kernel.ts(reference[j]) + HOUR,
                       "equity_net_bps": math.fsum(contributions), "equity_cost2_bps": math.fsum(contributions2),
                       "open_symbols": len(open_symbols), "held_symbols": len(held_symbols)})
    metrics = summarize_campaigns(campaigns, equity)
    metrics.update(eligible_signals=sum(e["status"] not in ("NO_SIGNAL", "QUALITY_GATE_REJECTED") for e in events),
                   ownership_rejected_signals=sum(e["status"] == "OWNERSHIP_REJECTED" for e in events),
                   unfilled_boundary_signals=sum(e["status"] == "UNFILLED_BOUNDARY_SIGNAL" for e in events),
                   quality_gate_rejected_signals=sum(e["status"] == "QUALITY_GATE_REJECTED" for e in events))
    metrics["average_concurrent_unit_notional_exposure"] = metrics["symbol_hours"] / (end_exclusive - start_index)
    if equity and not math.isclose(equity[-1]["equity_net_bps"], metrics["terminal_net_bps"], abs_tol=1e-8):
        raise ValueError("COMMON_TERMINAL_ACCOUNTING_BRIDGE")
    return {"schema": "trendrider_common_replay_v1", "partition": partition,
            "start_index": start_index, "end_exclusive": end_exclusive,
            "starts_flat": True, "cost_sha": digest(dict(cost_tuple)), "campaigns": campaigns,
            "events": events, "equity": equity, "metrics": metrics,
            "signal_snapshot_sha": digest(list(signals)), "production_grade": False,
            "formal_credit": 0, "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED"}
