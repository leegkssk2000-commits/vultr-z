from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from backend.strategy25.strategy_family_indicator_search_v2 import FAMILY_MAP, variants_for, wrap_strategy


ROOT = Path(__file__).resolve().parents[2]
PARENT_PATH = ROOT / "backend/tools/r7a4d_strategy_family_indicator_lab.py"
SHORTLIST = (
    "trend_ma_macd",
    "obv_trend",
    "anchor_vwap_trend",
    "vwap_revert",
    "grid_rebalance",
    "squeeze_break",
    "turtle_trend",
    "pivot_reversal",
    "fvg_revert",
    "vol_spike_fade",
    "session_bias",
    "scalp_snap",
    "alpha_combo",
)


def _load_parent() -> Any:
    name = "r7a4d_strategy_family_indicator_lab_parent_v4"
    spec = importlib.util.spec_from_file_location(name, PARENT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("PARENT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


def _robust_dev_score(windows: list[Mapping[str, Any]]) -> float:
    trades = sum(int(row["stats"].get("trade_count") or 0) for row in windows)
    if trades <= 0:
        return -1e9
    net_values = [_number(row["stats"].get("net_return_pct_sum"), -1000.0) for row in windows]
    pf_values = [min(max(_number(row["stats"].get("net_profit_factor"), 0.0), 0.0), 3.0) for row in windows]
    payoff_values = [min(max(_number(row["stats"].get("payoff_ratio"), 0.0), 0.0), 5.0) for row in windows]
    minimum_net = min(net_values)
    positive_windows = sum(value > 0.0 for value in net_values)
    positive_symbol_sum = sum(int(row["positive_symbols"]) for row in windows)
    trade_penalty = max(18 - trades, 0) * 8.0
    zero_window_penalty = sum(int(row["stats"].get("trade_count") or 0) == 0 for row in windows) * 12.0
    return (
        sum(net_values) * 6.0
        + minimum_net * 4.0
        + (min(pf_values) - 1.0) * 8.0
        + (sum(pf_values) / len(pf_values) - 1.0) * 5.0
        + (sum(payoff_values) / len(payoff_values) - 1.0) * 1.5
        + positive_windows * 3.0
        + positive_symbol_sum * 0.5
        + math.log1p(trades)
        - trade_penalty
        - zero_window_penalty
    )


def main() -> int:
    parent = _load_parent()
    parent.FAMILY_MAP = FAMILY_MAP
    parent.FAMILIES = tuple(sorted(set(FAMILY_MAP.values())))
    parent.EXPECTED_IDS = SHORTLIST
    parent.variants_for = variants_for
    parent.wrap_strategy = wrap_strategy
    parent._dev_score = _robust_dev_score
    return int(parent.main())


if __name__ == "__main__":
    raise SystemExit(main())
