from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import zel_exact25_selected_indicator_screen_v1 as screen

VERSION = "ZEL_EXACT25_SELECTED_INDICATOR_SCREEN_FAST_V1"
MIN_NET_R = 0.0
MIN_PROFIT_FACTOR = 1.0
MIN_EXPECTANCY_R = 0.0
MIN_PAYOFF_RATIO = 1.0


def link_source_read_only(source_root: Path, destination: Path) -> None:
    """Expose immutable sources without copying runtime/data/backups."""
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"SOURCE_LINK_DESTINATION_ALREADY_EXISTS:{destination}")
    os.symlink(source_root.resolve(), destination, target_is_directory=True)


def payoff_fields(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    values: list[float] = []
    for row in rows:
        raw = row.get("realized_R_including_funding_estimate")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss_abs = abs(sum(losses) / len(losses)) if losses else 0.0
    if average_loss_abs == 0.0:
        payoff = 999.0 if average_win > 0.0 else 0.0
    else:
        payoff = average_win / average_loss_abs
    return {
        "average_win_R": average_win,
        "average_loss_abs_R": average_loss_abs,
        "payoff_ratio": payoff,
    }


def metrics_by_window_with_payoff(engine: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for window in ("1m_w1", "1m_w2", "1m_w3"):
        window_rows = [row for row in rows if str(row.get("window_id")) == window]
        metrics = dict(engine.metrics(window_rows, "realized_R_including_funding_estimate"))
        metrics.update(payoff_fields(window_rows))
        result[window] = metrics
    all_metrics = dict(engine.metrics(rows, "realized_R_including_funding_estimate"))
    all_metrics.update(payoff_fields(rows))
    result["all"] = all_metrics
    return result


def window_pass_with_payoff(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    minimum_retention: float,
    minimum_count: int,
) -> tuple[bool, dict[str, Any], list[str]]:
    _, delta, blockers = screen.window_pass(
        base, candidate, minimum_retention, minimum_count
    )
    delta = dict(delta)
    blockers = list(blockers)
    candidate_net = float(candidate.get("net_R") or 0.0)
    candidate_pf = float(candidate.get("profit_factor") or 0.0)
    candidate_expectancy = float(candidate.get("expectancy_R") or 0.0)
    candidate_payoff = float(candidate.get("payoff_ratio") or 0.0)
    delta["delta_payoff_ratio"] = candidate_payoff - float(base.get("payoff_ratio") or 0.0)
    delta["delta_expectancy_R"] = candidate_expectancy - float(base.get("expectancy_R") or 0.0)
    delta["absolute_candidate_net_R"] = candidate_net
    delta["absolute_candidate_profit_factor"] = candidate_pf
    delta["absolute_candidate_expectancy_R"] = candidate_expectancy
    delta["absolute_candidate_payoff_ratio"] = candidate_payoff
    if delta["delta_payoff_ratio"] < -1e-12:
        blockers.append("PAYOFF_RATIO_WORSE")
    if delta["delta_expectancy_R"] < -1e-12:
        blockers.append("EXPECTANCY_R_WORSE")
    if candidate_net <= MIN_NET_R:
        blockers.append("ABSOLUTE_NET_R_NOT_POSITIVE")
    if candidate_pf < MIN_PROFIT_FACTOR:
        blockers.append("ABSOLUTE_PROFIT_FACTOR_BELOW_ONE")
    if candidate_expectancy <= MIN_EXPECTANCY_R:
        blockers.append("ABSOLUTE_EXPECTANCY_NOT_POSITIVE")
    if candidate_payoff < MIN_PAYOFF_RATIO:
        blockers.append("ABSOLUTE_PAYOFF_RATIO_BELOW_ONE")
    return not blockers, delta, blockers


def self_test() -> int:
    rows = [
        {"window_id": "1m_w1", "realized_R_including_funding_estimate": 2.0},
        {"window_id": "1m_w1", "realized_R_including_funding_estimate": -1.0},
        {"window_id": "1m_w1", "realized_R_including_funding_estimate": 1.0},
    ]
    fields = payoff_fields(rows)
    assert fields["average_win_R"] == 1.5
    assert fields["average_loss_abs_R"] == 1.0
    assert fields["payoff_ratio"] == 1.5
    base = {
        "sample_count": 100,
        "net_R": -10.0,
        "profit_factor": 0.5,
        "max_drawdown_R": 20.0,
        "payoff_ratio": 1.0,
        "expectancy_R": -0.1,
    }
    still_negative = {
        "sample_count": 70,
        "net_R": -5.0,
        "profit_factor": 0.6,
        "max_drawdown_R": 12.0,
        "payoff_ratio": 1.2,
        "expectancy_R": -0.071,
    }
    passed, _, blockers = window_pass_with_payoff(base, still_negative, 60.0, 20)
    assert passed is False
    assert "ABSOLUTE_NET_R_NOT_POSITIVE" in blockers
    positive = {
        "sample_count": 70,
        "net_R": 5.0,
        "profit_factor": 1.2,
        "max_drawdown_R": 12.0,
        "payoff_ratio": 1.2,
        "expectancy_R": 0.071,
    }
    passed, delta, blockers = window_pass_with_payoff(base, positive, 60.0, 20)
    assert passed is True and not blockers
    assert delta["absolute_candidate_net_R"] > 0
    print("PASS")
    return 0


def main() -> int:
    if "--self-test-fast-wrapper" in sys.argv:
        return self_test()
    screen.copy_source = link_source_read_only
    screen.metrics_by_window = metrics_by_window_with_payoff
    screen.window_pass = window_pass_with_payoff
    return screen.main()


if __name__ == "__main__":
    raise SystemExit(main())
