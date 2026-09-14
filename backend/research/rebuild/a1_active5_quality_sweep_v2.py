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

ROOT = Path(__file__).resolve().parents[3]
SYMBOLS = "BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,LINK-USDT,DOGE-USDT"
VARIANTS: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "trend_rider": [
        ("body035", {"--signal-body-atr-max": 0.35}),
        ("body040", {"--signal-body-atr-max": 0.40}),
        ("body045", {"--signal-body-atr-max": 0.45}),
        ("body040_cd1", {"--signal-body-atr-max": 0.40, "--extra-sl-cooldown-bars": 1}),
    ],
    "break_and_continue": [
        ("body090", {"--signal-body-atr-min": 0.90}),
        ("body100", {"--signal-body-atr-min": 1.00}),
        ("body110", {"--signal-body-atr-min": 1.10}),
    ],
    "trend_ma_macd": [
        ("chase070", {"--chase-atr-max": 0.70}),
        ("chase080", {"--chase-atr-max": 0.80}),
        ("chase090", {"--chase-atr-max": 0.90}),
        ("chase100", {"--chase-atr-max": 1.00}),
    ],
}


def compact(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    m = data.get("metrics") or {}
    return {
        "completed_trades": int(data.get("completed_trades") or 0),
        "win_rate": m.get("win_rate"),
        "net_pnl_bps": m.get("net_pnl_bps"),
        "net_expectancy_bps": m.get("net_expectancy_bps"),
        "profit_factor": m.get("net_profit_factor"),
        "drawdown_bps": m.get("max_drawdown_bps"),
        "quality_rejected": len(data.get("quality_rejected_intents") or []),
    }


def run_once(strategy_id: str, out: Path, options: dict[str, Any]) -> dict[str, Any]:
    argv = [
        "sweep",
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


def delta(base: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "completed_trades",
        "win_rate",
        "net_pnl_bps",
        "net_expectancy_bps",
        "profit_factor",
        "drawdown_bps",
    )
    return {
        k: None if base.get(k) is None or cand.get(k) is None else cand[k] - base[k]
        for k in keys
    }


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
    with tempfile.TemporaryDirectory(prefix="active5_quality_sweep_") as td:
        ledger = json.loads(BASELINE_LEDGER.read_text(encoding="utf-8"))
        ledger["strategies"][args.strategy_id]["status"] = "ACTIVE"
        temp_ledger = Path(td) / "ledger.json"
        temp_ledger.write_text(
            json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        ev.LEDGER_PATH = temp_ledger
        try:
            base = run_once(args.strategy_id, args.out_dir / "baseline.json", {})
            rows = []
            for name, opts in VARIANTS[args.strategy_id]:
                cand = run_once(args.strategy_id, args.out_dir / f"{name}.json", opts)
                d = delta(base, cand)
                preserve = bool(
                    (cand.get("win_rate") or 0) > (base.get("win_rate") or 0)
                    and (cand.get("net_pnl_bps") or 0) >= (base.get("net_pnl_bps") or 0)
                    and (cand.get("profit_factor") or 0)
                    >= (base.get("profit_factor") or 0)
                )
                rows.append(
                    {
                        "name": name,
                        "options": opts,
                        "metrics": cand,
                        "delta": d,
                        "wr_pnl_pf_preserved": preserve,
                    }
                )
                print("SWEEP_ROW=" + json.dumps(rows[-1], sort_keys=True), flush=True)
        finally:
            ev.LEDGER_PATH = original_ledger
            ev.fetch_bars, ev.fetch_execution_snapshot = orig_b, orig_s
    result = {
        "schema_version": "zel.a1.active5_quality_sweep.v2",
        "strategy_id": args.strategy_id,
        "baseline": base,
        "rows": rows,
        "bar_cache_keys": [list(k) for k in sorted(bar_cache)],
        "snapshot_symbols": sorted(snap_cache),
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    (args.out_dir / "REPORT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    winners = [x["name"] for x in rows if x["wr_pnl_pf_preserved"]]
    print(
        "SWEEP_DONE="
        + json.dumps(
            {
                "strategy_id": args.strategy_id,
                "preserved": winners,
                "bar_cache_unique": len(bar_cache),
                "snapshots": len(snap_cache),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
