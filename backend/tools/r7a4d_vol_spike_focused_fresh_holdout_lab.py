from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

from backend.strategy25.strategy_family_indicator_search_v2 import variants_for, wrap_strategy


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
TRACE_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repair_loss_anatomy.py"
OUTPUT_DIR = "artifacts/vol_spike_focused_fresh_holdout_lab_v1"
STRATEGY_ID = "vol_spike_fade"
WINDOW_BARS = 700
WARMUP_BARS = 180
HISTORY_BARS = 220
COST_BPS_PER_SIDE = 4.0


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load(BASE_PATH, "r7a4d_vol_spike_focused_base_v1")
trace = _load(TRACE_PATH, "r7a4d_vol_spike_focused_trace_v1")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _aggregate(windows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return base._aggregate([{"stats": row["stats"]} for row in windows])


def _window_replay(
    frames: Mapping[str, pd.DataFrame],
    strategy: Callable[..., dict[str, Any]],
    index: int,
    label: str,
) -> dict[str, Any]:
    start = index * WINDOW_BARS
    end = start + WINDOW_BARS
    runs: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    for symbol in base.SYMBOLS:
        replay = base._replay(
            frames[symbol].iloc[start:end].reset_index(drop=True),
            strategy,
            warmup_bars=WARMUP_BARS,
            history_bars=HISTORY_BARS,
            cost_bps_per_side=COST_BPS_PER_SIDE,
        )
        runs.append(replay)
        symbols.append({"symbol": symbol, "stats": replay["stats"], "signal_count": replay.get("signal_count")})
    stats = base._aggregate(runs)
    return {
        "window_id": label,
        "stats": stats,
        "positive_symbols": sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in symbols),
        "symbols": symbols,
    }


def _selection_score(windows: list[Mapping[str, Any]]) -> float:
    stats = _aggregate(windows)
    trades = int(stats.get("trade_count") or 0)
    net = _number(stats.get("net_return_pct_sum"), -1000.0)
    pf = min(_number(stats.get("net_profit_factor"), 0.0), 5.0)
    payoff = min(_number(stats.get("payoff_ratio"), 0.0), 5.0)
    positive_windows = sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in windows)
    positive_symbols = sum(int(row["positive_symbols"]) for row in windows)
    validation = windows[-1]
    validation_net = _number(validation["stats"].get("net_return_pct_sum"), -1000.0)
    validation_pf = min(_number(validation["stats"].get("net_profit_factor"), 0.0), 5.0)
    validation_trades = int(validation["stats"].get("trade_count") or 0)
    return (
        net * 7.0
        + (pf - 1.0) * 10.0
        + (payoff - 1.0) * 2.0
        + positive_windows * 3.0
        + positive_symbols * 0.5
        + validation_net * 8.0
        + (validation_pf - 1.0) * 6.0
        + math.log1p(max(trades, 0))
        - max(25 - trades, 0) * 3.0
        - max(4 - validation_trades, 0) * 6.0
    )


def _descriptor_matches_result(result: Mapping[str, Any], descriptor: Mapping[str, str]) -> bool:
    if str(result.get("action") or "hold").lower() != "enter":
        return False
    kind = descriptor["kind"]
    value = descriptor["value"]
    if kind == "why":
        return str(result.get("why") or "unknown") == value
    if kind == "skill":
        return str(result.get("skill") or "none") == value
    if kind == "tag":
        return value in {str(item) for item in (result.get("tags") or [])}
    indicators = result.get("indicators") if isinstance(result.get("indicators"), Mapping) else {}
    if kind == "indicator_true":
        return indicators.get(value) is True
    if kind == "indicator_false":
        return indicators.get(value) is False
    return False


def _descriptor_matches_trade(trade: Mapping[str, Any], descriptor: Mapping[str, str]) -> bool:
    kind = descriptor["kind"]
    value = descriptor["value"]
    if kind == "why":
        return str(trade.get("entry_why") or "unknown") == value
    if kind == "skill":
        return str(trade.get("entry_skill") or "none") == value
    if kind == "tag":
        return value in {str(item) for item in (trade.get("entry_tags") or [])}
    indicators = trade.get("entry_indicators") if isinstance(trade.get("entry_indicators"), Mapping) else {}
    if kind == "indicator_true":
        return indicators.get(value) is True
    if kind == "indicator_false":
        return indicators.get(value) is False
    return False


def _descriptors(trades: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    ignored = {"family_variant_allowed", "trend_alignment_gate_blocked", "trend_nonbeam_gate_blocked"}
    for trade in trades:
        why = str(trade.get("entry_why") or "unknown")
        skill = str(trade.get("entry_skill") or "none")
        found[("why", why)] = {"kind": "why", "value": why}
        found[("skill", skill)] = {"kind": "skill", "value": skill}
        for tag in trade.get("entry_tags") or []:
            text = str(tag)
            found[("tag", text)] = {"kind": "tag", "value": text}
        indicators = trade.get("entry_indicators") if isinstance(trade.get("entry_indicators"), Mapping) else {}
        for key, value in indicators.items():
            if key in ignored or not isinstance(value, bool):
                continue
            kind = "indicator_true" if value else "indicator_false"
            found[(kind, str(key))] = {"kind": kind, "value": str(key)}
    return list(found.values())


def _cluster(trades: list[dict[str, Any]], descriptor: Mapping[str, str]) -> dict[str, Any] | None:
    rows = [trade for trade in trades if _descriptor_matches_trade(trade, descriptor)]
    if len(rows) < 5 or len(rows) >= len(trades):
        return None
    returns = [_number(row.get("net_return_pct")) for row in rows]
    wins = sum(value > 0.0 for value in returns)
    losses = sum(value < 0.0 for value in returns)
    net = sum(returns)
    precision = losses / len(rows)
    if losses < 4 or precision < 0.65 or net >= 0.0:
        return None
    kind_weight = {"why": 1.20, "skill": 1.15, "tag": 1.0, "indicator_true": 0.9, "indicator_false": 0.85}.get(descriptor["kind"], 0.8)
    score = (-net) * precision * math.log1p(len(rows)) * kind_weight / max(wins + 1, 1)
    return {
        "descriptor": dict(descriptor),
        "trade_count": len(rows),
        "win_count": wins,
        "loss_count": losses,
        "loss_precision_pct": precision * 100.0,
        "net_return_pct_sum": net,
        "score": score,
    }


def _blocked(strategy: Callable[..., dict[str, Any]], descriptor: Mapping[str, str]):
    counter = {"blocked_entry_signals": 0}

    def wrapped(history: pd.DataFrame, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = strategy(history, *args, **kwargs)
        if not isinstance(result, Mapping):
            raise TypeError("STRATEGY_RESULT_MAPPING_REQUIRED")
        output = dict(result)
        if _descriptor_matches_result(output, descriptor):
            counter["blocked_entry_signals"] += 1
            indicators = dict(output.get("indicators") or {})
            indicators["single_cause_block"] = dict(descriptor)
            output.update({
                "side": None,
                "action": "hold",
                "size": 0.0,
                "why": f"single_cause_block:{descriptor['kind']}:{descriptor['value']}",
                "skill": "none",
                "confidence": 0.0,
                "indicators": indicators,
            })
        return output

    return wrapped, counter


def _selection_contract(baseline: list[Mapping[str, Any]], candidate: list[Mapping[str, Any]], blocked: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    base_stats = _aggregate(baseline)
    stats = _aggregate(candidate)
    validation = candidate[-1]
    if blocked <= 0:
        reasons.append("NO_BEHAVIORAL_DELTA")
    if int(stats.get("trade_count") or 0) < 25:
        reasons.append("SELECTION_TRADES_LT_25")
    if _number(stats.get("net_return_pct_sum")) <= 1.0:
        reasons.append("SELECTION_NET_LE_1PCT")
    if _number(stats.get("net_profit_factor"), 0.0) <= 1.05:
        reasons.append("SELECTION_PF_LE_1_05")
    if sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in candidate) < 3:
        reasons.append("POSITIVE_WINDOWS_LT_3_OF_5")
    if int(validation["stats"].get("trade_count") or 0) < 4:
        reasons.append("VALIDATION_TRADES_LT_4")
    if _number(validation["stats"].get("net_return_pct_sum")) <= 0.0:
        reasons.append("VALIDATION_NET_NOT_POSITIVE")
    if _number(validation["stats"].get("net_profit_factor"), 0.0) <= 1.0:
        reasons.append("VALIDATION_PF_NOT_ABOVE_1")
    base_payoff = _number(base_stats.get("payoff_ratio"), 0.0)
    payoff = _number(stats.get("payoff_ratio"), 0.0)
    if base_payoff > 0.0 and payoff < base_payoff * 0.90:
        reasons.append("PAYOFF_DEGRADED_GT_10PCT")
    if _number(stats.get("net_return_pct_sum")) <= _number(base_stats.get("net_return_pct_sum")):
        reasons.append("NET_NOT_IMPROVED")
    return not reasons, reasons


def _fresh_holdout_contract(window: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    stats = window["stats"]
    if int(stats.get("trade_count") or 0) < 4:
        reasons.append("FRESH_HOLDOUT_TRADES_LT_4")
    if _number(stats.get("net_return_pct_sum")) <= 0.0:
        reasons.append("FRESH_HOLDOUT_NET_NOT_POSITIVE")
    if _number(stats.get("net_profit_factor"), 0.0) <= 1.0:
        reasons.append("FRESH_HOLDOUT_PF_NOT_ABOVE_1")
    if int(window["positive_symbols"]) < 2:
        reasons.append("FRESH_HOLDOUT_POSITIVE_SYMBOLS_LT_2")
    return not reasons, reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--top-clusters", type=int, default=8)
    args = parser.parse_args()
    root = Path(args.root).resolve()

    # Original five-window family range ended immediately before the prior census.
    prior_end_ms = int(pd.Timestamp(base.FIXED_END_ISO).timestamp() * 1000)
    prior_end_ms = (prior_end_ms // base.INTERVAL_MS) * base.INTERVAL_MS
    prior_start_ms = prior_end_ms - (int(base.WINDOW_BARS) * 2 - 1) * base.INTERVAL_MS
    prior_single_end_ms = prior_start_ms - base.INTERVAL_MS
    prior_single_start_ms = prior_single_end_ms - (1200 - 1) * base.INTERVAL_MS
    original_lab_end_ms = prior_single_start_ms - base.INTERVAL_MS
    original_lab_start_ms = original_lab_end_ms - (WINDOW_BARS * 5 - 1) * base.INTERVAL_MS
    fresh_holdout_end_ms = original_lab_start_ms - base.INTERVAL_MS
    fresh_holdout_start_ms = fresh_holdout_end_ms - (WINDOW_BARS - 1) * base.INTERVAL_MS
    fetch_start_ms = fresh_holdout_start_ms
    fetch_end_ms = original_lab_end_ms
    expected_rows = WINDOW_BARS * 6

    blockers: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    fetch_results: list[dict[str, Any]] = []
    for symbol in base.SYMBOLS:
        try:
            frame, endpoint, requests = base._fetch_exact(symbol, start_ms=fetch_start_ms, end_ms=fetch_end_ms, expected_rows=expected_rows)
            frames[symbol] = frame
            fetch_results.append({
                "symbol": symbol,
                "status": "PASS",
                "rows": len(frame),
                "start": pd.Timestamp(frame["timestamp"].iloc[0]).isoformat(),
                "end": pd.Timestamp(frame["timestamp"].iloc[-1]).isoformat(),
                "endpoint": endpoint,
                "request_count": requests,
            })
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    registry = base._load_registry(root)
    canonical = base._load_canonical_strategy(root, STRATEGY_ID, registry[STRATEGY_ID])
    labels = ["FRESH_HOLDOUT", "D1", "D2", "D3", "V1", "H1"]

    variant_rows: list[dict[str, Any]] = []
    if not blockers:
        for spec in variants_for(STRATEGY_ID):
            strategy = wrap_strategy(canonical, spec)
            selection_windows = [_window_replay(frames, strategy, index, labels[index]) for index in range(1, 6)]
            variant_rows.append({
                "variant_id": spec.variant_id,
                "selection_windows": selection_windows,
                "selection_combined": _aggregate(selection_windows),
                "selection_score": _selection_score(selection_windows),
            })

    variant_rows = sorted(variant_rows, key=lambda row: float(row["selection_score"]), reverse=True)
    selected_variant = variant_rows[0] if variant_rows else None
    clusters: list[dict[str, Any]] = []
    experiments: list[dict[str, Any]] = []
    accepted = False
    acceptance_reasons = ["NO_VARIANT"]
    chosen: dict[str, Any] | None = None

    if selected_variant is not None and not blockers:
        spec = next(spec for spec in variants_for(STRATEGY_ID) if spec.variant_id == selected_variant["variant_id"])
        selected_strategy = wrap_strategy(canonical, spec)
        discovery_trades: list[dict[str, Any]] = []
        for index in range(1, 5):  # D1-D3 and V1 only; H1 is validation.
            start = index * WINDOW_BARS
            end = start + WINDOW_BARS
            for symbol in base.SYMBOLS:
                replay = trace._replay_trace(
                    frames[symbol].iloc[start:end].reset_index(drop=True),
                    selected_strategy,
                    warmup_bars=WARMUP_BARS,
                    history_bars=HISTORY_BARS,
                    cost_bps_per_side=COST_BPS_PER_SIDE,
                )
                for trade in replay.get("trades", []):
                    discovery_trades.append({"symbol": symbol, "window_id": labels[index], **trade})

        for descriptor in _descriptors(discovery_trades):
            row = _cluster(discovery_trades, descriptor)
            if row is not None:
                clusters.append(row)
        clusters.sort(key=lambda row: float(row["score"]), reverse=True)

        baseline_selection = selected_variant["selection_windows"]
        for cluster in clusters[: args.top_clusters]:
            gated, counter = _blocked(selected_strategy, cluster["descriptor"])
            candidate_selection = [_window_replay(frames, gated, index, labels[index]) for index in range(1, 6)]
            passed, reasons = _selection_contract(baseline_selection, candidate_selection, int(counter["blocked_entry_signals"]))
            experiments.append({
                "cluster": cluster,
                "blocked_entry_signals": counter["blocked_entry_signals"],
                "selection_windows": candidate_selection,
                "selection_combined": _aggregate(candidate_selection),
                "selection_pass": passed,
                "selection_reasons": reasons,
                "selection_score": _selection_score(candidate_selection),
            })

        experiments.sort(key=lambda row: (bool(row["selection_pass"]), float(row["selection_score"])), reverse=True)
        chosen = experiments[0] if experiments else None
        if chosen is not None and chosen["selection_pass"]:
            final_strategy, final_counter = _blocked(selected_strategy, chosen["cluster"]["descriptor"])
            fresh_holdout = _window_replay(frames, final_strategy, 0, labels[0])
            holdout_pass, holdout_reasons = _fresh_holdout_contract(fresh_holdout)
            chosen["fresh_holdout"] = fresh_holdout
            chosen["fresh_holdout_blocked_entry_signals"] = final_counter["blocked_entry_signals"]
            chosen["fresh_holdout_pass"] = holdout_pass
            chosen["fresh_holdout_reasons"] = holdout_reasons
            accepted = holdout_pass
            acceptance_reasons = holdout_reasons
        elif chosen is not None:
            acceptance_reasons = list(chosen["selection_reasons"])
        else:
            acceptance_reasons = ["NO_CAUSAL_CLUSTER"]

    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_FOCUSED_SEARCH_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "strategy_id": STRATEGY_ID,
        "window_contract": {
            "fresh_holdout_start": pd.Timestamp(fresh_holdout_start_ms, unit="ms", tz="UTC").isoformat(),
            "fresh_holdout_end": pd.Timestamp(fresh_holdout_end_ms, unit="ms", tz="UTC").isoformat(),
            "original_lab_start": pd.Timestamp(original_lab_start_ms, unit="ms", tz="UTC").isoformat(),
            "original_lab_end": pd.Timestamp(original_lab_end_ms, unit="ms", tz="UTC").isoformat(),
            "window_bars": WINDOW_BARS,
            "warmup_bars": WARMUP_BARS,
            "history_bars": HISTORY_BARS,
            "cost_bps_per_side": COST_BPS_PER_SIDE,
            "fresh_holdout_untouched_during_selection": True,
        },
        "fetch_results": fetch_results,
        "variant_results": variant_rows,
        "selected_variant": selected_variant,
        "cluster_candidates": clusters,
        "surgery_experiments": experiments,
        "chosen_surgery": chosen,
        "meaningful_positive_accepted": accepted,
        "acceptance_reasons": acceptance_reasons,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "shadow_allowed": False,
        "next": "THIRD_OOS_THEN_SHADOW" if accepted else "NEXT_FOCUSED_STRATEGY_WITH_NEW_UNTOUCHED_HOLDOUT",
    }
    _atomic_json(root / OUTPUT_DIR / "summary.json", report)
    print(json.dumps({
        "STATE": report["state"],
        "SELECTED_VARIANT": None if selected_variant is None else {"variant_id": selected_variant["variant_id"], "selection": selected_variant["selection_combined"]},
        "CLUSTERS": len(clusters),
        "CHOSEN": None if chosen is None else {"descriptor": chosen["cluster"]["descriptor"], "blocked": chosen["blocked_entry_signals"], "selection_pass": chosen["selection_pass"], "selection": chosen["selection_combined"], "fresh_holdout": chosen.get("fresh_holdout"), "fresh_holdout_pass": chosen.get("fresh_holdout_pass")},
        "ACCEPTED": accepted,
        "REASONS": acceptance_reasons,
        "BLOCKERS": blockers,
        "NEXT": report["next"],
    }, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
