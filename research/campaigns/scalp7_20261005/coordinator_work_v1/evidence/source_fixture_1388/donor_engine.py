"""Causal Multi-Timeframe Backtest Execution Engine.

Simulates trades with strict zero-lookahead causality:
- Entry on next bar OPEN after signal confirmation
- Initial SL placed at LTF structural invalidation
- MTF monotonic structural trailing stop
- HTF take-profit destination
- Adverse-first intrabar collision resolution (SL before TP)
- Realistic taker fees and slippage
- Strictly enforces >= 4R minimum floor
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class TradeRecord:
    symbol: str
    stream_id: str
    direction: int  # +1 LONG, -1 SHORT
    entry_ts: int
    exit_ts: int
    entry_px: float
    exit_px: float
    initial_sl: float
    target_px: float
    initial_risk_dist: float
    target_r: float
    realized_r: float
    exit_reason: str  # HTF_TP, MTF_TRAIL, LTF_SL, TIME_EXIT
    bars_held: int
    fee_bps: float
    slippage_bps: float
    mfe_r: float = 0.0
    mae_r: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamMetrics:
    stream_id: str
    symbol: str
    timeframe_set: str
    hypothesis: str
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    loss_rate: float = 0.0
    expectancy_r: float = 0.0
    total_r: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_r: float = 0.0
    average_r: float = 0.0
    median_r: float = 0.0
    largest_win_r: float = 0.0
    largest_loss_r: float = 0.0
    target_4r_hit_rate: float = 0.0
    avg_bars_held: float = 0.0
    trade_frequency_per_month: float = 0.0
    net_pnl_pct: float = 0.0
    trades: List[TradeRecord] = field(default_factory=list)

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "symbol": self.symbol,
            "timeframe_set": self.timeframe_set,
            "hypothesis": self.hypothesis,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "loss_rate": round(self.loss_rate, 4),
            "expectancy_r": round(self.expectancy_r, 4),
            "total_r": round(self.total_r, 2),
            "profit_factor": round(self.profit_factor, 3),
            "max_drawdown_r": round(self.max_drawdown_r, 2),
            "average_r": round(self.average_r, 4),
            "largest_win_r": round(self.largest_win_r, 2),
            "largest_loss_r": round(self.largest_loss_r, 2),
            "target_4r_hit_rate": round(self.target_4r_hit_rate, 4),
            "avg_bars_held": round(self.avg_bars_held, 1),
        }


class CausalBacktestEngine:
    """Executes trade signals on LTF candle streams under strict institutional constraints."""

    def __init__(
        self,
        taker_fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        min_target_r: float = 4.0,
        max_holding_bars: int = 200,
    ):
        self.taker_fee_bps = taker_fee_bps
        self.slippage_bps = slippage_bps
        self.min_target_r = min_target_r
        self.max_holding_bars = max_holding_bars

    def execute_stream(
        self,
        stream_id: str,
        symbol: str,
        timeframe_set: str,
        hypothesis: str,
        ltf_opens: np.ndarray,
        ltf_highs: np.ndarray,
        ltf_lows: np.ndarray,
        ltf_closes: np.ndarray,
        ltf_timestamps: np.ndarray,
        signal_candidates: List[Dict[str, Any]],
        mtf_trailing_levels: Optional[Dict[int, float]] = None,
    ) -> StreamMetrics:
        """Simulate trade lifecycle for candidate signals over LTF candles."""
        n = len(ltf_closes)
        trades: List[TradeRecord] = []
        busy_until = -1
        slip_frac = self.slippage_bps / 1e4
        rt_fee_bps = self.taker_fee_bps * 2.0

        for cand in signal_candidates:
            sig_bar = cand["bar_index"] if isinstance(cand, dict) else cand.bar_index
            # Entry happens on NEXT bar (sig_bar + 1)
            entry_bar = sig_bar + 1
            if entry_bar >= n - 1 or entry_bar <= busy_until:
                continue

            direction = cand["direction"] if isinstance(cand, dict) else cand.direction
            raw_entry = float(ltf_opens[entry_bar])
            initial_sl = float(cand["stop_price"] if isinstance(cand, dict) else cand.stop_price)
            raw_target = float(cand["target_price"] if isinstance(cand, dict) else cand.target_price)
            target_r = float(cand.get("target_r", self.min_target_r) if isinstance(cand, dict) else getattr(cand, "target_r", self.min_target_r))

            if direction == 1:
                if initial_sl >= raw_entry or raw_target <= raw_entry:
                    continue
                risk_dist = raw_entry - initial_sl
                reward_dist = raw_target - raw_entry
            else:
                if initial_sl <= raw_entry or raw_target >= raw_entry:
                    continue
                risk_dist = initial_sl - raw_entry
                reward_dist = raw_entry - raw_target

            if risk_dist <= 0 or reward_dist <= 0:
                continue

            # Check minimum 4R floor: < 4R = REJECT
            proposed_r = reward_dist / risk_dist
            if proposed_r < self.min_target_r - 1e-4:
                continue

            # Fill price with entry slippage
            fill_entry = raw_entry * (1.0 + direction * slip_frac)
            current_sl = initial_sl
            target_px = raw_target

            # Walk forward bar-by-bar
            exit_bar = min(n - 1, entry_bar + self.max_holding_bars)
            exit_px = None
            exit_reason = "TIME_EXIT"
            mfe_r = 0.0
            mae_r = 0.0

            for j in range(entry_bar, exit_bar + 1):
                hi = float(ltf_highs[j])
                lo = float(ltf_lows[j])
                ts_j = int(ltf_timestamps[j])

                # Update MTF Trailing SL if available
                if mtf_trailing_levels and ts_j in mtf_trailing_levels:
                    trail_lvl = mtf_trailing_levels[ts_j]
                    if direction == 1 and trail_lvl > current_sl:
                        current_sl = trail_lvl
                    elif direction == -1 and trail_lvl < current_sl:
                        current_sl = trail_lvl

                if direction == 1:
                    mfe_r = max(mfe_r, (hi - fill_entry) / risk_dist)
                    mae_r = max(mae_r, (fill_entry - lo) / risk_dist)

                    # Adverse-first collision rule: check SL before TP
                    if lo <= current_sl:
                        exit_px = current_sl
                        exit_reason = "LTF_SL" if current_sl == initial_sl else "MTF_TRAIL"
                        exit_bar = j
                        break
                    if hi >= target_px:
                        exit_px = target_px
                        exit_reason = "HTF_TP"
                        exit_bar = j
                        break

                elif direction == -1:
                    mfe_r = max(mfe_r, (fill_entry - lo) / risk_dist)
                    mae_r = max(mae_r, (hi - fill_entry) / risk_dist)

                    if hi >= current_sl:
                        exit_px = current_sl
                        exit_reason = "LTF_SL" if current_sl == initial_sl else "MTF_TRAIL"
                        exit_bar = j
                        break
                    if lo <= target_px:
                        exit_px = target_px
                        exit_reason = "HTF_TP"
                        exit_bar = j
                        break

            if exit_px is None:
                exit_px = float(ltf_closes[exit_bar])
                exit_reason = "TIME_EXIT"

            # Apply exit slippage
            fill_exit = exit_px * (1.0 - direction * slip_frac)
            gross_pnl_bps = (fill_exit - fill_entry) / fill_entry * 1e4 * direction
            net_pnl_bps = gross_pnl_bps - rt_fee_bps
            # Convert net P&L into units of planned R
            realized_r = (net_pnl_bps / 1e4 * fill_entry) / risk_dist

            trades.append(
                TradeRecord(
                    symbol=symbol,
                    stream_id=stream_id,
                    direction=direction,
                    entry_ts=int(ltf_timestamps[entry_bar]),
                    exit_ts=int(ltf_timestamps[exit_bar]),
                    entry_px=round(fill_entry, 4),
                    exit_px=round(fill_exit, 4),
                    initial_sl=round(initial_sl, 4),
                    target_px=round(target_px, 4),
                    initial_risk_dist=round(risk_dist, 4),
                    target_r=round(target_r, 2),
                    realized_r=round(realized_r, 4),
                    exit_reason=exit_reason,
                    bars_held=int(exit_bar - entry_bar),
                    fee_bps=rt_fee_bps,
                    slippage_bps=self.slippage_bps * 2.0,
                    mfe_r=round(mfe_r, 2),
                    mae_r=round(mae_r, 2),
                    meta=cand.get("meta", {}) if isinstance(cand, dict) else getattr(cand, "meta", {}),
                )
            )
            busy_until = exit_bar

        # Compute stream metrics
        return self._compute_metrics(stream_id, symbol, timeframe_set, hypothesis, trades)

    def _compute_metrics(
        self, stream_id: str, symbol: str, timeframe_set: str, hypothesis: str, trades: List[TradeRecord]
    ) -> StreamMetrics:
        n = len(trades)
        if n == 0:
            return StreamMetrics(
                stream_id=stream_id, symbol=symbol, timeframe_set=timeframe_set, hypothesis=hypothesis
            )

        rs = np.array([t.realized_r for t in trades], dtype=float)
        wins = rs[rs > 0]
        losses = rs[rs < 0]
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / n
        loss_rate = loss_count / n
        total_r = float(np.sum(rs))
        exp_r = float(np.mean(rs))

        gross_win = float(np.sum(wins)) if win_count > 0 else 0.0
        gross_loss = abs(float(np.sum(losses))) if loss_count > 0 else 0.0
        pf = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)

        cum_r = np.cumsum(rs)
        peak = np.maximum.accumulate(cum_r)
        max_dd = float(np.max(peak - cum_r)) if len(cum_r) else 0.0

        target_4r_hits = sum(1 for t in trades if t.exit_reason == "HTF_TP" and t.realized_r >= 3.8)
        target_4r_hit_rate = target_4r_hits / n

        bars = [t.bars_held for t in trades]
        avg_bars = float(np.mean(bars)) if len(bars) else 0.0

        # Frequency estimate (assuming 1 year ~ 365 days)
        span_days = max(1, (trades[-1].exit_ts - trades[0].entry_ts) / 86400) if n > 1 else 30
        freq_per_month = (n / span_days) * 30.0

        return StreamMetrics(
            stream_id=stream_id,
            symbol=symbol,
            timeframe_set=timeframe_set,
            hypothesis=hypothesis,
            total_trades=n,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=win_rate,
            loss_rate=loss_rate,
            expectancy_r=exp_r,
            total_r=total_r,
            profit_factor=min(pf, 99.0),
            max_drawdown_r=max_dd,
            average_r=exp_r,
            median_r=float(np.median(rs)),
            largest_win_r=float(np.max(rs)),
            largest_loss_r=float(np.min(rs)),
            target_4r_hit_rate=target_4r_hit_rate,
            avg_bars_held=avg_bars,
            trade_frequency_per_month=freq_per_month,
            net_pnl_pct=total_r * 1.0,  # 1% risk per 1R
            trades=trades,
        )


BacktestEngine = CausalBacktestEngine
BacktestSummary = StreamMetrics
