#!/usr/bin/env python3
"""Archived transform semantics on synthetic OHLC only; never a strategy repair.

Only the hash-pinned transform function is compiled. Its imports, main,
build_parent and native network/economic dependencies are never executed.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any


NATIVE_SHA256 = "44a682e474ca73eb2b2fa5bb1860f40a2c332c36d42eb9590aba617848df62f8"
NATIVE_BASENAME = "a1_trend_rider_delayed_fill_evaluator_v1.py"
HOUR_MS = 3_600_000
BASE_MS = 1_700_002_800_000
CONTRACT = {"challenger_id": "SYNTHETIC_ARCHIVED_SEMANTICS_ONLY",
            "changed_axis": "NONE_DIAGNOSTIC_NOT_A_CHILD"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def extract_transform(native_source: Path) -> tuple[ast.FunctionDef, dict[str, Any]]:
    raw = Path(native_source).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != NATIVE_SHA256:
        raise ValueError("NATIVE_SOURCE_SHA256_MISMATCH")
    source = raw.decode("utf-8")
    tree = ast.parse(source, filename=NATIVE_BASENAME)
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name == "transform"]
    if len(found) != 1 or found[0].decorator_list:
        raise ValueError("EXPECTED_ONE_UNDECORATED_TRANSFORM")
    function = found[0]
    # Hash verification precedes parsing/compilation. No other top-level node runs.
    if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(function)):
        raise ValueError("UNEXPECTED_IMPORT_INSIDE_TRANSFORM")
    needles = {
        "completed_rows_only": "symbols = sorted({str(x[\"symbol\"]) for x in parent.get(\"trades\") or []})",
        "signal_stop": "stop = signal_close - 1.5 * signal_atr",
        "stop_exact_fill": "exit_price = float(stop)",
        "timeout_close_price": "exit_price = float(bars[last][\"close\"])",
        "inherited_cost": "cost = float(trade[\"realized_cost_bps\"])",
        "bar_open_exit_timestamp": "\"exit_ts\": int(bars[exit_index][\"ts_ms\"])",
        "shallow_parent_receipt": "receipt = dict(parent)",
    }
    lines = source.splitlines()
    source_lines = {key: [i for i, line in enumerate(lines, 1) if needle in line]
                    for key, needle in needles.items()}
    return function, {
        "native_source_name": NATIVE_BASENAME,
        "native_source_sha256": actual,
        "expected_native_source_sha256": NATIVE_SHA256,
        "compiled_native_functions": ["transform"],
        "transform_line_start": function.lineno,
        "transform_line_end": function.end_lineno,
        "transform_ast_sha256": hashlib.sha256(ast.dump(function, include_attributes=False).encode()).hexdigest(),
        "source_lines": source_lines,
        "native_module_imported": False,
        "native_main_or_build_parent_executed": False,
    }


def bars(values: list[tuple[float, float, float, float]]) -> list[dict[str, float | int]]:
    rows = []
    for index, (op, hi, lo, cl) in enumerate(values):
        if not lo <= min(op, cl) <= max(op, cl) <= hi:
            raise ValueError("INVALID_SYNTHETIC_OHLC")
        rows.append({"ts_ms": BASE_MS + index * HOUR_MS,
                     "open": op, "high": hi, "low": lo, "close": cl})
    return rows


def parent_fixture() -> dict[str, Any]:
    return {
        "completed_trades": 1, "intent_count": 3, "config_sha": "synthetic-parent-config",
        "trades": [{"symbol": "BTC-USDT", "signal_ts": BASE_MS,
                    "entry_ts": BASE_MS + HOUR_MS, "exit_ts": BASE_MS + 2 * HOUR_MS,
                    "side": "long", "entry": 100.0, "exit": 101.0,
                    "gross_bps": 100.0, "realized_cost_bps": 17.25, "net_bps": 82.75,
                    "intent_sha": "synthetic-intent", "cost_snapshot_sha": "synthetic-cost",
                    "intent_geometry": {"sl": 85.0, "tp": None, "timeout": {"bars": 48}}}],
        "open_intents": [{"symbol": "ETH-USDT", "intent_sha": "synthetic-open",
                          "entry_ts": BASE_MS + HOUR_MS,
                          "ownership_reserved_through_ts": BASE_MS + 4 * HOUR_MS}],
        "ownership_rejected_intents": [{"symbol": "SOL-USDT", "intent_sha": "synthetic-reject",
                                       "reason": "PYRAMIDING_OR_COOLDOWN_BLOCK"}],
        "native_policy_ownership": {"raw_intent_count": 3, "admitted_open_intent_count": 1,
                                    "admitted_completed_trade_count": 1, "rejected_intent_count": 1},
    }


def invoke(function: ast.FunctionDef, rows: list[dict[str, Any]],
           parent: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute exactly one synthetic closed lifecycle with explicit dependencies."""
    calls: dict[str, Any] = {"synthetic_fetch_calls": [], "atr_calls": [],
                             "policy_helper_calls": 0, "metrics_calls": 0}
    parent = copy.deepcopy(parent_fixture() if parent is None else parent)

    def fetch(symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        if (symbol, interval, limit) != ("BTC-USDT", "1h", 1000):
            raise ValueError("UNEXPECTED_SYNTHETIC_FETCH_ARGUMENTS")
        calls["synthetic_fetch_calls"].append({"symbol": symbol, "interval": interval, "limit": limit})
        return copy.deepcopy(rows)

    def fake_atr(prefix: list[dict[str, Any]], length: int) -> float:
        calls["atr_calls"].append({"prefix_rows": len(prefix), "length": length,
                                  "last_ts_ms": prefix[-1]["ts_ms"]})
        return 10.0

    def one_row_policy(values: list[dict[str, Any]], config: Any) -> tuple[list, list]:
        if len(values) > 1:
            raise ValueError("HARNESS_HAS_NO_MULTI_TRADE_POLICY_AUTHORITY")
        calls["policy_helper_calls"] += 1
        return values, []

    def fake_metrics(values: list[dict[str, Any]]) -> dict[str, Any]:
        calls["metrics_calls"] += 1
        return {"harness_stub": True, "row_count": len(values)}

    namespace = {
        "__builtins__": {name: value for name, value in {
            "dict": dict, "list": list, "str": str, "int": int, "float": float,
            "sorted": sorted, "len": len, "min": min, "max": max, "sum": sum,
            "enumerate": enumerate, "range": range, "RuntimeError": RuntimeError,
        }.items()},
        "Any": Any,
        "policy": SimpleNamespace(TrendPolicyConfig=lambda: SimpleNamespace(
            timeframe_ms=HOUR_MS, atr_len=14, timeout_bars=48)),
        "v1": SimpleNamespace(fetch_bars=fetch), "atr": fake_atr,
        "enforce_policy_execution": one_row_policy, "metrics": fake_metrics,
        "stable_sha": digest,
    }
    module = ast.Module(body=[copy.deepcopy(function)], type_ignores=[])
    exec(compile(module, NATIVE_BASENAME + "::transform-only", "exec"), namespace)
    result = namespace["transform"](parent, copy.deepcopy(CONTRACT))
    return result, calls


def run_diagnostics(native_source: Path) -> dict[str, Any]:
    function, provenance = extract_transform(native_source)
    prefix = [(100, 101, 99, 100), (100, 102, 98, 101)]
    paths = {
        "adverse_entry_gap": bars(prefix + [(80, 82, 78, 79), (79, 81, 77, 80), (80, 82, 79, 81)]),
        "later_gap": bars(prefix + [(100, 101, 95, 100), (80, 82, 78, 79), (79, 81, 77, 80)]),
        "timeout": bars(prefix + [(102, 104, 99, 103), (103, 105, 100, 104), (104, 112, 102, 110)]),
    }
    outcomes, call_logs = {}, {}
    for name, synthetic in paths.items():
        outcomes[name], call_logs[name] = invoke(function, synthetic)
    gap = outcomes["adverse_entry_gap"]["trades"][0]
    later = outcomes["later_gap"]["trades"][0]
    timeout = outcomes["timeout"]["trades"][0]
    original = parent_fixture()
    checks: dict[str, Any] = {}

    def record(name: str, expected: dict, observed: dict, confirmed: bool,
               interpretation: str) -> None:
        if not confirmed:
            raise AssertionError("ARCHIVED_COUNTEREXAMPLE_NOT_REPRODUCED:" + name)
        checks[name] = {"status": "ARCHIVED_BEHAVIOR_REPRODUCED",
                        "expected_native_behavior": expected, "observed": observed,
                        "interpretation": interpretation}

    record("long_adverse_entry_beyond_initial_stop",
           {"initial_stop": 85.0, "delayed_open": 80.0, "exit": 85.0, "reason": "SL"},
           {"entry": gap["entry"], "exit": gap["exit"], "reason": gap["reason"],
            "exit_bar_high": 82.0, "gross_bps": gap["gross_bps"], "net_bps": gap["net_bps"]},
           gap["entry"] == 80 and gap["exit"] == 85 and gap["reason"] == "SL" and gap["exit"] > 82,
           "Native long SL fill is above delayed entry and outside that entire bar's high/low range. No canonical replacement fill is selected.")
    record("later_bar_gap_through_stop",
           {"entry": 100.0, "gap_open": 80.0, "bar_high": 82.0, "native_stop_fill": 85.0},
           {"entry": later["entry"], "exit": later["exit"], "reason": later["reason"],
            "exit_ts": later["exit_ts"], "gross_bps": later["gross_bps"]},
           later["entry"] == 100 and later["exit"] == 85 and later["reason"] == "SL"
           and later["exit_ts"] == BASE_MS + 3 * HOUR_MS,
           "The gap bar never trades at 85; native transform fills exactly at the original stop, without an open-gap branch.")
    record("timeout_close_value_with_bar_open_timestamp",
           {"exit_price": 110.0, "exit_ts": BASE_MS + 4 * HOUR_MS,
            "close_available_not_before": BASE_MS + 5 * HOUR_MS},
           {"reason": timeout["reason"], "exit": timeout["exit"], "exit_ts": timeout["exit_ts"],
            "timestamp_lead_ms_relative_to_synthetic_bar_close": HOUR_MS},
           timeout["reason"] == "TIMEOUT" and timeout["exit"] == 110
           and timeout["exit_ts"] == BASE_MS + 4 * HOUR_MS,
           "Synthetic rows use 1h bar-open ts_ms. A terminal close price is stamped one hour before that close is available.")
    record("parent_cost_copied_after_changed_entry_and_exit",
           {"realized_cost_bps": 17.25, "parent_entry": 100.0, "parent_exit": 101.0},
           {"new_entry": timeout["entry"], "new_exit": timeout["exit"],
            "parent_entry_ts": timeout["parent_entry_ts"], "new_entry_ts": timeout["entry_ts"],
            "parent_cost_bps": 17.25, "new_cost_bps": timeout["realized_cost_bps"],
            "new_gross_bps": timeout["gross_bps"], "new_net_bps": timeout["net_bps"]},
           timeout["entry"] == 102 and timeout["exit"] == 110
           and timeout["realized_cost_bps"] == 17.25
           and abs(timeout["net_bps"] - (timeout["gross_bps"] - 17.25)) < 1e-9,
           "Parent aggregate realized cost is retained. This transform does not recompute time-dependent funding or changed execution costs.")
    record("short_available_horizon_forced_to_timeout",
           {"configured_timeout_bars": 48, "available_bar_index_distance_after_delayed_entry": 2,
            "native_reason": "TIMEOUT", "native_not_closed_count": 0},
           {"reason": timeout["reason"], "last_available_bar_ts": paths["timeout"][-1]["ts_ms"],
            "exit_ts": timeout["exit_ts"],
            "not_closed_after_delay_count": outcomes["timeout"]["delayed_fill_integrity"]["not_closed_after_delay_count"]},
           timeout["reason"] == "TIMEOUT" and timeout["exit_ts"] == paths["timeout"][-1]["ts_ms"]
           and outcomes["timeout"]["delayed_fill_integrity"]["not_closed_after_delay_count"] == 0,
           "With this minimal available horizon, min(last_bar, entry+48) still closes at the final available bar. This is not proof that 48 bars elapsed.")
    state_fields = ("open_intents", "ownership_rejected_intents", "native_policy_ownership")
    record("inherited_open_and_rejected_state_not_replayed",
           {"fields_retained_verbatim": list(state_fields), "synthetic_fetch_symbols": ["BTC-USDT"]},
           {"fields_equal_parent": {key: outcomes["timeout"][key] == original[key] for key in state_fields},
            "synthetic_fetch_symbols": [call["symbol"] for call in call_logs["timeout"]["synthetic_fetch_calls"]],
            "open_symbol": "ETH-USDT", "rejected_symbol": "SOL-USDT"},
           all(outcomes["timeout"][key] == original[key] for key in state_fields)
           and len(call_logs["timeout"]["synthetic_fetch_calls"]) == 1,
           "Only parent completed trades feed transform. Open/rejected parent records and ownership summary survive the shallow receipt copy; their symbols are not replayed.")

    annotated_parent = parent_fixture()
    annotated_parent["trades"][0]["intent_geometry"].update({
        "partial": {"enabled": True, "fraction": 0.5, "take_profit_r": 0.1},
        "trailing": {"enabled": True, "type": "synthetic_annotation_only"},
        "runner": {"enabled": True}})
    annotated, call_logs["inert_management_annotations"] = invoke(function, paths["timeout"], annotated_parent)
    actual_fields = ("entry", "exit", "entry_ts", "exit_ts", "reason", "gross_bps", "net_bps", "realized_cost_bps")
    literals = {node.value for node in ast.walk(function)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    record("partial_trailing_annotations_not_executed_by_transform",
           {"same_execution_fields": list(actual_fields), "transform_has_management_field_literals": False},
           {"execution_fields_unchanged": {key: annotated["trades"][0][key] == timeout[key] for key in actual_fields},
            "management_field_literals_present": sorted(literals & {"partial", "trailing", "runner"})},
           all(annotated["trades"][0][key] == timeout[key] for key in actual_fields)
           and not literals & {"partial", "trailing", "runner"},
           "Diagnostic annotations are inert and transform implements no partial/trailing/runner branch. The annotations are not claimed to be the archived sealed-intent schema or a repaired policy.")
    return {
        "schema": "zel.trend256.archived_native_lifecycle_counterexamples.v1",
        "classification": "SYNTHETIC_SOURCE_SEMANTICS_ONLY_NOT_ECONOMIC_RESULT",
        "provenance": provenance, "checks": checks, "synthetic_bars": paths,
        "harness": {"config": {"timeframe_ms": HOUR_MS, "atr_len": 14, "timeout_bars": 48},
                    "atr": "constant 10.0; not native ATR computation or warmup validation",
                    "policy_helper": "single-row passthrough; native policy helper NOT executed, rejects multi-row harness use",
                    "metrics": "stub count only; no native economics engine",
                    "hash": "local deterministic JSON SHA256 stub; no native hash parity claim",
                    "calls": call_logs},
        "limitations": [
            "No archived 256T ledger is loaded, replayed, repriced or altered.",
            "These fixtures identify source semantics; they do not measure their incidence or PnL impact in 256T.",
            "No child adapter, revised fill policy, threshold, candidate ranking or economic recommendation is created.",
            "The multi-trade transition/cooldown helper, native ATR and signal formation are outside this isolated test.",
        ],
        "actual_price_rows_used": 0, "market_api_calls": 0, "new_economic_full_runs": 0,
        "archived_trades_repriced": 0, "orders": 0,
        "authority": {"order_authority": "BLOCKED", "selection": False, "promotion": False},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-source", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="Optional new JSON path; existing files are never overwritten")
    args = parser.parse_args(argv)
    report = run_diagnostics(args.native_source)
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
