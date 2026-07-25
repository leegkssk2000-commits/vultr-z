from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
BASE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
INTERVAL_MS = 900_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
ANCHOR_ENDS = (
    "2026-03-01T00:00:00Z",
    "2026-03-13T00:00:00Z",
    "2026-03-25T00:00:00Z",
    "2026-04-06T00:00:00Z",
    "2026-04-18T00:00:00Z",
    "2026-04-30T00:00:00Z",
    "2026-05-12T00:00:00Z",
    "2026-05-24T00:00:00Z",
    "2026-06-05T00:00:00Z",
    "2026-06-17T00:00:00Z",
)
WINDOW_ROLES = ("S1", "S2", "S3", "S4", "S5", "S6", "V1", "V2", "H1", "H2")
WINDOW_BARS = 900


def _load_base() -> Any:
    name = "r7a4d_strategy11_prepare_base_v2"
    spec = importlib.util.spec_from_file_location(name, BASE_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_RUNNER_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--window-bars", type=int, default=WINDOW_BARS)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cache = root / "artifacts/strategy11_market_cache_v2"
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    blockers = []

    for role, anchor in zip(WINDOW_ROLES, ANCHOR_ENDS):
        end_ms = int(pd.Timestamp(anchor).timestamp() * 1000)
        end_ms = (end_ms // INTERVAL_MS) * INTERVAL_MS
        start_ms = end_ms - (args.window_bars - 1) * INTERVAL_MS
        for symbol in SYMBOLS:
            path = cache / f"{role}-{symbol}.csv"
            try:
                if path.is_file():
                    frame = pd.read_csv(path)
                    if len(frame) != args.window_bars:
                        raise ValueError(f"CACHE_ROWS:{len(frame)}!={args.window_bars}")
                    endpoint = "CACHE_REUSE"
                    requests = 0
                else:
                    frame, endpoint, requests = base._fetch_exact(
                        symbol,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        expected_rows=args.window_bars,
                    )
                    frame.to_csv(path, index=False)
                rows.append({
                    "window_id": role,
                    "symbol": symbol,
                    "status": "PASS",
                    "rows": len(frame),
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "path": str(path),
                    "endpoint": endpoint,
                    "request_count": requests,
                })
            except Exception as exc:
                error = f"{role}:{symbol}:{type(exc).__name__}:{exc}"
                blockers.append(error)
                rows.append({"window_id": role, "symbol": symbol, "status": "HOLD", "error": error})

    manifest = {
        "schema_version": "2.0",
        "state": "PASS" if not blockers else "HOLD",
        "anchors": list(ANCHOR_ENDS),
        "roles": list(WINDOW_ROLES),
        "symbols": list(SYMBOLS),
        "window_bars": args.window_bars,
        "rows": rows,
        "blockers": blockers,
        "authority": "READ_ONLY_MARKET_DATA_CACHE",
        "route_allowed": False,
        "shadow_allowed": False,
        "execution_allowed": False,
    }
    (cache / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"STATE": manifest["state"], "BLOCKERS": blockers, "CACHE_ROWS": len(rows)}, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
