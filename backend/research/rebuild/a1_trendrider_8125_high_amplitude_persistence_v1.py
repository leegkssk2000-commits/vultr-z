#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as diag
from backend.research.rebuild import a1_trend_rider_wr80_winner_restore_attribution_v1 as first
from backend.research.rebuild import a1_top5_additive_entry_union_v1 as add

ROOT = Path(__file__).resolve().parents[3]
PARENT_META = ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_exact_parent_v1.json"
SCHEMA = "zel.a1.trendrider.8125.high_amplitude_persistence.v1"
FROZEN_PREFIX = 24
BROAD_T = 30
HIGH_AMPLITUDE_BPS = 1820.358210683229


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def payoff(trades: list[Mapping[str, Any]]) -> float | None:
    vals = [float(x["net_bps"]) for x in trades]
    wins = [x for x in vals if x > 0.0]
    losses = [-x for x in vals if x < 0.0]
    if not wins or not losses:
        return None
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def key(t: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return str(t["symbol"]), int(t["signal_ts"]), int(t["entry_ts"]), str(t["side"])


def side_progress_3(trade: Mapping[str, Any], bars: list[dict[str, Any]]) -> bool:
    idx = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
    i = idx.get(int(trade["signal_ts"]))
    if i is None or i < 3:
        raise RuntimeError(f"PROGRESS3_SIGNAL_BAR_MISSING:{trade['symbol']}:{trade['signal_ts']}")
    closes = [float(bars[j]["close"]) for j in range(i - 3, i + 1)]
    deltas = [closes[j] - closes[j - 1] for j in range(1, len(closes))]
    if str(trade["side"]) == "long":
        return all(x > 0.0 for x in deltas)
    if str(trade["side"]) == "short":
        return all(x < 0.0 for x in deltas)
    raise RuntimeError(f"UNKNOWN_SIDE:{trade['side']}")


def fetch_map(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        symbol: [dict(x) for x in ev.fetch_bars(symbol, "1h", 1000)]
        for symbol in sorted({str(x["symbol"]) for x in rows})
    }


def reconstruct_primary() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="trend8125_amp_") as td:
        receipt = diag._run_receipt("trend_rider", Path(td) / "trend.json")
    rows = [dict(x) for x in (receipt.get("trades") or [])]
    rows.sort(key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))
    if len(rows) < FROZEN_PREFIX:
        raise RuntimeError(f"FROZEN_24_UNAVAILABLE:{len(rows)}")
    rows = rows[:FROZEN_PREFIX]
    first._enrich(receipt, rows)
    if any(bool(x.get("feature_missing")) for x in rows):
        raise RuntimeError("PRIMARY_FEATURE_MISSING")
    base = [x for x in rows if x["session"] != "US" or x["chase_state"] == "COOLING_OR_FLAT"]
    remaining = [x for x in rows if x["session"] == "US" and x["chase_state"] != "COOLING_OR_FLAT"]
    return base, remaining, receipt


def verify_parent(base: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    meta = read(PARENT_META)
    expected = meta.get("metrics") or {}
    m = add.metrics(base)
    checks = {
        "T": int(m["trades"]) == int(expected["completed_trades"]),
        "WR": abs(float(m["win_rate"]) - float(expected["win_rate"])) <= 1e-12,
        "PnL": abs(float(m["net_pnl_bps"]) - float(expected["net_pnl_bps"])) <= 0.05,
        "Exp": abs(float(m["net_expectancy_bps"]) - float(expected["net_expectancy_bps"])) <= 0.01,
        "PF": abs(float(m["profit_factor"]) - float(expected["profit_factor"])) <= 0.05,
        "DD": abs(float(m["drawdown_bps"]) - float(expected["max_drawdown_bps"])) <= 0.05,
        "Payoff": abs(float(payoff(base) or 0.0) - float(expected["payoff"])) <= 0.05,
    }
    if not all(checks.values()):
        raise RuntimeError("PRIMARY_8125_ECONOMIC_AUTHORITY_MISMATCH:" + json.dumps({"checks": checks, "actual": m, "expected": expected}, sort_keys=True))
    return m, expected


def verify_broad(broad: dict[str, Any]) -> list[dict[str, Any]]:
    if broad.get("strategy_id") != "trend_rider" or int(broad.get("completed_trades") or -1) != BROAD_T:
        raise RuntimeError("BROAD_70_SOURCE_ID_OR_COUNT_MISMATCH")
    metrics = broad.get("metrics") or {}
    expected = {
        "win_rate": 0.7,
        "net_pnl_bps": 34960.57723836853,
        "net_expectancy_bps": 1165.3525746122843,
        "max_drawdown_bps": 413.7929696059291,
        "net_profit_factor": 60.814848013018874,
        "net_payoff": 26.063506291293802,
    }
    for k, v in expected.items():
        if abs(float(metrics.get(k)) - v) > 1e-8 * max(1.0, abs(v)):
            raise RuntimeError(f"BROAD_70_METRIC_MISMATCH:{k}:{metrics.get(k)}:{v}")
    rows = [dict(x) for x in broad.get("trades") or []]
    if len(rows) != BROAD_T:
        raise RuntimeError("BROAD_70_TRADE_PAYLOAD_COUNT_MISMATCH")
    return rows


def donor_summary(rows: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, Any]:
    high_all = [x for x in rows if float(x["net_bps"]) >= HIGH_AMPLITUDE_BPS]
    high_sel = [x for x in selected if float(x["net_bps"]) >= HIGH_AMPLITUDE_BPS]
    wins = [x for x in selected if float(x["net_bps"]) > 0.0]
    return {
        "broad_T": len(rows),
        "selected_T": len(selected),
        "selected_WR": len(wins) / len(selected) if selected else None,
        "selected_expectancy_bps": sum(float(x["net_bps"]) for x in selected) / len(selected) if selected else None,
        "selected_payoff": payoff(selected),
        "high_amplitude_definition_bps": HIGH_AMPLITUDE_BPS,
        "high_amplitude_all_T": len(high_all),
        "high_amplitude_selected_T": len(high_sel),
        "high_amplitude_recall": len(high_sel) / len(high_all) if high_all else None,
        "high_amplitude_precision": len(high_sel) / len(selected) if selected else None,
    }


def run(broad_path: Path, out: Path) -> dict[str, Any]:
    base, remaining, _ = reconstruct_primary()
    parent_actual, parent_expected = verify_parent(base)
    broad_rows = verify_broad(read(broad_path))

    all_rows = base + remaining + broad_rows
    bars = fetch_map(all_rows)
    broad_selected = [x for x in broad_rows if side_progress_3(x, bars[str(x["symbol"])])]
    remaining_selected = [x for x in remaining if side_progress_3(x, bars[str(x["symbol"])])]

    parent_receipt = {"strategy_id": "trend_rider", "trades": base}
    lane_receipt = {"strategy_id": "trend_rider", "trades": remaining_selected}
    additive = add.evaluate(parent_receipt, lane_receipt)
    combined = base + remaining_selected
    p_payoff = payoff(base)
    c_payoff = payoff(combined)
    payoff_non_decrease = c_payoff is not None and p_payoff is not None and c_payoff >= p_payoff
    strict_all_metric = additive["state"] == "PASS_ADD_ONLY_ENTRY_LANE" and payoff_non_decrease

    remaining_compact = [{
        "symbol": x["symbol"], "side": x["side"], "signal_ts": x["signal_ts"],
        "net_bps": x["net_bps"], "selected_progress3": side_progress_3(x, bars[str(x["symbol"])])
    } for x in remaining]

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_HISTORICAL_HIGH_AMPLITUDE_ADD_ONLY_DISCOVERY" if strict_all_metric else "HOLD_HISTORICAL_HIGH_AMPLITUDE_ADD_ONLY_DISCOVERY",
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_primary_wr8125",
        "changed_axis": "PREENTRY_3BAR_DIRECTIONAL_PERSISTENCE",
        "changed_axis_count": 1,
        "predicate": "last_3_signal_bar_close_deltas_all_with_trade_side",
        "numeric_threshold_sweep": False,
        "outcome_blind_at_application": True,
        "prior_failed_axes_excluded": [
            "ema_slope_state", "ema_spread_state", "body_state", "range_state", "volume_state",
            "directional_progress_state", "directional_impulse_state", "atr_accel_state", "side_close_location",
        ],
        "primary_parent_metrics": parent_actual,
        "primary_parent_payoff": p_payoff,
        "primary_expected_metrics": parent_expected,
        "remaining_us_T": len(remaining),
        "remaining_us_selected_T": len(remaining_selected),
        "remaining_us_attribution": remaining_compact,
        "additive_receipt": additive,
        "combined_payoff": c_payoff,
        "payoff_non_decrease": payoff_non_decrease,
        "strict_all_metric_pass": strict_all_metric,
        "broad70_donor_control": donor_summary(broad_rows, broad_selected),
        "broad70_source_receipt_sha256": read(broad_path).get("receipt_sha256"),
        "historical_discovery_promotable": False,
        "fresh_prospective_confirmation_required": True,
        "next": "FREEZE_DISCOVERY_AND_REQUIRE_FRESH_PROSPECTIVE" if strict_all_metric else "TERMINALIZE_PROGRESS3_AND_TRY_NEXT_SINGLE_CAUSAL_AXIS",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert HIGH_AMPLITUDE_BPS > 1800.0
    assert BROAD_T == 30 and FROZEN_PREFIX == 24
    print("PASS_A1_TRENDRIDER_8125_HIGH_AMPLITUDE_PERSISTENCE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broad-source", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_8125_high_amplitude_persistence_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.broad_source is None:
        raise RuntimeError("--broad-source required")
    r = run(args.broad_source, args.out)
    print("A1_TRENDRIDER_8125_HIGH_AMPLITUDE=" + json.dumps({
        "state": r["state"],
        "remaining_us_selected_T": r["remaining_us_selected_T"],
        "combined_metrics": r["additive_receipt"]["combined_metrics"],
        "combined_payoff": r["combined_payoff"],
        "strict_all_metric_pass": r["strict_all_metric_pass"],
        "broad70_donor_control": r["broad70_donor_control"],
        "next": r["next"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
