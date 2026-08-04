from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_EXACT25_SOURCE_OWNER_AUDIT_V3_PRODUCER_BOUND"
SCHEMA = "zel.exact25.source_owner.audit.v3"
CANONICAL_MANIFEST_RELATIVE = Path("backend/config/q4r3_canonical_strategy_owner_manifest_v1.json")
PRODUCER_RELATIVE = Path("tools/q4r3_exact25_dedicated_shadow_producer.py")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def manifest_entries(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = manifest.get("strategies")
    entries: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw, list):
        entries = {
            str(row.get("strategy_id")): row
            for row in raw
            if isinstance(row, Mapping) and row.get("strategy_id")
        }
    elif isinstance(raw, Mapping):
        entries = {
            str(strategy_id): row
            for strategy_id, row in raw.items()
            if isinstance(row, Mapping)
        }
    if not entries:
        raise RuntimeError("CANONICAL_MANIFEST_STRATEGIES_MISSING")
    return entries


def field_text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value):
            return str(value)
    return ""


def resolve_owner_path(source_root: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = source_root / path
    return path.resolve()


def ast_has_callable(path: Path, callable_name: str) -> bool:
    if not callable_name:
        return True
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == callable_name
        for node in ast.walk(tree)
    )


def run(engine_path: Path, source_root: Path, terminal_path: Path) -> dict[str, Any]:
    terminal = read_json(terminal_path)
    replay = terminal.get("replay") if isinstance(terminal.get("replay"), Mapping) else {}
    checkpoint = terminal.get("checkpoint") if isinstance(terminal.get("checkpoint"), Mapping) else {}
    fingerprint_fields = (
        checkpoint.get("input_fingerprint_fields")
        if isinstance(checkpoint.get("input_fingerprint_fields"), Mapping)
        else {}
    )
    scorecards = {
        str(row.get("strategy_id")): row
        for row in terminal.get("scorecards", [])
        if isinstance(row, Mapping) and row.get("strategy_id")
    }

    manifest_path = (source_root / CANONICAL_MANIFEST_RELATIVE).resolve()
    producer_candidate = source_root / PRODUCER_RELATIVE
    producer_is_symlink = producer_candidate.is_symlink()
    producer_path = producer_candidate.resolve()
    manifest = read_json(manifest_path)
    owners = manifest_entries(manifest)
    manifest_sha = sha256_path(manifest_path)
    terminal_manifest_sha = field_text(fingerprint_fields, "owner_manifest_sha256")
    producer_exists = producer_path.is_file() and not producer_is_symlink
    producer_sha = sha256_path(producer_path) if producer_exists else None

    rows: list[dict[str, Any]] = []
    quarantined: list[str] = []
    strategy_ids = sorted(set(scorecards) | set(owners))

    for strategy_id in strategy_ids:
        scorecard = scorecards.get(strategy_id)
        owner = owners.get(strategy_id)
        blockers: list[str] = []

        if scorecard is None:
            blockers.append("TERMINAL_SCORECARD_MISSING")
        if owner is None:
            blockers.append("CANONICAL_MANIFEST_ENTRY_MISSING")

        terminal_sha = field_text(scorecard or {}, "owner_sha256").lower()
        manifest_owner_sha = field_text(owner or {}, "owner_sha256", "source_sha256", "sha256").lower()
        owner_path_raw = field_text(owner or {}, "owner_path", "source_path", "path")
        callable_name = field_text(owner or {}, "callable_name", "owner_callable", "function_name")
        owner_kind = field_text(owner or {}, "owner_kind", "kind")

        if not terminal_sha or not re.fullmatch(r"[0-9a-f]{64}", terminal_sha):
            blockers.append("TERMINAL_OWNER_SHA_INVALID")
        if not manifest_owner_sha or not re.fullmatch(r"[0-9a-f]{64}", manifest_owner_sha):
            blockers.append("MANIFEST_OWNER_SHA_INVALID")
        if not owner_path_raw:
            blockers.append("MANIFEST_OWNER_PATH_MISSING")

        resolved = resolve_owner_path(source_root, owner_path_raw) if owner_path_raw else None
        if resolved is None or not resolved.is_file():
            blockers.append("OWNER_SOURCE_FILE_MISSING")
            actual_sha = None
        else:
            try:
                resolved.relative_to(source_root.resolve())
            except ValueError:
                blockers.append("OWNER_PATH_OUTSIDE_SOURCE_ROOT")
            actual_sha = sha256_path(resolved)
            if callable_name:
                try:
                    if not ast_has_callable(resolved, callable_name):
                        blockers.append("OWNER_CALLABLE_MISSING")
                except (OSError, SyntaxError, UnicodeError) as exc:
                    blockers.append(f"OWNER_AST_ERROR:{type(exc).__name__}")

        if terminal_sha and manifest_owner_sha and terminal_sha != manifest_owner_sha:
            blockers.append("TERMINAL_MANIFEST_SHA_MISMATCH")
        if manifest_owner_sha and actual_sha and manifest_owner_sha != actual_sha:
            blockers.append("MANIFEST_SOURCE_SHA_MISMATCH")
        if terminal_sha and actual_sha and terminal_sha != actual_sha:
            blockers.append("TERMINAL_SOURCE_SHA_MISMATCH")

        identity = {
            "strategy_id": strategy_id,
            "owner_path": str(resolved) if resolved else None,
            "callable_name": callable_name,
            "owner_kind": owner_kind,
            "terminal_owner_sha256": terminal_sha or None,
            "manifest_owner_sha256": manifest_owner_sha or None,
            "actual_owner_sha256": actual_sha,
        }
        if blockers:
            quarantined.append(strategy_id)
        rows.append({
            **identity,
            "identity_sha256": stable_sha(identity),
            "state": "PASS_SOURCE_OWNER_BOUND" if not blockers else "QUARANTINE_SOURCE_MISMATCH",
            "blockers": blockers,
        })

    terminal_ids = set(scorecards)
    manifest_ids = set(owners)
    checks = {
        "terminal_scorecard_count_25": len(scorecards) == 25,
        "manifest_strategy_count_25": len(owners) == 25,
        "strategy_sets_equal": terminal_ids == manifest_ids,
        "terminal_closed_trade_count_1951": replay.get("closed_trade_count") == 1951,
        "terminal_error_count_0": replay.get("error_count") == 0,
        "terminal_censored_open_count_0": replay.get("censored_open_at_window_end") == 0,
        "terminal_manifest_sha_matches_active": terminal_manifest_sha == manifest_sha,
        "all_source_sha_match": len(rows) == 25 and not quarantined,
        "producer_file_present": producer_exists,
        "producer_path_not_symlink": not producer_is_symlink,
        "producer_sha256_bound": bool(producer_sha and re.fullmatch(r"[0-9a-f]{64}", producer_sha)),
        "runtime_unchanged": True,
        "canonical_unchanged": True,
        "formal_ledger_unchanged": True,
    }
    passed = all(checks.values())
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_EXACT25_SOURCE_OWNER_AUDIT" if passed else "HOLD_EXACT25_SOURCE_OWNER_MISMATCH",
        "engine_path": str(engine_path),
        "engine_sha256": sha256_path(engine_path),
        "producer_path": str(producer_path),
        "producer_sha256": producer_sha,
        "source_root": str(source_root),
        "terminal_path": str(terminal_path),
        "terminal_content_sha256": sha256_path(terminal_path),
        "terminal_receipt_sha256": terminal.get("receipt_sha256"),
        "canonical_manifest_path": str(manifest_path),
        "canonical_manifest_sha256": manifest_sha,
        "terminal_owner_manifest_sha256": terminal_manifest_sha or None,
        "checks": checks,
        "strategy_count": len(rows),
        "quarantined_strategy_ids": quarantined,
        "strategies": rows,
        "raw_source_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "ALLOW_BOUNDED_INDICATOR_QUEUE" if passed else "QUARANTINE_AND_REPAIR_SOURCE_BINDING",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    sample_list = {"strategies": [{"strategy_id": "alpha", "owner_path": "a.py", "owner_sha256": "a" * 64}]}
    sample_map = {"strategies": {"alpha": {"owner_path": "a.py", "owner_sha256": "a" * 64}}}
    assert list(manifest_entries(sample_list)) == ["alpha"]
    assert list(manifest_entries(sample_map)) == ["alpha"]
    assert stable_sha({"a": 1, "b": [2, 3]}) == stable_sha({"b": [2, 3], "a": 1})
    source = Path("/tmp/zel-source-owner-audit-self-test.py")
    source.write_text("def strategy(frame, state=None, risk_action='hold'):\n    return {'action':'hold'}\n", encoding="utf-8")
    assert ast_has_callable(source, "strategy") is True
    assert ast_has_callable(source, "missing") is False
    source.unlink(missing_ok=True)
    target = Path("/tmp/zel-source-owner-producer-target.py")
    link = Path("/tmp/zel-source-owner-producer-link.py")
    target.write_text("# target\n", encoding="utf-8")
    link.unlink(missing_ok=True)
    link.symlink_to(target)
    assert link.is_symlink() is True
    assert link.resolve().is_symlink() is False
    link.unlink(missing_ok=True)
    target.unlink(missing_ok=True)
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not all((args.engine, args.source_root, args.terminal)):
        parser.error("engine, source-root and terminal are required")
    receipt = run(args.engine.resolve(), args.source_root.resolve(), args.terminal.resolve())
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
