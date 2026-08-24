#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
BASELINE_LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def metrics(receipt: dict[str, Any]) -> dict[str, Any]:
    m = receipt.get("metrics") or {}
    return {
        "completed_trades": int(receipt.get("completed_trades") or 0),
        "win_rate": m.get("win_rate"),
        "net_pnl_bps": m.get("net_pnl_bps"),
        "net_expectancy_bps": m.get("net_expectancy_bps"),
        "profit_factor": m.get("net_profit_factor"),
        "drawdown_bps": m.get("max_drawdown_bps"),
    }


def run(league_path: Path, out_dir: Path, aggregate_path: Path, symbols: str) -> dict[str, Any]:
    league = read(league_path); ledger = read(BASELINE_LEDGER); inventory = read(INVENTORY)
    active = list(league.get("active_top5") or [])
    canonical = set((inventory.get("strategies") or {}).keys())
    if len(active) != 5 or len(set(active)) != 5 or any(x not in canonical for x in active):
        raise RuntimeError(f"ACTIVE_TOP5_INVALID:{active}")

    shadow = json.loads(json.dumps(ledger))
    for sid in active:
        entry = (shadow.get("strategies") or {}).get(sid)
        if not isinstance(entry, dict):
            raise RuntimeError(f"LEDGER_ENTRY_REQUIRED:{sid}")
        if not entry.get("prospective_boundary_utc"):
            raise RuntimeError(f"PROSPECTIVE_BOUNDARY_REQUIRED:{sid}")
        # In-memory/temporary replay authority only. The canonical ledger is never written.
        entry["status"] = "ACTIVE"

    bar_cache: dict[tuple[str, str, int], Any] = {}
    execution_cache: dict[str, Any] = {}
    original_bars = ev.fetch_bars; original_snapshot = ev.fetch_execution_snapshot
    original_ledger = ev.LEDGER_PATH; original_argv = list(sys.argv)

    def cached_bars(symbol: str, interval: str, limit: int = 1000):
        key = (symbol, interval, int(limit))
        if key not in bar_cache:
            bar_cache[key] = original_bars(symbol, interval, limit)
        return bar_cache[key]

    def cached_snapshot(symbol: str, authority: dict[str, Any]):
        if symbol not in execution_cache:
            execution_cache[symbol] = original_snapshot(symbol, authority)
        return execution_cache[symbol]

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="strategy25_active_replay_") as td:
        temp_ledger = Path(td) / "terminal_replay_ledger.json"
        write(temp_ledger, shadow)
        ev.LEDGER_PATH = temp_ledger
        ev.fetch_bars = cached_bars
        ev.fetch_execution_snapshot = cached_snapshot
        try:
            for sid in active:
                receipt_path = out_dir / f"{sid}.json"
                sys.argv = [
                    "a1_exact25_generic_evaluator_v1.py", "--strategy-id", sid,
                    "--symbols", symbols, "--out", str(receipt_path),
                ]
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        ev.main()
                    receipt = read(receipt_path)
                    row = {
                        "strategy_id": sid,
                        "identity": sid,
                        "state": receipt.get("state"),
                        "metrics": metrics(receipt),
                        "completed_trades": int(receipt.get("completed_trades") or 0),
                        "integrity_defects": list(receipt.get("integrity_defects") or []),
                        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
                        "native_policy_ownership": receipt.get("native_policy_ownership"),
                        "source_receipt_sha256": receipt.get("receipt_sha256"),
                        "source_path": str(receipt_path),
                        **AUTH,
                    }
                    rows.append(row)
                except Exception as exc:
                    errors.append({"strategy_id": sid, "error": f"{type(exc).__name__}:{exc}"})
        finally:
            ev.LEDGER_PATH = original_ledger
            ev.fetch_bars = original_bars
            ev.fetch_execution_snapshot = original_snapshot
            sys.argv = original_argv

    result = {
        "schema_version": "zel.a1.strategy25_active_deep_replay.v1",
        "state": "PASS_ACTIVE5_SHARED_CACHE_DEEP_REPLAY" if rows else "HOLD_ACTIVE5_DEEP_REPLAY_NO_SUCCESS",
        "research_only": True,
        "active_top5": active,
        "requested_count": len(active),
        "success_count": len(rows),
        "error_count": len(errors),
        "rows": rows,
        "errors": errors,
        "shared_cache": {
            "enabled": True,
            "bar_fetch_unique_keys": [list(x) for x in sorted(bar_cache)],
            "bar_fetch_unique_count": len(bar_cache),
            "execution_snapshot_symbols": sorted(execution_cache),
            "execution_snapshot_unique_count": len(execution_cache),
            "reuse_scope": "ONE_PROCESS_ALL_ACTIVE_TOP5",
        },
        "canonical_ledger_mutated": False,
        "temporary_terminal_replay_ledger": True,
        "symbols": [x.strip() for x in symbols.split(",") if x.strip()],
        **AUTH,
    }
    write(aggregate_path, result)
    if not rows:
        raise RuntimeError("ACTIVE5_DEEP_REPLAY_ZERO_SUCCESS")
    return result


def self_test() -> int:
    ledger = read(BASELINE_LEDGER); inventory = read(INVENTORY)
    assert int(ledger.get("done_count") or 0) == 25
    assert len((inventory.get("strategies") or {})) == 25
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    assert AUTH["live_trade_authority"] == "BLOCKED" and AUTH["protected_mutations"] == 0
    print("PASS_A1_STRATEGY25_ACTIVE_DEEP_REPLAY_V1_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--self-test", action="store_true")
    p.add_argument("--league", type=Path, default=Path("out/a1_strategy25_improvement_league_pre.json"))
    p.add_argument("--out-dir", type=Path, default=Path("out/strategy25_active_deep"))
    p.add_argument("--aggregate", type=Path, default=Path("out/a1_strategy25_active_deep_replay_latest.json"))
    p.add_argument("--symbols", default="BTC-USDT,ETH-USDT")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.league, args.out_dir, args.aggregate, args.symbols)
    print("ACTIVE5_DEEP_REPLAY=" + json.dumps({
        "active": r["active_top5"], "success": r["success_count"], "errors": r["error_count"],
        "bar_fetch_unique": r["shared_cache"]["bar_fetch_unique_count"],
        "execution_snapshot_unique": r["shared_cache"]["execution_snapshot_unique_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
