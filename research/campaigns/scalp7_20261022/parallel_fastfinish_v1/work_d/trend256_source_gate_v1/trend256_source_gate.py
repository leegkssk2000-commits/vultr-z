#!/usr/bin/env python3
"""Reproduce a closed, hash-bound source deficiency; never propose a trading rule.

Reads the original seven-member artifact, native text and saved 256 rows only.
No imports of the native evaluators, prices, signals, filters or repricing.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

from trend256_attribution import load_verified, identity

ROOT = Path(__file__).resolve().parent
ZIP_SHA = "412e3f7456c53dd79869f7b6c9934fc3d3247d01250166cc165076e64fe3a819"
BINDINGS_SHA = "58f8b830cabc837350cc195de666b33c491b410d80ffe8975564ea54f9dc8382"
POLICY_SHA = "5212f92a0b181e523c235dc546b64ea2852045e7"
CONFIG_SHA = "ac462a17bf7c607cd0d3e97fa37bd33c5cc0672b7a81ecf37bd9e586d91fd2c4"
MEMBERS = {
    "long_only_development.json", "parent_development.json",
    "long_only_prospective.json", "long_only_development_hardening.json",
    "parent_development.parent.json", "parent_prospective.json",
    "parent_prospective.parent.json",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def content_inventory(value):
    """Count complete native object shapes, never infer a hash's preimage."""
    nodes = list(objects(value))
    return {
        "ohlc_objects": sum({"open", "high", "low", "close"} <= x.keys() for x in nodes),
        "native_feature_bodies": sum(
            {"strategy_id", "symbol", "signal_ts", "close", "atr", "values"} <= x.keys()
            for x in nodes),
        "feature_hash_references": sum("feature_sha" in x for x in nodes),
        "explicit_available_timestamps": sum(
            any(k in x for k in ("available_ts", "available_ts_ms", "feature_available_ts_ms"))
            for x in nodes),
    }


def verify_sources(source_dir=ROOT):
    root = Path(source_dir)
    raw = (root / "SOURCE_BINDINGS.json").read_bytes()
    if sha(raw) != BINDINGS_SHA:
        raise ValueError("SOURCE_BINDINGS_CHANGED")
    files = json.loads(raw)["files"]
    for item in files:
        data = (root / item["path"]).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if sha(data) != item["sha256"] or blob != item["git_blob_sha"]:
            raise ValueError("NATIVE_SOURCE_CHANGED:" + item["path"])
    return files


def inspect_archive(path, receipt_path):
    raw = Path(path).read_bytes()
    if sha(raw) != ZIP_SHA:
        raise ValueError("ORIGINAL_ARTIFACT_CHANGED")
    result = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if set(archive.namelist()) != MEMBERS or len(archive.namelist()) != len(MEMBERS):
            raise ValueError("ORIGINAL_ARTIFACT_MEMBER_SET_CHANGED")
        if archive.read("long_only_prospective.json") != Path(receipt_path).read_bytes():
            raise ValueError("RECEIPT_NOT_EXACT_ARCHIVE_MEMBER")
        for name in sorted(MEMBERS):
            member = archive.read(name)
            result.append({"member": name, "bytes": len(member), "sha256": sha(member),
                           **content_inventory(json.loads(member))})
    return result


def audit_rows(receipt):
    rows = receipt["trades"]
    if len(rows) != 256 or any(r["policy_sha"] != POLICY_SHA or r["config_sha"] != CONFIG_SHA for r in rows):
        raise ValueError("EXACT_256_POLICY_CONFIG_REQUIRED")
    feature_counts = content_inventory(rows)
    # This program closes this exact immutable artifact. A later source-complete
    # study needs its own reviewed binding; it must not silently turn this into PASS.
    if feature_counts["native_feature_bodies"] or feature_counts["ohlc_objects"]:
        raise ValueError("UNEXPECTED_INPUT_SHAPE_REQUIRES_NEW_REVIEWED_BINDING")
    below_stop = []
    for r in rows:
        if r["side"] == "long" and r["entry"] < r["intent_geometry"]["sl"]:
            below_stop.append({"row_identity": identity(r), "intent_sha": r["intent_sha"],
                               "symbol": r["symbol"], "signal_ts": r["signal_ts"],
                               "entry_ts": r["entry_ts"], "exit_ts": r["exit_ts"],
                               "entry": r["entry"], "sealed_sl": r["intent_geometry"]["sl"],
                               "saved_exit": r["exit"], "reason": r["reason"],
                               "gross_bps": r["gross_bps"], "saved_net1_bps": r["net_bps"],
                               "semantics": "Observed saved geometry inconsistency; no path or alternative fill inferred"})
    return {"complete_rows": len(rows), "rows_with_feature_hash": sum(bool(r["feature_sha"]) for r in rows),
            "all_native_policy_and_config_bound": True, **feature_counts,
            "entry_below_sealed_stop": below_stop,
            "recovery_winner_count": None,
            "recovery_blocker": "No intrahold price/stop/MTM path; final winners cannot establish recovery",
            "inherited_parent_open_intents": len(receipt.get("open_intents", [])),
            "inherited_parent_rejected_intents": len(receipt.get("ownership_rejected_intents", [])),
            "child_opportunity_chronology_complete": False}


def run(receipt_path, artifact_zip, source_dir=ROOT):
    receipt = load_verified(receipt_path, "long256")
    sources = verify_sources(source_dir)
    members = inspect_archive(artifact_zip, receipt_path)
    row_audit = audit_rows(receipt)
    if any(m["ohlc_objects"] or m["native_feature_bodies"] for m in members):
        raise ValueError("ARCHIVE_CONTENT_REQUIRES_NEW_REVIEWED_BINDING")
    return {
        "scope_key": "ZEL_D_TRENDRIDER_LOSS_CONCENTRATION_AFTER_K117_V1",
        "state": "NO_CAUSAL_CHILD", "first_blocker": "SOURCE_FEATURE_BLOCKED",
        "validation_state": "PASS_EXACT_ARCHIVE_AND_NATIVE_SOURCE_BOUND_DEFICIENCY",
        "native_checkout": "758fde9213032ef0211e5d8d3ffc914f6dad5ca2",
        "checkout_job_id": 114020351819, "run_id": 37989679810,
        "run_conclusion": "failure", "run_failure_stage": "prospective hardening BINGX_API_ERROR:100410",
        "artifact_id": 11646670634, "artifact_zip_sha256": ZIP_SHA,
        "receipt_raw_sha256": sha(Path(receipt_path).read_bytes()),
        "receipt_semantic_sha256": receipt["receipt_sha256"],
        "source_bindings": sources, "archive_inventory": members, "row_audit": row_audit,
        "timeframe": receipt["source"]["interval"],
        "source_symbol_count": len(receipt["source"]["symbols"]),
        "feature_requirements": [
            {"axis": "prior completed BTC/ETH trend", "state": "BLOCKED",
             "missing": "Native full OHLC prefix/seed, peer feature bodies, completed-bar and received/available timestamps"},
            {"axis": "volatility", "state": "BLOCKED",
             "missing": "Native ATR14/full prefix; sealed SL and final PnL do not determine the original volatility"},
            {"axis": "entry chase", "state": "BLOCKED",
             "missing": "Original close/EMA50/ATR14 feature body matching each feature_sha and as-of availability"},
            {"axis": "hold/exit recovery", "state": "BLOCKED",
             "missing": "Intrahold native bars, stop/exit state, terminal precedence; no MFE/MAE inferred from final exit"},
        ],
        "changed_axis": None, "child_adapter": None, "new_candidate_count": 0,
        "preservation": {"input_rows_retained": 256, "rows_deleted": 0, "rows_repriced": 0,
                         "all_winners_retained": True, "native_source_mutations": 0,
                         "K117": "CLOSED_FROZEN_NO_CAUSAL_CHILD_UNTOUCHED"},
        "economic_improvement": "UNMEASURED_NO_CHILD", "independent_opportunities": None,
        "new_economic_comparisons": 0, "new_full_runs": 0, "market_api_calls": 0,
        "orders": 0, "order_authority": "BLOCKED",
        "scope_limit": "Absence is established within this exact run artifact and native path, not all possible external archives",
        "owner_next_action": "Consume terminal source/lifecycle evidence; route to an already eligible distinct mechanism. Do not rerun this T256 or K117 and do not relabel tried peer/chase axes as new.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long-only-receipt", type=Path, required=True)
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.long_only_receipt, args.artifact_zip, args.source_dir)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
