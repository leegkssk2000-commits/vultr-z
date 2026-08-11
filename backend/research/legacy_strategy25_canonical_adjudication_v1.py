#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "zel.legacy_strategy25.canonical_adjudication.v1"
CANONICAL_REL_ROOT = Path("backend/strategies")
PROVENANCE_MARKERS = ("runtime", "archive", "backup", "restore")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def syntax_receipt(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    functions = sorted(
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    classes = sorted(node.name for node in tree.body if isinstance(node, ast.ClassDef))
    return {
        "syntax_ok": True,
        "top_level_functions": functions,
        "top_level_classes": classes,
    }


def provenance_copies(root: Path, legacy_name: str, canonical: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    needle = f"{legacy_name}.py"
    for path in root.rglob(needle):
        if path == canonical or not path.is_file():
            continue
        rel = path.relative_to(root)
        lowered = "/".join(rel.parts).lower()
        if not any(marker in lowered for marker in PROVENANCE_MARKERS):
            continue
        rows.append({
            "path": str(path),
            "sha256": sha256_file(path),
            "role": "PROVENANCE_COPY_NOT_EXECUTABLE_AUTHORITY",
        })
    rows.sort(key=lambda row: row["path"])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--inventory", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    root = ns.root.resolve()
    inventory = json.loads(ns.inventory.read_text(encoding="utf-8"))
    names = list(inventory.get("historical_implementation_inventory_25") or [])
    if inventory.get("schema_version") != "zel.legacy_strategy25.inventory.v1":
        raise RuntimeError("INVENTORY_SCHEMA")
    if len(names) != 25 or len(set(names)) != 25:
        raise RuntimeError(f"INVENTORY_CARDINALITY:{len(names)}:{len(set(names))}")

    canonical_root = root / CANONICAL_REL_ROOT
    rows: list[dict[str, Any]] = []
    canonical_ok = 0
    missing = 0
    syntax_fail = 0

    for legacy_name in names:
        canonical = canonical_root / f"{legacy_name}.py"
        row: dict[str, Any] = {
            "legacy_name": legacy_name,
            "canonical_path": str(canonical),
            "canonical_exists": canonical.is_file(),
            "canonical_role": "EXECUTABLE_SOURCE_AUTHORITY",
            "canonical_sha256": None,
            "canonical_bytes": None,
            "syntax_ok": False,
            "top_level_functions": [],
            "top_level_classes": [],
            "provenance_copy_count": 0,
            "provenance_copies": [],
            "state": "HOLD_MISSING_CANONICAL_SOURCE",
        }
        if not canonical.is_file():
            missing += 1
            rows.append(row)
            continue
        row["canonical_sha256"] = sha256_file(canonical)
        row["canonical_bytes"] = canonical.stat().st_size
        try:
            syntax = syntax_receipt(canonical)
            row.update(syntax)
            copies = provenance_copies(root, legacy_name, canonical)
            row["provenance_copies"] = copies
            row["provenance_copy_count"] = len(copies)
            row["state"] = "PASS_CANONICAL_SOURCE_IDENTITY"
            canonical_ok += 1
        except (SyntaxError, UnicodeError) as exc:
            row["syntax_error"] = f"{type(exc).__name__}:{str(exc)[:240]}"
            row["state"] = "HOLD_CANONICAL_SOURCE_SYNTAX"
            syntax_fail += 1
        rows.append(row)

    all_pass = canonical_ok == 25 and missing == 0 and syntax_fail == 0
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "PASS_CANONICAL_SOURCE_IDENTITY_25_OF_25" if all_pass else "HOLD_CANONICAL_SOURCE_IDENTITY",
        "root": str(root),
        "canonical_source_root": str(canonical_root),
        "historical_inventory_count": len(names),
        "canonical_pass_count": canonical_ok,
        "missing_canonical_count": missing,
        "syntax_fail_count": syntax_fail,
        "source_ready_for_baseline_smoke": all_pass,
        "economic_replay_performed": False,
        "economic_replay_authority": False,
        "raw_market_values_emitted": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_mutated": False,
        "service_state_mutated": False,
        "canonical_adjudication_rule": "Only <root>/backend/strategies/<legacy_id>.py is executable source authority. runtime/archive/backup/restore copies are provenance-only and never create source ambiguity.",
        "rows": rows,
        "next": "STRATEGY25_ECONOMIC_EVIDENCE_RECOVERY_AND_ADMISSION" if all_pass else "REPAIR_CANONICAL_SOURCE_IDENTITY_ONLY",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "canonical_pass_count": canonical_ok,
        "missing_canonical_count": missing,
        "syntax_fail_count": syntax_fail,
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
