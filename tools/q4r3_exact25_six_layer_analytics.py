from __future__ import annotations

import bisect
import math
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any, Mapping, Sequence

from tools.q4r3_exact25_six_layer_observer_core import avg, mdd, now_iso, num, pf, rnd, ts

def bucket(value: Any, edges: Sequence[float]) -> str:
    value = num(value)
    if value is None: return "missing"
    for index, (low, high) in enumerate(zip(edges, edges[1:])):
        if low <= value < high or (index == len(edges) - 2 and value == high): return f"[{low:g},{high:g}{']' if index == len(edges) - 2 else ')'}"
    return "out_of_range"


def market_layer(rows: Sequence[Mapping[str, Any]], contexts: Sequence[Mapping[str, Any]], ssot: Mapping[str, Any], status: Mapping[str, Any]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in contexts:
        if str(item.get("symbol") or "") and ts(item.get("bar_epoch") or item.get("bar_ts")) is not None: grouped[str(item["symbol"]).upper()].append(item)
    index = {symbol: ([ts(item.get("bar_epoch") or item.get("bar_ts")) or 0.0 for item in sorted(items, key=lambda x: ts(x.get("bar_epoch") or x.get("bar_ts")) or 0.0)], sorted(items, key=lambda x: ts(x.get("bar_epoch") or x.get("bar_ts")) or 0.0)) for symbol, items in grouped.items()}
    bins = ssot.get("market_context", {}).get("numeric_bins", {}) if isinstance(ssot.get("market_context"), Mapping) else {}
    minimum = int(ssot.get("minimum_bucket_sample") or 30); tolerance = float(ssot.get("context_join_tolerance_sec") or 180)
    public: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list)); existing: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list)); joined = 0
    for row in rows:
        realized, entry = num(row.get("realized_R")), ts(row.get("entry_ts")); symbol = str(row.get("symbol") or "").upper()
        if realized is None: continue
        features = row.get("entry_features") if isinstance(row.get("entry_features"), Mapping) else {}
        for field in ("htf_bias", "swing_sequence", "premium_discount_side", "ote_0_5_0_79", "ltf_reversal_confirm", "session_window"):
            existing[field][str(features.get(field)).lower() if features.get(field) is not None else "missing"].append(realized)
        if entry is None or symbol not in index: continue
        times, items = index[symbol]; pos = bisect.bisect_left(times, entry); candidates = [i for i in (pos - 1, pos) if 0 <= i < len(times)]
        if not candidates: continue
        chosen = min(candidates, key=lambda i: abs(times[i] - entry))
        if abs(times[chosen] - entry) > tolerance: continue
        snapshot = items[chosen]; joined += 1
        for field, edges in bins.items():
            if isinstance(edges, list) and len(edges) > 1: public[str(field)][bucket(snapshot.get(field), [float(x) for x in edges])].append(realized)
        direction, side = str(snapshot.get("trend_direction") or "missing").lower(), str(row.get("side") or "").lower()
        public["trend_direction"][direction].append(realized)
        public["trend_side_alignment"][str(direction == side).lower() if direction in {"long", "short"} and side in {"long", "short"} else "missing"].append(realized)
    perf = lambda values: {"sample_count": len(values), "cumulative_R": rnd(sum(values)), "expectancy_R": rnd(avg(values)), "win_rate_pct": rnd(sum(x > 0 for x in values) / len(values) * 100.0, 6) if values else None, "profit_factor": rnd(pf(values)), "minimum_sample": minimum, "minimum_sample_met": len(values) >= minimum, "decision": "OBSERVE_ONLY"}
    render = lambda source: {field: {name: perf(values) for name, values in sorted(groups.items())} for field, groups in sorted(source.items())}
    return {"schema": "q4r3_exact25_market_context_regime_observer_v1", "generated_at": now_iso(), "formal_row_count": len(rows), "context_snapshot_count": len(contexts), "entry_context_joined_count": joined, "entry_context_coverage_pct": rnd(joined / len(rows) * 100.0, 6) if rows else None, "context_collector_state": status.get("state") if status else "NOT_STARTED", "context_collector_error_count": status.get("error_count") if status else None, "public_market_context_attribution": render(public), "existing_entry_feature_attribution": render(existing), "filter_enabled": False, "strategy_output_unchanged": True, "observer_only": True, "action": "hold"}


def corr(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2: return None
    mx, my = avg(xs), avg(ys)
    if mx is None or my is None: return None
    dx, dy = [x - mx for x in xs], [y - my for y in ys]
    den = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    return sum(x*y for x, y in zip(dx, dy)) / den if den else None


def portfolio_layer(rows: Sequence[Mapping[str, Any]], ssot: Mapping[str, Any]) -> dict[str, Any]:
    valid = sorted([row for row in rows if num(row.get("realized_R")) is not None and ts(row.get("entry_ts")) is not None and ts(row.get("exit_ts")) is not None], key=lambda row: ts(row.get("exit_ts")) or 0.0)
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list); blocks: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float)); block_sec = int(ssot.get("portfolio_block_minutes") or 360) * 60; minimum = int(ssot.get("minimum_pair_sample") or 10)
    for row in valid:
        name = str(row.get("strategy_id") or "unknown"); groups[name].append(row); blocks[name][int((ts(row.get("exit_ts")) or 0) // block_sec)] += num(row.get("realized_R")) or 0.0
    pairs = []
    for left, right in combinations(sorted(groups), 2):
        overlap = same = 0; minutes = 0.0
        for a in groups[left]:
            for b in groups[right]:
                width = min(ts(a.get("exit_ts")) or 0, ts(b.get("exit_ts")) or 0) - max(ts(a.get("entry_ts")) or 0, ts(b.get("entry_ts")) or 0)
                if width > 0:
                    overlap += 1; minutes += width / 60.0
                    same += int(str(a.get("symbol")).upper() == str(b.get("symbol")).upper() and str(a.get("side")).lower() == str(b.get("side")).lower())
        common = sorted(set(blocks[left]) & set(blocks[right])); xs = [blocks[left][key] for key in common]; ys = [blocks[right][key] for key in common]
        if overlap or common: pairs.append({"left": left, "right": right, "overlap_trade_pair_count": overlap, "overlap_minutes": rnd(minutes, 4), "same_symbol_side_overlap_count": same, "common_block_count": len(common), "block_R_correlation": rnd(corr(xs, ys)) if len(common) >= minimum else None, "correlation_minimum_sample_met": len(common) >= minimum, "co_loss_block_count": sum(x < 0 and y < 0 for x, y in zip(xs, ys))})
    rs = [num(row.get("realized_R")) or 0.0 for row in valid]; full_dd = mdd(rs)
    marginal = {name: {"closed_count": len(items), "net_R": rnd(sum(num(row.get("realized_R")) or 0.0 for row in items)), "full_portfolio_mdd_R": rnd(full_dd), "leave_one_out_mdd_R": rnd(mdd([num(row.get("realized_R")) or 0.0 for row in valid if str(row.get("strategy_id")) != name]))} for name, items in sorted(groups.items())}
    events = []
    for row in valid:
        key = f"{str(row.get('symbol')).upper()}|{str(row.get('side')).lower()}"; events += [(ts(row.get("entry_ts")) or 0.0, 1, key), (ts(row.get("exit_ts")) or 0.0, -1, key)]
    events.sort(key=lambda item: (item[0], item[1])); total = max_total = max_same = 0; active: Counter[str] = Counter()
    for _time, delta, key in events:
        total += delta; active[key] += delta
        if active[key] <= 0: active.pop(key, None)
        max_total, max_same = max(max_total, total), max(max_same, max(active.values(), default=0))
    return {"schema": "q4r3_exact25_portfolio_interaction_observer_v1", "generated_at": now_iso(), "closed_count": len(valid), "strategy_count_with_rows": len(groups), "max_concurrent_positions": max_total, "max_same_symbol_side_concurrent_positions": max_same, "pair_count": len(pairs), "pairs": pairs, "strategy_marginal_dd": marginal, "portfolio_net_R": rnd(sum(rs)), "portfolio_max_drawdown_R": rnd(full_dd), "observer_only": True, "action": "hold"}


def replay_stats(rows: Sequence[Mapping[str, Any]], adjusted: Sequence[float] | None = None) -> dict[str, Any]:
    rs = list(adjusted) if adjusted is not None else [value for value in (num(row.get("realized_R")) for row in rows) if value is not None]
    return {"sample_count": len(rs), "net_R": rnd(sum(rs)), "expectancy_R": rnd(avg(rs)), "profit_factor": rnd(pf(rs)), "max_drawdown_R": rnd(mdd(rs)), "win_rate_pct": rnd(sum(x > 0 for x in rs) / len(rs) * 100.0, 6) if rs else None}


def replay_layer(rows: Sequence[Mapping[str, Any]], ssot: Mapping[str, Any], hashes: Mapping[str, str]) -> dict[str, Any]:
    cfg = ssot.get("replay_lab") if isinstance(ssot.get("replay_lab"), Mapping) else {}; minimum = int(ssot.get("minimum_replay_sample") or 50); baseline = replay_stats(rows); results = []
    if cfg.get("ledger_ablation_enabled", True) and len(rows) >= minimum:
        for experiment in cfg.get("experiments", []):
            if not isinstance(experiment, Mapping): continue
            kind = str(experiment.get("type") or ""); selected = list(rows); adjusted = None; limitation = "UNSUPPORTED_EXPERIMENT_NO_CHANGE"
            if kind == "cost_stress":
                selected, adjusted = [], []
                for row in rows:
                    risk, result, entry, exit_price, qty = num(row.get("initial_risk_usdt")), num(row.get("realized_R")), num(row.get("entry_price")), num(row.get("exit_price")), num(row.get("qty"))
                    if risk and risk > 0 and result is not None and entry is not None and exit_price is not None and qty is not None:
                        selected.append(row); adjusted.append(result - (entry * qty + exit_price * qty) * (num(experiment.get("round_trip_cost_bps_delta")) or 0.0) / 10_000.0 / risk)
                limitation = "LEDGER_COST_STRESS_CAUSAL_ON_RECORDED_TRADES_ONLY"
            elif kind in {"feature_ablation", "lifecycle_ablation"}:
                selected = []
                for row in rows:
                    features = row.get("entry_features") if isinstance(row.get("entry_features"), Mapping) else {}; field = str(experiment.get("field") or ""); value = row.get(field) if field in row else features.get(field); keep = True
                    if isinstance(experiment.get("exclude"), list): keep = value not in experiment["exclude"]
                    if isinstance(experiment.get("include"), list): keep = value in experiment["include"]
                    if experiment.get("mode") == "side_aligned": keep = str(value or "").lower() == str(row.get("side") or "").lower()
                    if num(experiment.get("max")) is not None: keep = num(value) is not None and num(value) <= num(experiment.get("max"))
                    if keep: selected.append(row)
                limitation = "RETROSPECTIVE_LEDGER_ABLATION_NONCAUSAL_DO_NOT_PROMOTE"
            metrics = replay_stats(selected, adjusted); delta = None if metrics.get("expectancy_R") is None or baseline.get("expectancy_R") is None else rnd(metrics["expectancy_R"] - baseline["expectancy_R"])
            results.append({"experiment_id": experiment.get("id"), "type": kind, "retention_pct": rnd(metrics["sample_count"] / max(baseline["sample_count"], 1) * 100.0, 6), "metrics": metrics, "delta_expectancy_R": delta, "limitation": limitation, "decision": "OBSERVE_ONLY_NO_PROMOTION"})
    return {"schema": "q4r3_exact25_replay_ablation_lab_v1", "generated_at": now_iso(), "baseline_name": cfg.get("baseline_name"), "baseline_snapshot_hashes": dict(hashes), "baseline_metrics": baseline, "minimum_replay_sample": minimum, "minimum_replay_sample_met": len(rows) >= minimum, "ledger_ablation_enabled": bool(cfg.get("ledger_ablation_enabled", True)), "strategy_signal_replay_enabled": False, "candidate_execution_enabled": False, "promotion_enabled": False, "experiment_count": len(results), "experiments": results, "block_reason": None if len(rows) >= minimum else "MINIMUM_FORWARD_SAMPLE_NOT_MET", "hard_limit": "LEDGER_ABLATION_CANNOT_REPLACE_RAW_SIGNAL_AND_CANDLE_CAUSAL_REPLAY", "observer_only": True, "action": "hold"}

