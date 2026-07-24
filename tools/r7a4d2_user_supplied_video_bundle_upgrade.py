#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SYMBOLS = ("XRPUSDT", "LINKUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = (5, 15)
COSTS_BPS = (0.0, 4.0)


class AuditError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(code_root: Path, relative_path: str, module_name: str) -> Tuple[Any, Path]:
    path = code_root / relative_path
    if not path.is_file():
        raise AuditError(f"MODULE_MISSING:{relative_path}")
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AuditError(f"MODULE_SPEC_FAILED:{relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, path


@dataclass
class Position:
    side: int
    entry_index: int
    entry_ts_ms: int
    entry_price: float
    initial_stop: float
    trailing_stop: float


@dataclass
class Trade:
    side: str
    entry_ts_ms: int
    exit_ts_ms: int
    entry_price: float
    exit_price: float
    exit_reason: str
    gross_return: float
    net_return: float
    gross_r: float
    net_r: float
    hold_bars: int
    mfe_r: float
    mae_r: float


def profit_factor(values: Sequence[float]) -> float:
    positive = sum(value for value in values if value > 0.0)
    negative = abs(sum(value for value in values if value < 0.0))
    return positive / negative if negative else (float("inf") if positive else 0.0)


def maximum_drawdown(path: Sequence[float]) -> float:
    peak = path[0] if path else 1.0
    worst = 0.0
    for value in path:
        peak = max(peak, value)
        if peak > 0.0:
            worst = min(worst, value / peak - 1.0)
    return abs(worst)


def excursions(frame: Any, position: Position, exit_index: int) -> Tuple[float, float]:
    window = frame.iloc[position.entry_index : exit_index + 1]
    if position.side == 1:
        favorable = float(window["high"].max()) / position.entry_price - 1.0
        adverse = float(window["low"].min()) / position.entry_price - 1.0
    else:
        favorable = 1.0 - float(window["low"].min()) / position.entry_price
        adverse = 1.0 - float(window["high"].max()) / position.entry_price
    return favorable, adverse


def close_trade(
    *,
    frame: Any,
    position: Position,
    exit_index: int,
    exit_price: float,
    reason: str,
    cost_rate: float,
) -> Trade:
    gross_return = position.side * (float(exit_price) - position.entry_price) / position.entry_price
    net_return = gross_return - 2.0 * cost_rate
    risk = abs(position.entry_price - position.initial_stop) / position.entry_price
    denominator = risk if risk > 1e-12 else 1.0
    mfe, mae = excursions(frame, position, exit_index)
    return Trade(
        side="long" if position.side == 1 else "short",
        entry_ts_ms=position.entry_ts_ms,
        exit_ts_ms=int(frame["ts_ms"].iloc[exit_index]),
        entry_price=position.entry_price,
        exit_price=float(exit_price),
        exit_reason=reason,
        gross_return=gross_return,
        net_return=net_return,
        gross_r=gross_return / denominator,
        net_r=net_return / denominator,
        hold_bars=exit_index - position.entry_index + 1,
        mfe_r=mfe / denominator,
        mae_r=mae / denominator,
    )


def valid_entry_stop(side: int, entry_price: float, stop: float) -> bool:
    return math.isfinite(stop) and ((side == 1 and stop < entry_price) or (side == -1 and stop > entry_price))


def replay(frame: Any, signals: Any, cost_bps: float) -> Dict[str, Any]:
    cost_rate = float(cost_bps) / 10_000.0
    position: Optional[Position] = None
    pending_side = 0
    pending_stop = float("nan")
    trades: List[Trade] = []
    invalid_entry_stop_count = 0
    long_entry_count = 0
    short_entry_count = 0
    equity = 1.0
    marked_path = [equity]

    for index in range(len(frame)):
        bar = frame.iloc[index]
        open_price = float(bar["open"])
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        ts_ms = int(bar["ts_ms"])

        if pending_side:
            if position is not None and position.side != pending_side:
                trade = close_trade(
                    frame=frame,
                    position=position,
                    exit_index=index,
                    exit_price=open_price,
                    reason="OPPOSITE_SIGNAL_NEXT_OPEN",
                    cost_rate=cost_rate,
                )
                trades.append(trade)
                equity *= 1.0 + trade.net_return
                position = None

            if position is None:
                if valid_entry_stop(pending_side, open_price, pending_stop):
                    position = Position(
                        side=pending_side,
                        entry_index=index,
                        entry_ts_ms=ts_ms,
                        entry_price=open_price,
                        initial_stop=pending_stop,
                        trailing_stop=pending_stop,
                    )
                    long_entry_count += int(pending_side == 1)
                    short_entry_count += int(pending_side == -1)
                else:
                    invalid_entry_stop_count += 1
            pending_side = 0
            pending_stop = float("nan")

        if position is not None:
            stop = position.trailing_stop
            exit_price: Optional[float] = None
            exit_reason = ""
            if position.side == 1:
                if open_price <= stop:
                    exit_price, exit_reason = open_price, "SUPERTREND_STOP_GAP_OPEN"
                elif low <= stop:
                    exit_price, exit_reason = stop, "SUPERTREND_STOP_INTRABAR"
            else:
                if open_price >= stop:
                    exit_price, exit_reason = open_price, "SUPERTREND_STOP_GAP_OPEN"
                elif high >= stop:
                    exit_price, exit_reason = stop, "SUPERTREND_STOP_INTRABAR"
            if exit_price is not None:
                trade = close_trade(
                    frame=frame,
                    position=position,
                    exit_index=index,
                    exit_price=exit_price,
                    reason=exit_reason,
                    cost_rate=cost_rate,
                )
                trades.append(trade)
                equity *= 1.0 + trade.net_return
                position = None

        if position is not None:
            candidate = float(signals["trailing_stop"].iloc[index])
            if position.side == 1 and math.isfinite(candidate) and candidate < close:
                position.trailing_stop = max(position.trailing_stop, candidate)
            elif position.side == -1 and math.isfinite(candidate) and candidate > close:
                position.trailing_stop = min(position.trailing_stop, candidate)

        if index < len(frame) - 1:
            long_signal = bool(signals["entry_long"].iloc[index])
            short_signal = bool(signals["entry_short"].iloc[index])
            if long_signal and short_signal:
                raise AuditError(f"SIMULTANEOUS_ENTRY_SIGNAL:{index}")
            signal_side = 1 if long_signal else (-1 if short_signal else 0)
            if signal_side and (position is None or position.side != signal_side):
                pending_side = signal_side
                pending_stop = float(signals["trailing_stop"].iloc[index])

        marked = equity
        if position is not None:
            marked *= 1.0 + position.side * (close - position.entry_price) / position.entry_price
        marked_path.append(marked)

    gross_values = [trade.gross_return for trade in trades]
    net_values = [trade.net_return for trade in trades]
    net_r_values = [trade.net_r for trade in trades]
    winners = [trade for trade in trades if trade.net_return > 0.0]
    losers = [trade for trade in trades if trade.net_return < 0.0]
    return {
        "cost_bps_per_fill": float(cost_bps),
        "trade_count": len(trades),
        "long_entry_count": long_entry_count,
        "short_entry_count": short_entry_count,
        "invalid_entry_stop_count": invalid_entry_stop_count,
        "win_rate_pct": 100.0 * len(winners) / len(trades) if trades else 0.0,
        "gross_profit_factor": profit_factor(gross_values),
        "net_profit_factor": profit_factor(net_values),
        "gross_return_sum_pct": 100.0 * sum(gross_values),
        "net_return_sum_pct": 100.0 * sum(net_values),
        "net_expectancy_r": statistics.fmean(net_r_values) if net_r_values else 0.0,
        "average_win_r": statistics.fmean([trade.net_r for trade in winners]) if winners else 0.0,
        "average_loss_r": statistics.fmean([trade.net_r for trade in losers]) if losers else 0.0,
        "maximum_drawdown_pct": 100.0 * maximum_drawdown(marked_path),
        "terminal_position": "flat" if position is None else ("long" if position.side == 1 else "short"),
        "trade_rows": [asdict(trade) for trade in trades],
    }


def pooled(symbol_rows: Mapping[str, Mapping[str, Any]], profile: str) -> Dict[str, Any]:
    rows = [value[profile] for value in symbol_rows.values()]
    trades = [trade for row in rows for trade in row["trade_rows"]]
    returns = [float(row["net_return_sum_pct"]) for row in rows]
    net_values = [float(trade["net_return"]) for trade in trades]
    net_r_values = [float(trade["net_r"]) for trade in trades]
    return {
        "symbol_count": len(rows),
        "positive_symbol_count": sum(value > 0.0 for value in returns),
        "trade_count": len(trades),
        "long_entry_count": sum(int(row["long_entry_count"]) for row in rows),
        "short_entry_count": sum(int(row["short_entry_count"]) for row in rows),
        "profit_factor": profit_factor(net_values),
        "expectancy_r": statistics.fmean(net_r_values) if net_r_values else 0.0,
        "mean_symbol_return_pct": statistics.fmean(returns),
        "worst_symbol_return_pct": min(returns),
        "maximum_symbol_drawdown_pct": max(float(row["maximum_drawdown_pct"]) for row in rows),
    }


def validate_contract(contract: Mapping[str, Any], child: Any) -> Dict[str, Any]:
    videos = {item["video_id"]: item for item in contract["video_sources"]}
    required_ids = {"R2hZlnh37fQ", "g-PLctW8aU0", "cKKLujAdvzk"}
    algorithmic = videos.get("g-PLctW8aU0", {})
    baseline = contract.get("dema_supertrend_executable_baseline", {})
    checks = {
        "three_user_video_ids_present": set(videos) == required_ids,
        "algorithmic_strategy_id_match": algorithmic.get("strategy_id") == child.STRATEGY_ID,
        "child_source_video_match": child.SOURCE_VIDEO_ID == "g-PLctW8aU0",
        "dema_length_200": int(baseline.get("dema_length", 0)) == 200,
        "atr_length_12": int(baseline.get("supertrend_atr_length", 0)) == 12,
        "supertrend_factor_3": float(baseline.get("supertrend_factor", 0.0)) == 3.0,
        "manual_video_1_held": videos["R2hZlnh37fQ"]["automation_status"].startswith("HOLD_"),
        "manual_video_3_held": videos["cKKLujAdvzk"]["automation_status"].startswith("HOLD_"),
        "legacy_mutation_forbidden": contract["authority"]["legacy_strategy_mutation"] is False,
        "paper_live_order_forbidden": contract["authority"]["paper_live_order"] is False,
    }
    return {"pass": all(checks.values()), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--code-root", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    code_root = Path(args.code_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    utils, utils_path = load_module(
        code_root,
        "tools/r7a4d2_js_techtrading_supertrend_pullback_exact_oos_replay.py",
        "video_bundle_market_utils",
    )
    child, child_path = load_module(
        code_root,
        "backend/strategies/authentic/tradinglab_dema_supertrend_video_v1.py",
        "tradinglab_dema_supertrend_video_v1_runtime",
    )
    contract_path = code_root / "research" / "user_supplied_pullback_video_bundle_v1.json"
    if not contract_path.is_file():
        raise AuditError("VIDEO_BUNDLE_CONTRACT_MISSING")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract_check = validate_contract(contract, child)
    if not contract_check["pass"]:
        raise AuditError("VIDEO_BUNDLE_CONTRACT_MISMATCH")

    selected_files = utils.select_files(data_root)
    summary: Dict[str, Any] = {
        "schema": "r7a4d2_user_supplied_video_bundle_upgrade_v1",
        "state": "PASS_USER_SUPPLIED_VIDEO_BUNDLE_UPGRADE",
        "target_sha": args.target_sha,
        "source_video_ids": ["R2hZlnh37fQ", "g-PLctW8aU0", "cKKLujAdvzk"],
        "contract_check": contract_check,
        "contract_sha256": sha256_file(contract_path),
        "child_sha256": sha256_file(child_path),
        "market_utils_sha256": sha256_file(utils_path),
        "manual_contracts": {},
        "dema_supertrend_oos": {},
        "mutation_count": 0,
        "blockers": [],
    }

    for item in contract["video_sources"]:
        if item["execution_class"] == "MANUAL_DISCRETIONARY_CONTRACT":
            summary["manual_contracts"][item["video_id"]] = {
                "strategy_id": item["strategy_id"],
                "automation_status": item["automation_status"],
                "gemini_summary": item["gemini_summary"],
            }
            print(
                "MANUAL_VIDEO_CONTRACT="
                f"{item['video_id']}|STRATEGY={item['strategy_id']}"
                f"|STATUS={item['automation_status']}"
            )

    gate = contract["promotion_gate"]
    for timeframe in TIMEFRAMES:
        symbol_rows: Dict[str, Any] = {}
        for symbol in SYMBOLS:
            source = selected_files[symbol]
            one_minute = utils.load_market(source)
            frame, aggregation = utils.aggregate(one_minute, timeframe)
            cfg = child.TradingLabDEMASupertrendConfig(
                dema_length=200,
                atr_length=12,
                factor=3.0,
                trade_direction="Both",
                early_entry_enabled=False,
                early_entry_max_bars=0,
            )
            signals = child.compute_video_contract_signals(frame, cfg)
            results = {str(cost): replay(frame, signals, cost) for cost in COSTS_BPS}
            symbol_rows[symbol] = {
                "source_path": str(source),
                "source_sha256": sha256_file(source),
                "aggregation": aggregation,
                "long_signal_count": int(signals["entry_long"].sum()),
                "short_signal_count": int(signals["entry_short"].sum()),
                "0.0": results["0.0"],
                "4.0": results["4.0"],
            }
            print(
                "DEMA_ST_VIDEO_REPLAY="
                f"{symbol}|TF={timeframe}m"
                f"|LONG_SIGNALS={int(signals['entry_long'].sum())}"
                f"|SHORT_SIGNALS={int(signals['entry_short'].sum())}"
                f"|TRADES={results['0.0']['trade_count']}"
                f"|GROSS_PF={results['0.0']['net_profit_factor']:.6f}"
                f"|GROSS_EXP_R={results['0.0']['net_expectancy_r']:.6f}"
                f"|NET4BPS_PF={results['4.0']['net_profit_factor']:.6f}"
                f"|NET4BPS_EXP_R={results['4.0']['net_expectancy_r']:.6f}"
                f"|NET4BPS_RETURN_PCT={results['4.0']['net_return_sum_pct']:.6f}"
                f"|DD_PCT={results['4.0']['maximum_drawdown_pct']:.6f}"
            )

        gross = pooled(symbol_rows, "0.0")
        cost4 = pooled(symbol_rows, "4.0")
        promoted = (
            gross["trade_count"] >= int(gate["trade_count_min"])
            and gross["profit_factor"] > float(gate["gross_profit_factor_min"])
            and cost4["profit_factor"] > float(gate["net_4bps_profit_factor_min"])
            and cost4["expectancy_r"] > float(gate["net_4bps_expectancy_r_min"])
            and cost4["positive_symbol_count"] >= int(gate["positive_symbols_min"])
            and cost4["long_entry_count"] >= int(gate["long_entries_min"])
            and cost4["short_entry_count"] >= int(gate["short_entries_min"])
            and cost4["maximum_symbol_drawdown_pct"] <= float(gate["maximum_drawdown_pct_max"])
        )
        classification = "PROMOTION_CANDIDATE" if promoted else "ECONOMIC_FAIL_OR_FRAGILE"
        summary["dema_supertrend_oos"][f"{timeframe}m"] = {
            "symbols": symbol_rows,
            "gross": gross,
            "net4bps": cost4,
            "classification": classification,
        }
        print(
            "DEMA_ST_TIMEFRAME_RESULT="
            f"{timeframe}m|CLASS={classification}"
            f"|TRADES={cost4['trade_count']}"
            f"|GROSS_PF={gross['profit_factor']:.6f}"
            f"|NET4BPS_PF={cost4['profit_factor']:.6f}"
            f"|NET4BPS_EXP_R={cost4['expectancy_r']:.6f}"
            f"|POS_SYMBOLS={cost4['positive_symbol_count']}/5"
            f"|LONG_ENTRIES={cost4['long_entry_count']}"
            f"|SHORT_ENTRIES={cost4['short_entry_count']}"
            f"|MAX_DD_PCT={cost4['maximum_symbol_drawdown_pct']:.6f}"
        )

    candidates = [
        timeframe
        for timeframe, result in summary["dema_supertrend_oos"].items()
        if result["classification"] == "PROMOTION_CANDIDATE"
    ]
    summary["promotion_candidates"] = candidates
    summary["promotion_allowed"] = len(candidates) == 1
    summary["next_stage"] = (
        "R7.A4D2_USER_VIDEO_DEMA_SUPERTREND_INDEPENDENT_REPLAY_CONFIRMATION"
        if candidates
        else "R7.A4D2_USER_VIDEO_DEMA_SUPERTREND_LOSS_ANATOMY_OR_OPTIONAL_RULE_AUDIT"
    )
    output_path = output_dir / "user_supplied_video_bundle_upgrade_summary_v1.json"
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    print(f"STATE={summary['state']}")
    print("SOURCE_VIDEO_COUNT=3")
    print("MANUAL_CONTRACT_COUNT=2")
    print("EXECUTABLE_VIDEO_STRATEGY_COUNT=1")
    print(f"PROMOTION_CANDIDATES={json.dumps(candidates, separators=(',', ':'))}")
    print(f"PROMOTION_ALLOWED={str(summary['promotion_allowed']).lower()}")
    print(f"SUMMARY_JSON={output_path}")
    print("MUTATION_COUNT=0")
    print(f"NEXT_STAGE={summary['next_stage']}")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print("STATE=HOLD_USER_SUPPLIED_VIDEO_BUNDLE_UPGRADE_INPUT")
        print(f"BLOCKERS=[\"{str(exc)}\"]")
        print("RC=2")
        raise SystemExit(2)
