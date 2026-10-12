"""Read-only native opportunity funnel for the frozen Scalp7 30m parents.

This diagnostic replays the unchanged parent implementations on the already-used
245-day DEV source.  It emits counts and hashes only; it never exports candles,
changes a strategy rule, or opens fresh/OOS evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from backend.research.rebuild import scalp7_rolling_context_v2 as context
from backend.research.rebuild import scalp7_source_data_v2 as source


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "research/campaigns/scalp7_20260915/broad_rebuild_v2"
COST_PATH = ROOT / (
    "research/campaigns/scalp7_20260915/cost_snapshot_v2/"
    "SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
)
START = 1768262400000
END = 1789430400000
DAY = 86_400_000
EXPECTED_INVENTORY = "53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2"
EXPECTED = {
    positive.KELTNER_PARENT: {
        "ledger_sha256": "8863caa8231282fbd7dfd5660811b74e007c018c9cdafdaa52c24830cddfd989",
        "rolling_T": 109,
        "lane": "KELTNER_HG_30M",
    },
    positive.SQUEEZE_PARENT: {
        "ledger_sha256": "5f1af277aefb4e0887d723ef7a59311385551abf500cd4308693f9cbf6000e52",
        "rolling_T": 25,
        "lane": "SQUEEZE_PANIC_30M",
    },
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).date().isoformat()


def _daily_summary(timestamps: list[int]) -> dict[str, Any]:
    days = [_day(START + i * DAY) for i in range((END - START) // DAY)]
    counts = Counter(_day(value) for value in timestamps if START <= value < END)
    values = [int(counts.get(day, 0)) for day in days]
    return {
        "calendar_days": len(days),
        "total": sum(values),
        "days_with_event": sum(value > 0 for value in values),
        "zero_days": sum(value == 0 for value in values),
        "mean_per_calendar_day": sum(values) / len(values),
        "median_per_calendar_day": float(np.median(values)),
        "days_ge_3": sum(value >= 3 for value in values),
        "days_ge_4": sum(value >= 4 for value in values),
        "histogram": {str(key): value for key, value in sorted(Counter(values).items())},
        "counts": dict(zip(days, values)),
    }


def _native_stage_events(
    frames: Mapping[str, pd.DataFrame], identity: str
) -> dict[str, list[dict[str, Any]]]:
    stages: dict[str, list[dict[str, Any]]] = {
        "raw_setup": [],
        "source_condition": [],
        "regime_eligible": [],
    }
    for symbol, frame in sorted(frames.items()):
        for segment in positive.enriched_segments(frame):
            rows = segment.to_dict("records")
            if identity == positive.KELTNER_PARENT:
                state = positive.HolyGrailState()
                for i in range(1, len(rows)):
                    row, previous = rows[i], rows[i - 1]
                    event = positive._hg_event(state, row, previous) if i >= 121 else None
                    if not event:
                        continue
                    stamp = int(max(row["feature_available_ts_ms"], row.get("regime_available_ts_ms", 0)))
                    record = {"symbol": symbol, "signal_ts_ms": stamp, "signal_open_ts_ms": int(row["open_ts_ms"])}
                    stages["raw_setup"].append(record)
                    stages["source_condition"].append(record)
                    regime, _ = positive._regime(row, None)
                    if regime in {"PANIC_DISPERSION", "TREND_DISPERSED"}:
                        stages["regime_eligible"].append(record)
            else:
                for i in range(1, len(rows)):
                    row, previous = rows[i], rows[i - 1]
                    first_fire = i >= 80 and bool(previous["squeeze_on"]) and not bool(row["squeeze_on"])
                    if not first_fire:
                        continue
                    stamp = int(max(row["feature_available_ts_ms"], row.get("regime_available_ts_ms", 0)))
                    record = {"symbol": symbol, "signal_ts_ms": stamp, "signal_open_ts_ms": int(row["open_ts_ms"])}
                    stages["raw_setup"].append(record)
                    conditioned = (
                        math.isfinite(float(row["momentum"]))
                        and float(row["momentum"]) > 0
                        and float(row["momentum"]) > float(previous["momentum"])
                        and float(row["close"]) > float(row["g34"])
                        and float(row["g8"]) > float(row["g21"]) > float(row["g34"])
                    )
                    if not conditioned:
                        continue
                    stages["source_condition"].append(record)
                    regime, _ = positive._regime(row, None)
                    if regime == "PANIC_DISPERSION":
                        stages["regime_eligible"].append(record)
    return stages


def _entry_gate(
    signal: Mapping[str, Any], frames: Mapping[str, pd.DataFrame]
) -> tuple[bool, int | None, str]:
    frame = frames[str(signal["symbol"])]
    hits = frame.index[frame["open_ts_ms"] == int(signal["signal_open_ts_ms"])].tolist()
    if len(hits) != 1:
        return False, None, "SIGNAL_BAR_MISSING_OR_DUPLICATE"
    i = int(hits[0])
    if i + 1 >= len(frame):
        return False, None, "NO_NEXT_BAR"
    source_bar, entry_bar = frame.iloc[i], frame.iloc[i + 1]
    if (
        source_bar["segment_id"] != entry_bar["segment_id"]
        or int(entry_bar["open_ts_ms"]) != int(source_bar["close_ts_ms"])
    ):
        return False, None, "ENTRY_GAP"
    if int(signal["signal_ts_ms"]) > int(entry_bar["open_ts_ms"]):
        return False, None, "LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL"
    result = positive.entry_admission(signal, float(entry_bar["open"]))
    return bool(result["allowed"]), int(entry_bar["open_ts_ms"]), str(result["reason"])


def _load_saved(identity: str) -> tuple[Path, dict[str, Any]]:
    path = REPORT / "results" / (identity + ".trades.json.gz")
    expected = EXPECTED[identity]["ledger_sha256"]
    if _sha(path) != expected:
        raise ValueError("PARENT_LEDGER_SHA_MISMATCH:" + identity)
    with gzip.open(path, "rt") as handle:
        return path, json.load(handle)


def _replay_parent(
    identity: str,
    frames: dict[str, pd.DataFrame],
    costs: Mapping[str, float],
    windows: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str], list[int]]:
    all_rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    accepted_entry_ts: list[int] = []
    for window in windows:
        start, end = int(window["start_ms"]), int(window["end_ms"])
        chosen = [row for row in signals if start <= int(row["signal_ts_ms"]) < end]
        prefix_start = start - 200 * 30 * 60_000
        sliced = {
            symbol: frame[(frame["open_ts_ms"] >= prefix_start) & (frame["close_ts_ms"] <= end)].reset_index(drop=True)
            for symbol, frame in frames.items()
        }
        out = execution.replay(
            chosen,
            sliced,
            costs,
            identity=identity,
            exit_update=positive.exit_update,
            entry_update=positive.entry_update,
        )
        for row in out["trades"]:
            row["window_label"] = window["label"]
            row["partition"] = window["partition"]
            accepted_entry_ts.append(int(row["entry_ts_ms"]))
        for position in out["unresolved"]:
            position["window_label"] = window["label"]
            position["window_end_ms"] = end
            accepted_entry_ts.append(int(position["entry_ts_ms"]))
        all_rows.extend(out["trades"])
        unresolved.extend(out["unresolved"])
        rejections.update(out["rejections"])
    return all_rows, unresolved, rejections, accepted_entry_ts


def run(source_root: Path, output: Path) -> dict[str, Any]:
    contract = json.loads((REPORT / "CAMPAIGN_PREREGISTERED_V2.json").read_text())
    windows = contract["windows"]
    frames = source.load_candles(source_root, 30, cache_dir=None)
    if set(frames) != {"BTC-USDT", "DOGE-USDT", "ETH-USDT", "LINK-USDT", "SOL-USDT", "XRP-USDT"}:
        raise ValueError("SOURCE_COHORT_DRIFT")
    if {frame.attrs["source_inventory_sha256"] for frame in frames.values()} != {EXPECTED_INVENTORY}:
        raise ValueError("SOURCE_INVENTORY_SHA_MISMATCH")
    features = context.cross_features(frames)
    bound, fits = context.bind_context(frames, features, windows)
    costs = json.loads(COST_PATH.read_text())["costs_bps"]
    lanes: dict[str, Any] = {}
    for identity in EXPECTED:
        saved_path, saved = _load_saved(identity)
        signals = positive.generate_signals(bound, costs=costs, identities=(identity,))
        stage_events = _native_stage_events(bound, identity)
        expected_keys = Counter(
            (row["symbol"], int(row["signal_ts_ms"]), int(row["signal_open_ts_ms"]))
            for row in stage_events["regime_eligible"]
        )
        signal_keys = Counter(
            (row["symbol"], int(row["signal_ts_ms"]), int(row["signal_open_ts_ms"]))
            for row in signals
        )
        if signal_keys != expected_keys:
            raise ValueError("NATIVE_STAGE_SIGNAL_PARITY:" + identity)
        fill_clock_ts: list[int] = []
        cost_admitted_ts: list[int] = []
        preoccupancy_rejections: Counter[str] = Counter()
        for signal in signals:
            allowed, entry_ts, reason = _entry_gate(signal, bound)
            if entry_ts is not None:
                fill_clock_ts.append(entry_ts)
            if allowed and entry_ts is not None:
                cost_admitted_ts.append(entry_ts)
            else:
                preoccupancy_rejections[reason] += 1
        rows, unresolved, rejections, accepted_entry_ts = _replay_parent(
            identity, bound, costs, windows, signals
        )
        if rows != saved["trades"] or unresolved != saved["unresolved"]:
            raise ValueError("EXACT_PARENT_REPLAY_PARITY_FAILED:" + identity)
        rolling_rows = [row for row in rows if row["partition"] == "rolling"]
        if len(rolling_rows) != EXPECTED[identity]["rolling_T"]:
            raise ValueError("ROLLING_PARENT_T_PARITY_FAILED:" + identity)
        stages = {
            name: _daily_summary([int(row["signal_ts_ms"]) for row in values])
            for name, values in stage_events.items()
        }
        stages["fill_clock_eligible"] = _daily_summary(fill_clock_ts)
        stages["cost_admitted_preoccupancy"] = _daily_summary(cost_admitted_ts)
        stages["accepted_entry"] = _daily_summary(accepted_entry_ts)
        stages["completed_trade"] = _daily_summary(
            [int(row["entry_ts_ms"]) for row in rolling_rows]
        )
        rolling_signals = [row for row in signals if START <= int(row["signal_ts_ms"]) < END]
        same_time = Counter(int(row["signal_ts_ms"]) for row in rolling_signals)
        lanes[identity] = {
            "lane": EXPECTED[identity]["lane"],
            "parent_ledger_path": str(saved_path.relative_to(ROOT)),
            "parent_ledger_sha256": EXPECTED[identity]["ledger_sha256"],
            "rolling_T_exact": len(rolling_rows),
            "exact_saved_trade_and_unresolved_parity": True,
            "stages": stages,
            "preoccupancy_rejections": dict(sorted(preoccupancy_rejections.items())),
            "execution_rejections": dict(sorted(rejections.items())),
            "same_signal_time_multi_symbol_groups": sum(value > 1 for value in same_time.values()),
            "max_same_signal_time_count": max(same_time.values(), default=0),
        }
    report = {
        "schema": "zel.scalp7.dual_native_daily_funnel.v1",
        "state": "NATIVE_DAILY_FUNNEL_COMPLETE_PARENT_PARITY_PASS",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "used_dev_only": True,
        "fresh_or_oos": False,
        "economic_improvement": False,
        "source_root": str(source_root),
        "source_inventory_sha256": EXPECTED_INVENTORY,
        "window": {"start_ms": START, "end_exclusive_ms": END, "calendar_days": 245, "timeframe_min": 30},
        "context_fit_sha256": hashlib.sha256(json.dumps(fits, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "lanes": lanes,
        "raw_price_bodies_exported": False,
        "market_requests": 0,
        "economic_runs": 0,
        "order_live_paper_deploy": "BLOCKED_UNSURE_HOLD",
    }
    unsigned = (json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    report["receipt_sha256"] = hashlib.sha256(unsigned).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.source_root, args.output)
    print("NATIVE_DAILY_FUNNEL_RECEIPT=" + result["receipt_sha256"])
    for identity, row in result["lanes"].items():
        print(identity, json.dumps({name: value["total"] for name, value in row["stages"].items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
