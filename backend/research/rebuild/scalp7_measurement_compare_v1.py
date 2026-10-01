"""Independent SR segments with bounded fixtures and approval-gated genuine execution."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from backend.research.rebuild import scalp7_exact25_model_runner_v1 as runner
from backend.research.rebuild import scalp7_exact25_reference_models_v1 as reference
from backend.research.rebuild.scalp7_measurement_repair_v1 import (
    MINUTE,
    adapt_segment_details,
)
from backend.research.rebuild.scalp7_source_data_v2 import aggregate_minutes

MODELS = {"SR_CONTROL": reference.SR_CONTROL, "SR_RETEST": reference.SR}


def _save_durable_exclusive(path: Path, data: Mapping[str, Any]) -> None:
    """Persist both checkpoint bytes and its directory entry before returning."""
    with path.open("xb") as handle:
        handle.write(json.dumps(data, sort_keys=True, allow_nan=False).encode())
        handle.flush()
        os.fsync(handle.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def segment_inputs(
    detail_frames: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
    segment_id: str,
) -> dict[str, Any]:
    """Pure provided-data adapter. It never reads market files or calls a producer."""
    if set(detail_frames) != set(contract["symbols"]):
        raise ValueError("COMMON_SYMBOL_UNIVERSE_REQUIRED")
    segment = next(s for s in contract["segments"] if s["segment_id"] == segment_id)
    end = segment["evaluation_end_ts_ms"]
    frames, details = {}, {}
    for symbol, frame in detail_frames.items():
        original = frame.to_dict("records")
        if any(r.get("symbol", symbol) != symbol for r in original):
            raise ValueError("DETAIL_SYMBOL_CONFLICT")
        if frame.attrs.get("price_basis", "LAST_PRICE") != "LAST_PRICE":
            raise ValueError("LAST_PRICE_REFERENCE_ONLY")
        rows = [{**r, "symbol": symbol} for r in original]
        rows = adapt_segment_details(rows, contract, segment_id, symbol)
        if any(r["available_ts_ms"] != r["close_ts_ms"] for r in rows):
            raise ValueError("BAR_CLOSE_MODEL_REQUIRED_NO_AVAILABILITY_BACKDATE")
        if any(r.get("price_basis", "LAST_PRICE") != "LAST_PRICE" for r in rows):
            raise ValueError("LAST_PRICE_REFERENCE_ONLY")
        rows = [r for r in rows if r["close_ts_ms"] <= end]
        detail = pd.DataFrame(rows)
        if "volume" not in detail:
            raise ValueError("SOURCE_VOLUME_FIELD_REQUIRED_NO_FABRICATION")
        raw = detail[["open_ts_ms", "open", "high", "low", "close", "volume"]].rename(
            columns={"open_ts_ms": "timestamp_ms"}
        )
        decision = aggregate_minutes(raw, contract["decision_minutes"])
        decision["segment_id"] = detail["segment_id"].iloc[0]
        decision.attrs = dict(frame.attrs)
        detail.attrs = dict(frame.attrs)
        frames[symbol], details[symbol] = decision, detail
    start = segment["raw_start_ts_ms"]
    step = contract["decision_minutes"] * MINUTE
    times = sorted(
        {start, end, *range(((start + step - 1) // step) * step, end + 1, step)}
    )
    by_time = {
        s: {int(r["open_ts_ms"]): r for r in f.to_dict("records")}
        for s, f in details.items()
    }
    snapshots = []
    for stamp in times:
        prices = {}
        for symbol, lookup in by_time.items():
            row = lookup.get(stamp) or (lookup[end - MINUTE] if stamp == end else None)
            if row is None:
                raise ValueError("SEGMENT_SNAPSHOT_MISSING_NO_FILL")
            prices[symbol] = {
                "ts_ms": stamp,
                "price": row["close"] if stamp == end else row["open"],
                "price_basis": "LAST_PRICE",
                "price_available_ts_ms": row["available_ts_ms"],
                "price_event_phase": (
                    "TERMINAL_CLOSE" if stamp == end else "OPEN_AFTER_BOUNDARY_FILLS"
                ),
                "source_ref": "PROVIDED_SEGMENT:"
                + contract["contract_sha256"]
                + ":"
                + segment_id,
            }
        snapshots.append({"ts_ms": stamp, "prices": prices})
    return {"frames": frames, "detail_frames": details, "price_snapshots": snapshots}


def run_synthetic_comparison(
    contract: Mapping[str, Any],
    detail_frames: Mapping[str, pd.DataFrame],
    *,
    fixture_label: str,
    cost: Mapping[str, Any],
    initial_cash_usdt: float = 10000,
) -> dict[str, Any]:
    """Reuse unchanged SR compiler/order/exit with separate capital per eligible segment."""
    if fixture_label != "SYNTHETIC_UNIT_TEST_ONLY":
        raise PermissionError("NEW_GENUINE_FULL_NOT_AUTHORIZED")
    if not 1 <= len(detail_frames) <= 2 or any(
        len(f) > 5000 for f in detail_frames.values()
    ):
        raise PermissionError(
            "BOUNDED_SYNTHETIC_FIXTURE_ONLY_MAX_TWO_SYMBOLS_5000_MINUTES_EACH"
        )
    if any(
        f.attrs.get("data_kind") != "SYNTHETIC_FIXTURE"
        or f.attrs.get("source_rows_are_genuine") is not False
        for f in detail_frames.values()
    ):
        raise PermissionError("EXPLICIT_SYNTHETIC_PROVENANCE_REQUIRED")
    if any(not ref["path"].startswith("SYNTHETIC:") for ref in contract["source_refs"]):
        raise PermissionError("GENUINE_SOURCE_CONTRACT_CANNOT_ENTER_FIXTURE")
    output = {}
    for segment in contract["segments"]:
        if not segment["eligible_by_data_only"]:
            continue
        segment_id = segment["segment_id"]
        inputs = segment_inputs(detail_frames, contract, segment_id)
        windows = segment_windows(segment)
        paired = {}
        for label, model_id in MODELS.items():
            binding = runner.freeze_model(
                model_module=reference.__name__,
                model_id=model_id,
                strategy_id="sr_levels",
                baseline_id="measurement-independent-segments",
                changed_axis="COMMON_DATA_SEGMENT_AND_CAPITAL_BOUNDARY_ONLY",
                config={},
                data_manifest={
                    "data_kind": "SYNTHETIC_FIXTURE",
                    "construction_reason": fixture_label,
                    "symbols": contract["symbols"],
                    "continuous_contract_sha256": contract["contract_sha256"],
                    "segment_id": segment_id,
                },
                cost=cost,
                windows=windows,
                initial_cash_usdt=initial_cash_usdt,
            )
            paired[label] = runner.run_fixture(
                binding, inputs, expected_binding_sha256=binding["binding_sha256"]
            )
        output[segment_id] = paired
    return {
        "schema": "scalp7.measurement.synthetic_segment_compare.v1",
        "segments": output,
        "whole_period_nav": None,
        "cross_segment_nav_aggregation": "FORBIDDEN",
        "new_full_runs": 0,
        "old_unresolved_positions": "PRESERVED_SEPARATE_PARENT_STATE",
        "genuine_execution_status": "BLOCKED_NO_NEW_FULL_APPROVAL",
        "rules_changed": False,
        "funding_status": "UNKNOWN_NOT_ZERO",
    }


def segment_windows(segment: Mapping[str, Any]) -> list[dict[str, Any]]:
    start = segment["raw_start_ts_ms"]
    evaluation = segment["evaluation_start_ts_ms"]
    rows = []
    if start < evaluation:
        rows.append(
            {
                "name": segment["segment_id"] + "_context",
                "kind": "CONTEXT",
                "start_ts_ms": start,
                "end_ts_ms": evaluation,
            }
        )
    rows.append(
        {
            "name": segment["segment_id"],
            "kind": "VALIDATION",
            "start_ts_ms": evaluation,
            "end_ts_ms": segment["evaluation_end_ts_ms"],
        }
    )
    return rows


def freeze_comparison(
    parent_binding: Mapping[str, Any], contract: Mapping[str, Any], label: str
) -> dict[str, Any]:
    """Prepare one identity per model covering every eligible independent segment."""
    from dataclasses import asdict
    from backend.research.rebuild.economic7_campaign_registry_v1 import (
        CandidateIdentity,
        digest,
    )

    if label not in MODELS or parent_binding["model_id"] != MODELS[label]:
        raise ValueError("UNCHANGED_SR_PARENT_REQUIRED")
    if (
        parent_binding["model_module"] != reference.__name__
        or parent_binding["execution_mode"] != "DETAIL_CONDITIONAL"
    ):
        raise ValueError("UNCHANGED_SR_CALLER_REQUIRED")
    if (
        digest({k: v for k, v in contract.items() if k != "contract_sha256"})
        != contract["contract_sha256"]
    ):
        raise ValueError("CONTINUOUS_CONTRACT_HASH_MISMATCH")
    parent = dict(parent_binding)
    runner.verify_binding(parent, parent["binding_sha256"])
    segment_bindings = {}
    for segment in contract["segments"]:
        if segment["eligible_by_data_only"]:
            sid = segment["segment_id"]
            segment_bindings[sid] = runner.freeze_model(
                model_module=parent["model_module"],
                model_id=parent["model_id"],
                strategy_id=parent["strategy_id"],
                baseline_id=parent["identity_key"],
                changed_axis="DATA_CONTINUITY_AND_INDEPENDENT_CAPITAL_ONLY",
                config=parent["config"],
                data_manifest={
                    **parent["data_manifest"],
                    "continuous_contract_sha256": contract["contract_sha256"],
                    "segment_id": sid,
                },
                cost=parent["cost"],
                windows=segment_windows(segment),
                initial_cash_usdt=parent["initial_cash_usdt"],
            )
    if not segment_bindings:
        raise ValueError("NO_DATA_ELIGIBLE_SEGMENT")
    payload = {
        "schema": "scalp7.measurement.frozen_segment_compare.v1",
        "label": label,
        "parent_binding": parent,
        "continuous_contract": dict(contract),
        "segment_bindings": segment_bindings,
        "code_closure": runner.code_closure(__name__),
        "new_full_required": 1,
        "new_full_authorized": 0,
        "capital_policy": "SEPARATE_FLAT_RESEARCH_ACCOUNT_PER_SEGMENT_NO_PARENT_CLOSE",
        "cross_segment_nav_aggregation": "FORBIDDEN",
        "source_loader_policy": "ONLY_AFTER_EXISTING_EXACT_IDENTITY_ADMISSION_AND_START",
    }
    identity = CandidateIdentity(
        candidate_id=label + "_CONTINUOUS_SEGMENTS_V1",
        strategy_id=parent["strategy_id"],
        baseline_id=parent["identity_key"],
        changed_axis="DATA_CONTINUITY_AND_INDEPENDENT_CAPITAL_ONLY",
        rule_sha256=digest(
            {
                "code": payload["code_closure"],
                "model": parent["model_id"],
                "config": parent["config"],
                "capital_policy": payload["capital_policy"],
            }
        ),
        data_sha256=digest(
            {
                "parent": runner.data_identity(parent["data_manifest"]),
                "contract": contract,
            }
        ),
        cost_sha256=digest(parent["cost"]),
        window_sha256=digest({k: v["windows"] for k, v in segment_bindings.items()}),
    )
    payload["candidate_identity"] = asdict(identity)
    payload["identity_key"] = identity.key
    payload["binding_sha256"] = digest(payload)
    return payload


def run_authorized_comparison(
    binding: Mapping[str, Any],
    *,
    expected_binding_sha256: str,
    registry_path: str,
    scope: str,
    owner: str,
    output_path: str,
) -> dict[str, Any]:
    """Future one-FULL gateway; no allocation, automatic retry, or ownership reset."""
    import importlib
    from backend.research.rebuild.economic7_campaign_registry_v1 import (
        CampaignLedger,
        digest,
    )

    runner.admission(binding, registry_path=registry_path, scope=scope, owner=owner)
    if binding["parent_binding"]["data_manifest"]["data_kind"] != "GENUINE_RAW_HISTORY":
        raise ValueError("GENUINE_SOURCE_REQUIRED_FOR_NEW_FULL_GATEWAY")
    payload = {k: v for k, v in binding.items() if k != "binding_sha256"}
    if (
        binding["binding_sha256"] != expected_binding_sha256
        or digest(payload) != expected_binding_sha256
    ):
        raise ValueError("COMPARISON_BINDING_CHANGED")
    rebuilt = freeze_comparison(
        binding["parent_binding"], binding["continuous_contract"], binding["label"]
    )
    if rebuilt != binding:
        raise ValueError("COMPARISON_CODE_OR_IDENTITY_CHANGED")
    parent = binding["parent_binding"]
    runner._verify_input_files(parent["data_manifest"])
    destination = Path(output_path)
    if (
        destination.exists()
        or not destination.parent.is_dir()
        or destination.with_suffix(destination.suffix + ".partial").exists()
    ):
        raise ValueError("NEW_DURABLE_RESULT_PATH_REQUIRED")
    for sid in binding["segment_bindings"]:
        if destination.with_suffix("." + sid + ".checkpoint.json").exists():
            raise ValueError("EXISTING_SEGMENT_CHECKPOINT_REQUIRES_RECOVERY_NOT_RETRY")
    ledger = CampaignLedger(registry_path)
    key = binding["identity_key"]
    if not ledger.start(key, owner):
        raise PermissionError("EXISTING_EXECUTION_MUST_BE_RECOVERED_NOT_REPEATED")

    try:
        spec = parent["data_manifest"]["loader"]
        loader = getattr(importlib.import_module(spec["module"]), spec["function"])
        supplied = loader(parent["data_manifest"], parent["config"])
        results, receipts = {}, {}
        for sid, child in binding["segment_bindings"].items():
            inputs = segment_inputs(
                supplied["detail_frames"], binding["continuous_contract"], sid
            )
            module = runner.verify_binding(child, child["binding_sha256"])
            results[sid] = runner._replay(child, inputs, module)
            checkpoint = destination.with_suffix("." + sid + ".checkpoint.json")
            _save_durable_exclusive(
                checkpoint,
                {
                    "outer_identity_key": key,
                    "segment_id": sid,
                    "binding_sha256": binding["binding_sha256"],
                    "result": results[sid],
                },
            )
            receipts[sid] = {"path": str(checkpoint), "sha256": runner._sha(checkpoint)}
        result = {
            "schema": "scalp7.measurement.segment_comparison_result.v1",
            "identity_key": key,
            "binding_sha256": binding["binding_sha256"],
            "segments": results,
            "segment_checkpoints": receipts,
            "whole_period_nav": None,
            "cross_segment_nav_aggregation": "FORBIDDEN",
            "full_execution_performed": True,
            "full_execution_count": 1,
            "funding_status": "UNKNOWN_NOT_ZERO",
            "old_unresolved_positions": "PRESERVED_SEPARATE_PARENT_STATE",
            "authority": {"live": "BLOCKED", "order": "BLOCKED", "promotion": False},
        }
        partial = destination.with_suffix(destination.suffix + ".partial")
        _save_durable_exclusive(partial, result)
        os.link(partial, destination)
        partial.unlink()
        directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        ledger.finish(
            key,
            owner,
            "COMPLETED",
            {
                "result_path": str(destination),
                "result_file_sha256": runner._sha(destination),
                "binding_sha256": binding["binding_sha256"],
            },
        )
        return result
    except BaseException as exc:
        ledger.finish(
            key,
            owner,
            "FAILED",
            {
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "budget_consumed": True,
                "automatic_retry_forbidden": True,
                "partial_checkpoints_preserved": True,
            },
        )
        raise
