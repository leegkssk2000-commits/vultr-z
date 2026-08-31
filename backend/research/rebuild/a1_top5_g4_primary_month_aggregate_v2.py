#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as core

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_g4_primary_month_sharded_fasttrack_v2.json"
SCHEMA = "zel.a1.top5.g4.primary_month_sharded_fasttrack.receipt.v2"
LATEST = ROOT / "backend/research/rebuild/a1_top5_g4_primary_month_sharded_fasttrack_v2_latest.json"
LANE_ID = "trend_rider_primary_wr8125"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def days(start_ms: int, end_ms: int) -> float:
    return max(0.0, (end_ms - start_ms) / 86_400_000.0)


def pf_gt(metrics: Mapping[str, Any], threshold: float) -> bool:
    if bool(metrics.get("profit_factor_unbounded")):
        return True
    value = metrics.get("profit_factor")
    return value is not None and float(value) > threshold


def positive_month(metrics: Mapping[str, Any]) -> bool:
    return int(metrics.get("closed_T") or 0) > 0 and float(metrics.get("net_expectancy_bps") or 0.0) > 0.0


def fasttrack_gate(metrics: Mapping[str, Any], positive_months: int, rule: Mapping[str, Any]) -> dict[str, bool]:
    checks = {
        "T_min": int(metrics.get("closed_T") or 0) >= int(rule["minimum_closed_T"]),
        "net_pos": float(metrics.get("net_pnl_bps") or 0.0) > float(rule["net_pnl_bps_gt"]),
        "expectancy_pos": float(metrics.get("net_expectancy_bps") or 0.0) > float(rule["net_expectancy_bps_gt"]),
        "pf_gt": pf_gt(metrics, float(rule["profit_factor_gt"])),
        "positive_months_min": positive_months >= int(rule["minimum_positive_months"]),
    }
    checks["pass"] = all(checks.values())
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    contract = read(CONTRACT)
    windows = [dict(x) for x in contract.get("historical_windows", [])]
    symbols = [str(x) for x in contract.get("symbols", [])]
    expected = {(s, str(w["window_id"])) for s in symbols for w in windows}

    input_dir = Path(args.input_dir)
    files = sorted(input_dir.rglob("*.json"))
    shards: dict[tuple[str, str], dict[str, Any]] = {}
    source_files: dict[str, str] = {}
    for path in files:
        value = read(path)
        if value.get("schema_version") != "zel.a1.top5.g4.primary_month_shard.receipt.v2":
            continue
        key = (str(value.get("symbol")), str(value.get("window_id")))
        if key in shards:
            raise RuntimeError(f"DUPLICATE_PRIMARY_MONTH_SHARD:{key}")
        shards[key] = value
        source_files[f"{key[0]}::{key[1]}"] = str(path)

    missing = sorted(expected - set(shards))
    extra = sorted(set(shards) - expected)
    if missing:
        raise RuntimeError(f"MISSING_PRIMARY_MONTH_SHARDS:{missing}")
    if extra:
        raise RuntimeError(f"EXTRA_PRIMARY_MONTH_SHARDS:{extra}")
    if len(shards) != 12:
        raise RuntimeError(f"PRIMARY_MONTH_SHARD_COUNT:{len(shards)}")

    all_rows: list[dict[str, Any]] = []
    monthly: list[dict[str, Any]] = []
    by_symbol: dict[str, dict[str, Any]] = {}
    seen_trade_ids: set[str] = set()

    for symbol in symbols:
        symbol_rows: list[dict[str, Any]] = []
        for w in windows:
            wid = str(w["window_id"])
            shard = shards[(symbol, wid)]
            if shard.get("state") != "PRIMARY_MONTH_SHARD_OK":
                raise RuntimeError(f"PRIMARY_MONTH_SHARD_STATE:{symbol}:{wid}:{shard.get('state')}")
            if str(shard.get("contract_sha256")) != file_sha(CONTRACT):
                raise RuntimeError(f"PRIMARY_MONTH_CONTRACT_SHA_DRIFT:{symbol}:{wid}")
            start_ms, end_ms = utc_ms(str(w["start_utc"])), utc_ms(str(w["end_utc"]))
            for row in shard.get("trades", []):
                trade = dict(row)
                tid = str(trade.get("trade_id") or "")
                if not tid or tid in seen_trade_ids:
                    raise RuntimeError(f"PRIMARY_MONTH_DUPLICATE_TRADE_ID:{tid}")
                if str(trade.get("symbol")) != symbol or str(trade.get("lane_id")) != LANE_ID:
                    raise RuntimeError(f"PRIMARY_MONTH_TRADE_IDENTITY_DRIFT:{symbol}:{wid}")
                if not (start_ms <= int(trade["signal_ts"]) < end_ms):
                    raise RuntimeError(f"PRIMARY_MONTH_SIGNAL_WINDOW_DRIFT:{symbol}:{wid}:{tid}")
                seen_trade_ids.add(tid)
                symbol_rows.append(trade)
                all_rows.append(trade)
        symbol_rows.sort(key=lambda x: (int(x["exit_ts"]), int(x["signal_ts"]), str(x["trade_id"])))
        six_start, six_end = utc_ms(str(windows[0]["start_utc"])), utc_ms(str(windows[-1]["end_utc"]))
        by_symbol[symbol] = {
            "metrics_6m": core.metrics(symbol_rows, days(six_start, six_end)),
            "trade_count": len(symbol_rows),
        }

    all_rows.sort(key=lambda x: (int(x["exit_ts"]), int(x["signal_ts"]), str(x["symbol"]), str(x["trade_id"])))
    for w in windows:
        start_ms, end_ms = utc_ms(str(w["start_utc"])), utc_ms(str(w["end_utc"]))
        rows = [x for x in all_rows if start_ms <= int(x["signal_ts"]) < end_ms]
        monthly.append({
            **w,
            "metrics": core.metrics(rows, days(start_ms, end_ms)),
            "symbols": {
                s: shards[(s, str(w["window_id"]))]["metrics"] for s in symbols
            },
        })

    six_start, six_end = utc_ms(str(windows[0]["start_utc"])), utc_ms(str(windows[-1]["end_utc"]))
    three_start, three_end = utc_ms(str(windows[3]["start_utc"])), utc_ms(str(windows[-1]["end_utc"]))
    rows_6m = [x for x in all_rows if six_start <= int(x["signal_ts"]) < six_end]
    rows_3m = [x for x in all_rows if three_start <= int(x["signal_ts"]) < three_end]
    metrics_6m = core.metrics(rows_6m, days(six_start, six_end))
    metrics_3m = core.metrics(rows_3m, days(three_start, three_end))
    pos_6m = sum(1 for x in monthly if positive_month(x["metrics"]))
    pos_3m = sum(1 for x in monthly[3:] if positive_month(x["metrics"]))

    policy = contract["fasttrack_policy"]
    gate_3m = fasttrack_gate(metrics_3m, pos_3m, policy["recent_3m"])
    gate_6m = fasttrack_gate(metrics_6m, pos_6m, policy["recent_6m"])
    both = bool(gate_3m["pass"] and gate_6m["pass"])
    one = bool(gate_3m["pass"] ^ gate_6m["pass"])
    if both:
        state = "G4_HISTORICAL_SURVIVOR_READY_FORWARD_DEFERRED"
        next_action = "OPEN_NEXT_ROADMAP_PREP_SHADOW_KEEP_FRESH_CONFIRMATION"
    elif one:
        state = "HIST_MIXED_TRANSPLANT_OR_SALVAGE_DONOR_ONLY"
        next_action = "KEEP_AS_DONOR_ONLY_CONTINUE_FRESH_G4"
    else:
        state = "HIST_3M_6M_ECONOMIC_FAIL_ARCHITECTURE_REPLACEMENT_PRIORITY"
        next_action = "ARCHITECTURE_REPLACEMENT_OR_DONOR_DECOMPOSITION"

    payload = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": file_sha(CONTRACT),
        "lane_id": LANE_ID,
        "shard_count": len(shards),
        "expected_shard_count": len(expected),
        "shards_complete": set(shards) == expected,
        "source_files": source_files,
        "by_symbol": by_symbol,
        "monthly": monthly,
        "recent_3m": {
            "start_utc": windows[3]["start_utc"],
            "end_utc": windows[-1]["end_utc"],
            "metrics": metrics_3m,
            "positive_months": pos_3m,
            "gate": gate_3m,
        },
        "recent_6m": {
            "start_utc": windows[0]["start_utc"],
            "end_utc": windows[-1]["end_utc"],
            "metrics": metrics_6m,
            "positive_months": pos_6m,
            "gate": gate_6m,
        },
        "trade_count": len(all_rows),
        "trades": all_rows,
        "integrity": {
            "exact_12_shards": len(shards) == 12,
            "unique_symbol_window_pairs": len(shards) == len(expected),
            "unique_trade_ids": len(seen_trade_ids) == len(all_rows),
            "strategy_semantics_changed": False,
            "threshold_sweep": False,
            "window_sweep": False,
            "symbol_sweep": False,
            "historical_credit_to_fresh_g4_T": 0,
            "historical_credit_to_g5_T": 0,
        },
        "formal_credit": {"fresh_g4_T": 0, "g5_T": 0},
        "next": next_action,
        "paid_provider_calls": 0,
        **AUTH,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": state,
        "T_3m": metrics_3m["closed_T"],
        "net_3m": metrics_3m["net_pnl_bps"],
        "pf_3m": metrics_3m["profit_factor"],
        "pass_3m": gate_3m["pass"],
        "T_6m": metrics_6m["closed_T"],
        "net_6m": metrics_6m["net_pnl_bps"],
        "pf_6m": metrics_6m["profit_factor"],
        "pass_6m": gate_6m["pass"],
        "out": str(out),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
