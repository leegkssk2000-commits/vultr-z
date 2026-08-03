from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_EXACT25_SOURCE_OWNER_AUDIT_V1"
SCHEMA = "zel.exact25.source_owner.audit.v1"


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


def load_engine(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("zel_exact25_engine_owner_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ENGINE_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def owner_fields(owner: Any) -> dict[str, Any]:
    raw = vars(owner) if hasattr(owner, "__dict__") else {}
    return {
        "strategy_id": str(raw.get("strategy_id") or getattr(owner, "strategy_id", "")),
        "owner_path": str(raw.get("owner_path") or getattr(owner, "owner_path", "")),
        "callable_name": str(
            raw.get("callable_name")
            or raw.get("owner_callable")
            or raw.get("function_name")
            or getattr(owner, "callable_name", "")
            or getattr(owner, "owner_callable", "")
            or getattr(owner, "function_name", "")
        ),
        "owner_kind": str(raw.get("owner_kind") or getattr(owner, "owner_kind", "")),
    }


def ast_has_callable(path: Path, callable_name: str) -> bool:
    if not callable_name:
        return True
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == callable_name:
            return True
    return False


def run(engine_path: Path, source_root: Path, terminal_path: Path) -> dict[str, Any]:
    engine = load_engine(engine_path)
    producer = engine.import_producer(source_root)
    _, registry = producer.load_registry(source_root)
    terminal = read_json(terminal_path)
    scorecards = {
        str(row.get("strategy_id")): row
        for row in terminal.get("scorecards", [])
        if isinstance(row, Mapping) and row.get("strategy_id")
    }
    rows: list[dict[str, Any]] = []
    quarantined: list[str] = []
    for strategy_id in sorted(registry):
        owner = registry[strategy_id]
        fields = owner_fields(owner)
        owner_path_raw = fields["owner_path"]
        owner_path = Path(owner_path_raw)
        if not owner_path.is_absolute():
            owner_path = source_root / owner_path
        try:
            resolved = owner_path.resolve(strict=True)
        except FileNotFoundError:
            resolved = owner_path.resolve()
        blockers: list[str] = []
        if fields["strategy_id"] and fields["strategy_id"] != strategy_id:
            blockers.append("REGISTRY_OBJECT_STRATEGY_ID_MISMATCH")
        if not owner_path_raw:
            blockers.append("OWNER_PATH_MISSING")
        if not resolved.is_file():
            blockers.append("OWNER_SOURCE_FILE_MISSING")
        try:
            resolved.relative_to(source_root.resolve())
        except ValueError:
            blockers.append("OWNER_PATH_OUTSIDE_SOURCE_ROOT")
        actual_sha = sha256_path(resolved) if resolved.is_file() else None
        scorecard = scorecards.get(strategy_id)
        expected_sha = scorecard.get("owner_sha256") if isinstance(scorecard, Mapping) else None
        if scorecard is None:
            blockers.append("TERMINAL_SCORECARD_MISSING")
        if actual_sha != expected_sha:
            blockers.append("OWNER_SOURCE_SHA_MISMATCH")
        if fields["callable_name"] and resolved.is_file():
            try:
                if not ast_has_callable(resolved, fields["callable_name"]):
                    blockers.append("OWNER_CALLABLE_MISSING")
            except (OSError, SyntaxError, UnicodeError) as exc:
                blockers.append(f"OWNER_AST_ERROR:{type(exc).__name__}")
        identity = {
            "strategy_id": strategy_id,
            "owner_path": str(resolved),
            "callable_name": fields["callable_name"],
            "owner_kind": fields["owner_kind"],
            "owner_sha256": actual_sha,
            "terminal_owner_sha256": expected_sha,
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
    registry_ids = set(registry)
    checks = {
        "registry_count_25": len(registry) == 25,
        "terminal_scorecard_count_25": len(scorecards) == 25,
        "strategy_sets_equal": registry_ids == terminal_ids,
        "all_source_sha_match": not quarantined,
        "runtime_mutated": False,
        "canonical_mutated": False,
        "formal_ledger_mutated": False,
    }
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_EXACT25_SOURCE_OWNER_AUDIT" if all(checks.values()) else "HOLD_EXACT25_SOURCE_OWNER_MISMATCH",
        "engine_path": str(engine_path),
        "engine_sha256": sha256_path(engine_path),
        "source_root": str(source_root),
        "terminal_receipt_sha256": terminal.get("receipt_sha256"),
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
        "next": "ALLOW_BOUNDED_INDICATOR_QUEUE" if not quarantined else "QUARANTINE_AND_REPAIR_SOURCE_BINDING",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    sample = {"a": 1, "b": [2, 3]}
    assert stable_sha(sample) == stable_sha({"b": [2, 3], "a": 1})
    source = Path("/tmp/zel-source-owner-audit-self-test.py")
    source.write_text("def strategy(frame, state=None, risk_action='hold'):\n    return {'action':'hold'}\n", encoding="utf-8")
    assert ast_has_callable(source, "strategy") is True
    assert ast_has_callable(source, "missing") is False
    source.unlink(missing_ok=True)
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
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    if args.stdout:
        print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
