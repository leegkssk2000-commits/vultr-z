#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_REL = Path("backend/strategies/vwap_revert.py")
REGISTRY_REL = Path("backend/strategy25/canonical_strategy_registry_v1.json")

OLD_BLOCK = '''    if in_long and can_add_more:
        move_to_vwap = max(vwap_now - pos["avg_entry"], 1e-9)
        progress = (price - pos["avg_entry"]) / move_to_vwap if move_to_vwap > 0 else 0.0
        long_scale_in = progress >= cfg.scale_in_to_vwap_progress and rsi_now > cfg.long_rsi_reclaim
        long_water_add = extension_atr <= -cfg.water_add_extension_z_min and rsi_now <= cfg.long_rsi_trigger and price >= low

    if in_short and can_add_more:
        move_to_vwap = max(pos["avg_entry"] - vwap_now, 1e-9)
        progress = (pos["avg_entry"] - price) / move_to_vwap if move_to_vwap > 0 else 0.0
        short_scale_in = progress >= cfg.scale_in_to_vwap_progress and rsi_now < cfg.short_rsi_reclaim
        short_water_add = extension_atr >= cfg.water_add_extension_z_min and rsi_now >= cfg.short_rsi_trigger and price <= high
'''

NEW_BLOCK = '''    long_reversion_target = vwap_now - atr_now * cfg.trail_to_vwap_buffer_atr
    short_reversion_target = vwap_now + atr_now * cfg.trail_to_vwap_buffer_atr

    if in_long and can_add_more:
        long_avg_entry = pos["avg_entry"]
        if 0.0 < long_avg_entry < price < long_reversion_target:
            move_to_vwap = long_reversion_target - long_avg_entry
            progress = (price - long_avg_entry) / move_to_vwap
            long_scale_in = (
                cfg.scale_in_to_vwap_progress <= progress < 1.0
                and rsi_now > cfg.long_rsi_reclaim
            )
        long_water_add = extension_atr <= -cfg.water_add_extension_z_min and rsi_now <= cfg.long_rsi_trigger and price >= low

    if in_short and can_add_more:
        short_avg_entry = pos["avg_entry"]
        if short_reversion_target < price < short_avg_entry:
            move_to_vwap = short_avg_entry - short_reversion_target
            progress = (short_avg_entry - price) / move_to_vwap
            short_scale_in = (
                cfg.scale_in_to_vwap_progress <= progress < 1.0
                and rsi_now < cfg.short_rsi_reclaim
            )
        short_water_add = extension_atr >= cfg.water_add_extension_z_min and rsi_now >= cfg.short_rsi_trigger and price <= high
'''

REQUIRED_SNIPPETS = (
    'long_reversion_target = vwap_now - atr_now * cfg.trail_to_vwap_buffer_atr',
    'short_reversion_target = vwap_now + atr_now * cfg.trail_to_vwap_buffer_atr',
    '0.0 < long_avg_entry < price < long_reversion_target',
    'short_reversion_target < price < short_avg_entry',
    'cfg.scale_in_to_vwap_progress <= progress < 1.0',
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def transform_source(source: str) -> tuple[str, bool]:
    old_count = source.count(OLD_BLOCK)
    new_count = source.count(NEW_BLOCK)
    if old_count == 1 and new_count == 0:
        return source.replace(OLD_BLOCK, NEW_BLOCK, 1), True
    if old_count == 0 and new_count == 1:
        return source, False
    raise ValueError(
        f"VWAP_SCALE_IN_BLOCK_UNEXPECTED:old_count={old_count}:new_count={new_count}"
    )


def validate_source(source: str, filename: str) -> None:
    compile(source, filename, "exec")
    missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in source]
    if missing:
        raise ValueError("SOURCE_GUARD_MISSING:" + json.dumps(missing, ensure_ascii=False))
    if OLD_BLOCK in source:
        raise ValueError("UNSAFE_SCALE_IN_BLOCK_REMAINS")


def update_registry(
    registry: dict[str, Any], source_sha256: str
) -> tuple[dict[str, Any], str, bool]:
    updated = deepcopy(registry)
    matches = [
        row
        for row in updated.get("entries", [])
        if isinstance(row, dict) and row.get("strategy_id") == "vwap_revert"
    ]
    if len(matches) != 1:
        raise ValueError(f"VWAP_REGISTRY_ENTRY_COUNT:{len(matches)}")
    entry = matches[0]
    engine = entry.get("canonical_engine")
    if not isinstance(engine, dict):
        raise ValueError("VWAP_CANONICAL_ENGINE_MISSING")
    old_sha = str(engine.get("source_sha256") or "")
    changed = old_sha != source_sha256
    engine["source_sha256"] = source_sha256
    engine["binding_source"] = "R7.A4D2_VWAP_GEOMETRY_CLOSURE"
    engine["decision_reason"] = "VWAP_SCALE_IN_REVERSION_TARGET_GEOMETRY_CLOSED"
    return updated, old_sha, changed


def registry_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source_path = root / SOURCE_REL
    registry_path = root / REGISTRY_REL

    print("R7A4D2_VWAP_GEOMETRY_CLOSURE_START")
    print("MODE=" + ("ATOMIC_MINIMAL_PATCH" if args.apply else "READ_ONLY_PLAN"))
    print("STRATEGY_MUTATION_SCOPE=backend/strategies/vwap_revert.py_only")
    print("REGISTRY_MUTATION_SCOPE=vwap_revert_source_identity_only")
    print("CONFIG_MUTATION_ALLOWED=false")
    print("ROUTER_MUTATION_ALLOWED=false")
    print("SERVICE_MUTATION_ALLOWED=false")
    print("SHADOW_START_ALLOWED=false")
    print("PAPER_LIVE_ORDER_ALLOWED=false")

    if not source_path.is_file() or source_path.is_symlink():
        raise SystemExit(f"SOURCE_PATH_INVALID:{source_path}")
    if not registry_path.is_file() or registry_path.is_symlink():
        raise SystemExit(f"REGISTRY_PATH_INVALID:{registry_path}")

    original_source = source_path.read_text(encoding="utf-8")
    original_registry = load_json(registry_path)
    original_source_sha = sha256_bytes(original_source.encode("utf-8"))
    original_registry_sha = sha256_file(registry_path)

    registry_matches = [
        row
        for row in original_registry.get("entries", [])
        if isinstance(row, dict) and row.get("strategy_id") == "vwap_revert"
    ]
    if len(registry_matches) != 1:
        raise SystemExit(f"VWAP_REGISTRY_ENTRY_COUNT:{len(registry_matches)}")
    registered_before = str(
        registry_matches[0].get("canonical_engine", {}).get("source_sha256") or ""
    )
    if registered_before and registered_before != original_source_sha:
        raise SystemExit(
            "SOURCE_REGISTRY_PREFLIGHT_MISMATCH:"
            f"source={original_source_sha}:registry={registered_before}"
        )

    transformed_source, source_changed = transform_source(original_source)
    validate_source(transformed_source, str(source_path))
    new_source_sha = sha256_bytes(transformed_source.encode("utf-8"))
    transformed_registry, registered_before, registry_changed = update_registry(
        original_registry, new_source_sha
    )
    transformed_registry_text = registry_text(transformed_registry)
    new_registry_sha = sha256_bytes(transformed_registry_text.encode("utf-8"))

    backup_dir: Path | None = None
    rollback_performed = False
    if args.apply and (source_changed or registry_changed):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = root / "runtime/r7a4d2_vwap_revert_geometry_closure" / f"backup_{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source_path, backup_dir / source_path.name)
        shutil.copy2(registry_path, backup_dir / registry_path.name)
        try:
            atomic_write(source_path, transformed_source)
            atomic_write(registry_path, transformed_registry_text)
            if sha256_file(source_path) != new_source_sha:
                raise ValueError("POSTWRITE_SOURCE_SHA_MISMATCH")
            if sha256_file(registry_path) != new_registry_sha:
                raise ValueError("POSTWRITE_REGISTRY_SHA_MISMATCH")
            persisted_registry = load_json(registry_path)
            persisted_entry = [
                row
                for row in persisted_registry.get("entries", [])
                if isinstance(row, dict) and row.get("strategy_id") == "vwap_revert"
            ][0]
            if persisted_entry["canonical_engine"]["source_sha256"] != new_source_sha:
                raise ValueError("POSTWRITE_REGISTRY_SOURCE_SHA_MISMATCH")
        except Exception:
            shutil.copy2(backup_dir / source_path.name, source_path)
            shutil.copy2(backup_dir / registry_path.name, registry_path)
            rollback_performed = True
            raise

    applied = args.apply and not rollback_performed
    print(f"SOURCE_CHANGED={str(source_changed).lower()}")
    print(f"REGISTRY_CHANGED={str(registry_changed).lower()}")
    print(f"APPLIED={str(applied).lower()}")
    print(f"ROLLBACK_PERFORMED={str(rollback_performed).lower()}")
    print(f"OLD_SOURCE_SHA256={original_source_sha}")
    print(f"NEW_SOURCE_SHA256={new_source_sha}")
    print(f"OLD_REGISTRY_SHA256={original_registry_sha}")
    print(f"NEW_REGISTRY_SHA256={new_registry_sha}")
    print(f"REGISTERED_SOURCE_SHA256_BEFORE={registered_before}")
    print(f"REGISTERED_SOURCE_SHA256_AFTER={new_source_sha}")
    print("LONG_SCALE_IN_REVERSION_TARGET_GUARD=true")
    print("SHORT_SCALE_IN_REVERSION_TARGET_GUARD=true")
    print("SCALE_IN_PROGRESS_UPPER_BOUND_LT_1=true")
    print("BACKUP_DIR=" + (str(backup_dir) if backup_dir else ""))
    print("STATE=PASS_VWAP_REVERT_GEOMETRY_CLOSURE")
    print("NEXT_STAGE=R7.A4D2_TARGETED_REVERIFY_AFTER_VWAP_CLOSURE")
    print("RC=0")
    print("R7A4D2_VWAP_GEOMETRY_CLOSURE_COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
