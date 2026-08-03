from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_EXACT25_OWNER_INVENTORY_V1"
SCHEMA = "zel.exact25.owner_inventory.v1"

PATH_KEYS = {
    "owner_path", "path", "source_path", "module_path", "file_path",
    "strategy_path", "owner_file", "source_file",
}
SHA_KEYS = {
    "owner_sha256", "sha256", "source_sha256", "file_sha256",
    "expected_sha256", "owner_sha",
}
STRATEGY_KEYS = {"strategy_id", "strategy", "name", "id"}
NON_AUTHORITY_TOKENS = {
    "backup", ".bak", "quarantine", "archive", "old", "snapshot",
    "runtime_results", "tmp", ".git", "node_modules", "__pycache__",
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


def candidate_json_files(root: Path) -> Iterable[Path]:
    filename_tokens = ("manifest", "binding", "registry", "owner", "strategy")
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__"}
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in skip_dirs]
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        if depth > 8:
            dirs[:] = []
            continue
        for name in files:
            lowered = name.lower()
            if not lowered.endswith(".json") or not any(token in lowered for token in filename_tokens):
                continue
            path = current_path / name
            try:
                if path.stat().st_size > 5_000_000:
                    continue
            except OSError:
                continue
            yield path


def record_strategy_id(record: Mapping[str, Any], strategy_ids: set[str]) -> str | None:
    for key, value in record.items():
        if str(key).lower() in STRATEGY_KEYS and isinstance(value, str) and value in strategy_ids:
            return value
    return None


def path_and_sha(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    owner_path = None
    expected_sha = None
    for key, value in record.items():
        lowered = str(key).lower()
        if owner_path is None and (lowered in PATH_KEYS or lowered.endswith("_path")) and isinstance(value, str):
            owner_path = value
        if expected_sha is None and (lowered in SHA_KEYS or "sha256" in lowered) and isinstance(value, str):
            if re.fullmatch(r"[0-9a-fA-F]{64}", value):
                expected_sha = value.lower()
    return owner_path, expected_sha


def extract_records(
    value: Any,
    strategy_ids: set[str],
    trail: tuple[str, ...] = (),
) -> list[tuple[str, tuple[str, ...], Mapping[str, Any]]]:
    found: list[tuple[str, tuple[str, ...], Mapping[str, Any]]] = []
    if isinstance(value, Mapping):
        record = {str(key): item for key, item in value.items()}
        direct_id = record_strategy_id(record, strategy_ids)
        if direct_id is not None:
            found.append((direct_id, trail, record))
        for key, item in record.items():
            if key in strategy_ids and isinstance(item, Mapping):
                found.append((key, trail + (key,), {str(k): v for k, v in item.items()}))
            found.extend(extract_records(item, strategy_ids, trail + (key,)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(extract_records(item, strategy_ids, trail + (str(index),)))
    return found


def is_active_json(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    lowered_text = str(path).lower()
    if any(token in lowered_parts for token in NON_AUTHORITY_TOKENS):
        return False
    return not any(f"/{token}/" in lowered_text for token in NON_AUTHORITY_TOKENS)


def resolve_owner_path(root: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def terminal_scorecards(path: Path) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    terminal = read_json(path)
    if not isinstance(terminal, Mapping):
        raise RuntimeError("TERMINAL_OBJECT_REQUIRED")
    scorecards = {
        str(row.get("strategy_id")): row
        for row in terminal.get("scorecards", [])
        if isinstance(row, Mapping) and row.get("strategy_id")
    }
    return scorecards, dict(terminal)


def run(root: Path, terminal_path: Path) -> dict[str, Any]:
    scorecards, terminal = terminal_scorecards(terminal_path)
    strategy_ids = set(scorecards)
    source_files: list[str] = []
    candidates: dict[str, list[dict[str, Any]]] = {strategy_id: [] for strategy_id in strategy_ids}
    seen: set[tuple[str, str, tuple[str, ...], str | None, str | None]] = set()

    for path in sorted(candidate_json_files(root)):
        try:
            parsed = read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        extracted = extract_records(parsed, strategy_ids)
        if not extracted:
            continue
        source_files.append(str(path))
        for strategy_id, trail, record in extracted:
            owner_path_raw, expected_sha = path_and_sha(record)
            if owner_path_raw is None and expected_sha is None:
                continue
            key = (strategy_id, str(path), trail, owner_path_raw, expected_sha)
            if key in seen:
                continue
            seen.add(key)
            resolved = resolve_owner_path(root, owner_path_raw)
            actual_sha = file_sha(resolved) if resolved else None
            candidates[strategy_id].append({
                "json_path": str(path),
                "json_active": is_active_json(path),
                "record_trail": list(trail),
                "owner_path_raw": owner_path_raw,
                "owner_path_resolved": str(resolved) if resolved else None,
                "owner_file_exists": bool(resolved and resolved.is_file()),
                "record_expected_owner_sha256": expected_sha,
                "actual_owner_sha256": actual_sha,
            })

    rows: list[dict[str, Any]] = []
    quarantined: list[str] = []
    for strategy_id in sorted(strategy_ids):
        terminal_sha = str(scorecards[strategy_id].get("owner_sha256") or "").lower() or None
        active = [row for row in candidates[strategy_id] if row["json_active"]]
        expected_shas = sorted({row["record_expected_owner_sha256"] for row in active if row["record_expected_owner_sha256"]})
        owner_paths = sorted({row["owner_path_resolved"] for row in active if row["owner_path_resolved"]})
        actual_shas = sorted({row["actual_owner_sha256"] for row in active if row["actual_owner_sha256"]})
        valid = [
            row for row in active
            if terminal_sha
            and row["record_expected_owner_sha256"] == terminal_sha
            and row["actual_owner_sha256"] == terminal_sha
            and row["owner_file_exists"]
        ]
        blockers: list[str] = []
        if not active:
            blockers.append("ACTIVE_AUTHORITY_RECORD_MISSING")
        if len(expected_shas) > 1:
            blockers.append("CONFLICTING_ACTIVE_EXPECTED_SHA")
        if len(owner_paths) > 1:
            blockers.append("CONFLICTING_ACTIVE_OWNER_PATH")
        if not terminal_sha or not re.fullmatch(r"[0-9a-f]{64}", terminal_sha):
            blockers.append("TERMINAL_OWNER_SHA_INVALID")
        if active and terminal_sha not in expected_shas:
            blockers.append("TERMINAL_SHA_NOT_BOUND_BY_ACTIVE_RECORD")
        if active and not any(row["owner_file_exists"] for row in active):
            blockers.append("ACTIVE_OWNER_SOURCE_FILE_MISSING")
        if active and terminal_sha and not any(row["actual_owner_sha256"] == terminal_sha for row in active):
            blockers.append("ACTIVE_OWNER_SOURCE_SHA_MISMATCH")
        if not valid and not blockers:
            blockers.append("NO_EXACT_TERMINAL_MANIFEST_SOURCE_TRIPLE")
        state = "PASS_SOURCE_OWNER_BOUND" if not blockers else "QUARANTINE_SOURCE_MISMATCH"
        if blockers:
            quarantined.append(strategy_id)
        identity = {
            "strategy_id": strategy_id,
            "terminal_owner_sha256": terminal_sha,
            "active_expected_sha256": expected_shas,
            "active_owner_paths": owner_paths,
            "active_actual_sha256": actual_shas,
        }
        rows.append({
            **identity,
            "identity_sha256": stable_sha(identity),
            "state": state,
            "blockers": blockers,
            "active_candidate_count": len(active),
            "exact_triple_count": len(valid),
            "candidates": candidates[strategy_id],
        })

    checks = {
        "terminal_strategy_count_25": len(scorecards) == 25,
        "terminal_closed_trade_count_1951": terminal.get("closed_trade_count") == 1951,
        "terminal_error_count_0": terminal.get("error_count") == 0,
        "terminal_censored_open_count_0": terminal.get("censored_open_count") == 0,
        "all_25_exact_source_owner_bound": len(rows) == 25 and not quarantined,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
    }
    state = "PASS_EXACT25_OWNER_INVENTORY" if all(checks.values()) else "HOLD_EXACT25_OWNER_INVENTORY_MISMATCH"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "root": str(root),
        "terminal_path": str(terminal_path),
        "terminal_receipt_sha256": terminal.get("receipt_sha256"),
        "strategy_count": len(rows),
        "candidate_json_file_count": len(set(source_files)),
        "candidate_json_files": sorted(set(source_files)),
        "quarantined_strategy_ids": quarantined,
        "quarantine_count": len(quarantined),
        "checks": checks,
        "strategies": rows,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "ALLOW_SOURCE_GATED_RESEARCH" if not quarantined else "REPAIR_QUARANTINED_OWNER_AUTHORITIES_ONE_AT_A_TIME",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    ids = {"alpha", "beta"}
    sample = {"rows": [{"strategy_id": "alpha", "owner_path": "a.py", "owner_sha256": "a" * 64}], "beta": {"owner_path": "b.py", "owner_sha256": "b" * 64}}
    found = extract_records(sample, ids)
    assert {row[0] for row in found} == ids
    assert path_and_sha(found[0][2])[0] is not None
    assert stable_sha({"a": 1, "b": 2}) == stable_sha({"b": 2, "a": 1})
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.root or not args.terminal:
        parser.error("root and terminal are required")
    receipt = run(args.root.resolve(), args.terminal.resolve())
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
