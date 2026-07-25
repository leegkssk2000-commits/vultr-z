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
OUTPUT_DIR = "artifacts/trend_family_fresh_holdout_lab_v1"
STRATEGY_IDS = ("trend_ma_macd", "obv_trend")
WINDOW_BARS = 700
WARMUP_BARS = 180
HISTORY_BARS = 220
COST_BPS_PER_SIDE = 4.0
LABELS = ("FRESH_OLD_2", "FRESH_OLD_1", "D1", "D2", "D3", "V1", "H1")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load(BASE_PATH, "r7a4d_trend_family_base_v1")
trace = _load(TRACE_PATH, "r7a4d_trend_family_trace_v1")


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
    trades = sum(int(row["stats"].get("trade_count") or 0) for row in windows)
    wins = sum(int(row["stats"].get("win_count") or 0) for row in windows)
    losses = sum(int(row["stats"].get("loss_count") or 0) for row in windows)
    net = sum(_number(row["stats"].get("net_return_pct_sum")) for row in windows)
    gross_gain = sum(_number(row["stats"].get("average_win_pct")) * int(row["stats"].get("win_count") or 0) for row in windows)
    gross_loss = sum(_number(row["stats"].get("average_loss_pct_abs")) * int(row["stats"].get("loss_count") or 0) for row in windows)
    avg_win = gross_gain / wins if wins else None
    avg_loss = gross_loss / losses if losses else None
    return {
        "trade_count": trades,
        "win_count": wins,
        "loss_count": losses,
        "win_rate_pct": wins / trades * 100.0 if trades else None,
        "net_return_pct_sum": net,
        "net_profit_factor": gross_gain / gross_loss if gross_loss > 0.0 else (999.0 if gross_gain > 0.0 else None),
        "average_win_pct": avg_win,
        "average_loss_pct_abs": avg_loss,
        "payoff_ratio": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0.0) else None,
        "max_drawdown_pct_conservative_sum": sum(_number(row["stats"].get("max_drawdown_pct")) for row in windows),
    }


def _window(frames: Mapping[str, pd.DataFrame], strategy: Callable[..., dict[str, Any]], index: int) -> dict[str, Any]:
    start = index * WINDOW_BARS
    end = start + WINDOW_BARS
    replays = []
    symbols = []
    for symbol in base.SYMBOLS:
        replay = base._replay(
            frames[symbol].iloc[start:end].reset_index(drop=True),
            strategy,
            warmup_bars=WARMUP_BARS,
            history_bars=HISTORY_BARS,
            cost_bps_per_side=COST_BPS_PER_SIDE,
        )
        replays.append(replay)
        symbols.append({"symbol": symbol, "stats": replay["stats"], "signal_count": replay.get("signal_count")})
    stats = base._aggregate(replays)
    return {
        "window_id": LABELS[index],
        "stats": stats,
        "positive_symbols": sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in symbols),
        "symbols": symbols,
    }


def _selection_score(windows: list[Mapping[str, Any]]) -> float:
    stats = _aggregate(windows)
    validation = windows[-1]
    trades = int(stats.get("trade_count") or 0)
    net = _number(stats.get("net_return_pct_sum"), -1000.0)
    pf = min(_number(stats.get("net_profit_factor"), 0.0), 5.0)
    payoff = min(_number(stats.get("payoff_ratio"), 0.0), 5.0)
    positive_windows = sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in windows)
    positive_symbols = sum(int(row["positive_symbols"]) for row in windows)
    return (
        net * 8.0
        + (pf - 1.0) * 12.0
        + (payoff - 1.0) * 2.0
        + positive_windows * 4.0
        + positive_symbols * 0.6
        + _number(validation["stats"].get("net_return_pct_sum"), -1000.0) * 8.0
        + (min(_number(validation["stats"].get("net_profit_factor"), 0.0), 5.0) - 1.0) * 5.0
        + math.log1p(max(trades, 0))
        - max(15 - trades, 0) * 5.0
        - max(2 - int(validation["stats"].get("trade_count") or 0), 0) * 8.0
    )


def _selection_contract(windows: list[Mapping[str, Any]], combined: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    validation = windows[-1]
    if int(combined.get("trade_count") or 0) < 15:
        reasons.append("SELECTION_TRADES_LT_15")
    if _number(combined.get("net_return_pct_sum")) <= 1.0:
        reasons.append("SELECTION_NET_LE_1PCT")
    if _number(combined.get("net_profit_factor")) <= 1.10:
        reasons.append("SELECTION_PF_LE_1_10")
    if _number(combined.get("payoff_ratio")) <= 1.50:
        reasons.append("SELECTION_PAYOFF_LE_1_50")
    if sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in windows) < 3:
        reasons.append("POSITIVE_WINDOWS_LT_3_OF_5")
    if int(validation["stats"].get("trade_count") or 0) < 2:
        reasons.append("VALIDATION_TRADES_LT_2")
    if _number(validation["stats"].get("net_return_pct_sum")) <= 0.0:
        reasons.append("VALIDATION_NET_NOT_POSITIVE")
    if _number(validation["stats"].get("net_profit_factor")) <= 1.0:
        reasons.append("VALIDATION_PF_NOT_ABOVE_1")
    return not reasons, reasons


def _fresh_contract(windows: list[Mapping[str, Any]], combined: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    if int(combined.get("trade_count") or 0) < 4:
        reasons.append("FRESH_TRADES_LT_4")
    if _number(combined.get("net_return_pct_sum")) <= 0.0:
        reasons.append("FRESH_NET_NOT_POSITIVE")
    if _number(combined.get("net_profit_factor")) <= 1.0:
        reasons.append("FRESH_PF_NOT_ABOVE_1")
    if sum(int(row["positive_symbols"]) for row in windows) < 3:
        reasons.append("FRESH_POSITIVE_SYMBOL_SUM_LT_3")
    if any(_number(row["stats"].get("net_return_pct_sum")) < -1.0 for row in windows):
        reasons.append("FRESH_WINDOW_LOSS_LT_MINUS_1PCT")
    return not reasons, reasons


def _descriptor_matches_result(result: Mapping[str, Any], descriptor: Mapping[str, str]) -> bool:
    if str(result.get("action") or "hold").lower() != "enter":
        return False
    kind, value = descriptor["kind"], descriptor["value"]
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
    kind, value = descriptor["kind"], descriptor["value"]
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
    result: dict[tuple[str, str], dict[str, str]] = {}
    ignored = {"family_variant_allowed"}
    for trade in trades:
        why = str(trade.get("entry_why") or "unknown")
        skill = str(trade.get("entry_skill") or "none")
        result[("why", why)] = {"kind": "why", "value": why}
        result[("skill", skill)] = {"kind": "skill", "value": skill}
        for tag in trade.get("entry_tags") or []:
            text = str(tag)
            result[("tag", text)] = {"kind": "tag", "value": text}
        indicators = trade.get("entry_indicators") if isinstance(trade.get("entry_indicators"), Mapping) else {}
        for key, value in indicators.items():
            if key in ignored or not isinstance(value, bool):
                continue
            kind = "indicator_true" if value else "indicator_false"
            result[(kind, str(key))] = {"kind": kind, "value": str(key)}
    return list(result.values())


def _cluster(trades: list[dict[str, Any]], descriptor: Mapping[str, str]) -> dict[str, Any] | None:
    rows = [trade for trade in trades if _descriptor_matches_trade(trade, descriptor)]
    if len(rows) < 4 or len(rows) >= len(trades):
        return None
    returns = [_number(row.get("net_return_pct")) for row in rows]
    wins = sum(value > 0.0 for value in returns)
    losses = sum(value < 0.0 for value in returns)
    net = sum(returns)
    precision = losses / len(rows)
    if losses < 3 or precision < 0.65 or net >= 0.0:
        return None
    return {
        "descriptor": dict(descriptor),
        "trade_count": len(rows),
        "win_count": wins,
        "loss_count": losses,
        "loss_precision_pct": precision * 100.0,
        "net_return_pct_sum": net,
        "score": (-net) * precision * math.log1p(len(rows)) / max(wins + 1, 1),
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
            output.update({"side": None, "action": "hold", "size": 0.0, "why": f"single_cause_block:{descriptor['kind']}:{descriptor['value']}", "skill": "none", "confidence": 0.0, "indicators": indicators})
        return output

    return wrapped, counter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--top-clusters", type=int, default=5)
    args = parser.parse_args()
    root = Path(args.root).resolve()

    prior_end_ms = int(pd.Timestamp(base.FIXED_END_ISO).timestamp() * 1000)
    prior_end_ms = (prior_end_ms // base.INTERVAL_MS) * base.INTERVAL_MS
    prior_start_ms = prior_end_ms - (int(base.WINDOW_BARS) * 2 - 1) * base.INTERVAL_MS
    prior_single_end_ms = prior_start_ms - base.INTERVAL_MS
    prior_single_start_ms = prior_single_end_ms - (1200 - 1) * base.INTERVAL_MS
    original_end_ms = prior_single_start_ms - base.INTERVAL_MS
    original_start_ms = original_end_ms - (WINDOW_BARS * 5 - 1) * base.INTERVAL_MS
    fresh_end_ms = original_start_ms - base.INTERVAL_MS
    fresh_start_ms = fresh_end_ms - (WINDOW_BARS * 2 - 1) * base.INTERVAL_MS
    expected_rows = WINDOW_BARS * 7

    blockers = []
    frames = {}
    fetch_results = []
    for symbol in base.SYMBOLS:
        try:
            frame, endpoint, requests = base._fetch_exact(symbol, start_ms=fresh_start_ms, end_ms=original_end_ms, expected_rows=expected_rows)
            frames[symbol] = frame
            fetch_results.append({"symbol": symbol, "status": "PASS", "rows": len(frame), "endpoint": endpoint, "request_count": requests})
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    registry = base._load_registry(root)
    candidates = []
    strategy_lookup = {}
    if not blockers:
        for strategy_id in STRATEGY_IDS:
            canonical = base._load_canonical_strategy(root, strategy_id, registry[strategy_id])
            for spec in variants_for(strategy_id):
                strategy = wrap_strategy(canonical, spec)
                selection = [_window(frames, strategy, index) for index in range(2, 7)]
                combined = _aggregate(selection)
                passed, reasons = _selection_contract(selection, combined)
                row = {"strategy_id": strategy_id, "variant_id": spec.variant_id, "selection_windows": selection, "selection_combined": combined, "selection_score": _selection_score(selection), "selection_pass": passed, "selection_reasons": reasons}
                candidates.append(row)
                strategy_lookup[(strategy_id, spec.variant_id)] = strategy

    candidates.sort(key=lambda row: (bool(row["selection_pass"]), float(row["selection_score"])), reverse=True)
    selected = candidates[0] if candidates else None
    experiments = []
    clusters = []
    chosen_mode = "BASE_VARIANT"
    chosen_strategy = None
    chosen_selection = None
    surgery_accepted = False

    if selected is not None:
        base_strategy = strategy_lookup[(selected["strategy_id"], selected["variant_id"])]
        chosen_strategy = base_strategy
        chosen_selection = selected["selection_windows"]
        discovery_trades = []
        for index in range(2, 6):
            start = index * WINDOW_BARS
            end = start + WINDOW_BARS
            for symbol in base.SYMBOLS:
                replay = trace._replay_trace(frames[symbol].iloc[start:end].reset_index(drop=True), base_strategy, warmup_bars=WARMUP_BARS, history_bars=HISTORY_BARS, cost_bps_per_side=COST_BPS_PER_SIDE)
                for trade in replay.get("trades", []):
                    discovery_trades.append({"symbol": symbol, "window_id": LABELS[index], **trade})
        for descriptor in _descriptors(discovery_trades):
            row = _cluster(discovery_trades, descriptor)
            if row is not None:
                clusters.append(row)
        clusters.sort(key=lambda row: float(row["score"]), reverse=True)
        for cluster in clusters[: args.top_clusters]:
            gated, counter = _blocked(base_strategy, cluster["descriptor"])
            selection = [_window(frames, gated, index) for index in range(2, 7)]
            combined = _aggregate(selection)
            passed, reasons = _selection_contract(selection, combined)
            base_payoff = _number(selected["selection_combined"].get("payoff_ratio"))
            if base_payoff > 0.0 and _number(combined.get("payoff_ratio")) < base_payoff * 0.90:
                passed = False
                reasons = list(reasons) + ["PAYOFF_DEGRADED_GT_10PCT"]
            if _number(combined.get("net_return_pct_sum")) <= _number(selected["selection_combined"].get("net_return_pct_sum")):
                passed = False
                reasons = list(reasons) + ["NET_NOT_IMPROVED"]
            experiments.append({"cluster": cluster, "blocked_entry_signals": counter["blocked_entry_signals"], "selection_windows": selection, "selection_combined": combined, "selection_pass": passed, "selection_reasons": reasons, "selection_score": _selection_score(selection), "strategy": gated})
        experiments.sort(key=lambda row: (bool(row["selection_pass"]), float(row["selection_score"])), reverse=True)
        if experiments and experiments[0]["selection_pass"]:
            chosen_mode = "SINGLE_CAUSE_SURGERY"
            chosen_strategy = experiments[0].pop("strategy")
            chosen_selection = experiments[0]["selection_windows"]
            surgery_accepted = True
        for row in experiments:
            row.pop("strategy", None)

    fresh_windows = []
    fresh_combined = None
    fresh_pass = False
    fresh_reasons = ["NO_SELECTED_STRATEGY"]
    if chosen_strategy is not None:
        fresh_windows = [_window(frames, chosen_strategy, index) for index in range(0, 2)]
        fresh_combined = _aggregate(fresh_windows)
        fresh_pass, fresh_reasons = _fresh_contract(fresh_windows, fresh_combined)

    selection_pass = bool(selected and selected["selection_pass"])
    accepted = bool(selection_pass and fresh_pass)
    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_TREND_FAMILY_SEARCH_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "strategy_ids": list(STRATEGY_IDS),
        "candidate_results": candidates,
        "selected": selected,
        "cluster_candidates": clusters,
        "surgery_experiments": experiments,
        "chosen_mode": chosen_mode,
        "surgery_accepted": surgery_accepted,
        "chosen_selection_windows": chosen_selection,
        "chosen_selection_combined": _aggregate(chosen_selection) if chosen_selection else None,
        "fresh_holdout_windows": fresh_windows,
        "fresh_holdout_combined": fresh_combined,
        "fresh_holdout_pass": fresh_pass,
        "fresh_holdout_reasons": fresh_reasons,
        "meaningful_positive_accepted": accepted,
        "fetch_results": fetch_results,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "shadow_allowed": False,
        "next": "THIRD_OOS_CONFIRMATION" if accepted else "NEXT_STRATEGY_FAMILY_CANDIDATE",
    }
    _atomic_json(root / OUTPUT_DIR / "summary.json", report)
    print(json.dumps({"STATE": report["state"], "SELECTED": None if selected is None else {"strategy_id": selected["strategy_id"], "variant_id": selected["variant_id"], "selection": selected["selection_combined"], "selection_pass": selected["selection_pass"]}, "CHOSEN_MODE": chosen_mode, "SURGERY_ACCEPTED": surgery_accepted, "FRESH": fresh_combined, "FRESH_PASS": fresh_pass, "FRESH_REASONS": fresh_reasons, "ACCEPTED": accepted, "NEXT": report["next"]}, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
