#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SYMBOLS = ("XRPUSDT", "LINKUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")
COSTS_BPS = (0.0, 4.0)
TARGET_TIMEFRAME_MIN = 5
BASELINE_ID = "BASELINE_SUPERTREND_TRAIL"


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


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def close_enough(left: float, right: float, tolerance: float) -> bool:
    if math.isinf(left) or math.isinf(right):
        return left == right
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


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


@dataclass(frozen=True)
class Variant:
    variant_id: str
    partial_fraction: float
    partial_trigger_r: Optional[float]
    remaining_cost_be: bool
    profit_lock_trigger_r: Optional[float]
    profit_lock_r: Optional[float]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Variant":
        variant = cls(
            variant_id=str(payload["variant_id"]),
            partial_fraction=float(payload["partial_fraction"]),
            partial_trigger_r=None if payload.get("partial_trigger_r") is None else float(payload["partial_trigger_r"]),
            remaining_cost_be=bool(payload["remaining_cost_be"]),
            profit_lock_trigger_r=None if payload.get("profit_lock_trigger_r") is None else float(payload["profit_lock_trigger_r"]),
            profit_lock_r=None if payload.get("profit_lock_r") is None else float(payload["profit_lock_r"]),
        )
        variant.validate()
        return variant

    def validate(self) -> None:
        if not self.variant_id:
            raise AuditError("VARIANT_ID_EMPTY")
        if not 0.0 <= self.partial_fraction < 1.0:
            raise AuditError(f"PARTIAL_FRACTION_INVALID:{self.variant_id}")
        if self.partial_fraction == 0.0 and self.partial_trigger_r is not None:
            raise AuditError(f"PARTIAL_TRIGGER_WITHOUT_FRACTION:{self.variant_id}")
        if self.partial_fraction > 0.0 and (self.partial_trigger_r is None or self.partial_trigger_r <= 0.0):
            raise AuditError(f"PARTIAL_TRIGGER_INVALID:{self.variant_id}")
        if self.remaining_cost_be and self.partial_fraction <= 0.0:
            raise AuditError(f"COST_BE_WITHOUT_PARTIAL:{self.variant_id}")
        if (self.profit_lock_trigger_r is None) != (self.profit_lock_r is None):
            raise AuditError(f"LOCK_PAIR_INCOMPLETE:{self.variant_id}")
        if self.profit_lock_trigger_r is not None:
            if self.profit_lock_trigger_r <= 0.0 or self.profit_lock_r is None or self.profit_lock_r < 0.0:
                raise AuditError(f"LOCK_INVALID:{self.variant_id}")
            if self.profit_lock_r >= self.profit_lock_trigger_r:
                raise AuditError(f"LOCK_NOT_BELOW_TRIGGER:{self.variant_id}")


@dataclass
class Position:
    side: int
    entry_index: int
    entry_ts_ms: int
    entry_price: float
    initial_stop: float
    trailing_stop: float
    initial_risk_abs: float
    remaining_qty: float = 1.0
    realized_gross_return: float = 0.0
    realized_exit_cost: float = 0.0
    partial_done: bool = False
    lock_done: bool = False
    legs: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Trade:
    side: str
    entry_ts_ms: int
    exit_ts_ms: int
    entry_price: float
    final_exit_price: float
    weighted_exit_price: float
    exit_reason: str
    gross_return: float
    net_return: float
    gross_r: float
    net_r: float
    hold_bars: int
    mfe_r: float
    mae_r: float
    partial_fill_count: int
    partial_realized_r: float
    lock_triggered: bool
    exit_legs: List[Dict[str, Any]]


def favorable_touched(side: int, high: float, low: float, level: float) -> bool:
    return high >= level if side == 1 else low <= level


def stop_hit(side: int, open_price: float, high: float, low: float, stop: float) -> Optional[Tuple[float, str]]:
    if side == 1:
        if open_price <= stop:
            return open_price, "PROTECTIVE_STOP_GAP_OPEN"
        if low <= stop:
            return stop, "PROTECTIVE_STOP_INTRABAR"
    else:
        if open_price >= stop:
            return open_price, "PROTECTIVE_STOP_GAP_OPEN"
        if high >= stop:
            return stop, "PROTECTIVE_STOP_INTRABAR"
    return None


def valid_entry_stop(side: int, entry_price: float, stop: float) -> bool:
    return finite(stop) and ((side == 1 and stop < entry_price) or (side == -1 and stop > entry_price))


def excursion(frame: Any, position: Position, exit_index: int) -> Tuple[float, float]:
    window = frame.iloc[position.entry_index : exit_index + 1]
    if position.side == 1:
        favorable = float(window["high"].max()) / position.entry_price - 1.0
        adverse = float(window["low"].min()) / position.entry_price - 1.0
    else:
        favorable = 1.0 - float(window["low"].min()) / position.entry_price
        adverse = 1.0 - float(window["high"].max()) / position.entry_price
    return favorable, adverse


def apply_partial(position: Position, exit_price: float, quantity: float, cost_rate: float, reason: str) -> None:
    quantity = min(float(quantity), position.remaining_qty)
    if quantity <= 0.0:
        return
    gross = quantity * position.side * (float(exit_price) - position.entry_price) / position.entry_price
    position.realized_gross_return += gross
    position.realized_exit_cost += quantity * cost_rate
    position.remaining_qty -= quantity
    position.partial_done = True
    position.legs.append(
        {
            "quantity": quantity,
            "exit_price": float(exit_price),
            "reason": reason,
            "gross_return": gross,
            "exit_cost": quantity * cost_rate,
        }
    )


def finalize_trade(
    *,
    frame: Any,
    position: Position,
    exit_index: int,
    exit_price: float,
    reason: str,
    cost_rate: float,
) -> Trade:
    remaining = position.remaining_qty
    remaining_gross = remaining * position.side * (float(exit_price) - position.entry_price) / position.entry_price
    remaining_exit_cost = remaining * cost_rate
    gross_return = position.realized_gross_return + remaining_gross
    net_return = gross_return - cost_rate - position.realized_exit_cost - remaining_exit_cost
    risk_pct = position.initial_risk_abs / position.entry_price
    if risk_pct <= 1e-12:
        raise AuditError("FINALIZE_ZERO_INITIAL_RISK")
    mfe, mae = excursion(frame, position, exit_index)
    exit_legs = list(position.legs)
    exit_legs.append(
        {
            "quantity": remaining,
            "exit_price": float(exit_price),
            "reason": reason,
            "gross_return": remaining_gross,
            "exit_cost": remaining_exit_cost,
        }
    )
    weighted_exit = sum(float(leg["quantity"]) * float(leg["exit_price"]) for leg in exit_legs)
    partial_realized_r = position.realized_gross_return / risk_pct
    return Trade(
        side="long" if position.side == 1 else "short",
        entry_ts_ms=position.entry_ts_ms,
        exit_ts_ms=int(frame["ts_ms"].iloc[exit_index]),
        entry_price=position.entry_price,
        final_exit_price=float(exit_price),
        weighted_exit_price=weighted_exit,
        exit_reason=reason,
        gross_return=gross_return,
        net_return=net_return,
        gross_r=gross_return / risk_pct,
        net_r=net_return / risk_pct,
        hold_bars=exit_index - position.entry_index + 1,
        mfe_r=mfe / risk_pct,
        mae_r=mae / risk_pct,
        partial_fill_count=len(position.legs),
        partial_realized_r=partial_realized_r,
        lock_triggered=position.lock_done,
        exit_legs=exit_legs,
    )


def replay(frame: Any, signals: Any, cost_bps: float, variant: Variant) -> Dict[str, Any]:
    cost_rate = float(cost_bps) / 10_000.0
    position: Optional[Position] = None
    pending_side = 0
    pending_stop = float("nan")
    trades: List[Trade] = []
    invalid_entry_stop_count = 0
    long_entry_count = 0
    short_entry_count = 0
    partial_trigger_count = 0
    lock_trigger_count = 0
    post_trigger_same_bar_stop_count = 0
    equity = 1.0
    equity_path = [equity]

    for index in range(len(frame)):
        bar = frame.iloc[index]
        open_price = float(bar["open"])
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        ts_ms = int(bar["ts_ms"])

        if pending_side:
            if position is not None and position.side != pending_side:
                trade = finalize_trade(
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
                        initial_risk_abs=abs(open_price - pending_stop),
                    )
                    long_entry_count += int(pending_side == 1)
                    short_entry_count += int(pending_side == -1)
                else:
                    invalid_entry_stop_count += 1
            pending_side = 0
            pending_stop = float("nan")

        if position is not None:
            event = stop_hit(position.side, open_price, high, low, position.trailing_stop)
            if event is not None:
                exit_price, exit_reason = event
                trade = finalize_trade(
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

        stop_raised_this_bar = False
        if position is not None and variant.partial_fraction > 0.0 and not position.partial_done:
            assert variant.partial_trigger_r is not None
            partial_level = position.entry_price + position.side * variant.partial_trigger_r * position.initial_risk_abs
            if favorable_touched(position.side, high, low, partial_level):
                apply_partial(
                    position,
                    partial_level,
                    variant.partial_fraction,
                    cost_rate,
                    f"PARTIAL_{variant.partial_fraction:.2f}_AT_{variant.partial_trigger_r:.2f}R",
                )
                partial_trigger_count += 1
                if variant.remaining_cost_be:
                    cost_be = position.entry_price * (1.0 + position.side * 2.0 * cost_rate)
                    if position.side == 1:
                        position.trailing_stop = max(position.trailing_stop, cost_be)
                    else:
                        position.trailing_stop = min(position.trailing_stop, cost_be)
                    stop_raised_this_bar = True

        if position is not None and variant.profit_lock_trigger_r is not None and not position.lock_done:
            lock_trigger_level = position.entry_price + position.side * variant.profit_lock_trigger_r * position.initial_risk_abs
            if favorable_touched(position.side, high, low, lock_trigger_level):
                assert variant.profit_lock_r is not None
                lock_stop = position.entry_price + position.side * variant.profit_lock_r * position.initial_risk_abs
                if position.side == 1:
                    position.trailing_stop = max(position.trailing_stop, lock_stop)
                else:
                    position.trailing_stop = min(position.trailing_stop, lock_stop)
                position.lock_done = True
                lock_trigger_count += 1
                stop_raised_this_bar = True

        if position is not None and stop_raised_this_bar:
            post_trigger_hit = (
                low <= position.trailing_stop if position.side == 1 else high >= position.trailing_stop
            )
            if post_trigger_hit:
                trade = finalize_trade(
                    frame=frame,
                    position=position,
                    exit_index=index,
                    exit_price=position.trailing_stop,
                    reason="POST_TRIGGER_RAISED_STOP_SAME_BAR",
                    cost_rate=cost_rate,
                )
                trades.append(trade)
                equity *= 1.0 + trade.net_return
                post_trigger_same_bar_stop_count += 1
                position = None

        if position is not None:
            candidate = float(signals["trailing_stop"].iloc[index])
            if position.side == 1 and finite(candidate) and candidate < close:
                position.trailing_stop = max(position.trailing_stop, candidate)
            elif position.side == -1 and finite(candidate) and candidate > close:
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

        marked_equity = equity
        if position is not None:
            unrealized = position.remaining_qty * position.side * (close - position.entry_price) / position.entry_price
            current_trade_mark = (
                position.realized_gross_return
                + unrealized
                - cost_rate
                - position.realized_exit_cost
            )
            marked_equity *= 1.0 + current_trade_mark
        equity_path.append(marked_equity)

    gross_values = [trade.gross_return for trade in trades]
    net_values = [trade.net_return for trade in trades]
    net_r_values = [trade.net_r for trade in trades]
    winners = [trade for trade in trades if trade.net_return > 0.0]
    losers = [trade for trade in trades if trade.net_return < 0.0]
    return {
        "variant_id": variant.variant_id,
        "cost_bps_per_fill": float(cost_bps),
        "trade_count": len(trades),
        "long_entry_count": long_entry_count,
        "short_entry_count": short_entry_count,
        "invalid_entry_stop_count": invalid_entry_stop_count,
        "partial_trigger_count": partial_trigger_count,
        "lock_trigger_count": lock_trigger_count,
        "post_trigger_same_bar_stop_count": post_trigger_same_bar_stop_count,
        "win_rate_pct": 100.0 * len(winners) / len(trades) if trades else 0.0,
        "gross_profit_factor": profit_factor(gross_values),
        "net_profit_factor": profit_factor(net_values),
        "gross_return_sum_pct": 100.0 * sum(gross_values),
        "net_return_sum_pct": 100.0 * sum(net_values),
        "net_expectancy_r": statistics.fmean(net_r_values) if net_r_values else 0.0,
        "average_win_r": statistics.fmean([trade.net_r for trade in winners]) if winners else 0.0,
        "average_loss_r": statistics.fmean([trade.net_r for trade in losers]) if losers else 0.0,
        "maximum_drawdown_pct": 100.0 * maximum_drawdown(equity_path),
        "terminal_position": "flat" if position is None else ("long" if position.side == 1 else "short"),
        "trade_rows": [asdict(trade) for trade in trades],
    }


def pooled(symbol_rows: Mapping[str, Mapping[str, Any]], profile: str) -> Dict[str, Any]:
    rows = [payload[profile] for payload in symbol_rows.values()]
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
        "partial_trigger_count": sum(int(row["partial_trigger_count"]) for row in rows),
        "lock_trigger_count": sum(int(row["lock_trigger_count"]) for row in rows),
        "post_trigger_same_bar_stop_count": sum(int(row["post_trigger_same_bar_stop_count"]) for row in rows),
        "profit_factor": profit_factor(net_values),
        "expectancy_r": statistics.fmean(net_r_values) if net_r_values else 0.0,
        "mean_symbol_return_pct": statistics.fmean(returns),
        "worst_symbol_return_pct": min(returns),
        "maximum_symbol_drawdown_pct": max(float(row["maximum_drawdown_pct"]) for row in rows),
    }


def validate_source(source: Mapping[str, Any], loss: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    if source.get("schema") != "r7a4d2_user_supplied_video_bundle_upgrade_v1":
        raise AuditError("SOURCE_SUMMARY_SCHEMA_MISMATCH")
    if source.get("state") != "PASS_USER_SUPPLIED_VIDEO_BUNDLE_UPGRADE":
        raise AuditError("SOURCE_SUMMARY_STATE_NOT_PASS")
    if loss.get("schema") != contract.get("source_loss_anatomy_schema"):
        raise AuditError("LOSS_SUMMARY_SCHEMA_MISMATCH")
    if loss.get("state") != "PASS_USER_VIDEO_DEMA_SUPERTREND_LOSS_ANATOMY":
        raise AuditError("LOSS_SUMMARY_STATE_NOT_PASS")
    if loss.get("source_video_id") != contract.get("source_video_id"):
        raise AuditError("LOSS_VIDEO_ID_MISMATCH")
    five_minute = loss.get("timeframes", {}).get("5m")
    if not isinstance(five_minute, Mapping):
        raise AuditError("LOSS_5M_METRICS_MISSING")
    if five_minute.get("primary_mechanism") != "EXIT_CAPTURE_PRIMARY":
        raise AuditError("LOSS_5M_NOT_EXIT_CAPTURE_PRIMARY")


def baseline_parity(
    source: Mapping[str, Any],
    baseline_symbols: Mapping[str, Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> Dict[str, Any]:
    tolerance_pf = float(contract["baseline_parity"]["profit_factor_abs_tolerance"])
    tolerance_exp = float(contract["baseline_parity"]["expectancy_r_abs_tolerance"])
    checks: Dict[str, Any] = {}
    all_pass = True
    source_symbols = source["dema_supertrend_oos"]["5m"]["symbols"]
    for symbol in SYMBOLS:
        checks[symbol] = {}
        for profile in ("0.0", "4.0"):
            expected = source_symbols[symbol][profile]
            actual = baseline_symbols[symbol][profile]
            profile_checks = {
                "trade_count": int(actual["trade_count"]) == int(expected["trade_count"]),
                "long_entry_count": int(actual["long_entry_count"]) == int(expected["long_entry_count"]),
                "short_entry_count": int(actual["short_entry_count"]) == int(expected["short_entry_count"]),
                "profit_factor": close_enough(
                    float(actual["net_profit_factor"]),
                    float(expected["net_profit_factor"]),
                    tolerance_pf,
                ),
                "expectancy_r": close_enough(
                    float(actual["net_expectancy_r"]),
                    float(expected["net_expectancy_r"]),
                    tolerance_exp,
                ),
            }
            profile_checks["pass"] = all(profile_checks.values())
            checks[symbol][profile] = profile_checks
            all_pass = all_pass and profile_checks["pass"]
    return {"pass": all_pass, "checks": checks}


def classify_variant(
    variant_id: str,
    gross: Mapping[str, Any],
    net4: Mapping[str, Any],
    baseline_net4: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> str:
    if variant_id == BASELINE_ID:
        return "BASELINE_FAIL_REFERENCE"
    economic = (
        float(gross["profit_factor"]) > float(gate["gross_profit_factor_min"])
        and float(net4["profit_factor"]) > float(gate["net_4bps_profit_factor_min"])
        and float(net4["expectancy_r"]) > float(gate["net_4bps_expectancy_r_min"])
        and int(net4["positive_symbol_count"]) >= int(gate["positive_symbols_min"])
        and int(net4["long_entry_count"]) >= int(gate["long_entries_min"])
        and int(net4["short_entry_count"]) >= int(gate["short_entries_min"])
        and float(net4["maximum_symbol_drawdown_pct"]) <= float(gate["maximum_drawdown_pct_max"])
    )
    if economic:
        return "ECONOMIC_SURVIVOR_FOR_INDEPENDENT_OOS"
    improvement = (
        float(net4["profit_factor"]) > float(baseline_net4["profit_factor"]) + 0.05
        and float(net4["expectancy_r"]) > float(baseline_net4["expectancy_r"]) + 0.025
        and float(net4["mean_symbol_return_pct"]) > float(baseline_net4["mean_symbol_return_pct"])
    )
    return "MECHANISTIC_IMPROVEMENT_ONLY" if improvement else "NO_MATERIAL_IMPROVEMENT"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--code-root", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--source-summary", required=True)
    parser.add_argument("--loss-summary", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    code_root = Path(args.code_root).resolve()
    source_path = Path(args.source_summary).resolve()
    loss_path = Path(args.loss_summary).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not source_path.is_file():
        raise AuditError(f"SOURCE_SUMMARY_MISSING:{source_path}")
    if not loss_path.is_file():
        raise AuditError(f"LOSS_SUMMARY_MISSING:{loss_path}")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    loss = json.loads(loss_path.read_text(encoding="utf-8"))

    contract_path = code_root / "research" / "user_video_dema_supertrend_5m_profit_protection_audit_v1.json"
    if not contract_path.is_file():
        raise AuditError("PROFIT_PROTECTION_CONTRACT_MISSING")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    validate_source(source, loss, contract)
    variants = [Variant.from_payload(payload) for payload in contract["fixed_variants"]]
    if [variant.variant_id for variant in variants].count(BASELINE_ID) != 1:
        raise AuditError("BASELINE_VARIANT_COUNT_INVALID")

    utils, utils_path = load_module(
        code_root,
        "tools/r7a4d2_js_techtrading_supertrend_pullback_exact_oos_replay.py",
        "profit_protection_market_utils",
    )
    child, child_path = load_module(
        code_root,
        "backend/strategies/authentic/tradinglab_dema_supertrend_video_v1.py",
        "profit_protection_strategy_child",
    )
    selected_files = utils.select_files(data_root)

    variant_outputs: Dict[str, Any] = {
        variant.variant_id: {"variant": asdict(variant), "symbols": {}}
        for variant in variants
    }

    for symbol in SYMBOLS:
        market_path = selected_files[symbol]
        one_minute = utils.load_market(market_path)
        frame, aggregation = utils.aggregate(one_minute, TARGET_TIMEFRAME_MIN)
        config = child.TradingLabDEMASupertrendConfig(
            dema_length=200,
            atr_length=12,
            factor=3.0,
            trade_direction="Both",
            early_entry_enabled=False,
            early_entry_max_bars=0,
        )
        signals = child.compute_video_contract_signals(frame, config)
        for variant in variants:
            profiles = {str(cost): replay(frame, signals, cost, variant) for cost in COSTS_BPS}
            variant_outputs[variant.variant_id]["symbols"][symbol] = {
                "market_path": str(market_path),
                "market_sha256": sha256_file(market_path),
                "aggregation": aggregation,
                "long_signal_count": int(signals["entry_long"].sum()),
                "short_signal_count": int(signals["entry_short"].sum()),
                "0.0": profiles["0.0"],
                "4.0": profiles["4.0"],
            }
            print(
                "PROTECTION_CELL="
                f"{variant.variant_id}|{symbol}|TF=5m"
                f"|TRADES={profiles['4.0']['trade_count']}"
                f"|PARTIALS={profiles['4.0']['partial_trigger_count']}"
                f"|LOCKS={profiles['4.0']['lock_trigger_count']}"
                f"|PF0={profiles['0.0']['net_profit_factor']:.6f}"
                f"|PF4={profiles['4.0']['net_profit_factor']:.6f}"
                f"|EXP4_R={profiles['4.0']['net_expectancy_r']:.6f}"
                f"|RETURN4_PCT={profiles['4.0']['net_return_sum_pct']:.6f}"
                f"|DD4_PCT={profiles['4.0']['maximum_drawdown_pct']:.6f}"
            )

    parity = baseline_parity(source, variant_outputs[BASELINE_ID]["symbols"], contract)
    if not parity["pass"]:
        raise AuditError("BASELINE_REPLAY_PARITY_FAILED")

    baseline_net4: Optional[Mapping[str, Any]] = None
    for variant in variants:
        payload = variant_outputs[variant.variant_id]
        gross = pooled(payload["symbols"], "0.0")
        net4 = pooled(payload["symbols"], "4.0")
        payload["gross"] = gross
        payload["net4bps"] = net4
        if variant.variant_id == BASELINE_ID:
            baseline_net4 = net4

    if baseline_net4 is None:
        raise AuditError("BASELINE_AGGREGATE_MISSING")

    survivor_ids: List[str] = []
    improvement_ids: List[str] = []
    gate = contract["economic_survivor_gate"]
    for variant in variants:
        payload = variant_outputs[variant.variant_id]
        classification = classify_variant(
            variant.variant_id,
            payload["gross"],
            payload["net4bps"],
            baseline_net4,
            gate,
        )
        payload["classification"] = classification
        if classification == "ECONOMIC_SURVIVOR_FOR_INDEPENDENT_OOS":
            survivor_ids.append(variant.variant_id)
        elif classification == "MECHANISTIC_IMPROVEMENT_ONLY":
            improvement_ids.append(variant.variant_id)
        print(
            "PROTECTION_VARIANT_RESULT="
            f"{variant.variant_id}|CLASS={classification}"
            f"|TRADES={payload['net4bps']['trade_count']}"
            f"|PF0={payload['gross']['profit_factor']:.6f}"
            f"|PF4={payload['net4bps']['profit_factor']:.6f}"
            f"|EXP4_R={payload['net4bps']['expectancy_r']:.6f}"
            f"|POS_SYMBOLS={payload['net4bps']['positive_symbol_count']}/5"
            f"|MEAN_RETURN4_PCT={payload['net4bps']['mean_symbol_return_pct']:.6f}"
            f"|MAX_DD4_PCT={payload['net4bps']['maximum_symbol_drawdown_pct']:.6f}"
            f"|PARTIALS={payload['net4bps']['partial_trigger_count']}"
            f"|LOCKS={payload['net4bps']['lock_trigger_count']}"
        )

    if survivor_ids:
        next_stage = "R7.A4D2_USER_VIDEO_5M_PROFIT_PROTECTION_DISJOINT_OOS_CONFIRMATION"
    else:
        next_stage = "R7.A4D2_USER_VIDEO_15M_RSI50_DEMA_SLOPE_ENTRY_GATE_AUDIT"

    output = {
        "schema": "r7a4d2_user_video_dema_supertrend_5m_profit_protection_audit_v1",
        "state": "PASS_USER_VIDEO_DEMA_SUPERTREND_5M_PROFIT_PROTECTION_AUDIT",
        "target_sha": args.target_sha,
        "source_video_id": "g-PLctW8aU0",
        "strategy_id": child.STRATEGY_ID,
        "target_timeframe": "5m",
        "source_summary": str(source_path),
        "loss_summary": str(loss_path),
        "contract_sha256": sha256_file(contract_path),
        "child_sha256": sha256_file(child_path),
        "market_utils_sha256": sha256_file(utils_path),
        "baseline_parity": parity,
        "variants": variant_outputs,
        "independent_oos_candidates": survivor_ids,
        "mechanistic_improvements": improvement_ids,
        "promotion_allowed": False,
        "selection_allowed": False,
        "next_stage": next_stage,
        "mutation_count": 0,
        "blockers": [],
    }
    output_path = output_dir / "user_video_dema_supertrend_5m_profit_protection_audit_v1.json"
    output_path.write_text(
        json.dumps(output, indent=2, sort_keys=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    print(f"STATE={output['state']}")
    print("BASELINE_PARITY_PASS=true")
    print(f"ECONOMIC_SURVIVOR_COUNT={len(survivor_ids)}")
    print(f"ECONOMIC_SURVIVORS={json.dumps(survivor_ids, separators=(',', ':'))}")
    print(f"MECHANISTIC_IMPROVEMENTS={json.dumps(improvement_ids, separators=(',', ':'))}")
    print("PROMOTION_ALLOWED=false")
    print("SELECTION_ALLOWED=false")
    print(f"SUMMARY_JSON={output_path}")
    print("MUTATION_COUNT=0")
    print(f"NEXT_STAGE={next_stage}")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print("STATE=HOLD_USER_VIDEO_DEMA_SUPERTREND_5M_PROFIT_PROTECTION_INPUT")
        print(f"BLOCKERS=[\"{str(exc)}\"]")
        print("RC=2")
        raise SystemExit(2)
