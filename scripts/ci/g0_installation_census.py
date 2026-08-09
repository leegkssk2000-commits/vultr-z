#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".py", ".sh", ".json", ".yml", ".yaml", ".toml", ".ini", ".md", ".txt", ".service", ".timer"}
SCAN_ROOTS = [
    ".github/workflows",
    "backend",
    "config",
    "docs",
    "engine",
    "ensemble",
    "policies",
    "registry",
    "research",
    "scripts",
    "skill",
    "skills",
    "strategies",
    "strategy11_stream_v1",
]
COMPONENT_TOKENS = [
    "zbot", "zico", "zlice", "lico", "skill", "method",
    "trend_momentum", "carry_flow", "relative_value_psa",
    "replay", "cost", "slippage", "funding", "registry", "shadow", "paper", "live",
]
LOCAL_REF_RE = re.compile(r"(?P<path>(?:\.?/?(?:backend|config|docs|engine|ensemble|policies|registry|research|scripts|skill|skills|strategies|strategy11_stream_v1)/)[A-Za-z0-9_./-]+\.(?:py|sh|json|ya?ml|toml|ini|service|timer))")
USES_RE = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)
WORKFLOW_CALL_RE = re.compile(r"(?:^|/)\.github/workflows/([^@\s]+)")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return os.environ.get("GITHUB_SHA", "UNKNOWN")


def iter_text_files() -> Iterable[Path]:
    seen: set[Path] = set()
    for root_name in SCAN_ROOTS:
        base = ROOT / root_name
        if not base.exists():
            continue
        if base.is_file():
            candidates = [base]
        else:
            candidates = base.rglob("*")
        for path in candidates:
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
            except OSError:
                continue
            yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def workflow_triggers(text: str) -> list[str]:
    lines = text.splitlines()
    triggers: list[str] = []
    on_indent: int | None = None
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if on_indent is None:
            if stripped == "on:":
                on_indent = indent
                continue
            if stripped.startswith("on: [") and stripped.endswith("]"):
                inner = stripped[4:-1]
                return sorted(x.strip() for x in inner.split(",") if x.strip())
            if stripped.startswith("on: ") and not stripped.endswith(":"):
                return [stripped[4:].strip()]
        else:
            if indent <= on_indent:
                break
            if stripped.startswith("-"):
                continue
            if ":" in stripped:
                key = stripped.split(":", 1)[0].strip()
                child_indent = indent
                if child_indent == on_indent + 2 and key:
                    triggers.append(key)
    return sorted(set(triggers))


def workflow_census() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    wf_root = ROOT / ".github/workflows"
    rows: list[dict[str, Any]] = []
    dispatch_edges: list[dict[str, Any]] = []
    if not wf_root.exists():
        return rows, dispatch_edges
    for path in sorted(list(wf_root.glob("*.yml")) + list(wf_root.glob("*.yaml"))):
        text = read_text(path)
        rel = path.relative_to(ROOT).as_posix()
        uses = sorted(set(USES_RE.findall(text)))
        local_calls: list[str] = []
        for value in uses:
            m = WORKFLOW_CALL_RE.search(value)
            if m:
                local_calls.append(m.group(1))
        for target in sorted(set(local_calls)):
            dispatch_edges.append({"source": rel, "kind": "workflow_call", "target": f".github/workflows/{target}"})
        for marker in ("gh workflow run", "workflow_dispatch", "repository_dispatch"):
            if marker in text:
                dispatch_edges.append({"source": rel, "kind": marker, "target": None})
        rows.append({
            "path": rel,
            "sha256": sha256_file(path),
            "triggers": workflow_triggers(text),
            "uses": uses,
            "has_concurrency": "concurrency:" in text,
            "has_schedule": "schedule:" in text,
            "has_workflow_dispatch": "workflow_dispatch:" in text,
            "has_pull_request": "pull_request:" in text,
            "has_push": re.search(r"^\s*push:\s*$", text, re.MULTILINE) is not None,
        })
    return rows, dispatch_edges


def reference_graph(files: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    refs: dict[str, set[str]] = defaultdict(set)
    missing: dict[str, set[str]] = defaultdict(set)
    for path in files:
        text = read_text(path)
        if not text:
            continue
        source = path.relative_to(ROOT).as_posix()
        for match in LOCAL_REF_RE.finditer(text):
            raw = match.group("path").lstrip("./")
            target = (ROOT / raw)
            if target.exists():
                refs[raw].add(source)
            else:
                missing[raw].add(source)
    graph = [
        {"target": target, "inbound_count": len(sources), "sources": sorted(sources)}
        for target, sources in sorted(refs.items())
    ]
    unresolved = [
        {"target": target, "sources": sorted(sources)}
        for target, sources in sorted(missing.items())
    ]
    return graph, unresolved


def component_mentions(files: list[Path]) -> list[dict[str, Any]]:
    owners: dict[str, set[str]] = defaultdict(set)
    for path in files:
        text = read_text(path).lower()
        if not text:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for token in COMPONENT_TOKENS:
            if token in text:
                owners[token].add(rel)
    return [{"component": k, "mention_count": len(v), "paths": sorted(v)} for k, v in sorted(owners.items())]


def duplicate_trigger_candidates(workflows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for row in workflows:
        key = tuple(row["triggers"])
        if key:
            groups[key].append(row["path"])
    return [
        {"trigger_signature": list(sig), "workflow_count": len(paths), "paths": sorted(paths)}
        for sig, paths in sorted(groups.items()) if len(paths) > 1
    ]


def make_receipt(runtime_manifest: Path | None = None) -> dict[str, Any]:
    files = list(iter_text_files())
    workflows, edges = workflow_census()
    graph, unresolved = reference_graph(files)
    mentions = component_mentions(files)
    runtime: dict[str, Any] | None = None
    runtime_blockers: list[str] = []
    if runtime_manifest:
        try:
            runtime = json.loads(runtime_manifest.read_text(encoding="utf-8"))
            if not isinstance(runtime, dict):
                raise ValueError("runtime manifest root must be object")
            if runtime.get("state") not in {"PASS_RUNTIME_CENSUS", "PASS_G0_RUNTIME_CENSUS"}:
                runtime_blockers.append("RUNTIME_MANIFEST_NOT_PASS")
            if runtime.get("duplicate_active_owner_count", 0) != 0:
                runtime_blockers.append("RUNTIME_DUPLICATE_ACTIVE_OWNER")
            if runtime.get("unresolved_active_reference_count", 0) != 0:
                runtime_blockers.append("RUNTIME_UNRESOLVED_ACTIVE_REFERENCE")
        except Exception as exc:
            runtime_blockers.append(f"RUNTIME_MANIFEST_INVALID:{type(exc).__name__}")
    else:
        runtime_blockers.append("RUNTIME_CENSUS_REQUIRED")

    static_blockers: list[str] = []
    if not workflows:
        static_blockers.append("WORKFLOW_CENSUS_EMPTY")
    # Missing literal refs are evidence, not automatically fatal: old docs/evidence can cite retired paths.
    # They become fatal only when the runtime census says an active owner/reference is unresolved.
    duplicate_candidates = duplicate_trigger_candidates(workflows)
    state = "PASS_G0A_STATIC_AND_RUNTIME_CENSUS" if not static_blockers and not runtime_blockers else "HOLD_G0A_RUNTIME_OR_STATIC_CENSUS"
    receipt: dict[str, Any] = {
        "schema_version": "zel.g0.installation_census.receipt.v1",
        "state": state,
        "head_sha": git_head(),
        "scan_file_count": len(files),
        "workflow_count": len(workflows),
        "workflow_trigger_census": workflows,
        "workflow_dispatch_edges": edges,
        "duplicate_trigger_candidates": duplicate_candidates,
        "reference_graph": graph,
        "unresolved_literal_references": unresolved,
        "component_mentions": mentions,
        "runtime_census": runtime,
        "static_blockers": static_blockers,
        "runtime_blockers": runtime_blockers,
        "destructive_cleanup_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    material = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    receipt["receipt_sha256"] = hashlib.sha256(material).hexdigest()
    return receipt


def main() -> int:
    p = argparse.ArgumentParser(description="ZEL G0-A static/runtime ownership census")
    p.add_argument("--runtime-manifest", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--require-runtime-pass", action="store_true")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        assert workflow_triggers("name: t\non:\n  push:\n  pull_request:\njobs:\n  x:\n") == ["pull_request", "push"]
        assert workflow_triggers("on: [push, pull_request]\n") == ["pull_request", "push"]
        print("PASS_G0_CENSUS_SELF_TEST")
        return 0
    receipt = make_receipt(args.runtime_manifest)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    if receipt["static_blockers"]:
        return 2
    if args.require_runtime_pass and receipt["runtime_blockers"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
