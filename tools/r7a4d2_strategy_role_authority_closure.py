#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

TARGET_IDS = (
    "break_and_continue",
    "rbreaker_like",
    "squeeze_break",
    "trend_ma_macd",
    "vwap_revert",
)
ROLE = "standalone"
EXECUTION_SCOPE = "independent_entry_add_reduce_exit"
AUTHORITY_SOURCE = "R7.A4D2_ENTRY_TO_ADD_CHAIN_DIAGNOSE"
AUTHORITY_REASON = "SOURCE_ENTER_AND_ADD_BRANCHES_PRESENT_ROLE_AUTHORITY_EXPLICIT"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def validate_registry(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise ValueError("REGISTRY_ENTRIES_REQUIRED")
    if int(registry.get("strategy_count") or 0) != 25 or len(entries) != 25:
        raise ValueError(f"STRATEGY_COUNT_INVALID:{registry.get('strategy_count')}:{len(entries)}")

    by_id: dict[str, dict[str, Any]] = {}
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError("REGISTRY_ENTRY_OBJECT_REQUIRED")
        strategy_id = str(row.get("strategy_id") or "")
        if not strategy_id or strategy_id in by_id:
            raise ValueError(f"STRATEGY_ID_INVALID_OR_DUPLICATE:{strategy_id}")
        if row.get("active_allowed") is not False:
            raise ValueError(f"ACTIVE_ALLOWED_NOT_FALSE:{strategy_id}")
        engine = row.get("canonical_engine")
        if not isinstance(engine, dict):
            raise ValueError(f"CANONICAL_ENGINE_REQUIRED:{strategy_id}")
        if not str(engine.get("implementation_path") or ""):
            raise ValueError(f"IMPLEMENTATION_PATH_REQUIRED:{strategy_id}")
        if not str(engine.get("source_sha256") or ""):
            raise ValueError(f"SOURCE_SHA_REQUIRED:{strategy_id}")
        by_id[strategy_id] = row

    missing = [strategy_id for strategy_id in TARGET_IDS if strategy_id not in by_id]
    if missing:
        raise ValueError("TARGET_STRATEGY_MISSING:" + ",".join(missing))
    return by_id


def build_closed_registry(registry: dict[str, Any]) -> dict[str, Any]:
    closed = copy.deepcopy(registry)
    by_id = validate_registry(closed)
    for strategy_id in TARGET_IDS:
        row = by_id[strategy_id]
        existing_role = str(row.get("strategy_role") or "").strip().lower()
        if existing_role and existing_role != ROLE:
            raise ValueError(f"CONFLICTING_ROLE:{strategy_id}:{existing_role}")
        row["strategy_role"] = ROLE
        row["execution_scope"] = EXECUTION_SCOPE
        row["role_authority_source"] = AUTHORITY_SOURCE
        row["role_authority_reason"] = AUTHORITY_REASON
    return closed


def verify_closed(
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    before_by_id = validate_registry(before)
    after_by_id = validate_registry(after)

    if set(before_by_id) != set(after_by_id):
        raise ValueError("STRATEGY_ID_SET_CHANGED")

    for strategy_id in before_by_id:
        before_row = before_by_id[strategy_id]
        after_row = after_by_id[strategy_id]
        if before_row.get("canonical_engine") != after_row.get("canonical_engine"):
            raise ValueError(f"CANONICAL_ENGINE_CHANGED:{strategy_id}")
        if before_row.get("config_ref") != after_row.get("config_ref"):
            raise ValueError(f"CONFIG_REF_CHANGED:{strategy_id}")
        if before_row.get("active_allowed") != after_row.get("active_allowed"):
            raise ValueError(f"ACTIVE_ALLOWED_CHANGED:{strategy_id}")
        if before_row.get("fail_closed") != after_row.get("fail_closed"):
            raise ValueError(f"FAIL_CLOSED_CHANGED:{strategy_id}")

        if strategy_id in TARGET_IDS:
            if after_row.get("strategy_role") != ROLE:
                raise ValueError(f"ROLE_NOT_CLOSED:{strategy_id}")
            if after_row.get("execution_scope") != EXECUTION_SCOPE:
                raise ValueError(f"EXECUTION_SCOPE_NOT_CLOSED:{strategy_id}")
            if after_row.get("role_authority_source") != AUTHORITY_SOURCE:
                raise ValueError(f"AUTHORITY_SOURCE_NOT_CLOSED:{strategy_id}")
            if after_row.get("role_authority_reason") != AUTHORITY_REASON:
                raise ValueError(f"AUTHORITY_REASON_NOT_CLOSED:{strategy_id}")
        else:
            if before_row != after_row:
                raise ValueError(f"NON_TARGET_ENTRY_CHANGED:{strategy_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    config_path = root / "backend/strategy25/canonical_strategy25_config_v1.json"

    print("R7A4D2_STRATEGY_ROLE_AUTHORITY_CLOSURE_START")
    print("MODE=" + ("ATOMIC_APPLY" if args.apply else "READ_ONLY_PLAN"))
    print("REGISTRY_MUTATION_ALLOWED=" + str(bool(args.apply)).lower())
    print("STRATEGY_SOURCE_MUTATION_ALLOWED=false")
    print("STRATEGY_LOGIC_MUTATION_ALLOWED=false")
    print("CONFIG_MUTATION_ALLOWED=false")
    print("ROUTER_MUTATION_ALLOWED=false")
    print("SERVICE_MUTATION_ALLOWED=false")
    print("SHADOW_START_ALLOWED=false")
    print("PAPER_LIVE_ORDER_ALLOWED=false")

    if not registry_path.is_file() or not config_path.is_file():
        print("STATE=HOLD")
        print("BLOCKERS=[\"REGISTRY_OR_CONFIG_MISSING\"]")
        print("RC=2")
        return 2

    before_registry = load_json(registry_path)
    before_config_sha = sha256_file(config_path)
    before_registry_sha = sha256_file(registry_path)
    before_by_id = validate_registry(before_registry)

    source_hashes_before: dict[str, str] = {}
    for strategy_id, row in before_by_id.items():
        engine = row["canonical_engine"]
        source_path = root / str(engine["implementation_path"])
        if not source_path.is_file():
            raise ValueError(f"SOURCE_MISSING:{strategy_id}:{source_path}")
        actual_sha = sha256_file(source_path)
        if actual_sha != str(engine["source_sha256"]):
            raise ValueError(f"SOURCE_REGISTRY_SHA_MISMATCH:{strategy_id}")
        source_hashes_before[strategy_id] = actual_sha

    planned_registry = build_closed_registry(before_registry)
    verify_closed(before_registry, planned_registry)

    already_closed = before_registry == planned_registry
    print("TARGET_STRATEGY_COUNT=5")
    print("TARGET_STRATEGIES=" + json.dumps(list(TARGET_IDS), ensure_ascii=False))
    print("ROLE=standalone")
    print("EXECUTION_SCOPE=" + EXECUTION_SCOPE)
    print("ALREADY_CLOSED=" + str(already_closed).lower())
    print("PRE_REGISTRY_SHA256=" + before_registry_sha)
    print("PRE_CONFIG_SHA256=" + before_config_sha)

    backup_path: Path | None = None
    if args.apply and not already_closed:
        backup_dir = root / "runtime/r7a4d2_strategy_role_authority_closure/backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"canonical_strategy_registry_v1.{before_registry_sha}.json"
        if not backup_path.exists():
            backup_path.write_bytes(registry_path.read_bytes())

        try:
            atomic_write_json(registry_path, planned_registry)
            applied_registry = load_json(registry_path)
            verify_closed(before_registry, applied_registry)
            if sha256_file(config_path) != before_config_sha:
                raise ValueError("CONFIG_SHA_CHANGED")
            for strategy_id, expected_sha in source_hashes_before.items():
                source_path = root / str(before_by_id[strategy_id]["canonical_engine"]["implementation_path"])
                if sha256_file(source_path) != expected_sha:
                    raise ValueError(f"STRATEGY_SOURCE_CHANGED:{strategy_id}")
        except Exception:
            atomic_write_json(registry_path, before_registry)
            raise

    final_registry = load_json(registry_path) if args.apply else planned_registry
    verify_closed(before_registry, final_registry)
    final_by_id = validate_registry(final_registry)
    role_closed_count = sum(
        final_by_id[strategy_id].get("strategy_role") == ROLE for strategy_id in TARGET_IDS
    )

    print("STATE=PASS_STRATEGY_ROLE_AUTHORITY_CLOSURE")
    print("ROLE_CLOSED_COUNT=" + str(role_closed_count))
    print("CANONICAL_ENGINE_CHANGE_COUNT=0")
    print("STRATEGY_SOURCE_CHANGE_COUNT=0")
    print("CONFIG_CHANGE_COUNT=0")
    print("ACTIVE_ALLOWED_TRUE_COUNT=0")
    print("BACKUP_PATH=" + (str(backup_path) if backup_path else ""))
    print("POST_REGISTRY_SHA256=" + (sha256_file(registry_path) if args.apply else "PLAN_ONLY"))
    print("NEXT_STAGE=R7.A4D2_ENTRY_TRIGGER_CHAIN_REDESIGN")
    print("R7A4D2_STRATEGY_ROLE_AUTHORITY_CLOSURE_COMPLETE")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
