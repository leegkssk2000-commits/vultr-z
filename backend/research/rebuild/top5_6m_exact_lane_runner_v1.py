#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from backend.research.rebuild import top5_6m_exact_historical_replay_v1 as m

LANES = {
    "trend_rider": ("TrendRider Unified", m.trend_replay),
    "squeeze_kr3": ("Squeeze-KR3 Unified", m.squeeze_replay),
    "keltner": (
        "Keltner Reclaim",
        lambda: m.v2_replay(
            "keltner_replacement_trend_pull_long_4h_h12_v2", "Keltner Reclaim"
        ),
    ),
    "supertrend": (
        "Supertrend Momentum",
        lambda: m.v2_replay(
            "supertrend_replacement_highvol_mom_long_4h_h12_v2", "Supertrend Momentum"
        ),
    ),
    "q0": ("Q0 Channel Breakout", m.q0_replay),
}


def git_head_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()


def build_receipt(lane: str) -> dict:
    if lane not in LANES:
        raise ValueError(f"UNKNOWN_LANE:{lane}")
    expected_name, runner = LANES[lane]
    started = time.time()
    result = runner()
    if result.get("strategy") != expected_name:
        raise RuntimeError(f"LANE_IDENTITY_DRIFT:{lane}:{result.get('strategy')}")
    if result.get("integrity", {}).get("fresh_rows_used") is not False:
        raise RuntimeError(f"FRESH_ROWS_USED:{lane}")
    receipt = {
        "schema_version": "zel.top5.6m_exact_historical_replay.lane.v1",
        "state": "TERMINAL_TOP5_6M_EXACT_LANE",
        "lane": lane,
        "strategy": expected_name,
        "window": {
            "start_ms": m.START_MS,
            "end_ms": m.END_MS,
            "start_utc": "2026-03-12T14:00:00Z",
            "end_exclusive_utc": "2026-09-12T14:00:00Z",
            "calendar_days": m.WINDOW_DAYS,
        },
        "fresh_rows_used": False,
        "historical_backfill_to_g5": False,
        "formal_credit": 0,
        "strategy_tuning": False,
        "threshold_grid": False,
        "symbol_cherry_pick": False,
        "paid_ai": 0,
        "orders": 0,
        "live": 0,
        "deploy": 0,
        "result": result,
        "runtime_seconds": time.time() - started,
        "source_identity": {
            "head_at_runtime": git_head_sha(),
            "script_blob_sha": m.ev.git_blob_sha(Path(m.__file__)),
            "lane_runner_blob_sha": m.ev.git_blob_sha(Path(__file__)),
            "v2_freeze_sha256": m.stable(m.read(m.V2_FREEZE)),
            "squeeze_frozen_state_sha256": str(m.read(m.SQUEEZE_STATE)["state_sha256"]),
            "q0_frozen_state_sha256": str(m.read(m.Q0_STATE)["state_sha256"]),
        },
    }
    receipt["receipt_sha256"] = m.stable(receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", required=True, choices=sorted(LANES))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    receipt = build_receipt(args.lane)
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    r = receipt["result"]
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "lane": args.lane,
                "strategy": r["strategy"],
                "closed_T": r["closed_T"],
                "T_per_day": r["T_per_day"],
                "expected_days_for_20T": r["expected_days_for_20T"],
                "runtime_seconds": receipt["runtime_seconds"],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
