"""Isolated, read-only, pre-fresh-boundary BingX OHLC parity probe.

Never a survivor/economic screen. Only source/behavioral parity, with zero trade
or order authority. Retries, tuning, G5 holdout use and pipeline mutation forbidden.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import types
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from backend.research.architecture_factory import a1_external_research_exact8_through_a3_runner_v1 as runner
from backend.research.architecture_factory import a1_external_research_exact8_source_audit_v1 as source_audit

NEW = runner.core
OLD_PATH = "backend/research/architecture_factory/a1_external_research_exact8_through_a3_v1.py"
BASE_SHA = "d57993aa4168bb2bf9546fe3af1c6ce7d27a9c23"
BOUNDARY = int(NEW.read(NEW.BOUNDARY_PATH)["boundary_ms"])
DATA_CUTOFF = 1787227200000  # 2026-08-20T12:00Z; earlier than 2026-08-21 G5 boundary
ASSERT_DATA_BEFORE = int(datetime(2026, 8, 20, 12, tzinfo=timezone.utc).timestamp() * 1000)
assert DATA_CUTOFF == ASSERT_DATA_BEFORE and DATA_CUTOFF < BOUNDARY
TF = {300000: "5m", 3600000: "1h"}
WINDOWS = {
    300000: (int(datetime(2026, 8, 18, tzinfo=timezone.utc).timestamp() * 1000), DATA_CUTOFF),
    3600000: (int(datetime(2026, 8, 9, tzinfo=timezone.utc).timestamp() * 1000), DATA_CUTOFF),
}
LIMITS = {300000: 900, 3600000: 360}
ROOT = Path("out/issue1424_real_dev_parity")
ROOT.mkdir(parents=True, exist_ok=True)
report = {
    "schema": "zel.issue1424.preboundary_readonly_parity.v1",
    "state": "HOLD_PREBOUNDARY_SOURCE_NOT_YET_AUTHENTICATED",
    "base_sha": BASE_SHA,
    "optimized_sha": "a44020cae9f9ec8d15ef38a8ff46310cda6e9e99",
    "formal_credit": 0,
    "economic_candidate_claim": False,
    "selection_authority": False,
    "promotion_authority": False,
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "no_heldout_outcomes_accessed": True,
    "no_new_economic_evaluation": True,
    "g5_fresh_boundary_ms": BOUNDARY,
    "max_source_ts_exclusive": DATA_CUTOFF,
    "source": [],
    "lanes": [],
}

def persist() -> None:
    (ROOT / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")

def get_source(symbol: str, timeframe_ms: int) -> list[dict]:
    start, end = WINDOWS[timeframe_ms]
    params = {
        "symbol": symbol,
        "interval": TF[timeframe_ms],
        "startTime": start,
        "endTime": end,
        "limit": LIMITS[timeframe_ms],
    }
    url = "https://open-api.bingx.com/openApi/swap/v3/quote/klines?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent":"zel-pr1424-preboundary-cpu-parity/1.0"})
    with urllib.request.urlopen(request, timeout=22) as response:
        raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("SOURCE_RESPONSE_NOT_JSON") from exc
    if isinstance(value, dict) and value.get("code") not in (None, 0, "0"):
        raise RuntimeError("SOURCE_EXCHANGE_ERROR:" + str(value.get("code")))
    arr = source_audit.extract_rows(value)
    primary_count = len(arr)
    primary_sha = digest
    fallback_count = None
    fallback_sha = None
    retrieval_mode = "START_AND_END"
    if not arr:
        # One bounded alternate public endpoint parameterization, not a replay retry.
        time.sleep(1.1)
        end_only = {
            "symbol": symbol, "interval": TF[timeframe_ms],
            "endTime": end, "limit": LIMITS[timeframe_ms],
        }
        end_url = "https://open-api.bingx.com/openApi/swap/v3/quote/klines?" + urllib.parse.urlencode(end_only)
        with urllib.request.urlopen(
            urllib.request.Request(end_url, headers={"Accept":"application/json","User-Agent":"zel-pr1424-preboundary-cpu-parity/1.0"}),
            timeout=22,
        ) as response:
            fallback_raw = response.read()
        fallback_sha = hashlib.sha256(fallback_raw).hexdigest()
        try:
            fallback_value = json.loads(fallback_raw.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("SOURCE_ENDTIME_RESPONSE_NOT_JSON") from exc
        if isinstance(fallback_value, dict) and fallback_value.get("code") not in (None, 0, "0"):
            raise RuntimeError("SOURCE_ENDTIME_EXCHANGE_ERROR:" + str(fallback_value.get("code")))
        fallback = source_audit.extract_rows(fallback_value)
        fallback_count = len(fallback)
        if fallback:
            raw, digest, arr = fallback_raw, fallback_sha, fallback
            retrieval_mode = "END_ONLY_PREBOUNDARY"
    if len(arr) < 125:
        report.setdefault("blocked_source_requests", []).append({
            "symbol": symbol, "timeframe": TF[timeframe_ms],
            "start_end_count": primary_count, "start_end_raw_sha256": primary_sha,
            "end_only_count": fallback_count, "end_only_raw_sha256": fallback_sha,
            "exchange_response_code": value.get("code") if isinstance(value, dict) else None,
            "no_private_credentials_used": True,
        })
        raise RuntimeError(f"SOURCE_BARS_TOO_FEW_BOTH_PARAM_FORMS:{symbol}:{TF[timeframe_ms]}:{len(arr)}")
    audit, closed = source_audit.audit_stream(arr, symbol=symbol, timeframe_ms=timeframe_ms, now_ms=end+3*timeframe_ms)
    if audit["state"] != "PASS_SOURCE_STREAM_INTEGRITY":
        raise RuntimeError(f"SOURCE_AUDIT_INVALID:{symbol}:{TF[timeframe_ms]}:{audit['state']}:{audit.get('blockers')}")
    # End-only responses can extend earlier than the pinned interval. Select only
    # already-completed pre-fresh-bounded bars, without inventing or filling gaps.
    closed = [row for row in closed if start <= int(row["ts_ms"]) < end]
    if len(closed) < 125:
        raise RuntimeError("SOURCE_TOO_FEW_VERIFIED_BARS_IN_DEV_WINDOW")
    if min(int(x["ts_ms"]) for x in closed) < start or max(int(x["ts_ms"]) for x in closed) >= end:
        raise RuntimeError(f"NOT_PREBOUNDARY_FIXED_DEV_WINDOW:{symbol}:{TF[timeframe_ms]}")
    if any(int(x["ts_ms"]) >= BOUNDARY for x in closed):
        raise RuntimeError("FORBIDDEN_G5_FRESH_TIMESTAMP")
    if any(int(x["ts_ms"]) % timeframe_ms for x in closed):
        raise RuntimeError("BARS_NOT_ON_CLOSED_TIMEFRAME_GRID")
    # Reproducibility: archive exactly the source response received; no silent repair.
    rawname = f"{symbol.replace('-', '')}_{TF[timeframe_ms]}.raw.json"
    (ROOT / rawname).write_bytes(raw)
    report["source"].append({
        "retrieval_mode": retrieval_mode,
        "symbol": symbol,
        "timeframe_ms": timeframe_ms,
        "raw_response_sha256": digest,
        "saved_raw_file": rawname,
        "raw_count": len(arr),
        "audited_closed_count": len(closed),
        "first_open_ms": int(closed[0]["ts_ms"]),
        "last_open_ms": int(closed[-1]["ts_ms"]),
        "audit_state": audit["state"],
        "interval_gap_count": audit.get("interval_gap_count"),
        "event_time_only_historical_latency_unobserved": True,
        "volume_contract_units_unproven": True,
    })
    print(json.dumps({"source":symbol+"/"+TF[timeframe_ms], "count":len(closed), "raw_sha256":digest, "first_ms":int(closed[0]["ts_ms"]), "last_ms":int(closed[-1]["ts_ms"])}),flush=True)
    return closed

def run() -> None:
    oldsource=subprocess.check_output(["git","show",BASE_SHA+":"+OLD_PATH],text=True)
    old=types.ModuleType("a1_issue1424_preboundary_old")
    old.__file__=str(Path.cwd()/OLD_PATH)
    sys.modules[old.__name__]=old
    exec(compile(oldsource,old.__file__,"exec"),old.__dict__)
    spec=NEW.read(NEW.SPEC_PATH)
    state={"streams":{},"cost_snapshot_by_symbol":{},"integrity_defects":[]}
    for sym in NEW.SYMBOLS:
        state["cost_snapshot_by_symbol"][sym]={"pretrade_verified_cost_bps":14.0}
        for tf in TF:
            rows=get_source(sym,tf)
            state["streams"][f"{sym}|{tf}"]=rows
            time.sleep(1.1)  # BingX public-market API per-IP request cadence
    for pid in NEW.SOURCE_READY:
        tf=int(spec["specs"][pid]["timeframe_ms"])
        span=[state["streams"][f"{symbol}|{tf}"] for symbol in NEW.SYMBOLS]
        warmup=int(source_audit.CANDIDATE_WARMUPS[pid])
        start=max(int(x[0]["ts_ms"])+tf*(warmup+3) for x in span)
        if start >= DATA_CUTOFF:
            raise RuntimeError(f"NO_PREBOUNDARY_DEV_WINDOW:{pid}")
        # Research test-only start. NEVER the sealed G5 boundary, stage or claim.
        state["boundary_ms"]=start
        old_start=time.perf_counter()
        before=old.replay_child(pid,state,spec)
        old_s=time.perf_counter()-old_start
        new_start=time.perf_counter()
        after=NEW.replay_child(pid,state,spec)
        new_s=time.perf_counter()-new_start
        bsha=NEW.stable_sha(before)
        asha=NEW.stable_sha(after)
        if bsha!=asha:
            raise AssertionError(f"REAL_DEV_SOURCE_LEDGER_MISMATCH:{pid}:{bsha}:{asha}")
        report["lanes"].append({
            "parent":pid,
            "child":spec["specs"][pid]["child_id"],
            "market":"BINGX_USDT_M_FUTURES_PUBLIC_KLINE",
            "symbol_count":len(NEW.SYMBOLS),
            "timeframe_ms":tf,
            "dev_test_boundary_ms":start,
            "parent_opportunities":len(before["parent_opportunities"]),
            "child_trades":len(before["child_trades"]),
            "old_hash":bsha,
            "optimized_hash":asha,
            "old_seconds":round(old_s,5),
            "new_seconds":round(new_s,5),
            "same_all_opportunities_and_trades":True,
            "zero_economic_credit":True,
        })
        print(json.dumps(report["lanes"][-1]),flush=True)
    report["state"]="PASS_PREBOUNDARY_MARKET_SOURCE_REPLAY_PARITY_ONLY_NOT_A1_A2_A3"
    report["source_count"]=len(report["source"])
    report["tested_lane_count"]=len(report["lanes"])
    report["observed_parent_opportunities"]=sum(x["parent_opportunities"] for x in report["lanes"])
    report["observed_child_trades"]=sum(x["child_trades"] for x in report["lanes"])

try:
    run()
except Exception as exc:
    report["state"]="HOLD_PREBOUNDARY_SOURCE_OR_PARITY"
    report["blocker"]=f"{type(exc).__name__}:{exc}"
    persist()
    print(json.dumps({"state":report["state"],"blocker":report["blocker"],"sources_retained":len(report["source"])}),flush=True)
    raise
persist()
print(json.dumps({"state":report["state"],"source_count":report["source_count"],"tested_lane_count":report["tested_lane_count"],"observed_child_trades":report["observed_child_trades"],"formal_credit":0}),flush=True)
