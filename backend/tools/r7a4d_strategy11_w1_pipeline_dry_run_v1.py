from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.tools import r7a4d_strategy11_data_wait_pool_compute_v1 as compute

VERSION = "R7A4D_STRATEGY11_W1_PIPELINE_DRY_RUN_V1"


def write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def frame(start_ms: int, end_ms: int, rows: int) -> pd.DataFrame:
    stamps = np.arange(start_ms, end_ms + compute.INTERVAL_MS, compute.INTERVAL_MS, dtype=np.int64)
    if len(stamps) != rows:
        raise RuntimeError(f"FIXTURE_BOUNDARY_ROWS:{len(stamps)}!={rows}")
    price = np.linspace(100.0, 104.0, rows)
    return pd.DataFrame({
        "timestamp_ms": stamps,
        "open": price,
        "high": price + 0.8,
        "low": price - 0.8,
        "close": price + 0.2,
        "volume": np.linspace(1000.0, 2000.0, rows),
    })


def funding(start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    points = np.linspace(start_ms, end_ms, 6, dtype=np.int64)
    rates = (0.00001, 0.00002, 0.00003, 0.00004, 0.00005, 0.00006)
    return [{"timestamp_ms": int(ts), "funding_rate": rate} for ts, rate in zip(points, rates)]


def blocked_defect(out: Path, authority_end_ms: int, ready_now_ms: int, defect: str) -> str:
    original = compute.base._fetch_exact

    def bad(symbol: str, *, start_ms: int, end_ms: int, expected_rows: int):
        data = frame(start_ms, end_ms, expected_rows)
        if symbol == compute.SYMBOLS[0]:
            if defect == "duplicate":
                data.loc[1, "timestamp_ms"] = data.loc[0, "timestamp_ms"]
            elif defect == "gap":
                data.loc[1:, "timestamp_ms"] += compute.INTERVAL_MS
            elif defect == "ohlc":
                data.loc[10, "low"] = data.loc[10, "high"] + 1.0
            elif defect == "rows":
                data = data.iloc[:-1].copy()
        return data, "fixture://market", 1

    compute.base._fetch_exact = bad
    try:
        try:
            compute.collect_window(out=out, authority_end_ms=authority_end_ms, now_ms=ready_now_ms)
        except RuntimeError as exc:
            text = str(exc)
            if text.startswith("W1_MARKET_INVALID"):
                return text
            raise
        raise RuntimeError(f"DEFECT_NOT_BLOCKED:{defect}")
    finally:
        compute.base._fetch_exact = original


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--compute-source", required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    source_path = Path(args.compute_source).resolve()
    source_text = source_path.read_text(encoding="utf-8")

    authority_end_ms = int(pd.Timestamp("2026-07-27T08:30:00Z").timestamp() * 1000)
    evaluation_end_ms = authority_end_ms + compute.EVALUATION_BARS * compute.INTERVAL_MS
    ready_now_ms = evaluation_end_ms + compute.INTERVAL_MS
    old_fetch, old_funding = compute.base._fetch_exact, compute.evidence.fetch_funding

    def good_fetch(symbol: str, *, start_ms: int, end_ms: int, expected_rows: int):
        return frame(start_ms, end_ms, expected_rows), f"fixture://market/{symbol}", 1

    def good_funding(symbol: str, start_ms: int, end_ms: int):
        return funding(start_ms, end_ms), f"fixture://funding/{symbol}"

    compute.base._fetch_exact, compute.evidence.fetch_funding = good_fetch, good_funding
    ready_root = out / "ready_fixture"
    try:
        state, manifest = compute.collect_window(out=ready_root, authority_end_ms=authority_end_ms, now_ms=ready_now_ms)
    finally:
        compute.base._fetch_exact, compute.evidence.fetch_funding = old_fetch, old_funding

    if state != "READY" or not isinstance(manifest, Mapping):
        raise RuntimeError(f"READY_FIXTURE_FAILED:{state}")
    if manifest.get("evaluation_bars") != 480 or manifest.get("warmup_bars") != 220:
        raise RuntimeError("WINDOW_CONTRACT_MISMATCH")
    if set(row.get("symbol") for row in manifest.get("files", [])) != set(compute.SYMBOLS):
        raise RuntimeError("SYMBOL_SET_MISMATCH")
    if [int(row.get("rows") or 0) for row in manifest["files"]] != [700] * 5:
        raise RuntimeError("MARKET_ROWS_NOT_700")

    frames, features, funding_map = compute.load_window(ready_root, manifest)
    if (len(frames), len(features), len(funding_map)) != (5, 5, 5):
        raise RuntimeError("LOAD_WINDOW_SET_MISMATCH")
    quantiles = compute.evidence.funding_rate_quantiles(funding_map)
    if any(set(values) != {"p75", "p95"} or values["p75"] > values["p95"] for values in quantiles.values()):
        raise RuntimeError("FUNDING_QUANTILE_CONTRACT_FAIL")

    symbol = compute.SYMBOLS[0]
    entry = compute.iso(int(manifest["evaluation_start_ms"]))
    exit_ = compute.iso(int(manifest["evaluation_end_ms"]))
    trade = {"symbol": symbol, "entry_ts": entry, "exit_ts": exit_, "initial_qty": 1.0, "qty_timeline": [{"ts": entry, "qty": 1.0}], "net_return_pct_before_funding": 1.0}
    scenarios: dict[str, float] = {}
    for scenario in ("OBSERVED", "ADVERSE_P75", "ADVERSE_P95"):
        adjusted = compute.evidence.apply_funding([trade], funding_map, scenario, quantiles)[0]
        scenarios[scenario] = float(adjusted.get("funding_cost_pct") or 0.0)
    if scenarios["ADVERSE_P75"] > scenarios["ADVERSE_P95"]:
        raise RuntimeError("FUNDING_STRESS_ORDER_FAIL")

    wait_state, wait_payload = compute.collect_window(
        out=out / "wait_fixture",
        authority_end_ms=authority_end_ms,
        now_ms=authority_end_ms + 100 * compute.INTERVAL_MS,
    )
    if wait_state != "WAIT_DATA" or int((wait_payload or {}).get("missing_bars") or 0) != 381:
        raise RuntimeError(f"WAIT_DATA_TRANSITION_FAIL:{wait_payload}")

    defect_results = {name: blocked_defect(out / f"defect_{name}", authority_end_ms, ready_now_ms, name) for name in ("duplicate", "gap", "ohlc", "rows")}
    ids = ["alpha_combo", "turtle_trend", "ema_ribbon_scalp"] + [f"pool_{index:02d}" for index in range(22)]
    pool = [value for value in ids if value not in compute.PRIMARY_REVIEW_QUEUE]
    if len(pool) != 22 or set(pool) & compute.PRIMARY_REVIEW_QUEUE:
        raise RuntimeError("PRIMARY_EXCLUSION_FAIL")

    lineage = compute.add_lineage([{"symbol": symbol, "entry_ts": entry, "exit_ts": exit_}], strategy_id="pool_00", candidate_sha="fixture-config-sha", manifest=manifest)
    if not lineage[0].get("trade_id") or not lineage[0].get("market_file_sha256"):
        raise RuntimeError("PER_TRADE_LINEAGE_FAIL")

    static = {
        "evaluation_480": "EVALUATION_BARS = 480" in source_text,
        "warmup_220": "WARMUP_BARS = 220" in source_text,
        "five_symbols": "BTCUSDT" in source_text and "LINKUSDT" in source_text,
        "primary_exclusion": "PRIMARY_REVIEW_QUEUE" in source_text,
        "active_candidate_cap_3": "active = queue[:3]" in source_text,
        "candidate_zero_to_next_window": "WAIT_NEXT_NON_OVERLAP_480_BAR_WINDOW" in source_text,
        "observed_funding": '"OBSERVED"' in source_text,
        "p95_funding": '"ADVERSE_P95"' in source_text,
        "protected_mutations_zero": '"protected_mutations": 0' in source_text,
    }
    if not all(static.values()):
        raise RuntimeError(f"STATIC_COMPUTE_CONTRACT_FAIL:{static}")

    result = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_PIPELINE_CONTRACT",
        "fixture_only": True,
        "performance_claim_allowed": False,
        "source_compute_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "ready_contract": {
            "evaluation_bars": manifest["evaluation_bars"],
            "warmup_bars": manifest["warmup_bars"],
            "symbols": list(compute.SYMBOLS),
            "rows_per_symbol": [row["rows"] for row in manifest["files"]],
            "evaluation_start": manifest["evaluation_start"],
            "evaluation_end": manifest["evaluation_end"],
            "manifest_file_count": len(manifest["files"]),
            "funding_event_counts": manifest["funding_event_counts"],
        },
        "funding_scenarios": scenarios,
        "negative_fixture_blocks": defect_results,
        "wait_data_contract": dict(wait_payload or {}),
        "pool_contract": {"input_count": 25, "primary_excluded": sorted(compute.PRIMARY_REVIEW_QUEUE), "pool_count": len(pool)},
        "lineage_contract": {"state": "PASS", "trade_id": lineage[0]["trade_id"], "market_file_sha256": lineage[0]["market_file_sha256"]},
        "static_contract": static,
        "next": "EVIDENCE_VISUALIZATION_READY",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    write(out / "summary.json", result)
    print(json.dumps({"state": result["state"], "defects_blocked": len(defect_results), "pool": len(pool), "next": result["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
