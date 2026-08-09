#!/usr/bin/env python3
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import subprocess
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()
ESCROW = Path(os.environ.get("G0_ESCROW_ROOT", "/home/z/.zel-g0-source-escrow")).resolve()


def decode_json_env(name: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(os.environ[name]).decode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def runtime_path(source_path: str) -> Path:
    if source_path.startswith("external:"):
        return Path(source_path[len("external:"):])
    return ROOT / source_path


def canonical_path(source_path: str) -> Path:
    if source_path.startswith("external:"):
        return ESCROW / "sources_external" / source_path[len("external:"):].lstrip("/")
    return ESCROW / "sources" / source_path


def run(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return p.returncode, p.stdout.strip()


def active_entry_paths() -> list[str]:
    found: set[str] = set()
    rc, units = run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"])
    if rc == 0:
        for line in units.splitlines():
            unit = line.split()[0] if line.split() else ""
            if not unit:
                continue
            rc2, show = run(["systemctl", "show", unit, "-p", "ExecStart", "--value"])
            if rc2 != 0:
                continue
            for token in show.replace(";", " ").replace("{", " ").replace("}", " ").split():
                if token.startswith("/") and (token.endswith(".py") or token.endswith(".sh")):
                    found.add(token)
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
                found.add(token)
            elif token.endswith(".py"):
                try:
                    cwd = Path(os.readlink(child / "cwd"))
                    cand = (cwd / token).resolve()
                    if cand.exists():
                        found.add(str(cand))
                except OSError:
                    pass
    return sorted(found)


def module_name_for_path(path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(ROOT)
    except Exception:
        return None
    if rel.suffix != ".py":
        return None
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def import_graph() -> tuple[dict[str, set[str]], dict[str, str]]:
    graph: dict[str, set[str]] = {}
    module_to_path: dict[str, str] = {}
    for base_name in ("backend", "tools", "scripts"):
        base = ROOT / base_name
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                if path.stat().st_size > 1_500_000:
                    continue
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except Exception:
                continue
            mod = module_name_for_path(path)
            if not mod:
                continue
            module_to_path[mod] = str(path)
            deps: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        deps.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        deps.add(node.module)
            graph[mod] = deps
    return graph, module_to_path


def reachable_source_paths(entries: list[str]) -> set[str]:
    graph, module_to_path = import_graph()
    roots: list[str] = []
    for raw in entries:
        mod = module_name_for_path(Path(raw))
        if mod:
            roots.append(mod)
    seen: set[str] = set()
    q = deque(roots)
    while q:
        mod = q.popleft()
        if mod in seen:
            continue
        seen.add(mod)
        for dep in graph.get(mod, set()):
            if dep in graph and dep not in seen:
                q.append(dep)
            else:
                # Follow package prefixes when imports target submodules not directly indexed.
                parts = dep.split(".")
                for i in range(len(parts), 0, -1):
                    candidate = ".".join(parts[:i])
                    if candidate in graph and candidate not in seen:
                        q.append(candidate)
                        break
    paths: set[str] = set()
    for mod in seen:
        raw = module_to_path.get(mod)
        if not raw:
            continue
        try:
            paths.add(Path(raw).resolve().relative_to(ROOT).as_posix())
        except Exception:
            pass
    return paths


def json_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def main() -> int:
    pin = decode_json_env("EXPECTED_PIN_B64")
    legacy = decode_json_env("LEGACY25_B64")
    alpha = decode_json_env("ALPHA_B64")

    canonical_pin_path = ESCROW / "canonical_source_pin_candidate.json"
    canonical_pin = json.loads(canonical_pin_path.read_text()) if canonical_pin_path.is_file() else None
    entries = active_entry_paths()
    reachable = reachable_source_paths(entries)

    duplicate_owner_count = 0
    unresolved_reference_count = 0
    runtime_census_path = ESCROW / "runtime_census_latest.json"
    if runtime_census_path.is_file():
        try:
            census = json.loads(runtime_census_path.read_text())
            duplicate_owner_count = int(census.get("duplicate_active_owner_count", 0))
            unresolved_reference_count = int(census.get("unresolved_active_reference_count", 0))
        except Exception:
            pass

    module_rows: list[dict[str, Any]] = []
    for module in pin.get("modules", []):
        module_id = str(module.get("module_id") or "")
        sources = [str(x) for x in module.get("source_paths", [])]
        files = []
        runtime_present = 0
        canonical_present = 0
        parity = 0
        bound_sources = 0
        direct_owner_sources = 0
        for source in sources:
            rp = runtime_path(source)
            cp = canonical_path(source)
            r_exists = rp.is_file()
            c_exists = cp.is_file()
            r_sha = sha256_file(rp) if r_exists else None
            c_sha = sha256_file(cp) if c_exists else None
            if r_exists:
                runtime_present += 1
            if c_exists:
                canonical_present += 1
            if r_sha and c_sha and r_sha == c_sha:
                parity += 1
            if not source.startswith("external:") and source in reachable:
                bound_sources += 1
            if source.startswith("external:") and str(rp) in entries:
                direct_owner_sources += 1
            files.append({
                "source_path": source,
                "runtime_present": r_exists,
                "canonical_present": c_exists,
                "runtime_sha256": r_sha,
                "canonical_sha256": c_sha,
                "runtime_canonical_match": bool(r_sha and c_sha and r_sha == c_sha),
                "reachable_from_active_entry": (not source.startswith("external:") and source in reachable),
                "direct_active_entry": (source.startswith("external:") and str(rp) in entries),
            })
        l0 = canonical_present == len(sources) and len(sources) > 0
        # L1 is intentionally conservative: source must be canonicalized and there must be an active direct/static route.
        active_bound = (bound_sources + direct_owner_sources) > 0
        l1 = l0 and active_bound and duplicate_owner_count == 0 and unresolved_reference_count == 0
        module_rows.append({
            "component": module_id,
            "kind": "PINNED_MODULE",
            "source_count": len(sources),
            "runtime_present_count": runtime_present,
            "canonical_present_count": canonical_present,
            "runtime_canonical_match_count": parity,
            "active_bound_source_count": bound_sources + direct_owner_sources,
            "L0_PRESENT": "PASS" if l0 else "HOLD",
            "L1_BOUND": "PASS" if l1 else "HOLD",
            "files": files,
        })

    registry_candidates = [
        ROOT / "backend/strategy25/canonical_strategy_registry_v1.json",
        ROOT / "backend/strategies/registry.py",
    ]
    registry_blob = "\n".join(json_text(p) for p in registry_candidates if p.exists())
    legacy_names = list(legacy.get("historical_implementation_inventory_25", []))
    strategy_rows = []
    for name in legacy_names:
        source = f"backend/strategies/{name}.py"
        rp = ROOT / source
        cp = ESCROW / "sources" / source
        r_exists = rp.is_file()
        c_exists = cp.is_file()
        match = r_exists and c_exists and sha256_file(rp) == sha256_file(cp)
        registry_bound = name in registry_blob
        active_reachable = source in reachable
        l0 = c_exists
        l1 = l0 and registry_bound and duplicate_owner_count == 0 and unresolved_reference_count == 0
        strategy_rows.append({
            "strategy": name,
            "source_path": source,
            "runtime_present": r_exists,
            "canonical_present": c_exists,
            "runtime_canonical_match": bool(match),
            "registry_bound": registry_bound,
            "reachable_from_active_entry": active_reachable,
            "L0_PRESENT": "PASS" if l0 else "HOLD",
            "L1_BOUND": "PASS" if l1 else "HOLD",
        })

    skill_registry = ROOT / "backend/contracts/ZOS_SKILL_REGISTRY_v1.json"
    skill_text = json_text(skill_registry)
    skill_count = None
    if skill_text:
        try:
            obj = json.loads(skill_text)
            # Count leaf skill ids/names conservatively by known top-level list/dict shapes.
            if isinstance(obj, list):
                skill_count = len(obj)
            elif isinstance(obj, dict):
                for key in ("skills", "profiles", "registry", "items"):
                    val = obj.get(key)
                    if isinstance(val, (list, dict)):
                        skill_count = len(val)
                        break
        except Exception:
            pass

    alpha_rows = []
    branch_registry = ROOT / "strategies/alpha_engine/registry.py"
    branch_registry_text = json_text(branch_registry)
    for family in alpha.get("alpha_engine", {}).get("allowlist", []):
        contract = alpha.get("alpha_engine", {}).get("base_contracts", {}).get(family, {})
        branch_declared = family in branch_registry_text or family in json.dumps(alpha, sort_keys=True)
        status = contract.get("status")
        l0 = branch_declared
        # No vNext family is considered runtime-bound merely because its config exists.
        l1 = False
        alpha_rows.append({
            "family": family,
            "contract_status": status,
            "branch_declared": branch_declared,
            "runtime_bound": False,
            "L0_PRESENT": "PASS" if l0 else "HOLD",
            "L1_BOUND": "HOLD",
        })

    all_l0 = [r["L0_PRESENT"] for r in module_rows] + [r["L0_PRESENT"] for r in strategy_rows] + [r["L0_PRESENT"] for r in alpha_rows]
    all_l1 = [r["L1_BOUND"] for r in module_rows] + [r["L1_BOUND"] for r in strategy_rows] + [r["L1_BOUND"] for r in alpha_rows]
    state = "PASS_G0B_L0_L1" if all(x == "PASS" for x in all_l0 + all_l1) else "HOLD_G0B_L0_L1_GAPS"

    receipt = {
        "schema_version": "zel.g0b.l0_l1.certification.v1",
        "state": state,
        "runtime_root": str(ROOT),
        "escrow_root": str(ESCROW),
        "canonical_pin_present": canonical_pin is not None,
        "active_entry_count": len(entries),
        "active_entries": entries,
        "duplicate_active_owner_count": duplicate_owner_count,
        "unresolved_active_reference_count": unresolved_reference_count,
        "module_rows": module_rows,
        "strategy25_rows": strategy_rows,
        "strategy25_l0_pass": sum(r["L0_PRESENT"] == "PASS" for r in strategy_rows),
        "strategy25_l1_pass": sum(r["L1_BOUND"] == "PASS" for r in strategy_rows),
        "alpha_family_rows": alpha_rows,
        "skill_registry_present": skill_registry.is_file(),
        "skill_registry_detected_count": skill_count,
        "l0_pass_total": sum(x == "PASS" for x in all_l0),
        "l0_total": len(all_l0),
        "l1_pass_total": sum(x == "PASS" for x in all_l1),
        "l1_total": len(all_l1),
        "L2_CONTRACT": "NOT_STARTED",
        "L3_EVIDENCE": "NOT_STARTED",
        "L4_SHADOW_READY": "NOT_STARTED",
        "destructive_cleanup_authority": False,
        "runtime_mutated": False,
        "service_state_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
