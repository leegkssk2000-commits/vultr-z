"""Costed used-DEV comparison for one frozen Squeeze regime-overlay axis.

The parent stays immutable. The child changes only the allowed regime set from
PANIC_DISPERSION to PANIC_DISPERSION plus TREND_DISPERSED while keeping the
core squeeze/momentum/MA, next-open fill, cost gate, stop, exit and occupancy
callbacks unchanged. Inputs are the already-used 245-day DEV source.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_metrics_v2 as metrics
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from backend.research.rebuild import scalp7_rolling_context_v2 as context
from backend.research.rebuild import scalp7_source_data_v2 as source
from ops import scalp7_dual_native_funnel_v1 as common


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / (
    "research/campaigns/scalp7_20261012/dual_frequency_v1/"
    "SQUEEZE_TREND_DISPERSED_OVERLAY_CHILD_V1.json"
)
CHILD = "scalp7_squeeze_panic_plus_trend_disperse_utc30m_v1"
ALLOWED_REGIMES = {"PANIC_DISPERSION", "TREND_DISPERSED"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _window_for(
    windows: list[dict[str, Any]], stamp: int
) -> dict[str, Any] | None:
    return next(
        (
            window
            for window in windows
            if int(window["start_ms"]) <= stamp < int(window["end_ms"])
        ),
        None,
    )


def _source_condition(row: Mapping[str, Any], previous: Mapping[str, Any]) -> bool:
    return (
        math.isfinite(float(row["momentum"]))
        and float(row["momentum"]) > 0
        and float(row["momentum"]) > float(previous["momentum"])
        and float(row["close"]) > float(row["g34"])
        and float(row["g8"]) > float(row["g21"]) > float(row["g34"])
    )


def _squeeze_parent_signal(
    symbol: str,
    row: Mapping[str, Any],
    regime: str,
    regime_available: int,
    cost: float,
) -> dict[str, Any]:
    stamp = max(int(row["feature_available_ts_ms"]), int(regime_available))
    return {
        "symbol": symbol,
        "timeframe_min": positive.TIMEFRAME_MIN,
        "signal_open_ts_ms": int(row["open_ts_ms"]),
        "signal_ts_ms": stamp,
        "segment_id": row["segment_id"],
        "take_profit_r": None,
        # The common callbacks must see the parent identity. Output rows are
        # relabelled only after execution as the separate frozen child.
        "identity": positive.SQUEEZE_PARENT,
        "lane": "squeeze_break",
        "side": 1,
        "stop_price": float(row["g21"]) - 2.0 * float(row["atr20"]),
        "max_hold_bars": 11,
        "exit_policy": "SQUEEZE_TWO_WEAK_MOMENTUM",
        "meta": {
            "spec_sha256": positive.SPEC_SHA256,
            "regime": regime,
            "feature_available_ts_ms": stamp,
            "frozen_cost_bps": float(cost),
            "historical_parity_claim": False,
            "atr_price": float(row["atr20"]),
            "entry_cost_gate": {
                "atr_price": float(row["atr20"]),
                "min_ratio": 4.0,
            },
            "fallback_stop_atr_mult": 2.0,
            "be_arm_r": None,
            "event_trace": [
                "BB_KC_FIRST_FIRE",
                "MOMENTUM_ACCEL",
                "STACKED_MA",
                "REGIME_OVERLAY_CHILD:" + regime,
            ],
        },
    }


def _added_trend_disperse_signals(
    frames: Mapping[str, Any],
    costs: Mapping[str, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    added: list[dict[str, Any]] = []
    source_by_regime: Counter[str] = Counter()
    rolling_source_by_regime: Counter[str] = Counter()
    for symbol, frame in sorted(frames.items()):
        cost = float(costs.get(symbol, float("nan")))
        if not math.isfinite(cost) or cost <= 0:
            raise ValueError("SQUEEZE_CHILD_COST_UNBOUND:" + symbol)
        for segment in positive.enriched_segments(frame):
            rows = segment.to_dict("records")
            for i in range(1, len(rows)):
                row, previous = rows[i], rows[i - 1]
                first_fire = (
                    i >= 80
                    and bool(previous["squeeze_on"])
                    and not bool(row["squeeze_on"])
                )
                if not first_fire or not _source_condition(row, previous):
                    continue
                regime, regime_available = positive._regime(row, None)
                stamp = max(
                    int(row["feature_available_ts_ms"]), int(regime_available)
                )
                source_by_regime[str(regime)] += 1
                if common.START <= stamp < common.END:
                    rolling_source_by_regime[str(regime)] += 1
                if regime != "TREND_DISPERSED":
                    continue
                added.append(
                    _squeeze_parent_signal(
                        symbol,
                        row,
                        str(regime),
                        int(regime_available),
                        cost,
                    )
                )
    added.sort(
        key=lambda row: (
            int(row["signal_ts_ms"]),
            str(row["symbol"]),
            str(row["identity"]),
        )
    )
    return added, {
        "source_conditioned_by_regime_all_partitions": dict(
            sorted(source_by_regime.items())
        ),
        "source_conditioned_by_regime_rolling": dict(
            sorted(rolling_source_by_regime.items())
        ),
    }


def _relabel(value: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(value))
    out["identity"] = CHILD
    signal = out.get("signal")
    if isinstance(signal, dict):
        signal["identity"] = CHILD
        signal.setdefault("meta", {})["lifecycle_adapter_parent_identity"] = (
            positive.SQUEEZE_PARENT
        )
    position = out.get("position")
    if isinstance(position, dict) and isinstance(position.get("signal"), dict):
        position["signal"]["identity"] = CHILD
        position["signal"].setdefault("meta", {})[
            "lifecycle_adapter_parent_identity"
        ] = positive.SQUEEZE_PARENT
    return out


def _run_child(
    frames: Mapping[str, Any],
    costs: Mapping[str, float],
    windows: list[dict[str, Any]],
    parent_signals: list[dict[str, Any]],
    added_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    combined = sorted(
        [*parent_signals, *added_signals],
        key=lambda row: (
            int(row["signal_ts_ms"]),
            str(row["symbol"]),
            str(row["identity"]),
        ),
    )
    keys = [
        (
            str(row["symbol"]),
            int(row["signal_ts_ms"]),
            int(row["signal_open_ts_ms"]),
        )
        for row in combined
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("SQUEEZE_CHILD_DUPLICATE_SIGNAL")
    raw_rows, raw_unresolved, rejections, accepted_entry_ts = common._replay_parent(
        positive.SQUEEZE_PARENT,
        dict(frames),
        costs,
        windows,
        combined,
    )
    by_label = {str(window["label"]): window for window in windows}
    trades: list[dict[str, Any]] = []
    boundary_excluded: list[dict[str, Any]] = []
    for raw in raw_rows:
        row = _relabel(raw)
        end = int(by_label[str(row["window_label"])]["end_ms"])
        if int(row["outcome_available_ts_ms"]) >= end:
            row["boundary_exclusion_reason"] = (
                "OUTCOME_AT_OR_AFTER_WINDOW_END_UNAVAILABLE"
            )
            row["window_end_ms"] = end
            boundary_excluded.append(row)
        else:
            trades.append(row)
    unresolved: list[dict[str, Any]] = []
    for raw in raw_unresolved:
        row = _relabel(raw)
        window = by_label[str(row["window_label"])]
        row["partition"] = str(window["partition"])
        unresolved.append(row)
    for row in boundary_excluded:
        if "partition" not in row:
            row["partition"] = str(by_label[str(row["window_label"])]["partition"])
    trades.sort(
        key=lambda row: (
            int(row["outcome_available_ts_ms"]),
            str(row["identity"]),
            str(row["symbol"]),
        )
    )
    return {
        "signals": combined,
        "trades": trades,
        "unresolved": unresolved,
        "boundary_excluded": boundary_excluded,
        "rolling_rejections": dict(sorted(rejections.items())),
        "accepted_entry_ts": accepted_entry_ts,
    }


def _partition_signal_count(
    signals: list[dict[str, Any]], windows: list[dict[str, Any]]
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for signal in signals:
        window = _window_for(windows, int(signal["signal_ts_ms"]))
        if window is not None:
            counts[str(window["partition"])] += 1
    return dict(sorted(counts.items()))


def _partition_result(
    result: Mapping[str, Any],
    windows: list[dict[str, Any]],
) -> dict[str, Any]:
    signal_count = _partition_signal_count(list(result["signals"]), windows)
    return {
        name: {
            "signal_count": int(signal_count.get(name, 0)),
            "completed_trade_count": sum(
                row.get("partition") == name for row in result["trades"]
            ),
            "unresolved_count": sum(
                row.get("partition") == name for row in result["unresolved"]
            ),
            "boundary_excluded_count": sum(
                row.get("partition") == name
                for row in result["boundary_excluded"]
            ),
        }
        for name in ("validation", "rolling")
    }


def run(source_root: Path, output: Path) -> dict[str, Any]:
    contract = json.loads(
        (common.REPORT / "CAMPAIGN_PREREGISTERED_V2.json").read_text()
    )
    child_contract = json.loads(CONTRACT.read_text())
    if child_contract["child_identity"] != CHILD:
        raise ValueError("SQUEEZE_CHILD_CONTRACT_IDENTITY_MISMATCH")
    if set(child_contract["child_allowed_regimes"]) != ALLOWED_REGIMES:
        raise ValueError("SQUEEZE_CHILD_ALLOWED_REGIME_DRIFT")
    windows = contract["windows"]
    frames = source.load_candles(source_root, 30, cache_dir=None)
    expected_symbols = {
        "BTC-USDT",
        "DOGE-USDT",
        "ETH-USDT",
        "LINK-USDT",
        "SOL-USDT",
        "XRP-USDT",
    }
    if set(frames) != expected_symbols:
        raise ValueError("SOURCE_COHORT_DRIFT")
    if {frame.attrs["source_inventory_sha256"] for frame in frames.values()} != {
        common.EXPECTED_INVENTORY
    }:
        raise ValueError("SOURCE_INVENTORY_SHA_MISMATCH")
    features = context.cross_features(frames)
    bound, fits = context.bind_context(frames, features, windows)
    costs = json.loads(common.COST_PATH.read_text())["costs_bps"]

    parent_path, saved = common._load_saved(positive.SQUEEZE_PARENT)
    parent_signals = positive.generate_signals(
        bound,
        costs=costs,
        identities=(positive.SQUEEZE_PARENT,),
    )
    parent_rows, parent_unresolved, parent_rejections, _ = common._replay_parent(
        positive.SQUEEZE_PARENT,
        bound,
        costs,
        windows,
        parent_signals,
    )
    if parent_rows != saved["trades"] or parent_unresolved != saved["unresolved"]:
        raise ValueError("EXACT_PARENT_REPLAY_PARITY_FAILED")
    parent_rolling = [
        row for row in parent_rows if row["partition"] == "rolling"
    ]
    if len(parent_rolling) != common.EXPECTED[positive.SQUEEZE_PARENT]["rolling_T"]:
        raise ValueError("ROLLING_PARENT_T_PARITY_FAILED")

    added_signals, source_census = _added_trend_disperse_signals(bound, costs)
    child = _run_child(
        bound,
        costs,
        windows,
        parent_signals,
        added_signals,
    )
    child_rolling = [
        row for row in child["trades"] if row["partition"] == "rolling"
    ]
    child_unresolved = [
        row for row in child["unresolved"] if row["partition"] == "rolling"
    ]
    child_boundary = [
        row
        for row in child["boundary_excluded"]
        if row["partition"] == "rolling"
    ]

    parent_metrics = {
        "cost1x": metrics.summarize(
            parent_rolling, common.START, common.END, 1.0
        ),
        "cost2x": metrics.summarize(
            parent_rolling, common.START, common.END, 2.0
        ),
        "daily_cost1x": common._daily_economics(parent_rolling, 1.0),
        "daily_cost2x": common._daily_economics(parent_rolling, 2.0),
    }
    child_metrics = {
        "cost1x": metrics.summarize(
            child_rolling, common.START, common.END, 1.0
        ),
        "cost2x": metrics.summarize(
            child_rolling, common.START, common.END, 2.0
        ),
        "daily_cost1x": common._daily_economics(child_rolling, 1.0),
        "daily_cost2x": common._daily_economics(child_rolling, 2.0),
    }
    opportunity = common._opportunity_comparison(
        parent_rolling,
        child_rolling,
    )
    report: dict[str, Any] = {
        "schema": "zel.scalp7.squeeze_regime_overlay_child.v1",
        "state": "USED_DEV_COSTED_SINGLE_AXIS_RESULT_NOT_FRESH_NOT_SURVIVOR",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_identity": positive.SQUEEZE_PARENT,
        "child_identity": CHILD,
        "single_axis": (
            "allowed regime overlay PANIC_DISPERSION only to "
            "PANIC_DISPERSION plus TREND_DISPERSED"
        ),
        "unchanged": [
            "30m core squeeze on-to-off first fire",
            "positive accelerating momentum",
            "close above g34 and g8>g21>g34",
            "causal regime availability clock",
            "next-open fill and gap handling",
            "ATR20 cost gate min_ratio 4.0",
            "g21 minus 2*ATR20 stop",
            "11-bar hold and two-weak-momentum exit",
            "symbol occupancy and duplicate handling",
            "cost snapshot and 245-day source",
        ],
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": _sha(CONTRACT),
        "source_inventory_sha256": common.EXPECTED_INVENTORY,
        "parent_ledger_path": str(parent_path.relative_to(ROOT)),
        "parent_ledger_sha256": common.EXPECTED[
            positive.SQUEEZE_PARENT
        ]["ledger_sha256"],
        "window": {
            "start_ms": common.START,
            "end_exclusive_ms": common.END,
            "calendar_days": 245,
            "timeframe_min": 30,
        },
        "context_fit_sha256": hashlib.sha256(
            json.dumps(fits, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "parent_exact_signal_trade_unresolved_pnl_parity": True,
        "source_census": source_census,
        "parent_signal_count_by_partition": _partition_signal_count(
            parent_signals, windows
        ),
        "added_trend_disperse_signal_count_by_partition": (
            _partition_signal_count(added_signals, windows)
        ),
        "child_partition_census": _partition_result(child, windows),
        "parent_rolling_rejections": dict(sorted(parent_rejections.items())),
        "child_rolling_rejections": child["rolling_rejections"],
        "parent": parent_metrics,
        "child": child_metrics,
        "opportunity_comparison": opportunity,
        "trade_rows": child_rolling,
        "unresolved": child_unresolved,
        "boundary_excluded": child_boundary,
        "used_dev_only": True,
        "fresh_or_oos": False,
        "economic_runs": 1,
        "promotion": False,
        "survivor_count_delta": 0,
        "account_nav_or_mtm": None,
        "market_requests": 0,
        "raw_price_bodies_exported": False,
        "order_live_paper_deploy": "BLOCKED_UNSURE_HOLD",
    }
    unsigned = (
        json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()
    report["receipt_sha256"] = hashlib.sha256(unsigned).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.source_root, args.output)
    print("SQUEEZE_REGIME_OVERLAY_RECEIPT=" + result["receipt_sha256"])
    print(
        "SQUEEZE_REGIME_OVERLAY_COUNTS="
        + json.dumps(
            {
                "parent_T": result["parent"]["cost1x"]["T"],
                "child_T": result["child"]["cost1x"]["T"],
                "added": result["opportunity_comparison"]["added_T"],
                "removed": result["opportunity_comparison"]["removed_T"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
