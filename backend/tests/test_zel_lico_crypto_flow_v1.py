from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "zel_lico_crypto_flow_v1.py"
SPEC = importlib.util.spec_from_file_location("zel_lico_crypto_flow_v1", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("LICO_CRYPTO_IMPORT_FAILED")
flow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flow)


def contract_fixture() -> dict:
    return {
        "source": {"symbols": ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT"]},
        "research_thresholds": {
            "risk_off_btc_4h_lte_pct": -2.0,
            "risk_off_breadth_lte": 0.2,
            "risk_on_btc_4h_gte_pct": 2.0,
            "risk_on_breadth_gte": 0.8,
            "rotation_alt_relative_24h_gte_pct": 2.0,
            "rotation_breadth_gte": 0.6,
            "crowded_long_funding_median_gte_pct": 0.03,
            "crowded_short_funding_median_lte_pct": -0.03,
            "maximum_snapshot_age_ms": 7_200_000,
        },
        "candidate_filters": [
            {"config_id": "BLOCK_LONG_RISK_OFF", "description": "x"},
            {"config_id": "BLOCK_SHORT_RISK_ON", "description": "x"},
            {"config_id": "BLOCK_CROWDED_SAME_SIDE", "description": "x"},
            {"config_id": "BLOCK_DIRECTIONAL_CONFLICT", "description": "x"},
        ],
        "evaluation": {
            "minimum_retention_pct": 60.0,
            "minimum_confirmation_trade_count": 3,
            "net_R_gt": 0.0,
            "profit_factor_gte": 1.0,
            "expectancy_R_gt": 0.0,
            "payoff_ratio_gte": 1.0,
        },
    }


def main() -> int:
    contract = contract_fixture()
    symbols = contract["source"]["symbols"]
    market: dict[str, list[dict]] = {}
    for symbol in symbols:
        rows = []
        price = 100.0
        for hour in range(90):
            if hour >= 40:
                price *= 0.992 if symbol == "BTC-USDT" else 0.996
            rows.append({"timestamp_ms": hour * flow.INTERVAL_MS, "close": price, "volume": 1.0})
        market[symbol] = rows
    snapshots = flow.build_snapshots(market, {symbol: [] for symbol in symbols}, contract)
    assert snapshots and snapshots[-1]["state"] == "RISK_OFF", snapshots[-1]

    trades: list[dict] = []
    for window_index, window in enumerate(("W1", "W2", "W3")):
        for index in range(5):
            trades.append({
                "identity": f"{window}-{index}",
                "strategy_id": "fixture",
                "symbol": "BTC-USDT",
                "entry_ms": (48 + window_index * 10 + index) * flow.INTERVAL_MS + 1,
                "side": "long" if index < 2 else "short",
                "window": window,
                "r": -1.0 if index < 2 else 1.0,
            })
    bound, binding = flow.bind_trades(trades, snapshots, contract)
    assert binding["binding_coverage_pct"] == 100.0, binding
    assert binding["future_snapshot_leak_count"] == 0, binding
    result = flow.evaluate(bound, contract)
    assert result["selected_config_id"] in {"BLOCK_LONG_RISK_OFF", "BLOCK_DIRECTIONAL_CONFLICT"}, result
    assert result["selected_frozen_w2_w3"] is True, result
    assert result["survivor"] is True, result
    assert flow.normalize_side("BUY") == "long"
    assert flow.normalize_window("1m_w3") == "W3"
    assert flow.parse_timestamp_ms("2026-01-01T00:00:00Z") > 0
    print(json.dumps({"state": "PASS_LICO_CRYPTO_FLOW_TEST", "version": flow.VERSION}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
