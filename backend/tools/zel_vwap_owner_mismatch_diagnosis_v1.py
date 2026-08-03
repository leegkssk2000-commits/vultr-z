from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_VWAP_OWNER_MISMATCH_DIAGNOSIS_V1"
SCHEMA = "zel.vwap_owner_mismatch.diagnosis.v1"
TARGET = "vwap_revert"

PATH_KEYS = {
    "owner_path", "path", "source_path", "module_path", "file_path",
    "strategy_path", "owner_file", "source_file",
}
SHA_KEYS = {
    "owner_sha256", "sha256", "source_sha256", "file_sha256",
    "expected_sha256", "owner_sha",
}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def target_records(value: Any, trail: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Mapping[str, Any]]]:
    found: list[tuple[tuple[str, ...], Mapping[str, Any]]] = []
    if isinstance(value, Mapping):
        keys = {str(key): item for key, item in value.items()}
        direct = any(str(item) == TARGET for item in keys.values())
        keyed = TARGET in keys
        if direct:
            found.append((trail, keys))
        if keyed:
            item = keys[TARGET]
            if isinstance(item, Mapping):
                found.append((trail + (TARGET,), {str(key): val for key, val in item.items()}))
        for key, item in keys.items():
            found.extend(target_records(item, trail + (key,)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(target_records(item, trail + (str(index),)))
    return found


def path_and_sha(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    path_value = None
    sha_value = None
    for key, value in record.items():
        key_lower = key.lower()
        if path_value is None and (key_lower in PATH_KEYS or key_lower.endswith("_path")) and isinstance(value, str):
            path_value = value
        if sha_value is None and (key_lower in SHA_KEYS or "sha256" in key_lower) and isinstance(value, str):
            if re.fullmatch(r"[0-9a-fA-F]{64}", value):
                sha_value = value.lower()
    return path_value, sha_value


def classify_path(path: Path) -> str:
    lowered = str(path).lower()
    if any(token in lowered for token in ("backup", ".bak", "quarantine", "archive", "old", "snapshot")):
        return "NON_AUTHORITATIVE_CANDIDATE"
    if "runtime_results" in lowered or "/tmp/" in lowered:
        return "RESULT_OR_TEMP_CANDIDATE"
    return "ACTIVE_PATH_CANDIDATE"


def candidate_json_files(root: Path) -> Iterable[Path]:
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__"}
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in skip_dirs]
        current_path = Path(current)
        if len(current_path.relative_to(root).parts) > 8:
            dirs[:] = []
            continue
        for name in files:
            if not name.lower().endswith(".json"):
                continue
            path = current_path / name
            try:
                if path.stat().st_size > 5_000_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if TARGET in text and any(token in name.lower() for token in ("manifest", "binding", "registry", "owner", "strategy")):
                yield path


def ast_function_summary(path: Path, function_name: str) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            segment = ast.get_source_segment(source, node) or ""
            literals = sorted({
                item.value
                for item in ast.walk(node)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
                and ("manifest" in item.value.lower() or "binding" in item.value.lower() or "owner" in item.value.lower())
            })
            return {
                "function": function_name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
                "arguments": [argument.arg for argument in node.args.args],
                "defaults": [ast.unparse(default) for default in node.args.defaults],
                "relevant_string_literals": literals,
                "source_sha256": hashlib.sha256(segment.encode()).hexdigest(),
            }
    return {"function": function_name, "missing": True}


def terminal_target(path: Path) -> dict[str, Any]:
    terminal = read_json(path)
    row = next(
        (item for item in terminal.get("scorecards", []) if isinstance(item, Mapping) and item.get("strategy_id") == TARGET),
        None,
    )
    if not isinstance(row, Mapping):
        raise RuntimeError("TERMINAL_VWAP_SCORECARD_MISSING")
    return {
        "owner_sha256": row.get("owner_sha256"),
        "close_count": row.get("close_count"),
        "signal_count": row.get("signal_count"),
        "valid_entry_count": row.get("valid_entry_count"),
        "claim_tier": row.get("claim_tier"),
        "failure_fingerprint": row.get("failure_fingerprint"),
        "terminal_receipt_sha256": terminal.get("receipt_sha256"),
    }


def diagnose(root: Path, producer_path: Path, loader_path: Path, terminal_path: Path) -> dict[str, Any]:
    terminal = terminal_target(terminal_path)
    candidates: list[dict[str, Any]] = []
    for path in sorted(set(candidate_json_files(root))):
        try:
            parsed = read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for trail, record in target_records(parsed):
            owner_path_raw, expected_sha = path_and_sha(record)
            resolved = None
            actual_sha = None
            if owner_path_raw:
                candidate = Path(owner_path_raw)
                resolved = candidate if candidate.is_absolute() else root / candidate
                resolved = resolved.resolve()
                actual_sha = file_sha(resolved)
            candidates.append({
                "json_path": str(path),
                "json_path_class": classify_path(path),
                "json_mtime_ns": path.stat().st_mtime_ns,
                "record_trail": list(trail),
                "record_keys": sorted(record.keys()),
                "owner_path_raw": owner_path_raw,
                "owner_path_resolved": str(resolved) if resolved else None,
                "owner_file_exists": bool(resolved and resolved.is_file()),
                "expected_owner_sha256": expected_sha,
                "actual_owner_sha256": actual_sha,
                "expected_matches_actual": bool(expected_sha and actual_sha and expected_sha == actual_sha),
                "terminal_matches_expected": bool(expected_sha and terminal["owner_sha256"] == expected_sha),
                "terminal_matches_actual": bool(actual_sha and terminal["owner_sha256"] == actual_sha),
            })
    active = [row for row in candidates if row["json_path_class"] == "ACTIVE_PATH_CANDIDATE"]
    exact_matches = [row for row in active if row["expected_matches_actual"]]
    terminal_actual_matches = [row for row in active if row["terminal_matches_actual"]]
    mismatches = [row for row in active if row["expected_owner_sha256"] and row["actual_owner_sha256"] and not row["expected_matches_actual"]]
    unique_actual = sorted({row["actual_owner_sha256"] for row in active if row["actual_owner_sha256"]})
    unique_expected = sorted({row["expected_owner_sha256"] for row in active if row["expected_owner_sha256"]})
    checks = {
        "producer_exists": producer_path.is_file(),
        "loader_exists": loader_path.is_file(),
        "terminal_owner_sha_present": bool(terminal["owner_sha256"]),
        "active_candidate_records_found": bool(active),
        "single_active_actual_source_sha": len(unique_actual) == 1,
        "single_active_expected_source_sha": len(unique_expected) == 1,
        "active_expected_matches_actual": bool(exact_matches) and not mismatches,
        "terminal_matches_active_actual": bool(terminal_actual_matches),
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
    }
    if not active:
        cause = "NO_ACTIVE_MANIFEST_OR_BINDING_RECORD_FOUND"
    elif len(unique_actual) > 1:
        cause = "MULTIPLE_ACTIVE_OWNER_SOURCE_FILES"
    elif len(unique_expected) > 1:
        cause = "CONFLICTING_ACTIVE_EXPECTED_SHA"
    elif mismatches and terminal_actual_matches:
        cause = "MANIFEST_OR_BINDING_SHA_STALE_SOURCE_MATCHES_TERMINAL"
    elif mismatches and not terminal_actual_matches:
        cause = "OWNER_SOURCE_DRIFT_FROM_MANIFEST_AND_TERMINAL"
    elif exact_matches and terminal_actual_matches:
        cause = "NO_CURRENT_VWAP_MISMATCH_REPRODUCED"
    else:
        cause = "AMBIGUOUS_OWNER_AUTHORITY"
    state = "PASS_VWAP_OWNER_AUTHORITY_CONFIRMED" if all(checks.values()) else "HOLD_VWAP_OWNER_AUTHORITY_MISMATCH"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "strategy_id": TARGET,
        "root": str(root),
        "producer": {"path": str(producer_path), "sha256": file_sha(producer_path), "load_registry": ast_function_summary(producer_path, "load_registry") if producer_path.is_file() else None},
        "loader": {"path": str(loader_path), "sha256": file_sha(loader_path), "load_shadow_registry": ast_function_summary(loader_path, "load_shadow_registry") if loader_path.is_file() else None},
        "terminal": terminal,
        "checks": checks,
        "cause": cause,
        "active_candidate_count": len(active),
        "exact_match_count": len(exact_matches),
        "mismatch_count": len(mismatches),
        "unique_active_actual_sha256": unique_actual,
        "unique_active_expected_sha256": unique_expected,
        "candidates": candidates,
        "recommended_action": (
            "NO_CHANGE"
            if state.startswith("PASS")
            else "QUARANTINE_VWAP_REVERT_AND_REPAIR_SINGLE_AUTHORITY_RECORD"
        ),
        "raw_source_published": False,
        "credentials_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    sample = {"strategy_id": TARGET, "owner_path": "strategies/vwap.py", "owner_sha256": "a" * 64}
    records = target_records({"rows": [sample]})
    assert records and path_and_sha(records[0][1]) == ("strategies/vwap.py", "a" * 64)
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--producer", type=Path)
    parser.add_argument("--loader", type=Path)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not all((args.root, args.producer, args.loader, args.terminal)):
        parser.error("root, producer, loader and terminal are required")
    receipt = diagnose(args.root.resolve(), args.producer.resolve(), args.loader.resolve(), args.terminal.resolve())
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
