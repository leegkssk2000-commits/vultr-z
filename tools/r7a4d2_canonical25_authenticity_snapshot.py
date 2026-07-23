#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED = 25
REGISTRY = Path("backend/strategy25/canonical_strategy_registry_v1.json")
CONFIG = Path("backend/strategy25/canonical_strategy25_config_v1.json")
CONTRACT = Path("backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json")
SOURCE_MAP = Path("research/canonical25_authenticity_source_map_v1.json")
OUTDIR = Path("runtime/r7a4d2_canonical25_authenticity_snapshot")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def inspect_source(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    calls: Counter[str] = Counter()
    strings: Counter[str] = Counter()
    comparisons: list[dict[str, Any]] = []
    config_defaults: dict[str, dict[str, Any]] = {}
    classes: dict[str, list[str]] = {}
    functions: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes[node.name] = [child.name for child in node.body if isinstance(child, ast.FunctionDef)]
            if node.name.lower().endswith("config"):
                fields: dict[str, Any] = {}
                for child in node.body:
                    if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name) and child.value is not None:
                        fields[child.target.id] = literal(child.value)
                config_defaults[node.name] = fields
        elif isinstance(node, ast.FunctionDef):
            functions.append(node.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = call_name(node)
            if name:
                calls[name] += 1
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.strip()
            if text and len(text) <= 100:
                lowered = text.lower()
                if any(token in lowered for token in ("long", "short", "enter", "exit", "add", "reduce", "hold", "stop", "trend", "revert", "break")):
                    strings[text] += 1
        elif isinstance(node, ast.Compare) and len(comparisons) < 120:
            text = ast.get_source_segment(source, node) or ""
            text = " ".join(text.split())
            if text:
                comparisons.append({"line": int(getattr(node, "lineno", 0)), "expr": text[:220]})

    lowered_strings = [value.lower() for value in strings]
    return {
        "line_count": len(source.splitlines()),
        "config_defaults": config_defaults,
        "top_level_functions": functions,
        "class_methods": classes,
        "call_histogram": dict(calls.most_common(80)),
        "semantic_strings": dict(strings.most_common(100)),
        "comparisons": comparisons,
        "supports_long_static": any("long" in value for value in lowered_strings),
        "supports_short_static": any("short" in value for value in lowered_strings),
        "supports_add_static": any("add" in value for value in lowered_strings),
        "supports_reduce_static": any("reduce" in value for value in lowered_strings),
        "supports_exit_static": any("exit" in value for value in lowered_strings),
    }


def atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialized-root", required=True)
    parser.add_argument("--output-root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    materialized = Path(args.materialized_root).resolve()
    output_root = Path(args.output_root).resolve()
    required = [materialized / REGISTRY, materialized / CONFIG, materialized / CONTRACT, materialized / SOURCE_MAP]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_CANONICAL25_AUTHENTICITY_SNAPSHOT_INPUT")
        print("BLOCKERS=" + json.dumps(["MATERIALIZED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    registry = load(materialized / REGISTRY)
    config = load(materialized / CONFIG)
    contract = load(materialized / CONTRACT)
    source_map = load(materialized / SOURCE_MAP)
    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    external = {str(row.get("strategy_id")): row for row in source_map.get("strategies", []) if isinstance(row, dict)}
    config_rows = config.get("strategies") if isinstance(config.get("strategies"), dict) else {}
    blockers: list[str] = []
    if len(entries) != EXPECTED or int(registry.get("strategy_count") or -1) != EXPECTED:
        blockers.append(f"REGISTRY_COUNT_INVALID:{len(entries)}")
    if len(external) != EXPECTED:
        blockers.append(f"SOURCE_MAP_COUNT_INVALID:{len(external)}")
    if int(contract.get("expected_strategy_count") or -1) != EXPECTED:
        blockers.append("CONTRACT_COUNT_INVALID")

    reports: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda row: str(row.get("strategy_id") or "")):
        sid = str(entry.get("strategy_id") or "")
        engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
        rel = Path(str(engine.get("implementation_path") or ""))
        source_path = materialized / rel
        issues: list[str] = []
        details: dict[str, Any] = {}
        actual_sha = None
        if not source_path.is_file():
            issues.append("SOURCE_MISSING")
        else:
            actual_sha = digest(source_path)
            if actual_sha != str(engine.get("source_sha256") or ""):
                issues.append("SOURCE_SHA_MISMATCH")
            try:
                details = inspect_source(source_path)
            except Exception as exc:
                issues.append(f"SOURCE_PARSE_FAILED:{type(exc).__name__}")
        if sid not in external:
            issues.append("SOURCE_MAP_MISSING")
        if sid not in config_rows:
            issues.append("CONFIG_ENTRY_MISSING")

        origin = str((external.get(sid) or {}).get("origin_class") or "UNKNOWN")
        research_status = str((external.get(sid) or {}).get("research_status") or "UNKNOWN")
        if issues:
            status = "BIND_OR_PARSE_HOLD"
        elif origin.startswith("ZEL_SYNTHETIC"):
            status = "SYNTHETIC_HYPOTHESIS_REQUIRES_ECONOMIC_SPEC"
        elif research_status.startswith("NO_SINGLE"):
            status = "GENERIC_FAMILY_REQUIRES_EXPLICIT_ZEL_SPEC"
        else:
            status = "READY_FOR_MANUAL_SOURCE_TO_CODE_RULE_AUDIT"

        reports.append({
            "strategy_id": sid,
            "implementation_path": str(rel),
            "canonical_callable": engine.get("callable"),
            "registry_source_sha256": engine.get("source_sha256"),
            "materialized_source_sha256": actual_sha,
            "source_sha_match": actual_sha == str(engine.get("source_sha256") or ""),
            "active_allowed": entry.get("active_allowed"),
            "fail_closed": entry.get("fail_closed"),
            "config_bundle_value": config_rows.get(sid),
            "external_source_identity": external.get(sid),
            "current_implementation": details,
            "authenticity_audit_status": status,
            "issues": issues,
        })

    state = "PASS_CANONICAL25_AUTHENTICITY_SNAPSHOT" if not blockers else "HOLD_CANONICAL25_AUTHENTICITY_SNAPSHOT_INPUT"
    result = {
        "schema": "canonical25_current_implementation_snapshot_v1",
        "official_stage": "R7.A4D2_CANONICAL25_STRATEGY_AUTHENTICITY_SNAPSHOT",
        "state": state,
        "target_commit": args.target_sha,
        "strategy_count": len(reports),
        "reports": reports,
        "blockers": blockers,
        "strategy_mutation_allowed": False,
        "performance_upgrade_allowed": False,
        "next_stage": "R7.A4D2_CANONICAL25_SOURCE_TO_CODE_RULE_AUDIT_WAVES"
    }
    output = output_root / OUTDIR
    atomic(output / "canonical25_current_implementation_snapshot_v1.json", result)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("CANONICAL_STRATEGY_COUNT=" + str(len(reports)))
    print("GIT_OBJECT_MATERIALIZATION=true")
    for row in reports:
        current = row.get("current_implementation") if isinstance(row.get("current_implementation"), dict) else {}
        print(
            "AUTH_SNAPSHOT=" + row["strategy_id"] +
            "|STATUS=" + row["authenticity_audit_status"] +
            "|SHA_MATCH=" + str(row["source_sha_match"]).lower() +
            "|LINES=" + str(current.get("line_count", 0)) +
            "|LONG=" + str(bool(current.get("supports_long_static"))).lower() +
            "|SHORT=" + str(bool(current.get("supports_short_static"))).lower() +
            "|ISSUES=" + (",".join(row["issues"]) if row["issues"] else "none")
        )
    print("SNAPSHOT_JSON=" + str(output / "canonical25_current_implementation_snapshot_v1.json"))
    print("STRATEGY_MUTATION_ALLOWED=false")
    print("PERFORMANCE_UPGRADE_ALLOWED=false")
    print("NEXT_STAGE=R7.A4D2_CANONICAL25_SOURCE_TO_CODE_RULE_AUDIT_WAVES")
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
