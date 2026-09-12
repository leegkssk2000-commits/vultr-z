#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_DEFAULT = ROOT / "research/g5/TOP5_G5A_PHASE1_STATUS_V1.json"
HOUR = 3_600_000

LANES = {
    "TrendRider Unified": {
        "boundary_ms": 1789221600000,
        "timeframe": "1h",
        "state": ROOT / "backend/research/rebuild/g5_trend_rider_unified_state_v1.json",
        "kind": "trend",
    },
    "Keltner Reclaim": {
        "boundary_ms": 1789228800000,
        "timeframe": "4h",
        "state": ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json",
        "kind": "replacement",
        "lane_id": "keltner_trend_main",
        "child_id": "keltner_replacement_trend_pull_long_4h_h12_v2",
    },
    "Supertrend Momentum": {
        "boundary_ms": 1789228800000,
        "timeframe": "4h",
        "state": ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json",
        "kind": "replacement",
        "lane_id": "supertrend_pullback_main",
        "child_id": "supertrend_replacement_highvol_mom_long_4h_h12_v2",
    },
    "Squeeze-KR3 Unified": {
        "boundary_ms": 1789243200000,
        "timeframe": "4h",
        "state": ROOT / "backend/research/rebuild/g5_squeeze_kr3_unified_state_v1.json",
        "kind": "squeeze",
    },
    "Q0 Convex Channel Breakout": {
        "boundary_ms": 1789257600000,
        "timeframe": "4h+1m_stop_witness",
        "state": ROOT / "backend/research/rebuild/g5_q0_convex_state_v1.json",
        "kind": "q0",
    },
}


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def load(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def explicit_integrity(s: dict) -> dict:
    keys = {
        "duplicate_T": s.get("duplicate_T", s.get("duplicate_count")),
        "unknown_exit_T": s.get("unknown_exit_T"),
        "censored_open_T": s.get("censored_open_T"),
        "integrity_errors": s.get("integrity_errors"),
    }
    observed = {k: v for k, v in keys.items() if v is not None}
    fail = False
    for k, v in observed.items():
        if k == "censored_open_T":
            continue
        if isinstance(v, list) and v:
            fail = True
        elif isinstance(v, (int, float)) and v != 0:
            fail = True
    return {"state": "FAIL" if fail else ("EXPLICIT_ZERO_OR_EMPTY" if observed else "PENDING_EXPLICIT_FIELDS"), "observed": observed}


def replacement_lane(s: dict, cfg: dict) -> dict:
    x = (s.get("lanes") or {}).get(cfg["lane_id"], {})
    assert not x or x.get("child_id") == cfg["child_id"], "REPLACEMENT_CHILD_ID_DRIFT"
    trades = [t for t in x.get("closed_trades", []) if int(t.get("signal_ts") or -1) >= cfg["boundary_ms"]]
    last_bar = max((int(v.get("last_bar_ts") or -1) for v in (x.get("source_summary") or {}).values()), default=-1)
    return {
        "collector_total_closed_T": int(x.get("closed_T") or 0),
        "fresh_closed_T": len(trades),
        "fresh_open_T": 0,
        "fresh_signal_T": len(trades),
        "last_scanned_bar_open_ms": last_bar,
        "source_reached_boundary": last_bar >= cfg["boundary_ms"],
        "integrity": {"state": "PENDING_LANE_LOCAL_ACCOUNTANT", "observed": {}},
        "child_id": x.get("child_id"),
    }


def simple_lane(s: dict, cfg: dict) -> dict:
    kind = cfg["kind"]
    if kind == "trend":
        last = int(s.get("last_scanned_closed_1h_ms") or -1)
        signal = int(s.get("event_T") or 0)
        finalized = int(s.get("finalized_T") or 0)
    else:
        last = int(s.get("last_scanned_closed_4h_ms") or -1)
        signal = int(s.get("signal_T", s.get("event_T", 0)) or 0)
        finalized = int(s.get("finalized_T", s.get("closed_T", 0)) or 0)
    open_t = int(s.get("open_T", s.get("censored_open_T", 0)) or 0)
    return {
        "fresh_closed_T": finalized,
        "fresh_open_T": open_t,
        "fresh_signal_T": signal,
        "last_scanned_bar_open_ms": last,
        "source_reached_boundary": last >= cfg["boundary_ms"],
        "integrity": explicit_integrity(s),
        "rule_id": s.get("rule_id"),
    }


def build(now_ms: int) -> dict:
    lanes = {}
    for name, cfg in LANES.items():
        s = load(cfg["state"])
        info = replacement_lane(s, cfg) if cfg["kind"] == "replacement" else simple_lane(s, cfg)
        boundary_passed = now_ms >= cfg["boundary_ms"]
        if not boundary_passed:
            state = "WAIT_BOUNDARY"
        elif not s:
            state = "BLOCKED_MISSING_STATE"
        elif not info["source_reached_boundary"]:
            state = "WAIT_FIRST_POST_BOUNDARY_SOURCE"
        elif info["integrity"]["state"] == "FAIL":
            state = "BLOCKED_INTEGRITY"
        elif info["fresh_closed_T"] > 0:
            state = "FRESH_CLOSED_T_AVAILABLE_ACCOUNTING_PENDING_OR_ACTIVE"
        elif info["fresh_open_T"] > 0:
            state = "FRESH_OPEN_T_WAIT_CLOSE"
        else:
            state = "FRESH_SOURCE_ACTIVE_NO_CLOSED_T"
        lanes[name] = {
            "timeframe": cfg["timeframe"],
            "boundary_ms": cfg["boundary_ms"],
            "boundary_passed": boundary_passed,
            "state_path": str(cfg["state"].relative_to(ROOT)),
            "state_sha256": sha256(cfg["state"]),
            "phase1_state": state,
            **info,
        }
    return {
        "schema": "zel.top5.g5a.phase1.status.v1",
        "scope_key": "TOP5_G5A_FRESH_COLLECTION_AFTER_PHASE0_V1",
        "issue": 1313,
        "observed_at_ms": now_ms,
        "active_top5": list(LANES),
        "reserve": ["Break & Continue"],
        "formal_pass_authority": False,
        "strategy_mutation": False,
        "historical_backfill": False,
        "g5a_rows_reusable_for_g5b": False,
        "lanes": lanes,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--now-ms", type=int, default=None)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        r = build(1789218000000)
        assert all(x["phase1_state"] == "WAIT_BOUNDARY" for x in r["lanes"].values())
        assert r["formal_pass_authority"] is False and r["strategy_mutation"] is False
        print("PASS_TOP5_G5A_PHASE1_MONITOR_V1")
        return 0
    out = build(args.now_ms if args.now_ms is not None else int(time.time() * 1000))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"lanes": {k: v["phase1_state"] for k, v in out["lanes"].items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
