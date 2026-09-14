from __future__ import annotations

import argparse
import contextlib
import gzip
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_three_lane_v1 as ev
from backend.research.rebuild.a1_strategy25_active_deep_replay_v1 import (
    BASELINE_LEDGER,
    INVENTORY,
)

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK6 = {
    "liquidity_sweep",
    "scalp_snap",
    "vol_spike_fade",
    "ema_ribbon_scalp",
    "session_bias",
    "sr_levels",
}
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
TIMEFRAME_MS = 300_000


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def compact(receipt: dict[str, Any]) -> dict[str, Any]:
    m = receipt.get("metrics") or {}
    return {
        "T": int(receipt.get("completed_trades") or 0),
        "WR": m.get("win_rate"),
        "Net_bps": m.get("net_pnl_bps"),
        "Exp_bps_T": m.get("net_expectancy_bps"),
        "PF": m.get("net_profit_factor"),
        "DD_bps": m.get("max_drawdown_bps"),
        "integrity_defects": len(receipt.get("integrity_defects") or []),
    }


def load_cache(cache_root: Path) -> dict[str, list[dict[str, Any]]]:
    manifest = read_json(cache_root / "MANIFEST.json")
    if manifest.get("state") != "PASS_SHARED_CACHE_COMPLETE":
        raise RuntimeError("SHARED_CACHE_NOT_COMPLETE")
    out: dict[str, list[dict[str, Any]]] = {}
    for symbol in SYMBOLS:
        path = cache_root / "data" / f"{symbol.replace('-', '')}_5m.jsonl.gz"
        rows: list[dict[str, Any]] = []
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                x = json.loads(line)
                rows.append(
                    {
                        "ts_ms": int(x["timestamp_ms"]),
                        "open": float(x["open"]),
                        "high": float(x["high"]),
                        "low": float(x["low"]),
                        "close": float(x["close"]),
                        "volume": float(x["volume"]),
                    }
                )
        out[symbol] = rows
    return out


def lane_strategies() -> list[str]:
    inv = read_json(INVENTORY)
    ids = list((inv.get("strategies") or {}).keys())
    selected = [sid for sid in ids if sid not in BENCHMARK6]
    if len(selected) != 19 or len(set(selected)) != 19:
        raise RuntimeError(f"LANE_COUNT_INVALID:{len(selected)}")
    return selected


def run_one(sid: str, out: Path) -> dict[str, Any]:
    prior = list(sys.argv)
    sys.argv = [
        "lane19",
        "--strategy-id",
        sid,
        "--symbols",
        ",".join(SYMBOLS),
        "--out",
        str(out),
        "--timeframe-ms",
        str(TIMEFRAME_MS),
    ]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ev.main()
    finally:
        sys.argv = prior
    return read_json(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cache-root", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    args = p.parse_args()
    if args.shard_count < 1 or not (0 <= args.shard_index < args.shard_count):
        raise RuntimeError("INVALID_SHARD")
    all_ids = lane_strategies()
    selected = [
        sid for i, sid in enumerate(all_ids) if i % args.shard_count == args.shard_index
    ]
    bars = load_cache(args.cache_root)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    ledger = read_json(BASELINE_LEDGER)
    for sid in all_ids:
        entry = (ledger.get("strategies") or {}).get(sid)
        if not isinstance(entry, dict) or not entry.get("prospective_boundary_utc"):
            raise RuntimeError(f"LEDGER_ENTRY_INVALID:{sid}")
        entry["status"] = "ACTIVE"
    manifest = read_json(args.cache_root / "MANIFEST.json")
    original_ledger = ev.LEDGER_PATH
    original_bars = ev.fetch_bars
    original_snap = ev.fetch_execution_snapshot
    snap_cache: dict[str, Any] = {}

    def local_bars(symbol: str, interval: str, limit: int = 1000):
        if interval != "5m":
            raise RuntimeError(f"LANE19_INTERVAL_NOT_5M:{interval}")
        if symbol not in bars:
            raise RuntimeError(f"CACHE_SYMBOL_MISSING:{symbol}")
        return bars[symbol]

    def cached_snap(symbol: str, authority: dict[str, Any]):
        if symbol not in snap_cache:
            snap_cache[symbol] = original_snap(symbol, authority)
        return snap_cache[symbol]

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="lane19_5m_") as td:
        temp_ledger = Path(td) / "ledger.json"
        temp_ledger.write_text(
            json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        ev.LEDGER_PATH = temp_ledger
        ev.fetch_bars = local_bars
        ev.fetch_execution_snapshot = cached_snap
        try:
            for sid in selected:
                receipt_path = args.out_dir / f"{sid}.json"
                try:
                    if receipt_path.exists():
                        prior = read_json(receipt_path)
                        prior_source = prior.get("source") or {}
                        if prior_source.get("cache_manifest_sha256") == manifest.get(
                            "manifest_sha256"
                        ) and not (prior.get("integrity_defects") or []):
                            row = {"strategy_id": sid, **compact(prior)}
                            rows.append(row)
                            print(
                                "LANE19_RESUME=" + json.dumps(row, sort_keys=True),
                                flush=True,
                            )
                            continue
                    receipt = run_one(sid, receipt_path)
                    source = dict(receipt.get("source") or {})
                    source["endpoint"] = "LOCAL_SHARED_CACHE_1M_TO_5M"
                    source["cache_root"] = str(args.cache_root)
                    source["cache_manifest_sha256"] = manifest.get("manifest_sha256")
                    source["cache_total_rows_5m"] = manifest.get("total_rows_5m")
                    receipt["source"] = source
                    receipt["receipt_sha256"] = ev.stable_sha(
                        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
                    )
                    receipt_path.write_text(
                        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    row = {"strategy_id": sid, **compact(receipt)}
                    rows.append(row)
                    print("LANE19_ROW=" + json.dumps(row, sort_keys=True), flush=True)
                except Exception as exc:
                    err = {"strategy_id": sid, "error": f"{type(exc).__name__}:{exc}"}
                    errors.append(err)
                    print("LANE19_ERROR=" + json.dumps(err, sort_keys=True), flush=True)
        finally:
            ev.LEDGER_PATH = original_ledger
            ev.fetch_bars = original_bars
            ev.fetch_execution_snapshot = original_snap

    report = {
        "schema_version": "zel.a1.strategy19.5m.replay.v1",
        "state": (
            "PASS_LANE19_SHARD"
            if rows and not errors
            else ("PARTIAL_LANE19_SHARD" if rows else "HOLD_LANE19_SHARD")
        ),
        "research_only": True,
        "timeframe": "5m",
        "strategy_count_total": 19,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "requested": selected,
        "success_count": len(rows),
        "error_count": len(errors),
        "rows": rows,
        "errors": errors,
        "cache_manifest": manifest,
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
        "LANE19_DONE="
        + json.dumps(
            {"success": len(rows), "errors": len(errors), "shard": args.shard_index},
            sort_keys=True,
        )
    )
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
