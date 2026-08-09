#!/usr/bin/env python3
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()


def decode_json_env(name: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(os.environ[name]).decode("utf-8"))


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def aliases_for(path: Path) -> set[str]:
    aliases: set[str] = set()
    try:
        rel = path.resolve().relative_to(ROOT)
    except Exception:
        return aliases
    if rel.suffix != ".py":
        return aliases
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return aliases
    aliases.add(".".join(parts))
    if parts[0] == "backend" and len(parts) > 1:
        aliases.add(".".join(parts[1:]))
    return aliases


def source_to_aliases(source_path: str) -> set[str]:
    if source_path.startswith("external:"):
        return set()
    return aliases_for(ROOT / source_path)


def parse_deps(path: Path, current_aliases: set[str]) -> tuple[set[str], set[str]]:
    deps: set[str] = set()
    dynamic: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
        if len(text) > 2_000_000:
            return deps, dynamic
        tree = ast.parse(text)
    except Exception:
        return deps, dynamic

    primary = sorted(current_aliases, key=lambda x: (x.count("."), len(x)), reverse=True)
    current = primary[0] if primary else ""
    package = current.rsplit(".", 1)[0] if "." in current else current

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                deps.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and package:
                base_parts = package.split(".")
                cut = max(0, node.level - 1)
                if cut:
                    base_parts = base_parts[:-cut] if cut <= len(base_parts) else []
                full = ".".join([*base_parts, mod] if mod else base_parts)
                if full:
                    deps.add(full)
            elif mod:
                deps.add(mod)
        elif isinstance(node, ast.Call):
            fn = node.func
            fn_name = None
            if isinstance(fn, ast.Name):
                fn_name = fn.id
            elif isinstance(fn, ast.Attribute):
                left = fn.value.id if isinstance(fn.value, ast.Name) else ""
                fn_name = f"{left}.{fn.attr}" if left else fn.attr
            if fn_name in {"import_module", "importlib.import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    dynamic.add(arg.value)
    return deps, dynamic


def active_entries() -> list[Path]:
    paths: set[Path] = set()
    proc = Path("/proc")
    for child in proc.iterdir() if proc.exists() else []:
        if not child.name.isdigit():
            continue
        try:
            raw = (child / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except OSError:
            continue
        for token in raw.split():
            if token.startswith("/") and token.endswith(".py"):
                p = Path(token)
                if p.is_file():
                    paths.add(p.resolve())
            elif token.endswith(".py"):
                try:
                    cwd = Path(os.readlink(child / "cwd"))
                    p = (cwd / token).resolve()
                    if p.is_file():
                        paths.add(p)
                except OSError:
                    pass
    return sorted(paths)


def build_index() -> tuple[dict[str, Path], dict[Path, set[str]]]:
    alias_to_path: dict[str, Path] = {}
    path_to_aliases: dict[Path, set[str]] = {}
    for base_name in ("backend", "tools", "scripts", "strategies"):
        base = ROOT / base_name
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            a = aliases_for(path)
            if not a:
                continue
            rp = path.resolve()
            path_to_aliases[rp] = a
            for alias in a:
                alias_to_path.setdefault(alias, rp)
    return alias_to_path, path_to_aliases


def resolve_alias(name: str, alias_to_path: dict[str, Path]) -> Path | None:
    if name in alias_to_path:
        return alias_to_path[name]
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in alias_to_path:
            return alias_to_path[candidate]
    return None


def main() -> int:
    pin = decode_json_env("EXPECTED_PIN_B64")
    alias_to_path, path_to_aliases = build_index()
    entries = active_entries()

    # Graph nodes are paths. External active scripts can seed internal imports even if outside ROOT.
    edges: dict[Path, set[Path]] = defaultdict(set)
    dynamic_edges: dict[Path, set[Path]] = defaultdict(set)
    discovered: set[Path] = set(entries)
    q = deque(entries)
    while q:
        path = q.popleft()
        aliases = path_to_aliases.get(path, set())
        deps, dyn = parse_deps(path, aliases)
        for dep in deps:
            target = resolve_alias(dep, alias_to_path)
            if target:
                edges[path].add(target)
                if target not in discovered:
                    discovered.add(target)
                    q.append(target)
        for dep in dyn:
            target = resolve_alias(dep, alias_to_path)
            if target:
                dynamic_edges[path].add(target)
                if target not in discovered:
                    discovered.add(target)
                    q.append(target)

    parent: dict[Path, Path | None] = {p: None for p in entries}
    q = deque(entries)
    visited = set(entries)
    while q:
        src = q.popleft()
        for dst in sorted(edges.get(src, set())):
            if dst not in visited:
                visited.add(dst)
                parent[dst] = src
                q.append(dst)

    def chain_for(target: Path) -> list[str]:
        if target not in visited:
            return []
        chain: list[str] = []
        cur: Path | None = target
        while cur is not None:
            try:
                label = cur.relative_to(ROOT).as_posix()
            except Exception:
                label = str(cur)
            chain.append(label)
            cur = parent.get(cur)
        chain.reverse()
        return chain

    module_rows: list[dict[str, Any]] = []
    for module in pin.get("modules", []):
        module_id = str(module.get("module_id") or "")
        source_paths = [str(x) for x in module.get("source_paths", [])]
        bound: list[dict[str, Any]] = []
        dynamic_candidates: list[str] = []
        for source in source_paths:
            if source.startswith("external:"):
                p = Path(source[len("external:"):]).resolve()
                if p in entries:
                    bound.append({"source_path": source, "binding": "DIRECT_ACTIVE_ENTRY", "owner_chain": [str(p)]})
                continue
            p = (ROOT / source).resolve()
            if p in visited:
                bound.append({"source_path": source, "binding": "STATIC_IMPORT_REACHABLE", "owner_chain": chain_for(p)})
            elif any(p in xs for xs in dynamic_edges.values()):
                dynamic_candidates.append(source)
        module_rows.append({
            "component": module_id,
            "source_count": len(source_paths),
            "static_or_direct_bound_count": len(bound),
            "dynamic_binding_candidate_count": len(dynamic_candidates),
            "bound_sources": bound,
            "dynamic_binding_candidates": dynamic_candidates,
            "L1_OWNER_GRAPH": "PASS" if bound else "HOLD",
        })

    receipt = {
        "schema_version": "zel.g0b.l1.owner_graph.v1",
        "state": "PASS_G0B_L1_OWNER_GRAPH" if all(r["L1_OWNER_GRAPH"] == "PASS" for r in module_rows) else "HOLD_G0B_L1_OWNER_GRAPH_GAPS",
        "active_entry_count": len(entries),
        "active_entries": [str(p) for p in entries],
        "indexed_internal_module_alias_count": len(alias_to_path),
        "reachable_internal_path_count": sum(1 for p in visited if p.is_relative_to(ROOT)),
        "module_rows": module_rows,
        "runtime_mutated": False,
        "service_state_mutated": False,
        "destructive_cleanup_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
