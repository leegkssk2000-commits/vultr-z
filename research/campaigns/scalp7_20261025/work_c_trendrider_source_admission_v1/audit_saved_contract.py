"""Audit immutable saved TrendRider evidence; never import or replay strategy code.

Only artifact hashes, schemas, identities, clocks and contract counts are
checked. Stored economic metrics are not recomputed. Passing integrity checks
does not supply missing source eligibility or authorize a new experiment.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from typing import Mapping

HOUR_MS = 3_600_000
SOURCE_COMMIT = "93f5048dc6d57e49ddafe11bdcd1084fe5d830dd"
EXPECTED_SHA256 = {
    "freeze": "30f8d356f8a71fde7deb323a31c4339ed64e729a3623b83c5ba94f945f40431c",
    "result": "e99bbd783908628572a64875f7d019676fa5d686fdc7e7b29fd24cee2d4fab13",
    "robustness": "d3f716800de6665df0ce0465776bdb938227cf9803d9f1c1fb279d5ddc494cb3",
    "traces_gzip": "bc20d7e6b2f931cad8c5cd020fd3b396370dbf80e0bf746dd0fa1330f7e80239",
    "model_code": "c0c3a4899108508aad0db6c0b21f2d600363a4daf766d0ba7d8891978625e9ad",
    "filter_code": "a20e0977d278595d656d1560416824736144464e1eca57ebbf071cd65c49c508",
}


class AuditError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuditError(reason)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def read_json(raw: bytes) -> dict:
    value = json.loads(raw, object_pairs_hook=unique_object,
                       parse_constant=lambda value: (_ for _ in ()).throw(AuditError("NONFINITE_JSON:" + value)))
    require(isinstance(value, dict), "JSON_OBJECT_REQUIRED")
    return value


def not_run() -> dict:
    return {"status": "NOT_RUN", "T": None, "Net1x": None, "Net2x": None,
            "PF": None, "WR": None, "realized_DD": None, "account_DD": None,
            "max_loss_streak": None, "large_winner_retention": None,
            "ordinary_winner_retention": None}


def line_evidence(text: str, node: ast.AST) -> dict:
    return {"line": node.lineno, "end_line": node.end_lineno,
            "source": ast.get_source_segment(text, node)}


def static_findings(model_text: str, filter_text: str | None) -> dict:
    tree = ast.parse(model_text)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    require(all(name in functions for name in ("run_stage", "new_short_leg", "entry_loss_streak_circuit",
                                                "build_candidates", "metrics_stage")), "MODEL_INTERFACE_CHANGED")
    circuit = functions["entry_loss_streak_circuit"]
    extra_hour = [node for node in ast.walk(circuit)
                  if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
                  and isinstance(node.right, ast.Name) and node.right.id == "H"
                  and isinstance(node.left, ast.Subscript)
                  and isinstance(node.left.slice, ast.Constant) and node.left.slice.value == "end_ms"]
    short = functions["new_short_leg"]
    loops = [node for node in ast.walk(short) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "range"
             and len(node.args) == 2 and isinstance(node.args[1], ast.BinOp)
             and isinstance(node.args[1].op, ast.Add)
             and isinstance(node.args[1].left, ast.Name) and node.args[1].left.id == "s"
             and isinstance(node.args[1].right, ast.Constant) and node.args[1].right.value == 25]
    owner_end = [node for node in ast.walk(functions["run_stage"]) if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "end_ms" for t in node.targets)
                 and isinstance(node.value, ast.Subscript) and isinstance(node.value.slice, ast.Constant)
                 and node.value.slice.value == "effective_closed_at"]
    cost_lines = [node for node in ast.walk(functions["build_candidates"]) if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                          and t.slice.value == "instrument_source_cost_bps" for t in node.targets)]
    findings = {
        "loss_circuit_extra_hour_on_effective_close": bool(extra_hour and owner_end),
        "loss_circuit_clock_evidence": [line_evidence(model_text, node) for node in extra_hour + owner_end],
        "short_loop_allows_25_bars": bool(loops),
        "short_loop_evidence": [line_evidence(model_text, node) for node in loops],
        "cost_source_evidence": [line_evidence(model_text, node) for node in cost_lines],
        "calendar_metric_basis": "SIGNAL_TIMESTAMP" if 'month(int(x["signal_ts"]))' in model_text else "UNVERIFIED",
    }
    if filter_text is not None:
        filter_tree = ast.parse(filter_text)
        path_binding = [node for node in filter_tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "P" for t in node.targets)]
        baseline_reads = [node for node in ast.walk(filter_tree) if isinstance(node, ast.BinOp)
                          and isinstance(node.op, ast.Div) and isinstance(node.left, ast.Name)
                          and node.left.id == "P" and isinstance(node.right, ast.Constant)
                          and node.right.value in ("RESULT.json", "ROBUSTNESS.json")]
        findings["filter_source_cost_is_realized_field_not_entry_asof_evidence"] = (
            bool(cost_lines) and 'x["instrument_source_cost_bps"]' in filter_text)
        findings["filter_baseline_path_evidence"] = [line_evidence(filter_text, node) for node in path_binding + baseline_reads]
        findings["filter_baseline_uses_own_directory"] = bool(
            path_binding and ast.unparse(path_binding[0].value) == "Path(__file__).resolve().parent" and baseline_reads)
    return findings


def _integer(value: object, label: str) -> int:
    require(type(value) is int and value >= 0, "INVALID_CLOCK_OR_COUNT:" + label)
    return value


def audit_paths(freeze: Path, result: Path, robustness: Path, traces_gzip: Path,
                model_code: Path, filter_code: Path | None = None, *,
                expected_sha256: Mapping[str, str] | None = None) -> dict:
    """Pure audit. Explicit alternative pins are for finite synthetic fixtures.

    The CLI never accepts a caller-supplied replacement pin manifest.
    """
    paths = {"freeze": Path(freeze), "result": Path(result), "robustness": Path(robustness),
             "traces_gzip": Path(traces_gzip), "model_code": Path(model_code)}
    if filter_code is not None:
        paths["filter_code"] = Path(filter_code)
    expected = EXPECTED_SHA256 if expected_sha256 is None else expected_sha256
    blobs, pins = {}, {}
    for role, path in paths.items():
        require(path.is_file() and not path.is_symlink(), "INPUT_NOT_REGULAR_FILE:" + role)
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        require(role in expected and actual == expected[role], "SOURCE_PIN_MISMATCH:" + role)
        blobs[role] = raw
        pins[role] = {"path": str(path.resolve()), "sha256": actual, "bytes": len(raw)}
    f, r, rob = (read_json(blobs[role]) for role in ("freeze", "result", "robustness"))
    traces = read_json(gzip.decompress(blobs["traces_gzip"]))
    require(f.get("schema") == "zel.trendrider.unified_one_owner_causal_rescue.v1", "FREEZE_SCHEMA_CHANGED")
    require(r.get("schema") == "zel.trendrider.unified_one_owner_causal_rescue.result.v1", "RESULT_SCHEMA_CHANGED")
    require(rob.get("schema") == "zel.trendrider.unified_rescue.robustness.v1", "ROBUSTNESS_SCHEMA_CHANGED")
    require(traces.get("schema") == "zel.trendrider.unified.causal_exit_trace.v1", "TRACE_SCHEMA_CHANGED")
    for role, value in (("result", r.get("freeze_sha256")), ("robustness", rob.get("source_freeze_sha256")),
                        ("traces", traces.get("freeze_sha256"))):
        require(value == pins["freeze"]["sha256"], "FREEZE_LINEAGE_MISMATCH:" + role)
    require(rob.get("source_result_sha256") == pins["result"]["sha256"], "ROBUSTNESS_RESULT_LINEAGE_MISMATCH")
    require(traces.get("not_canonical_trade_ledger") is True and traces.get("live_order_authority") == "BLOCKED",
            "TRACE_AUTHORITY_CHANGED")
    counts = r["source_inputs"]["counts"]
    for key, value in {"EXACT_SIGNAL_DEDUPED": 97, "DELAYED_INVALID_NATIVE_STOP_GEOMETRY": 4,
                       "LIQUID_SELECTED": 119, "DELAYED_SELECTED": 148}.items():
        require(counts.get(key) == value and type(counts[key]) is int, "FROZEN_SOURCE_COUNT_CHANGED:" + key)
    require(set(traces["stages"]) == {"S0", "S1", "S2", "S3", "S4"} == set(r["stage_economics"]),
            "FROZEN_STAGE_SET_CHANGED")
    short_contract = [stage for stage in f["stages"] if stage["id"] == "S3_CONFIRM_REVERSAL_SHORT"]
    require(len(short_contract) == 1 and short_contract[0]["short_limit_hours"] == 24,
            "FROZEN_SHORT_LIMIT_CHANGED")
    summaries, violations = {}, []
    union_keys = None
    for stage_id, stage in sorted(traces["stages"].items()):
        accepted, rejected = stage["accepted"], stage["rejected"]
        keys = [x["key"] for x in accepted] + [x["key"] for x in rejected]
        require(len(keys) == 267 and len(set(keys)) == 267, "STAGE_PARTITION_OR_DUPLICATE_CHANGED:" + stage_id)
        require(union_keys is None or set(keys) == union_keys, "SOURCE_UNION_CHANGED_ACROSS_STAGES")
        union_keys = set(keys)
        saved = r["stage_economics"][stage_id]
        require(len(accepted) == saved["accepted_opportunities"] and
                len(rejected) == saved["admissions"]["rejected"], "SAVED_TRACE_COUNT_MISMATCH:" + stage_id)
        short_count, bad = 0, []
        for opportunity in accepted:
            legs = opportunity["legs"]
            require(1 <= len(legs) <= 2 and legs[0]["side"] == "long", "INVALID_ONE_OWNER_LEG_SEQUENCE")
            require(opportunity["end_ms"] == legs[-1]["effective_closed_at"], "OPPORTUNITY_EFFECTIVE_CLOSE_MISMATCH")
            for index, leg in enumerate(legs):
                require(leg["opportunity_key"] == opportunity["key"] and leg["symbol"] == opportunity["symbol"],
                        "LEG_OWNER_MISMATCH")
                entry = _integer(leg["entry_ts"], "entry_ts")
                opened = _integer(leg["exit_bar_ts"], "exit_bar_ts")
                closed = _integer(leg["effective_closed_at"], "effective_closed_at")
                require(entry <= closed and opened <= closed <= opened + HOUR_MS, "LEG_CLOCK_ORDER_INVALID")
                if index:
                    require(leg["side"] == "short" and entry >= legs[index - 1]["effective_closed_at"],
                            "SHORT_ENTERED_BEFORE_LONG_CLOSED")
                if leg["side"] != "short":
                    continue
                short_count += 1
                held = _integer(leg["short_held_bar_count"], "short_held_bar_count")
                require((opened - entry) % HOUR_MS == 0 and held == (opened - entry) // HOUR_MS + 1,
                        "SHORT_HELD_COUNT_CLOCK_MISMATCH")
                elapsed_ms = closed - entry
                if held > 24 or elapsed_ms > 24 * HOUR_MS:
                    item = {"stage": stage_id, "opportunity_key": opportunity["key"], "reason": leg["reason"],
                            "entry_ts": entry, "exit_bar_open_ts": opened, "effective_closed_at": closed,
                            "stored_held_bar_count": held, "effective_elapsed_ms": elapsed_ms,
                            "effective_elapsed_hours": elapsed_ms / HOUR_MS,
                            "timestamp_semantics": "EXIT_BAR_TS_IS_BAR_OPEN; EFFECTIVE_CLOSE_IS_SEPARATE",
                            "frozen_limit_hours": 24}
                    bad.append(item)
                    violations.append(item)
        require(short_count == saved["reverse_short_legs"], "SAVED_SHORT_COUNT_MISMATCH:" + stage_id)
        summaries[stage_id] = {"accepted": len(accepted), "rejected": len(rejected),
                               "saved_short_legs": short_count, "short_limit_violations": len(bad),
                               "violation_reason_counts": dict(Counter(x["reason"] for x in bad))}
    static = static_findings(blobs["model_code"].decode(), blobs.get("filter_code", b"").decode() or None)
    return {
        "schema": "zel.work_c.trendrider.saved_contract_audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "source_commit": SOURCE_COMMIT,
        "status": "BLOCKED_SAVED_CONTRACT_AND_SOURCE_ADMISSION",
        "artifact_integrity": "PASS_HASH_SCHEMA_LINEAGE_AND_COUNTS",
        "contract_conformance": "FAIL" if (violations or static["loss_circuit_extra_hour_on_effective_close"]
                                            or static["short_loop_allows_25_bars"]) else "NO_CHECKED_VIOLATION",
        "source_pins": pins, "frozen_source_counts": counts, "stage_counts": summaries,
        "frozen_24h_violations": violations, "static_code_findings": static,
        "source_admission": {
            "external_eligibility_receipt": "NOT_PROVIDED",
            "historical_received_at": r["source_timing"]["historical_real_received_at"],
            "fully_new_unseen_OOS": rob["fully_new_unseen_OOS"],
            "realized_broker_fee_funding": rob["realized_broker_fee_funding"],
            "low_timeframe_execution_witness": "NOT_PROVIDED",
            "all_raw_entry_event_stream": "NOT_PROVIDED_SAVED_COMPLETED_RECEIPT_UNION_ONLY",
            "new_economic_allowed": False,
        },
        "new_performance": not_run(),
        "activity": {"economic_replays": 0, "strategy_imports": 0, "new_market_requests": 0,
                     "new_rule_candidates": 0, "orders": 0, "actions_runs": 0, "source_mutations": 0},
        "limits": ["Trace clock counts are new integrity observations, not new strategy performance.",
                   "Effective-close timestamps are model booking/observation times, not verified exchange fill times.",
                   "No corrected circuit or 24h economics were run or inferred.",
                   "No stored 1h OHLC is promoted into actual quote/receipt/short funding evidence.",
                   "Synthetic fixture pins accepted by the Python API never confer source eligibility."]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--filter-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    source = args.source_dir
    report = audit_paths(source / "FREEZE.json", source / "RESULT.json", source / "ROBUSTNESS.json",
                         source / "TRACES.json.gz", source / "fuse_and_recover.py",
                         args.filter_dir / "mechanism_screen.py" if args.filter_dir else None)
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(raw)
    else:
        print(raw, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
