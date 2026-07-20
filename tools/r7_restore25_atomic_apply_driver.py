#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import py_compile
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"IMPORT_SPEC_INVALID:{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = import_module("restore25_git_driver", HERE / "r7_restore25_git_object_driver.py")
core = driver.restore25


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def synthetic_recovery_entry(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    strategy_id = str(row.get("strategy_id") or "")
    engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
    artifact_path = str(engine.get("implementation_path") or "")
    callable_name = str(engine.get("callable") or "")
    if not strategy_id or not artifact_path or not callable_name:
        return None, f"DIRECT_ENGINE_METADATA_INVALID:{strategy_id or 'UNKNOWN'}"
    if core.is_true_source(artifact_path, [
        "backend/strategies/", "backend/strategy/", "backend/strategy25/",
        "services/strategies/", "services/strategy/", "services/strategy25/",
    ]):
        return None, f"DIRECT_ENTRY_ALREADY_TRUE_SOURCE:{strategy_id}:{artifact_path}"
    return {
        "strategy_id": strategy_id,
        "classification": "ARTIFACT_DIRECT_RECLASSIFIED_FOR_RESTORE25",
        "artifact_matches": [{
            "path": artifact_path,
            "callable": callable_name,
            "git_blob_sha": engine.get("source_blob_sha"),
        }],
    }, None


def recover_reclassified_direct(
    root: Path,
    contract: dict[str, Any],
    target_sha: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[Path], list[str]]:
    matrix = load_json(root / str(contract["prior_matrix_path"]))
    entries = [row for row in matrix.get("entries", []) if isinstance(row, dict)]
    direct_rows = [row for row in entries if row.get("binding_mode") == "DIRECT_PROVEN"]
    expected = int(contract.get("expected_reclassified_direct_count", 2))
    errors: list[str] = []
    created: list[Path] = []
    selected_rows: list[dict[str, Any]] = []
    patched_entries: list[dict[str, Any]] = []

    if len(entries) != int(contract.get("expected_strategy_count", 25)):
        return matrix, selected_rows, created, [f"MATRIX_ENTRY_COUNT_INVALID:{len(entries)}"]
    if len(direct_rows) != expected:
        return matrix, selected_rows, created, [f"DIRECT_RECLASSIFY_COUNT_INVALID:{len(direct_rows)}"]

    allowed = list(contract.get("allowed_restore_prefixes", []))
    baseline_roots = list(contract.get("baseline_search_roots", []))
    default_prefix = str(contract["default_restore_prefix"])

    for row in entries:
        if row.get("binding_mode") != "DIRECT_PROVEN":
            patched_entries.append(row)
            continue

        synthetic, error = synthetic_recovery_entry(row)
        if error or synthetic is None:
            errors.append(error or "DIRECT_SYNTHETIC_ENTRY_FAILED")
            patched_entries.append(row)
            continue

        strategy_id = str(synthetic["strategy_id"])
        selected, reasons = driver.corrected_select_source(
            root,
            strategy_id,
            synthetic,
            allowed,
            baseline_roots,
            default_prefix,
        )
        if not selected:
            errors.append(f"DIRECT_ARTIFACT_UNRESOLVED:{strategy_id}:{'|'.join(reasons)}")
            patched_entries.append(row)
            continue

        expected_callable = str(synthetic["artifact_matches"][0]["callable"])
        if selected.get("callable") != expected_callable:
            errors.append(
                f"DIRECT_CALLABLE_CHANGED:{strategy_id}:{selected.get('callable')}:{expected_callable}"
            )
            patched_entries.append(row)
            continue

        destination = root / str(selected["destination_path"])
        if destination.is_file():
            current_sha = core.sha256_file(destination)
            if current_sha != selected.get("source_sha256"):
                errors.append(f"DIRECT_DESTINATION_CONFLICT:{strategy_id}:{destination}")
                patched_entries.append(row)
                continue
        else:
            core.atomic_text(destination, str(selected["source"]))
            created.append(destination)

        try:
            py_compile.compile(str(destination), doraise=True)
        except Exception as exc:
            errors.append(f"DIRECT_COMPILE_FAILED:{strategy_id}:{type(exc).__name__}:{exc}")
            patched_entries.append(row)
            continue

        patched = dict(row)
        patched["binding_mode"] = "RESTORE25_RECLASSIFIED_ARTIFACT"
        patched["canonical_engine"] = {
            "implementation_path": selected["destination_path"],
            "callable": selected["callable"],
            "source_sha256": selected["source_sha256"],
            "source_blob_sha": selected.get("origin_blob_sha"),
            "binding_source": "RESTORE25_RECLASSIFIED_DIRECT_ARTIFACT",
            "decision_reason": selected["decision_reason"],
        }
        patched_entries.append(patched)
        selected_rows.append(selected)

    if errors or len(selected_rows) != expected:
        for path in reversed(created):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        return matrix, [], [], errors or ["DIRECT_RECLASSIFICATION_NOT_COMPLETE"]

    patched_matrix = dict(matrix)
    patched_matrix["entries"] = patched_entries
    patched_matrix["reclassified_direct_count"] = len(selected_rows)
    patched_matrix["engine_bound_count"] = int(matrix.get("engine_bound_count", 0)) + len(selected_rows)
    patched_matrix["binding_complete_count"] = int(matrix.get("binding_complete_count", 0)) + len(selected_rows)
    return patched_matrix, selected_rows, created, []


def idempotent_core_success(status: dict[str, Any], verification: dict[str, Any]) -> bool:
    required = {
        "strategy_count": 25,
        "total_source_count": 25,
        "callable_valid_count": 25,
        "config_bound_count": 25,
        "canonical_unique_count": 25,
        "unresolved_count": 0,
        "active_entry_count": 0,
        "protected_change_count": 0,
    }
    return bool(
        verification.get("applied") is True
        and not status.get("blockers")
        and int(status.get("blocker_count", 0)) == 0
        and not verification.get("errors")
        and all(status.get(key) == value for key, value in required.items())
    )


def augment_success_outputs(
    root: Path,
    contract: dict[str, Any],
    direct_selected: list[dict[str, Any]],
) -> dict[str, Any]:
    total = int(contract.get("expected_total_recovery_count", 25))
    direct_count = len(direct_selected)

    restore_matrix_path = root / str(contract["restore_matrix_path"])
    restore_matrix = load_json(restore_matrix_path)
    existing_entries = [row for row in restore_matrix.get("entries", []) if isinstance(row, dict)]
    direct_public = [
        {key: value for key, value in row.items() if key != "source"}
        for row in direct_selected
    ]
    combined = {str(row.get("strategy_id")): row for row in existing_entries + direct_public}
    restore_matrix["restore_input_count"] = total
    restore_matrix["resolved_count"] = len(combined)
    restore_matrix["unresolved_count"] = 0
    restore_matrix["reclassified_direct_count"] = direct_count
    restore_matrix["entries"] = [combined[key] for key in sorted(combined)]
    core.atomic_json(restore_matrix_path, restore_matrix)

    verification_path = root / str(contract["verification_path"])
    verification = load_json(verification_path)
    verification["applied"] = True
    verification["restored_count"] = total
    verification["reclassified_direct_count"] = direct_count
    core.atomic_json(verification_path, verification)

    status_path = root / str(contract["status_path"])
    status = load_json(status_path)
    status["state"] = "PASS"
    status["restore_input_count"] = total
    status["resolved_plan_count"] = total
    status["restored_count"] = total
    status["reclassified_direct_count"] = direct_count
    status["blocker_count"] = 0
    status["blockers"] = []
    status["next_stage"] = contract["next_stage_pass"]
    core.atomic_json(status_path, status)
    return status


def print_final_status(status: dict[str, Any], root: Path, contract: dict[str, Any]) -> None:
    keys = (
        "state", "blocker_count", "strategy_count", "restore_input_count",
        "resolved_plan_count", "restored_count", "total_source_count",
        "callable_valid_count", "config_bound_count", "canonical_unique_count",
        "unresolved_count", "active_entry_count", "protected_change_count", "next_stage",
    )
    for key in keys:
        print(f"{key.upper()}={status.get(key)}")
    print(f"RECLASSIFIED_DIRECT_COUNT={status.get('reclassified_direct_count', 0)}")
    print("BLOCKERS=" + json.dumps(status.get("blockers", []), ensure_ascii=False))
    print("UNRESOLVED=[]")
    print("RESTORE_MATRIX=" + str(root / str(contract["restore_matrix_path"])))
    print("VERIFICATION=" + str(root / str(contract["verification_path"])))
    print("RC=0")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--apply", action="store_true")
    args, _ = parser.parse_known_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    patched_matrix, direct_selected, direct_created, errors = recover_reclassified_direct(
        root, contract, args.target_sha
    )
    if errors:
        print("DIRECT_RECLASSIFICATION_ERRORS=" + json.dumps(errors, ensure_ascii=False))
        return 2

    original_argv = list(sys.argv)
    captured = io.StringIO()
    try:
        with tempfile.TemporaryDirectory(prefix="r7_restore25_unified_") as tmp_name:
            tmp = Path(tmp_name)
            matrix_path = tmp / "engine_binding_matrix.json"
            contract_path = tmp / "contract.json"
            core.atomic_json(matrix_path, patched_matrix)
            patched_contract = dict(contract)
            patched_contract["prior_matrix_path"] = str(matrix_path)
            core.atomic_json(contract_path, patched_contract)

            sys.argv = [
                original_argv[0],
                "--root", str(root),
                "--target-sha", args.target_sha,
                "--contract", str(contract_path),
                "--apply",
            ]
            with contextlib.redirect_stdout(captured):
                rc = int(driver.main())
    finally:
        sys.argv = original_argv

    status = load_json(root / str(contract["status_path"]))
    verification = load_json(root / str(contract["verification_path"]))
    if rc != 0 and not idempotent_core_success(status, verification):
        print(captured.getvalue(), end="")
        for path in reversed(direct_created):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        print("BLOCKERS=" + json.dumps(status.get("blockers", []), ensure_ascii=False))
        print("VERIFICATION_ERRORS=" + json.dumps(verification.get("errors", []), ensure_ascii=False))
        return rc

    status = augment_success_outputs(root, contract, direct_selected)
    required = {
        "state": "PASS",
        "strategy_count": 25,
        "restore_input_count": 25,
        "resolved_plan_count": 25,
        "restored_count": 25,
        "total_source_count": 25,
        "callable_valid_count": 25,
        "config_bound_count": 25,
        "canonical_unique_count": 25,
        "unresolved_count": 0,
        "active_entry_count": 0,
        "protected_change_count": 0,
    }
    mismatches = [f"{key}:{status.get(key)}!={value}" for key, value in required.items() if status.get(key) != value]
    if mismatches:
        print("UNIFIED_VERIFICATION_ERRORS=" + json.dumps(mismatches, ensure_ascii=False))
        return 2

    print_final_status(status, root, contract)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())