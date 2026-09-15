"""Prepare hash-bound research-only forward context before one common start."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from backend.research.rebuild import scalp7_campaign_v2 as base


def prepare(start_ms: int) -> dict[str, Any]:
    now = int(time.time() * 1000)
    if start_ms <= now or start_ms % 900_000:
        raise ValueError("FUTURE_UTC15_START_REQUIRED")
    source = base.module("scalp7_source_data_v2")
    context = base.module("scalp7_rolling_context_v2")
    forward = base.module("scalp7_fresh_forward_v2")
    out = base.RUNTIME / "fresh_context"
    out.mkdir(parents=True, exist_ok=True)
    raw = {
        tf: source.load_candles(
            base.SOURCE_ROOT, tf, cache_dir=base.RUNTIME / "candle_cache"
        )
        for tf in (15, 30)
    }
    fit = context.fit_context(
        context.cross_features(raw[30]),
        {
            "train_start_ms": base.END - 90 * context.DAY,
            "train_end_ms": base.END,
            "start_ms": base.END,
            "end_ms": base.END + 30 * context.DAY,
        },
    )
    entries: dict[str, Any] = {}
    for tf, by in raw.items():
        entries[str(tf)] = {}
        for symbol, frame in by.items():
            # Numerical indicator burn-in and complete preceding pair weeks;
            # this is a declared fresh source seed, not historical trade credit.
            seed = frame[frame["open_ts_ms"] >= base.END - 30 * context.DAY]
            path = out / (symbol + "_" + str(tf) + "m.csv.gz")
            if not path.exists():
                seed.to_csv(
                    path, index=False, compression={"method": "gzip", "mtime": 0}
                )
            entries[str(tf)][symbol] = {"path": str(path), "sha256": base.sha(path)}
    campaign_path = base.REPORT / "CAMPAIGN_PREREGISTERED_V2.json"
    micro_path = base.RUNTIME / "micro_forward_trade_source/FREEZE.json"
    micro = json.loads(micro_path.read_text())
    names = (
        "scalp7_fresh_forward_v2",
        "scalp7_fresh_source_v2",
        "scalp7_source_data_v2",
    )
    config = {
        "fresh_start_ms": start_ms,
        "frozen_at_ms": now,
        "campaign_contract": {
            "path": str(campaign_path),
            "sha256": base.sha(campaign_path),
        },
        "cost_snapshot": {
            "path": str(base.COST_PATH),
            "sha256": base.sha(base.COST_PATH),
        },
        "sources": [
            {
                "path": str(base.RUNTIME / name),
                "identity_sha256": base.sha(base.RUNTIME / name / "IDENTITY.json"),
            }
            for name in ("fresh_1m", "fresh_1m_verified")
        ],
        "code_hashes": {
            "backend/research/rebuild/"
            + name
            + ".py": base.sha(base.ROOT / "backend/research/rebuild" / (name + ".py"))
            for name in names
        },
        "historical_context": entries,
        "historical_seed_days": 30,
        "regime_fit": fit,
        "producer_role": "SIGNALS_ONLY_NO_EXECUTABLE_FRESH_TRADES",
        "external_micro": {
            "identity": micro["identity"],
            "freeze": {"path": str(micro_path), "sha256": base.sha(micro_path)},
        },
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    path = base.RUNTIME / "FRESH_FORWARD_CONFIG_V2.json"
    base.write_json(path, config)
    freeze = forward.initialize(base.RUNTIME / "fresh_forward", path)
    base.write_json(base.REPORT / "FRESH_FORWARD_CONFIG_V2.json", config)
    base.write_json(base.REPORT / "FRESH_FORWARD_FREEZE_V2.json", freeze)
    return {"config": str(path), "fresh_start_ms": start_ms, "freeze": freeze}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-ms", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.start_ms), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
