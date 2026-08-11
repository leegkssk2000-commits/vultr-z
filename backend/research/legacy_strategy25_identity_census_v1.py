#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "zel.legacy_strategy25.identity_census.v1"
INVENTORY_SCHEMA = "zel.legacy_strategy25.inventory.v1"
DEFAULT_INVENTORY = Path("research/legacy_strategy25_inventory_v1.json")
DEFAULT_ROOT = Path(".")
ROOT_NAMES = ("strategies", "backend", "config", "policies", "research", "runtime", "scripts", "tools")
TEXT_SUFFIXES = {".py", ".json", ".jsonl", ".yml", ".yaml", ".md", ".txt", ".toml", ".ini", ".sh"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "archive", "artifacts", "cache", ".cache"}
ARCHIVE_MARKERS = ("archive", "backup", "snapshot", "restore")
MAX_FILES = 12000
MAX_BYTES = 1_000_000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def iter_files(root: Path) -> Iterable[Path]:
    emitted = 0
    for name in ROOT_NAMES:
        base = root / name
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for filename in filenames:
                path = Path(dirpath) / filename
                try:
                    if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > MAX_BYTES:
                        continue
                except OSError:
                    continue
                yield path
                emitted += 1
                if emitted >= MAX_FILES:
                    return


def read_bounded(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(MAX_BYTES).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def load_inventory(path: Path) -> list[str]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if row.get("schema_version") != INVENTORY_SCHEMA:
        raise RuntimeError("STRATEGY25_INVENTORY_SCHEMA_INVALID")
    names = row.get("historical_implementation_inventory_25")
    if not isinstance(names, list) or len(names) != 25 or len(set(names)) != 25:
        raise RuntimeError("STRATEGY25_INVENTORY_NOT_EXACT_25")
    if any(not isinstance(v, str) or not v.strip() for v in names):
        raise RuntimeError("STRATEGY25_INVENTORY_ID_INVALID")
    return [str(v) for v in names]


def explicit_id_pattern(name: str) -> re.Pattern[str]:
    q = re.escape(name)
    return re.compile(
        rf"(?:strategy_id|STRATEGY_ID|strategyId)\s*(?::|=)\s*[\"']{q}[\"']|[\"']strategy_id[\"']\s*:\s*[\"']{q}[\"']",
        re.I,
    )


def archived_runtime_copy(root: Path, path: Path) -> bool:
    rel = safe_rel(root, path).lower()
    if not rel.startswith("runtime/"):
        return False
    parts = tuple(part.lower() for part in Path(rel).parts)
    return any(any(marker in part for marker in ARCHIVE_MARKERS) for part in parts)


def classify(root: Path, name: str, files: list[Path], texts: dict[Path, str]) -> dict[str, Any]:
    token = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
    explicit = explicit_id_pattern(name)
    direct: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    for path in files:
        text = texts[path]
        basename_match = path.suffix.lower() == ".py" and path.stem == name
        explicit_match = path.suffix.lower() == ".py" and bool(explicit.search(text))
        token_match = bool(token.search(text))
        if not (basename_match or explicit_match or token_match):
            continue
        archived_copy = archived_runtime_copy(root, path)
        row = {
            "path": safe_rel(root, path),
            "sha256": sha256_file(path),
            "suffix": path.suffix.lower(),
            "basename_match": basename_match,
            "explicit_strategy_id_match": explicit_match,
            "archived_runtime_copy": archived_copy,
        }
        if (basename_match or explicit_match) and not archived_copy:
            direct.append(row)
        else:
            references.append(row)
    direct.sort(key=lambda x: x["path"])
    references.sort(key=lambda x: x["path"])
    if len(direct) == 1:
        state = "SOURCE_IDENTITY_UNIQUE"
    elif len(direct) == 0:
        state = "HOLD_SOURCE_IDENTITY_MISSING"
    else:
        state = "HOLD_SOURCE_IDENTITY_AMBIGUOUS"
    return {
        "legacy_name": name,
        "state": state,
        "direct_source_candidate_count": len(direct),
        "direct_source_candidates": direct,
        "reference_only_count": len(references),
        "reference_only_paths": references,
        "baseline_replay_allowed": False,
        "migration_decision_allowed": False,
    }


def census(root: Path, inventory_path: Path) -> dict[str, Any]:
    names = load_inventory(inventory_path)
    files = list(iter_files(root))
    texts = {path: read_bounded(path) for path in files}
    rows = [classify(root, name, files, texts) for name in names]
    unique_count = sum(row["state"] == "SOURCE_IDENTITY_UNIQUE" for row in rows)
    missing_count = sum(row["state"] == "HOLD_SOURCE_IDENTITY_MISSING" for row in rows)
    ambiguous_count = sum(row["state"] == "HOLD_SOURCE_IDENTITY_AMBIGUOUS" for row in rows)
    gate = unique_count == 25 and missing_count == 0 and ambiguous_count == 0
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "PASS_STRATEGY25_IDENTITY_25_OF_25" if gate else "HOLD_STRATEGY25_IDENTITY_INCOMPLETE",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root.resolve()),
        "inventory_path": str(inventory_path),
        "historical_inventory_count": len(names),
        "files_scanned_bounded": len(files),
        "unique_source_identity_count": unique_count,
        "missing_source_identity_count": missing_count,
        "ambiguous_source_identity_count": ambiguous_count,
        "identity_gate_pass": gate,
        "rows": rows,
        "next_if_pass": "IDENTITY_AND_BASELINE_SMOKE_25_OF_25",
        "next_if_hold": "RECOVER_OR_ADJUDICATE_SOURCE_LINEAGE_WITHOUT_REPLAY",
        "raw_market_values_emitted": False,
        "replay_performed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_mutated": False,
        "service_state_mutated": False,
        "action": "hold",
    }
    material = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    receipt["receipt_sha256"] = hashlib.sha256(material).hexdigest()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only legacy Strategy25 identity census")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    inventory = args.inventory
    if not inventory.is_absolute():
        inventory = args.root / inventory
    result = census(args.root.resolve(), inventory.resolve())
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "unique": result["unique_source_identity_count"],
        "missing": result["missing_source_identity_count"],
        "ambiguous": result["ambiguous_source_identity_count"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
