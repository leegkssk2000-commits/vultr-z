from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_EXACT25_OWNER_INVENTORY_V1"
SCHEMA = "zel.exact25.owner_inventory.v1"


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


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def terminal_scorecards(path: Path) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    terminal = read_object(path)
    rows = terminal.get("scorecards", [])
    scorecards = {
        str(row.get("strategy_id")): row
        for row in rows
        if isinstance(row, Mapping) and row.get("strategy_id")
    }
    return scorecards, terminal


def manifest_entries(path: Path) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    manifest = read_object(path)
    raw = manifest.get("strategies")
    entries: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw, list):
        entries = {
            str(row.get("strategy_id")): row
            for row in raw
            if isinstance(row, Mapping) and row.get("strategy_id")
        }
    elif isinstance(raw, Mapping):
        for strategy_id, row in raw.items():
            if isinstance(row, Mapping):
                entries[str(strategy_id)] = row
    if not entries:
        raise RuntimeError("CANONICAL_MANIFEST_STRATEGIES_MISSING")
    return entries, manifest


def resolve_owner_path(root: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def run(root: Path, terminal_path: Path, manifest_path: Path) -> dict[str, Any]:
    scorecards, terminal = terminal_scorecards(terminal_path)
    manifest, manifest_raw = manifest_entries(manifest_path)
    strategy_ids = sorted(set(scorecards) | set(manifest))
    quarantined: list[str] = []
    rows: list[dict[str, Any]] = []

    for strategy_id in strategy_ids:
        scorecard = scorecards.get(strategy_id)
        authority = manifest.get(strategy_id)
        terminal_sha = str(scorecard.get("owner_sha256") or "").lower() if scorecard else None
        owner_path_raw = str(authority.get("owner_path") or "") if authority else None
        manifest_sha = str(authority.get("owner_sha256") or "").lower() if authority else None
        owner_path = resolve_owner_path(root, owner_path_raw)
        actual_sha = file_sha(owner_path) if owner_path else None
        blockers: list[str] = []

        if scorecard is None:
            blockers.append("TERMINAL_SCORECARD_MISSING")
        if authority is None:
            blockers.append("CANONICAL_MANIFEST_ENTRY_MISSING")
        if not terminal_sha or not re.fullmatch(r"[0-9a-f]{64}", terminal_sha):
            blockers.append("TERMINAL_OWNER_SHA_INVALID")
        if not manifest_sha or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha):
            blockers.append("MANIFEST_OWNER_SHA_INVALID")
        if not owner_path_raw:
            blockers.append("MANIFEST_OWNER_PATH_MISSING")
        if owner_path is None or not owner_path.is_file():
            blockers.append("OWNER_SOURCE_FILE_MISSING")
        if terminal_sha and manifest_sha and terminal_sha != manifest_sha:
            blockers.append("TERMINAL_MANIFEST_SHA_MISMATCH")
        if manifest_sha and actual_sha and manifest_sha != actual_sha:
            blockers.append("MANIFEST_SOURCE_SHA_MISMATCH")
        if terminal_sha and actual_sha and terminal_sha != actual_sha:
            blockers.append("TERMINAL_SOURCE_SHA_MISMATCH")

        exact = bool(
            not blockers
            and terminal_sha
            and terminal_sha == manifest_sha == actual_sha
        )
        state = "PASS_SOURCE_OWNER_BOUND" if exact else "QUARANTINE_SOURCE_MISMATCH"
        if state != "PASS_SOURCE_OWNER_BOUND":
            quarantined.append(strategy_id)
        identity = {
            "strategy_id": strategy_id,
            "owner_path": str(owner_path) if owner_path else None,
            "terminal_owner_sha256": terminal_sha,
            "manifest_owner_sha256": manifest_sha,
            "actual_owner_sha256": actual_sha,
        }
        rows.append({
            **identity,
            "identity_sha256": stable_sha(identity),
            "state": state,
            "blockers": blockers,
        })

    terminal_ids = set(scorecards)
    manifest_ids = set(manifest)
    checks = {
        "terminal_strategy_count_25": len(scorecards) == 25,
        "manifest_strategy_count_25": len(manifest) == 25,
        "terminal_manifest_strategy_sets_equal": terminal_ids == manifest_ids,
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
        "canonical_manifest_path": str(manifest_path),
        "canonical_manifest_sha256": file_sha(manifest_path),
        "canonical_manifest_declared_sha256": manifest_raw.get("manifest_sha256") or manifest_raw.get("receipt_sha256"),
        "strategy_count": len(rows),
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
    sample_list = {"strategies": [{"strategy_id": "alpha", "owner_path": "a.py", "owner_sha256": "a" * 64}]}
    sample_map = {"strategies": {"alpha": {"owner_path": "a.py", "owner_sha256": "a" * 64}}}
    for sample in (sample_list, sample_map):
        path = Path("/tmp/zel-exact25-owner-inventory-self-test.json")
        path.write_text(json.dumps(sample), encoding="utf-8")
        entries, _ = manifest_entries(path)
        assert list(entries) == ["alpha"]
        path.unlink(missing_ok=True)
    assert stable_sha({"a": 1, "b": 2}) == stable_sha({"b": 2, "a": 1})
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.root or not args.terminal or not args.manifest:
        parser.error("root, terminal and manifest are required")
    receipt = run(args.root.resolve(), args.terminal.resolve(), args.manifest.resolve())
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
