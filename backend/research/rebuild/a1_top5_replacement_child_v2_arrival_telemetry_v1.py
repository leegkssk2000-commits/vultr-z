#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import _side, _validate_side
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as v1
from backend.research.rebuild import a1_top5_replacement_child_prospective_v2 as v2

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
DEFAULT_OUT = ROOT / "out/a1_top5_replacement_child_v2_arrival_telemetry_latest.json"
SCHEMA = "zel.a1.top5.replacement_child.v2.arrival_telemetry.v1"


def _read(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return x


def _lane_telemetry(child: Mapping[str, Any], boundary_ms: int, now_ms: int) -> dict[str, Any]:
    spec = child["executable_spec"]
    interval = str(spec["bar_interval"])
    hold = int(spec["max_hold_bars"])
    entry_rule = str(spec["entry_rule"])
    side_rule = str(spec["side_rule"])
    interval_ms = int(v1.INTERVAL_MS[interval])
    raw_signal_count = 0
    actionable_signal_count = 0
    closed_candidate_count = 0
    maturing_count = 0
    awaiting_entry_count = 0
    first_signal_ts = None
    latest_signal_ts = None
    symbol_rows: dict[str, Any] = {}

    for symbol in v2.EXPECTED_SYMBOLS:
        rows = v1._bars(symbol, interval, boundary_ms, now_ms)
        if len(rows) < 60:
            symbol_rows[symbol] = {"closed_bars": len(rows), "raw_signal_count": 0, "state": "INSUFFICIENT_BARS"}
            continue
        _, engine = v1._features(rows, spec)
        engine.validate(entry_rule)
        _validate_side(side_rule, engine)
        raw: list[int] = []
        i = 50
        while i < len(rows):
            signal_ts = int(rows[i]["ts"])
            if signal_ts < boundary_ms:
                i += 1
                continue
            try:
                fire = bool(engine.eval(entry_rule, i))
            except (TypeError, ZeroDivisionError, ValueError):
                fire = False
            if fire:
                raw.append(signal_ts)
            i += 1
        raw_signal_count += len(raw)
        if raw:
            first_signal_ts = raw[0] if first_signal_ts is None else min(first_signal_ts, raw[0])
            latest_signal_ts = raw[-1] if latest_signal_ts is None else max(latest_signal_ts, raw[-1])

        # Mirror collector sequencing: after a closed candidate, skip through its exit;
        # if the first live signal has not matured yet, stop that symbol until future bars close.
        i = 50
        sym_actionable = sym_closed = sym_maturing = sym_awaiting = 0
        first_actionable_ts = None
        while i < len(rows):
            signal_ts = int(rows[i]["ts"])
            if signal_ts < boundary_ms:
                i += 1
                continue
            try:
                fire = bool(engine.eval(entry_rule, i))
            except (TypeError, ZeroDivisionError, ValueError):
                fire = False
            if not fire:
                i += 1
                continue
            _ = _side(side_rule, engine, i)
            sym_actionable += 1
            actionable_signal_count += 1
            if first_actionable_ts is None:
                first_actionable_ts = signal_ts
            entry_i = i + 1
            if entry_i >= len(rows):
                sym_awaiting += 1
                awaiting_entry_count += 1
                break
            exit_i = entry_i + hold - 1
            if exit_i >= len(rows):
                sym_maturing += 1
                maturing_count += 1
                break
            sym_closed += 1
            closed_candidate_count += 1
            i = exit_i + 1

        state = "NO_SIGNAL"
        if sym_closed:
            state = "CLOSED_CANDIDATE_AVAILABLE"
        elif sym_maturing:
            state = "SIGNAL_LIVE_MATURING"
        elif sym_awaiting:
            state = "SIGNAL_AWAITING_ENTRY_BAR"
        elif raw:
            state = "RAW_SIGNAL_SEEN"
        symbol_rows[symbol] = {
            "closed_bars": len(rows),
            "last_bar_ts": int(rows[-1]["ts"]) if rows else None,
            "raw_signal_count": len(raw),
            "first_raw_signal_ts": raw[0] if raw else None,
            "latest_raw_signal_ts": raw[-1] if raw else None,
            "collector_actionable_signal_count": sym_actionable,
            "closed_candidate_count": sym_closed,
            "maturing_count": sym_maturing,
            "awaiting_entry_count": sym_awaiting,
            "first_actionable_signal_ts": first_actionable_ts,
            "state": state,
        }

    return {
        "lane_id": child["lane_id"],
        "child_id": child["child_id"],
        "bar_interval": interval,
        "hold_bars": hold,
        "hold_hours": hold * interval_ms / 3_600_000,
        "raw_signal_count": raw_signal_count,
        "collector_actionable_signal_count": actionable_signal_count,
        "closed_candidate_count": closed_candidate_count,
        "maturing_count": maturing_count,
        "awaiting_entry_count": awaiting_entry_count,
        "first_signal_ts": first_signal_ts,
        "latest_signal_ts": latest_signal_ts,
        "symbols": symbol_rows,
    }


def run(out: Path, now_ms: int | None = None) -> dict[str, Any]:
    contract = _read(CONTRACT)
    children = v2._assert_contract(contract)
    boundary = contract["prospective_boundary"]
    boundary_ms = int(boundary["ms"])
    current_ms = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    lanes = {str(c["lane_id"]): _lane_telemetry(c, boundary_ms, current_ms) for c in children}
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_OBSERVER_ONLY_G4_V2_ARRIVAL_TELEMETRY",
        "observed_at_utc": datetime.fromtimestamp(current_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "boundary_utc": boundary["utc"],
        "boundary_ms": boundary_ms,
        "frozen_symbol_universe": list(v2.EXPECTED_SYMBOLS),
        "lane_count": len(lanes),
        "total_raw_signal_count": sum(int(x["raw_signal_count"]) for x in lanes.values()),
        "total_actionable_signal_count": sum(int(x["collector_actionable_signal_count"]) for x in lanes.values()),
        "total_closed_candidate_count": sum(int(x["closed_candidate_count"]) for x in lanes.values()),
        "total_maturing_count": sum(int(x["maturing_count"]) for x in lanes.values()),
        "total_awaiting_entry_count": sum(int(x["awaiting_entry_count"]) for x in lanes.values()),
        "economic_pass_credit": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "paid_provider_calls": 0,
        "alpha_mutated": False,
        "threshold_mutated": False,
        "cost_model_mutated": False,
        "lanes": lanes,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = _read(CONTRACT)
    children = v2._assert_contract(c)
    assert len(children) == 3
    assert all(int(x["executable_spec"]["max_hold_bars"]) in {6, 12} for x in children)
    print("PASS_G4_V2_ARRIVAL_TELEMETRY_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--now-ms", type=int)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out, args.now_ms)
    print(json.dumps({
        "state": r["state"],
        "raw": r["total_raw_signal_count"],
        "actionable": r["total_actionable_signal_count"],
        "maturing": r["total_maturing_count"],
        "closed_candidates": r["total_closed_candidate_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
