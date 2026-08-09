#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except Exception:
        return str(path)


def source_candidates(name: str) -> list[Path]:
    return [
        ROOT / "backend" / "strategies" / f"{name}.py",
        ROOT / "strategies" / f"{name}.py",
    ]


def static_smoke(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8", errors="strict")
    except Exception as exc:
        return {
            "ast_ok": False,
            "error_class": type(exc).__name__,
            "top_level_functions": [],
            "top_level_classes": [],
            "signal_like_symbols": [],
            "import_execution_performed": False,
        }
    try:
        tree = ast.parse(raw, filename=str(path))
    except SyntaxError as exc:
        return {
            "ast_ok": False,
            "error_class": "SyntaxError",
            "syntax_line": exc.lineno,
            "top_level_functions": [],
            "top_level_classes": [],
            "signal_like_symbols": [],
            "import_execution_performed": False,
        }
    functions = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    symbols = functions + classes
    hints = [
        x for x in symbols
        if any(k in x.lower() for k in ("signal", "entry", "exit", "strategy", "generate", "decide", "compute"))
    ]
    return {
        "ast_ok": True,
        "error_class": None,
        "top_level_functions": functions[:80],
        "top_level_classes": classes[:40],
        "signal_like_symbols": hints[:40],
        "import_execution_performed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True)
    args = ap.parse_args()
    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    names = [str(x) for x in inv.get("historical_implementation_inventory_25", [])]

    rows: list[dict[str, Any]] = []
    hashes: dict[str, list[str]] = defaultdict(list)
    blockers: list[str] = []
    for name in names:
        existing = [p for p in source_candidates(name) if p.is_file()]
        if not existing:
            rows.append({
                "legacy_name": name,
                "present": False,
                "source_path": None,
                "source_sha256": None,
                "size_bytes": None,
                "duplicate_path_count": 0,
                "static_smoke": {"ast_ok": False, "error_class": "SOURCE_MISSING", "import_execution_performed": False},
            })
            continue
        path = existing[0]
        digest = sha256_file(path)
        hashes[digest].append(name)
        rows.append({
            "legacy_name": name,
            "present": True,
            "source_path": rel(path),
            "source_sha256": digest,
            "size_bytes": path.stat().st_size,
            "duplicate_path_count": len(existing),
            "alternate_paths": [rel(p) for p in existing[1:]],
            "static_smoke": static_smoke(path),
        })

    present_count = sum(1 for x in rows if x["present"])
    ast_ok_count = sum(1 for x in rows if x.get("static_smoke", {}).get("ast_ok") is True)
    duplicate_path_names = [x["legacy_name"] for x in rows if int(x.get("duplicate_path_count", 0)) > 1]
    identical_hash_groups = [sorted(v) for v in hashes.values() if len(v) > 1]
    missing = [x["legacy_name"] for x in rows if not x["present"]]
    ast_fail = [x["legacy_name"] for x in rows if x["present"] and not x.get("static_smoke", {}).get("ast_ok")]

    if len(names) != 25:
        blockers.append("INVENTORY_NOT_25")
    if missing:
        blockers.append("STRATEGY_SOURCE_MISSING")
    if ast_fail:
        blockers.append("STATIC_AST_SMOKE_FAILED")
    if duplicate_path_names:
        blockers.append("MULTIPLE_SOURCE_PATHS_REQUIRE_LINEAGE_ADJUDICATION")

    state = "PASS_P5_IDENTITY_AND_STATIC_SMOKE_25_OF_25" if not blockers else "HOLD_P5_IDENTITY_OR_STATIC_SMOKE_GAP"
    out = {
        "schema_version": "zel.p5.strategy25.identity_census.v1",
        "state": state,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_root": str(ROOT),
        "inventory_count": len(names),
        "present_count": present_count,
        "ast_ok_count": ast_ok_count,
        "missing": missing,
        "ast_fail": ast_fail,
        "duplicate_path_names": duplicate_path_names,
        "identical_source_hash_groups": identical_hash_groups,
        "rows": rows,
        "baseline_smoke_scope": "source_presence_hash_and_ast_parse_only_no_strategy_import_no_signal_execution_no_replay",
        "registry_binding_authority": "research/evidence/g0_installation_l0_l1_receipt_20260809.json:strategy25_registry_binding=25/25",
        "next_gate_if_pass": "P5_ZERO_SIGNAL_FUNNEL_OR_TRADE_BEARING_EXACT_SOURCE_PARITY",
        "blockers": blockers,
        "selection_authority": False,
        "promotion_authority": False,
        "runtime_mutated": False,
        "service_state_mutated": False,
        "strategy_import_executed": False,
        "signal_execution_performed": False,
        "replay_performed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
