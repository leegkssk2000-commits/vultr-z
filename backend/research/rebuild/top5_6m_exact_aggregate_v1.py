#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from backend.research.rebuild import top5_6m_exact_historical_replay_v1 as m

ORDER = [
    ("trend_rider", "TrendRider Unified"),
    ("squeeze_kr3", "Squeeze-KR3 Unified"),
    ("keltner", "Keltner Reclaim"),
    ("supertrend", "Supertrend Momentum"),
    ("q0", "Q0 Channel Breakout"),
]


def git_head_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()


def aggregate(lane_dir: Path) -> dict:
    missing: list[str] = []
    lane_receipts: list[dict] = []
    results: list[dict] = []
    for lane, strategy in ORDER:
        p = lane_dir / f"{lane}.json"
        if not p.exists():
            missing.append(lane)
            continue
        r = json.loads(p.read_text())
        if r.get("state") != "TERMINAL_TOP5_6M_EXACT_LANE":
            raise RuntimeError(f"LANE_STATE_INVALID:{lane}:{r.get('state')}")
        if r.get("lane") != lane or r.get("strategy") != strategy:
            raise RuntimeError(f"LANE_IDENTITY_INVALID:{lane}")
        if r.get("fresh_rows_used") is not False:
            raise RuntimeError(f"LANE_FRESH_ROWS_USED:{lane}")
        if r.get("historical_backfill_to_g5") is not False or r.get("formal_credit") != 0:
            raise RuntimeError(f"LANE_FORMAL_AUTHORITY_DRIFT:{lane}")
        lane_receipts.append(
            {
                "lane": lane,
                "strategy": strategy,
                "receipt_sha256": r["receipt_sha256"],
                "runtime_seconds": r["runtime_seconds"],
            }
        )
        results.append(r["result"])

    receipt = {
        "schema_version": "zel.top5.6m_exact_historical_replay.aggregate.v1",
        "state": (
            "TERMINAL_TOP5_6M_EXACT_HISTORICAL_REPLAY"
            if not missing
            else "PARTIAL_TOP5_6M_EXACT_HISTORICAL_REPLAY"
        ),
        "missing_lanes": missing,
        "completed_lanes": [x["lane"] for x in lane_receipts],
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
        "lane_receipts": lane_receipts,
        "results": results,
        "source_identity": {
            "aggregate_head": git_head_sha(),
            "script_blob_sha": m.ev.git_blob_sha(Path(m.__file__)),
            "aggregate_blob_sha": m.ev.git_blob_sha(Path(__file__)),
        },
    }
    receipt["receipt_sha256"] = m.stable(receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--lane-dir",
        default="research/development_evidence/TOP5_6M_EXACT_REPLAY_V1/LANES",
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--require-complete", action="store_true")
    args = ap.parse_args()
    receipt = aggregate(Path(args.lane_dir))
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "completed_lanes": receipt["completed_lanes"],
                "missing_lanes": receipt["missing_lanes"],
                "closed_T": {x["strategy"]: x["closed_T"] for x in receipt["results"]},
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    if args.require_complete and receipt["missing_lanes"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
