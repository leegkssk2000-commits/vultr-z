from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_VWAP_CHANGE_LINEAGE_V1"
SCHEMA = "zel.vwap_change_lineage.v1"

INTEREST_KEYS = (
    "state", "status", "result", "action", "next", "strategy_id", "candidate_id",
    "approved", "approval", "applied", "application", "canonical", "mutation",
    "rebaseline", "baseline", "source_sha", "sha256", "before", "after", "rollback",
    "execution_authority", "order_authority", "promotion_authority", "live", "paper",
)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(value: Any, trail: tuple[str, ...] = (), out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if out is None:
        out = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(token in lowered for token in INTEREST_KEYS) and isinstance(item, (str, int, float, bool, type(None))):
                out.append({"trail": list(trail + (key_text,)), "value": item})
            extract(item, trail + (key_text,), out)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            extract(item, trail + (str(index),), out)
    return out


def json_summaries(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in {".git", "__pycache__"}]
        for name in files:
            if not name.endswith(".json"):
                continue
            path = Path(current) / name
            try:
                if path.stat().st_size > 3_000_000:
                    continue
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            rows.append({
                "path": str(path),
                "mtime_ns": path.stat().st_mtime_ns,
                "size": path.stat().st_size,
                "sha256": file_sha(path),
                "facts": extract(parsed)[:250],
            })
    return sorted(rows, key=lambda row: row["path"])


def function_hashes(path: Path) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    result: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            segment = ast.get_source_segment(source, node) or ""
            result[node.name] = hashlib.sha256(segment.encode()).hexdigest()
    return result


def compare_sources(expected: Path, active: Path) -> dict[str, Any]:
    expected_lines = expected.read_text(encoding="utf-8").splitlines()
    active_lines = active.read_text(encoding="utf-8").splitlines()
    expected_functions = function_hashes(expected)
    active_functions = function_hashes(active)
    names = sorted(set(expected_functions) | set(active_functions))
    return {
        "expected_path": str(expected),
        "active_path": str(active),
        "expected_sha256": file_sha(expected),
        "active_sha256": file_sha(active),
        "expected_line_count": len(expected_lines),
        "active_line_count": len(active_lines),
        "functions_added": [name for name in names if name not in expected_functions],
        "functions_removed": [name for name in names if name not in active_functions],
        "functions_changed": [name for name in names if name in expected_functions and name in active_functions and expected_functions[name] != active_functions[name]],
        "function_count_expected": len(expected_functions),
        "function_count_active": len(active_functions),
    }


def run(root: Path, expected: Path, active: Path, plan_dirs: list[Path]) -> dict[str, Any]:
    plans = [{"root": str(path), "files": json_summaries(path)} for path in plan_dirs]
    all_facts = [fact for plan in plans for file in plan["files"] for fact in file["facts"]]
    text = json.dumps(all_facts, sort_keys=True).lower()
    signals = {
        "approval_signal_present": any(token in text for token in ('"approved"', 'pass_', 'apply_allowed')),
        "canonical_application_signal_present": any(token in text for token in ('canonical_applied', 'canonical_mutated", true', 'application_allowed", true')),
        "rebaseline_complete_signal_present": any(token in text for token in ('rebaseline_complete', 'pass_rebaseline', 'terminal_pass')),
        "rollback_signal_present": "rollback" in text,
        "authority_block_signal_present": any(token in text for token in ('order_authority", "blocked', 'execution_authority", "none', 'promotion_authority", false')),
    }
    if signals["canonical_application_signal_present"] and signals["rebaseline_complete_signal_present"]:
        cause = "INTENTIONAL_SOURCE_CHANGE_WITH_COMPLETED_REBASELINE"
        next_step = "UPDATE_AUTHORITY_TO_NEW_EPOCH_ONLY_AFTER_RECEIPT_PARITY"
    elif signals["canonical_application_signal_present"]:
        cause = "INTENTIONAL_SOURCE_CHANGE_WITHOUT_COMPLETED_REBASELINE"
        next_step = "KEEP_QUARANTINED_AND_COMPLETE_NEW_EPOCH_REBASELINE"
    elif signals["approval_signal_present"]:
        cause = "PLANNED_OR_APPROVED_CHANGE_NOT_PROVEN_APPLIED"
        next_step = "RESTORE_TERMINAL_SOURCE_OR_PROVE_APPLICATION_RECEIPT"
    else:
        cause = "NO_PROVEN_CHANGE_AUTHORITY"
        next_step = "RESTORE_TERMINAL_PINNED_SOURCE_AFTER_ROLLBACK_REHEARSAL"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_VWAP_CHANGE_LINEAGE_AUDIT",
        "strategy_id": "vwap_revert",
        "source_comparison": compare_sources(expected, active),
        "plan_directories": plans,
        "signals": signals,
        "cause": cause,
        "next": next_step,
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
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--plan-dir", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()
    receipt = run(args.root, args.expected, args.active, args.plan_dir)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
