"""Prepare immutable Issue 1361 historical-fit identities without test replay.

This is phase one of the H validation.  It verifies the preserved archive,
loads the existing causal 30m bars and computes each past-only 90d context fit.
It deliberately imports neither the signal generator nor either execution
engine.  Test-period signals, fills and economics belong to phase two and are
forbidden until independent approval and the permanent six-instance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from ops import issue1361_repeatability_v1 as scope

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "research/campaigns/scalp7_20261005/issue1358_ema21_limit_v1/CONTRACT_GITHUB.json"
CANDIDATE = "scalp7_squeeze_release_ema21_limit_utc30m_v1"
PARENT = "scalp7_squeeze_panic_cost4_parent_utc30m_v2"
HISTORY_CLAIM_REF = "refs/heads/research-execution-claims/issue1361-history-20261006-v1"
FIT_SCHEMA = "zel.issue1361.history_fit_manifest.v1"
FROZEN_COSTS_BPS = {
    "BTC-USDT": 14.0,
    "DOGE-USDT": 16.73064726730116,
    "ETH-USDT": 14.0,
    "LINK-USDT": 15.705017808034006,
    "SOL-USDT": 14.019991840065801,
    "XRP-USDT": 15.2464337863639,
}
ENTRY_PROFILES = {
    CANDIDATE: "MODELED_MINUTE_TOUCH_ADVERSE_LIMIT_BOUND",
    PARENT: "UTC_NEXT_30M_OPEN_MARKET_MODEL",
}
FIT_PAYLOAD_KEYS = {
    "training_feature_sha256",
    "disp_q67",
    "meanabs_q85",
    "vol_q25",
    "vol_q67",
    "train_start_ms",
    "train_end_ms",
    "last_fit_observation_ms",
    "train_rows",
}


class HistoryPreparationError(RuntimeError):
    """Source, fit, or immutable identity violates the frozen protocol."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def fit_payload_sha256(value: Mapping[str, Any]) -> str:
    """Hash exactly the payload serialized by rolling_context.fit_context."""
    if not isinstance(value, Mapping) or set(value) != FIT_PAYLOAD_KEYS | {"sha256"}:
        raise HistoryPreparationError("FIT_PAYLOAD_PROFILE")
    payload = {key: value[key] for key in FIT_PAYLOAD_KEYS}
    if not (
        isinstance(payload["training_feature_sha256"], str)
        and len(payload["training_feature_sha256"]) == 64
        and all(c in "0123456789abcdef" for c in payload["training_feature_sha256"])
    ):
        raise HistoryPreparationError("FIT_TRAINING_FEATURE_HASH")
    for key in (
        "train_start_ms",
        "train_end_ms",
        "last_fit_observation_ms",
        "train_rows",
    ):
        if isinstance(payload[key], bool) or not isinstance(payload[key], int):
            raise HistoryPreparationError("FIT_INTEGER_PROFILE:" + key)
    if payload["train_rows"] <= 0:
        raise HistoryPreparationError("FIT_TRAIN_ROWS")
    for key in ("disp_q67", "meanabs_q85", "vol_q25", "vol_q67"):
        number = payload[key]
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            raise HistoryPreparationError("FIT_FINITE_NUMERIC_PROFILE:" + key)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_fit(value: Mapping[str, Any], planned: Mapping[str, Any]) -> dict[str, Any]:
    fit = dict(value)
    expected_sha256 = fit_payload_sha256(fit)
    supplied_sha256 = fit.get("sha256")
    if (
        not isinstance(supplied_sha256, str)
        or supplied_sha256 != expected_sha256
        or fit["train_start_ms"] != planned["fit_start_ms"]
        or fit["train_end_ms"] != planned["fit_end_ms"]
        or fit["last_fit_observation_ms"] >= planned["test_start_ms"]
    ):
        raise HistoryPreparationError("FIT_CHRONOLOGY_OR_HASH:" + planned["id"])
    return fit


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fit_window(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": row["id"],
        "partition": "retrospective_pipeline_stability",
        "train_start_ms": int(row["fit_start_ms"]),
        "train_end_ms": int(row["fit_end_ms"]),
        "start_ms": int(row["test_start_ms"]),
        "end_ms": int(row["test_end_ms"]),
        "partial_window": False,
        "formation_inspection": "STRATEGY_FORMED_AFTER_HISTORY_OBSERVED",
        "oos_scope": scope.CLASSIFICATION,
        "initial_position": "FLAT_INDEPENDENT_WINDOW",
        "boundary_trade_policy": "NO_SYNTHETIC_CLOSE_EXCLUDE_UNRESOLVED_AND_CROSS_BOUNDARY",
    }


def validate_costs(costs: Any) -> dict[str, float]:
    if costs != FROZEN_COSTS_BPS:
        raise HistoryPreparationError("FROZEN_COSTS_CHANGED")
    return dict(costs)


def frozen_instance(
    row: Mapping[str, Any],
    *,
    identity: str,
    model: str,
    fit_sha256: str,
    code_bundle_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "zel.issue1361.history_instance.v1",
        "issue": 1361,
        "instance_id": row["id"] + ":" + model,
        "fold_id": row["id"],
        "identity": identity,
        "model": model,
        "fit_sha256": fit_sha256,
        "source_inventory_sha256": scope.SOURCE_INVENTORY_SHA256,
        "protocol_sha256": scope.PROTOCOL_SHA256,
        "rule_sha256": scope.RULE_SHA256,
        "cost_sha256": scope.COST_SHA256,
        "code_bundle_sha256": code_bundle_sha256,
        "fit_start_ms": row["fit_start_ms"],
        "fit_end_ms": row["fit_end_ms"],
        "test_start_ms": row["test_start_ms"],
        "test_end_ms": row["test_end_ms"],
        "clock_profile": row["clock_profile"],
        "classification": scope.CLASSIFICATION,
        "entry_profile": ENTRY_PROFILES[identity],
        "cost_profiles": ["1x", "2x"],
        "fresh_oos": False,
        "order_authority": "BLOCKED",
    }


def code_hashes(root: Path = ROOT) -> dict[str, str]:
    paths = (
        "ops/issue1361_history_v1.py",
        "ops/issue1361_repeatability_v1.py",
        "ops/issue1358_ema21_limit_v1.py",
        "ops/scalp7_clocked_execution_v1.py",
        "ops/squeeze_nonpositive_exit_v1.py",
        "ops/kp_committed_cursor_snapshot_v1.py",
        "ops/kp_connected_research_validation_v1.py",
        "ops/kp_price_input_export_v1.py",
        "backend/research/rebuild/scalp7_source_data_v2.py",
        "backend/research/rebuild/economic7_canonical_history_v1.py",
        "backend/research/rebuild/scalp7_fresh_forward_v2.py",
        "backend/research/rebuild/scalp7_fresh_source_v2.py",
        "backend/research/rebuild/scalp7_rolling_context_v2.py",
        "backend/research/rebuild/scalp7_positive_lanes_v2.py",
        "backend/research/rebuild/scalp7_execution_v2.py",
        "backend/research/rebuild/scalp7_metrics_v2.py",
    )
    return {name: sha_file(root / name) for name in paths}


def source_coverage(frames: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for symbol in scope.SYMBOLS:
        if symbol not in frames:
            raise HistoryPreparationError("EXACT_SIX_SYMBOL_SOURCE_REQUIRED")
        frame = frames[symbol]
        if frame.empty:
            raise HistoryPreparationError("EMPTY_SYMBOL_SOURCE:" + symbol)
        if (frame["available_ts_ms"] < frame["close_ts_ms"]).any():
            raise HistoryPreparationError("BAR_AVAILABLE_BEFORE_CLOSE:" + symbol)
        folds = []
        for row in rows:
            train = frame[
                (frame["open_ts_ms"] >= row["fit_start_ms"])
                & (frame["open_ts_ms"] < row["fit_end_ms"])
            ]
            test = frame[
                (frame["open_ts_ms"] >= row["test_start_ms"])
                & (frame["open_ts_ms"] < row["test_end_ms"])
            ]
            if train.empty or test.empty:
                raise HistoryPreparationError(f"FOLD_SOURCE_EMPTY:{row['id']}:{symbol}")
            folds.append(
                {
                    "id": row["id"],
                    "train_rows_30m": int(len(train)),
                    "test_rows_30m": int(len(test)),
                    "train_first_open_ms": int(train.iloc[0]["open_ts_ms"]),
                    "train_last_open_ms": int(train.iloc[-1]["open_ts_ms"]),
                    "test_first_open_ms": int(test.iloc[0]["open_ts_ms"]),
                    "test_last_open_ms": int(test.iloc[-1]["open_ts_ms"]),
                }
            )
        coverage[symbol] = {
            "first_open_ms": int(frame.iloc[0]["open_ts_ms"]),
            "last_open_ms": int(frame.iloc[-1]["open_ts_ms"]),
            "rows_30m": int(len(frame)),
            "availability_basis": frame.attrs.get("availability_basis"),
            "folds": folds,
        }
    return coverage


def build_manifest(
    *,
    inventory: Mapping[str, Any],
    fits: list[Mapping[str, Any]],
    coverage: Mapping[str, Any],
    costs: Mapping[str, float],
    hashes: Mapping[str, str],
) -> dict[str, Any]:
    rows = scope.planned_history()
    scope.check_history(rows)
    if len(fits) != 3:
        raise HistoryPreparationError("EXACT_THREE_FITS_REQUIRED")
    fit_rows = []
    instances = []
    code_bundle_sha256 = canonical_sha256(dict(sorted(hashes.items())))
    for row, supplied in zip(rows, fits, strict=True):
        fit = validate_fit(supplied, row)
        fit_rows.append({"id": row["id"], "fit": fit})
        for identity, model in (
            (CANDIDATE, "EMA21_BUY_LIMIT"),
            (PARENT, "SQUEEZE_PARENT"),
        ):
            frozen = frozen_instance(
                row,
                identity=identity,
                model=model,
                fit_sha256=fit["sha256"],
                code_bundle_sha256=code_bundle_sha256,
            )
            instances.append({**frozen, "state_sha256": canonical_sha256(frozen)})
    manifest = {
        "schema": FIT_SCHEMA,
        "issue": 1361,
        "phase": "FIT_COMPLETE_NO_TEST_SIGNALS",
        "classification": scope.CLASSIFICATION,
        "source": {
            "root_label": "canonical_12m+gapday+postgap",
            "full_inventory_files": inventory["full_inventory_files"],
            "full_inventory_sha256": inventory["full_inventory_sha256"],
            "expected_full_inventory_sha256": scope.SOURCE_INVENTORY_SHA256,
            "state": inventory["history_input_state"],
            "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        },
        "rule_sha256": scope.RULE_SHA256,
        "protocol_sha256": scope.PROTOCOL_SHA256,
        "cost_sha256": scope.COST_SHA256,
        "costs_bps": dict(sorted(costs.items())),
        "code_sha256": dict(sorted(hashes.items())),
        "fits": fit_rows,
        "instances": instances,
        "coverage": coverage,
        "allocation": {"H_claimed": 0, "H_limit": 6, "economic_runs": 0},
        "history_claim_ref": HISTORY_CLAIM_REF,
        "test_period_signal_generation": 0,
        "test_period_model_replays": 0,
        "authority": "FIT_ONLY_NO_ECONOMIC_CLAIM_NO_ORDER",
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    validate_manifest(manifest)
    return manifest


def validate_manifest(value: Mapping[str, Any]) -> None:
    if value.get("schema") != FIT_SCHEMA or value.get("phase") != "FIT_COMPLETE_NO_TEST_SIGNALS":
        raise HistoryPreparationError("FIT_MANIFEST_PROFILE")
    if value.get("test_period_signal_generation") != 0 or value.get("test_period_model_replays") != 0:
        raise HistoryPreparationError("UNCLAIMED_TEST_EXECUTION")
    validate_costs(value.get("costs_bps"))
    if value.get("cost_sha256") != scope.COST_SHA256:
        raise HistoryPreparationError("FROZEN_COST_HASH_MISMATCH")
    if value.get("rule_sha256") != scope.RULE_SHA256:
        raise HistoryPreparationError("FROZEN_RULE_HASH_MISMATCH")
    if value.get("protocol_sha256") != scope.PROTOCOL_SHA256:
        raise HistoryPreparationError("FROZEN_PROTOCOL_HASH_MISMATCH")
    code_map = value.get("code_sha256")
    if (
        not isinstance(code_map, Mapping)
        or not code_map
        or any(
            not isinstance(name, str)
            or not isinstance(digest, str)
            or len(digest) != 64
            for name, digest in code_map.items()
        )
    ):
        raise HistoryPreparationError("CODE_MAP_PROFILE")
    code_bundle_sha256 = canonical_sha256(dict(sorted(code_map.items())))

    fit_rows = value.get("fits")
    planned = scope.planned_history()
    if (
        not isinstance(fit_rows, list)
        or len(fit_rows) != len(planned)
        or [row.get("id") for row in fit_rows] != [row["id"] for row in planned]
    ):
        raise HistoryPreparationError("EXACT_THREE_CANONICAL_FITS_REQUIRED")
    fit_by_id: dict[str, Mapping[str, Any]] = {}
    for planned_row, fit_row in zip(planned, fit_rows, strict=True):
        fit = fit_row.get("fit")
        if not isinstance(fit, Mapping):
            raise HistoryPreparationError("FIT_PAYLOAD_PROFILE")
        fit_by_id[planned_row["id"]] = validate_fit(fit, planned_row)

    instances = value.get("instances", [])
    if len(instances) != 6 or len({x.get("instance_id") for x in instances}) != 6:
        raise HistoryPreparationError("EXACT_SIX_INSTANCE_IDENTITIES_REQUIRED")
    expected_matrix = {
        (row["id"], CANDIDATE, "EMA21_BUY_LIMIT") for row in planned
    } | {(row["id"], PARENT, "SQUEEZE_PARENT") for row in planned}
    actual_matrix = {
        (instance.get("fold_id"), instance.get("identity"), instance.get("model"))
        for instance in instances
    }
    if actual_matrix != expected_matrix:
        raise HistoryPreparationError("FOLD_MODEL_INSTANCE_MATRIX_MISMATCH")
    planned_by_id = {row["id"]: row for row in planned}
    for instance in instances:
        row = planned_by_id[instance["fold_id"]]
        fit = fit_by_id[instance["fold_id"]]
        expected_model = (
            "EMA21_BUY_LIMIT" if instance["identity"] == CANDIDATE else "SQUEEZE_PARENT"
        )
        if (
            instance.get("cost_sha256") != scope.COST_SHA256
            or instance.get("cost_profiles") != ["1x", "2x"]
        ):
            raise HistoryPreparationError("INSTANCE_COST_BINDING_MISMATCH")
        frozen = {k: v for k, v in instance.items() if k != "state_sha256"}
        expected = frozen_instance(
            row,
            identity=instance["identity"],
            model=expected_model,
            fit_sha256=fit["sha256"],
            code_bundle_sha256=code_bundle_sha256,
        )
        if frozen != expected:
            raise HistoryPreparationError("INSTANCE_FROZEN_PROFILE_MISMATCH")
        if canonical_sha256(frozen) != instance.get("state_sha256"):
            raise HistoryPreparationError("INSTANCE_STATE_HASH_MISMATCH")
    frozen_manifest = {k: v for k, v in value.items() if k != "manifest_sha256"}
    if canonical_sha256(frozen_manifest) != value.get("manifest_sha256"):
        raise HistoryPreparationError("FIT_MANIFEST_HASH_MISMATCH")


def prepare_history(source_root: Path, output: Path, cache_dir: Path, contract_path: Path = CONTRACT) -> dict[str, Any]:
    # Lazy imports keep this phase structurally separate from signal/execution code.
    from backend.research.rebuild import scalp7_rolling_context_v2 as context
    from backend.research.rebuild import scalp7_source_data_v2 as source

    inventory = scope.inventory_source(source_root)
    if inventory["history_input_state"] != "READY":
        raise HistoryPreparationError("SOURCE_INVENTORY_NOT_READY")
    contract = json.loads(contract_path.read_bytes())
    costs = validate_costs(contract.get("reference_costs_bps"))
    frames = source.load_candles(source_root, 30, cache_dir=cache_dir)
    rows = scope.planned_history()
    coverage = source_coverage(frames, rows)
    features = context.cross_features(frames)
    fits = [context.fit_context(features, fit_window(row)) for row in rows]
    manifest = build_manifest(
        inventory=inventory,
        fits=fits,
        coverage=coverage,
        costs=costs,
        hashes=code_hashes(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
        handle.flush()
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prepare", nargs="?")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    args = parser.parse_args()
    manifest = prepare_history(args.source_root, args.output, args.cache_dir, args.contract)
    print(json.dumps({"state": manifest["phase"], "manifest_sha256": manifest["manifest_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
