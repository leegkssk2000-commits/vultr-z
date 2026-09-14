from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_three_lane_v1 as ev
from backend.research.rebuild.a1_strategy25_active_deep_replay_v1 import BASELINE_LEDGER

SYMBOLS = "BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,LINK-USDT,DOGE-USDT"
MIN_T_RETENTION = 0.75
VARIANTS: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "supertrend_pullback": [
        ("cd1", {"--extra-sl-cooldown-bars": 1}),
        ("cd2", {"--extra-sl-cooldown-bars": 2}),
        ("cd3", {"--extra-sl-cooldown-bars": 3}),
    ],
    "trend_rider": [
        ("body035", {"--signal-body-atr-max": 0.35}),
        ("body040", {"--signal-body-atr-max": 0.40}),
        ("body045", {"--signal-body-atr-max": 0.45}),
        ("body050", {"--signal-body-atr-max": 0.50}),
        ("body040_cd1", {"--signal-body-atr-max": 0.40, "--extra-sl-cooldown-bars": 1}),
    ],
    "keltner_trend": [
        ("cd1", {"--extra-sl-cooldown-bars": 1}),
        ("cd2", {"--extra-sl-cooldown-bars": 2}),
        ("cd3", {"--extra-sl-cooldown-bars": 3}),
    ],
    "break_and_continue": [
        ("body050", {"--signal-body-atr-min": 0.50}),
        ("body060", {"--signal-body-atr-min": 0.60}),
        ("body070", {"--signal-body-atr-min": 0.70}),
        ("body080", {"--signal-body-atr-min": 0.80}),
        ("body090", {"--signal-body-atr-min": 0.90}),
    ],
    "trend_ma_macd": [
        ("chase100", {"--chase-atr-max": 1.00}),
        ("chase110", {"--chase-atr-max": 1.10}),
        ("chase120", {"--chase-atr-max": 1.20}),
        ("chase130", {"--chase-atr-max": 1.30}),
        ("chase140", {"--chase-atr-max": 1.40}),
    ],
}


def compact(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    m = data.get("metrics") or {}
    return {
        "T": int(data.get("completed_trades") or 0),
        "WR": m.get("win_rate"),
        "Net_bps": m.get("net_pnl_bps"),
        "Exp_bps_T": m.get("net_expectancy_bps"),
        "PF": m.get("net_profit_factor"),
        "DD_bps": m.get("max_drawdown_bps"),
        "quality_rejected": len(data.get("quality_rejected_intents") or []),
    }


def run_once(strategy_id: str, out: Path, options: dict[str, Any]) -> dict[str, Any]:
    argv = [
        "sweep-v3",
        "--strategy-id",
        strategy_id,
        "--symbols",
        SYMBOLS,
        "--out",
        str(out),
    ]
    for key, value in options.items():
        argv.extend([key, str(value)])
    prior = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ev.main()
    finally:
        sys.argv = prior
    return compact(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy-id", required=True, choices=sorted(VARIANTS))
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    bar_cache: dict[tuple[str, str, int], Any] = {}
    snap_cache: dict[str, Any] = {}
    orig_b, orig_s = ev.fetch_bars, ev.fetch_execution_snapshot

    def cached_b(symbol: str, interval: str, limit: int = 1000):
        key = (symbol, interval, int(limit))
        if key not in bar_cache:
            bar_cache[key] = orig_b(symbol, interval, limit)
        return bar_cache[key]

    def cached_s(symbol: str, authority: Any):
        if symbol not in snap_cache:
            snap_cache[symbol] = orig_s(symbol, authority)
        return snap_cache[symbol]

    ev.fetch_bars, ev.fetch_execution_snapshot = cached_b, cached_s
    original_ledger = ev.LEDGER_PATH
    with tempfile.TemporaryDirectory(prefix="active5_quality_sweep_v3_") as td:
        ledger = json.loads(BASELINE_LEDGER.read_text(encoding="utf-8"))
        ledger["strategies"][args.strategy_id]["status"] = "ACTIVE"
        temp_ledger = Path(td) / "ledger.json"
        temp_ledger.write_text(
            json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        ev.LEDGER_PATH = temp_ledger
        try:
            baseline = run_once(args.strategy_id, args.out_dir / "baseline.json", {})
            rows: list[dict[str, Any]] = []
            for name, options in VARIANTS[args.strategy_id]:
                candidate = run_once(
                    args.strategy_id, args.out_dir / f"{name}.json", options
                )
                retention = candidate["T"] / max(1, baseline["T"])
                row = {
                    "name": name,
                    "options": options,
                    "metrics": candidate,
                    "T_retention": retention,
                }
                row["multi_metric_pass"] = bool(
                    retention >= MIN_T_RETENTION
                    and candidate["WR"] > baseline["WR"]
                    and candidate["Net_bps"] >= baseline["Net_bps"]
                    and candidate["PF"] >= baseline["PF"]
                    and candidate["DD_bps"] <= baseline["DD_bps"]
                )
                rows.append(row)
                print("SWEEP_V3_ROW=" + json.dumps(row, sort_keys=True), flush=True)
        finally:
            ev.LEDGER_PATH = original_ledger
            ev.fetch_bars, ev.fetch_execution_snapshot = orig_b, orig_s

    report = {
        "schema_version": "zel.a1.active5_quality_sweep.v3",
        "strategy_id": args.strategy_id,
        "baseline": baseline,
        "minimum_T_retention": MIN_T_RETENTION,
        "rows": rows,
        "pass_candidates": [row["name"] for row in rows if row["multi_metric_pass"]],
        "bar_cache_unique": len(bar_cache),
        "snapshot_unique": len(snap_cache),
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    (args.out_dir / "REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "SWEEP_V3_DONE="
        + json.dumps(
            {"strategy_id": args.strategy_id, "passes": report["pass_candidates"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
