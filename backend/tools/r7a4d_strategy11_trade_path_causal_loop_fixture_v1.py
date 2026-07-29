from __future__ import annotations

import argparse
import copy
import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.research.strategy11_pre_shadow_path_optimize_planner_v1 import build_plan, canonical_sha, read_json, write_json
from backend.research.strategy11_trade_path_enricher_v1 import file_sha

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
VERSION = "R7A4D_STRATEGY11_TRADE_PATH_CAUSAL_LOOP_FIXTURE_V1"


def iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def build_market(path: Path) -> list[dict[str, Any]]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(120):
        timestamp_ms = int((start + timedelta(minutes=15 * index)).timestamp() * 1000)
        rows.append({
            "timestamp_ms": timestamp_ms,
            "open": 100.0,
            "high": 100.1,
            "low": 99.9,
            "close": 100.0,
            "volume": 1000.0 + index,
        })
    signal_indices = [5, 23, 41, 59, 77, 95]
    for trade_index, signal_index in enumerate(signal_indices):
        entry = signal_index + 1
        exit_index = entry + 4
        rows[signal_index].update(open=100.0, high=100.1, low=99.9, close=100.0)
        rows[entry].update(open=100.0, high=100.6, low=99.9, close=100.4)
        rows[entry + 1].update(open=100.4, high=101.2, low=100.0, close=100.7)
        rows[entry + 2].update(open=100.7, high=100.9, low=99.8, close=100.1)
        rows[entry + 3].update(open=100.1, high=100.3, low=99.7, close=99.9)
        if trade_index == 0:
            rows[exit_index].update(open=99.9, high=100.0, low=98.9, close=99.0)
            rows[exit_index + 1].update(open=99.0, high=100.0, low=98.9, close=99.8)
        else:
            rows[exit_index].update(open=99.9, high=100.0, low=99.7, close=99.8)
            rows[exit_index + 1].update(open=99.8, high=100.0, low=99.7, close=99.9)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_ms", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def build_trade(index: int, rows: list[dict[str, Any]], market_sha: str) -> dict[str, Any]:
    signal_indices = [5, 23, 41, 59, 77, 95]
    signal_index = signal_indices[index]
    entry_index = signal_index + 1
    exit_index = entry_index + 4
    stop = index == 0
    exit_price = 99.0 if stop else 99.8
    return {
        "trade_id": f"fixture-trade-{index:02d}",
        "window_id": "F1",
        "symbol": "BTCUSDT",
        "variant_id": "NEAR_MFE",
        "signal_ts": iso(rows[signal_index]["timestamp_ms"]),
        "entry_ts": iso(rows[entry_index]["timestamp_ms"]),
        "exit_ts": iso(rows[exit_index]["timestamp_ms"]),
        "entry_price": 100.0,
        "exit_price": exit_price,
        "initial_sl": 99.0,
        "initial_tp": 103.0,
        "risk_price": 1.0,
        "net_loss_r": -0.8 if stop else -0.2,
        "mfe_r": 1.2,
        "mae_r": 0.3,
        "bars_to_mfe": 2,
        "bars_to_mae": 3,
        "bars_held": 4,
        "exit_reason": "SL" if stop else "TIME_STOP",
        "signal_skill": "TREND",
        "signal_why": "fixture-mfe-giveback",
        "path_ambiguous": False,
        "market_file_sha256": market_sha,
        "candidate_config_sha": canonical_sha({"candidate": "NEAR_MFE"}),
        "strategy_source_sha": canonical_sha({"strategy": "fixture_strategy"}),
        "features": {
            "atr14": 1.0,
            "atr_percentile": 50.0,
            "htf_trend_up": True,
            "trend_ema20_50": True,
        },
    }


def build_inputs(root: Path) -> None:
    fresh = root / "fresh"
    market_path = fresh / "market" / "F1-BTCUSDT.csv"
    rows = build_market(market_path)
    market_sha = file_sha(market_path)
    manifest = {
        "schema_version": "fixture.fresh.manifest.v1",
        "authority_data_set_sha256": canonical_sha({"fixture": "data"}),
        "authority_manifest_sha256": canonical_sha({"fixture": "manifest"}),
        "market": [{"window_id": "F1", "symbol": "BTCUSDT", "sha256": market_sha}],
    }
    write_json(fresh / "manifest.json", manifest)
    replay = {
        "variant_id": "NEAR_MFE",
        "trades": [build_trade(index, rows, market_sha) for index in range(6)],
    }
    write_json(root / "replay" / "fixture_strategy" / "NEAR_MFE" / "replay-A.json", replay)


def build_triage(path: Path) -> dict[str, Any]:
    triage = {
        "schema_version": "strategy11.source_bound_replay_triage.v1.1",
        "state": "PASS_SOURCE_BOUND_REPLAY_TRIAGE",
        "duplicate_strategy_axis_config_data_count": 0,
        "rows": [{
            "strategy_id": "fixture_strategy",
            "strategy_state": "NEAR_PASS_LOSS_SHAPE",
            "l090_survivor_ids": [],
            "near_pass_ids": ["NEAR_MFE"],
            "candidates": [{"candidate_id": "NEAR_MFE", "relation": {"state": "NEAR_PASS_LOSS_SHAPE"}}],
        }],
        **SAFETY,
    }
    triage["triage_sha"] = canonical_sha(triage)
    write_json(path, triage)
    return triage


def build_ledger(path: Path) -> dict[str, Any]:
    ledger = {
        "schema_version": "strategy11.search_ledger.fixture.v1",
        "state": "PASS_FIXTURE_SEARCH_LEDGER",
        "duplicate_strategy_axis_data_runs": 0,
        "rows": [{
            "strategy_id": "fixture_strategy",
            "incumbent_candidate_sha": canonical_sha({"incumbent": "fixture"}),
            "tested_axes": ["ENTRY_CONTEXT_GATE"],
            "axis_generation_count": {"ENTRY_CONTEXT_GATE": 1, "MFE_TRAILING": 0, "PARTIAL": 0},
            "tested_candidate_ids": [],
            "selected_candidate_ids": [],
            "remaining_axes": ["MFE_TRAILING", "PARTIAL", "BREAKEVEN", "STOP", "TARGET", "TIME_STOP"],
            "next_axis": "MFE_TRAILING",
        }],
        **SAFETY,
    }
    write_json(path, ledger)
    return ledger


def run(command: list[str]) -> None:
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(f"COMMAND_FAILED:{process.returncode}:{process.stdout}:{process.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--enricher", type=Path, required=True)
    parser.add_argument("--planner", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    build_inputs(args.root)
    triage = build_triage(args.root / "triage.json")
    ledger = build_ledger(args.root / "search_ledger.json")

    run([
        sys.executable, str(args.enricher),
        "--replay-root", str(args.root / "replay"),
        "--fresh-root", str(args.root / "fresh"),
        "--out", str(args.root / "path"),
    ])
    run([
        sys.executable, str(args.planner),
        "--path-index", str(args.root / "path" / "index.json"),
        "--path-root", str(args.root / "path"),
        "--triage", str(args.root / "triage.json"),
        "--search-ledger", str(args.root / "search_ledger.json"),
        "--policy", str(args.policy),
        "--out", str(args.root / "plan.json"),
    ])

    bundle = read_json(args.root / "path" / "fixture_strategy" / "NEAR_MFE" / "path_evidence.json")
    plan = read_json(args.root / "plan.json")
    assert bundle["state"] == "PASS_TRADE_PATH_EVIDENCE"
    assert bundle["event_count"] == 6
    assert bundle["duplicate_event_count"] == 0
    first = bundle["events"][0]
    assert abs(first["first3_mfe_r"] - 1.2) < 1e-9
    assert abs(first["first3_mae_r"] - 0.2) < 1e-9
    assert abs(first["pre_entry_mfe_r"]) < 1e-9
    assert first["post_stop_mfe_r"] >= 1.0
    assert abs(first["stop_distance_atr"] - 1.0) < 1e-9
    assert first["feature_lineage_sha"] and first["path_segment_sha"]

    assert plan["state"] == "PASS_PRE_SHADOW_PATH_OPTIMIZE_BATCH_PLAN"
    assert plan["candidate_count"] == 1
    assert plan["ml_light_consumed"] is False
    assert plan["failure_learning_consumed"] is False
    row = plan["rows"][0]
    assert row["basis_variant_id"] == "NEAR_MFE"
    assert row["selected_fingerprint"]["fingerprint"] == "MFE_GIVEBACK"
    proposal = row["next_candidate_proposal"]
    assert proposal["candidate_id"] == "PATH_TRAIL_R075_ATR075"
    assert proposal["axis"] == "MFE_TRAILING"
    assert proposal["single_axis"] is True
    assert proposal["replay_started"] is False

    exhausted_ledger = copy.deepcopy(ledger)
    exhausted_ledger["rows"][0]["axis_generation_count"].update({"MFE_TRAILING": 2, "PARTIAL": 2})
    exhausted = build_plan(
        path_index=read_json(args.root / "path" / "index.json"),
        path_root=args.root / "path",
        triage=triage,
        ledger=exhausted_ledger,
        policy=read_json(args.policy),
    )
    assert exhausted["candidate_count"] == 0
    assert exhausted["rows"][0]["state"] == "WAIT_NEW_EVIDENCE_AXIS_EXHAUSTED"
    write_json(args.root / "exhausted_plan.json", exhausted)

    ambiguous_triage = copy.deepcopy(triage)
    ambiguous_triage["rows"][0]["near_pass_ids"] = ["NEAR_MFE", "OTHER_NEAR"]
    ambiguous_triage["triage_sha"] = canonical_sha(ambiguous_triage)
    ambiguous = build_plan(
        path_index=read_json(args.root / "path" / "index.json"),
        path_root=args.root / "path",
        triage=ambiguous_triage,
        ledger=ledger,
        policy=read_json(args.policy),
    )
    assert ambiguous["candidate_count"] == 0
    assert ambiguous["rows"][0]["state"] == "HOLD_BASIS_AMBIGUITY"
    write_json(args.root / "ambiguous_plan.json", ambiguous)

    summary = {
        "schema_version": "strategy11.trade_path_causal_loop.fixture.summary.v1",
        "version": VERSION,
        "state": "PASS_TRADE_PATH_CAUSAL_LOOP_FIXTURE",
        "event_count": bundle["event_count"],
        "selected_fingerprint": row["selected_fingerprint"]["fingerprint"],
        "selected_candidate_id": proposal["candidate_id"],
        "selected_axis": proposal["axis"],
        "exhausted_state": exhausted["rows"][0]["state"],
        "ambiguous_state": ambiguous["rows"][0]["state"],
        "fixture_only": True,
        **SAFETY,
    }
    summary["fixture_sha"] = canonical_sha(summary)
    write_json(args.root / "summary.json", summary)
    print(summary["state"], summary["selected_fingerprint"], summary["selected_candidate_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
