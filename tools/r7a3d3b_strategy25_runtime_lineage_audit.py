#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

MAX_SOURCE_BYTES = 1_500_000
REF_RE = re.compile(r"[A-Za-z0-9_@+./:-]+\.(?:py|sh|service)")


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def sha256(path: str) -> str | None:
    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def git_tree(root: Path, target_sha: str) -> tuple[str, dict[str, str]]:
    resolved = run(["git", "-C", str(root), "rev-parse", f"{target_sha}^{{commit}}"])
    if resolved.returncode != 0:
        raise RuntimeError("TARGET_SHA_NOT_RESOLVED")
    commit = resolved.stdout.strip()
    listed = run(["git", "-C", str(root), "ls-tree", "-r", commit])
    if listed.returncode != 0:
        raise RuntimeError("GIT_TREE_LIST_FAILED")
    blobs: dict[str, str] = {}
    for line in listed.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        fields = meta.split()
        if len(fields) >= 3:
            blobs[path] = fields[2]
    return commit, blobs


def extract_archive(root: Path, commit: str, destination: Path) -> None:
    archive = subprocess.Popen(
        ["git", "-C", str(root), "archive", "--format=tar", commit],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert archive.stdout is not None
    with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
        stream.extractall(destination, filter="data")
    stderr = archive.stderr.read().decode("utf-8", errors="replace") if archive.stderr else ""
    rc = archive.wait(timeout=180)
    if rc != 0:
        raise RuntimeError(f"GIT_ARCHIVE_FAILED:{stderr[-300:]}")


def module_name(path: str) -> str:
    raw = path[:-3].replace("/", ".") if path.endswith(".py") else path.replace("/", ".")
    return raw[:-9] if raw.endswith(".__init__") else raw


def resolve_import(current_path: str, module: str | None, level: int, modules: dict[str, str]) -> list[str]:
    current = module_name(current_path)
    package = current.split(".") if current_path.endswith("/__init__.py") else current.split(".")[:-1]
    if level:
        keep = max(0, len(package) - (level - 1))
        base = package[:keep]
        target = ".".join(base + ([module] if module else []))
    else:
        target = module or ""
    candidates = [target]
    while "." in target:
        target = target.rsplit(".", 1)[0]
        candidates.append(target)
    return [modules[name] for name in candidates if name in modules]


def source_references(text: str, root: Path, paths: set[str], by_name: dict[str, list[str]]) -> set[str]:
    found: set[str] = set()
    for raw in REF_RE.findall(text):
        token = raw.strip("'\"()[]{};,=")
        if token.startswith(str(root) + "/"):
            token = token[len(str(root)) + 1:]
        token = token.lstrip("./")
        if token in paths:
            found.add(token)
            continue
        matches = by_name.get(Path(token).name, [])
        if len(matches) == 1:
            found.add(matches[0])
    return found


def build_graph(snapshot: Path, root: Path, blobs: dict[str, str]) -> dict[str, set[str]]:
    paths = set(blobs)
    by_name: dict[str, list[str]] = defaultdict(list)
    modules: dict[str, str] = {}
    for path in paths:
        by_name[Path(path).name].append(path)
        if path.endswith(".py"):
            modules[module_name(path)] = path
    graph: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        if not path.endswith((".py", ".sh", ".service")):
            continue
        source = snapshot / path
        if not source.is_file() or source.stat().st_size > MAX_SOURCE_BYTES:
            continue
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        graph[path].update(source_references(text, root, paths, by_name))
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text, filename=path)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    graph[path].update(resolve_import(path, alias.name, 0, modules))
            elif isinstance(node, ast.ImportFrom):
                graph[path].update(resolve_import(path, node.module, node.level, modules))
                if node.module:
                    for alias in node.names:
                        graph[path].update(resolve_import(path, f"{node.module}.{alias.name}", node.level, modules))
    return graph


def systemd_inventory() -> list[dict[str, Any]]:
    listed = run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"], 60)
    if listed.returncode != 0:
        return []
    units = [line.split()[0] for line in listed.stdout.splitlines() if line.split()]
    result: list[dict[str, Any]] = []
    for unit in units:
        shown = run([
            "systemctl", "show", unit, "-p", "Id", "-p", "ExecStart", "-p", "FragmentPath",
            "-p", "MainPID", "-p", "ControlGroup",
        ], 30)
        props = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
        if not props:
            continue
        fragment = props.get("FragmentPath", "")
        fragment_text = ""
        try:
            if fragment and Path(fragment).is_file():
                fragment_text = Path(fragment).read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        pids: set[int] = set()
        try:
            main_pid = int(props.get("MainPID", "0") or 0)
            if main_pid > 0:
                pids.add(main_pid)
        except ValueError:
            pass
        control = props.get("ControlGroup", "")
        cgroup_procs = Path("/sys/fs/cgroup") / control.lstrip("/") / "cgroup.procs"
        try:
            if cgroup_procs.is_file():
                for raw in cgroup_procs.read_text().splitlines()[:50]:
                    if raw.isdigit():
                        pids.add(int(raw))
        except Exception:
            pass
        processes = []
        for pid in sorted(pids):
            proc = Path("/proc") / str(pid)
            try:
                cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
            except Exception:
                cmdline = ""
            try:
                exe = os.readlink(proc / "exe")
            except Exception:
                exe = ""
            try:
                cwd = os.readlink(proc / "cwd")
            except Exception:
                cwd = ""
            processes.append({"pid": pid, "cmdline": cmdline, "exe": exe, "cwd": cwd})
        result.append({**props, "fragment_text": fragment_text, "processes": processes})
    return result


def active_roots(inventory: list[dict[str, Any]], root: Path, paths: set[str]) -> tuple[set[str], list[dict[str, Any]]]:
    by_name: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        by_name[Path(path).name].append(path)
    roots: set[str] = set()
    compact = []
    for row in inventory:
        haystacks = [str(row.get("ExecStart", "")), str(row.get("fragment_text", ""))]
        for proc in row.get("processes", []):
            haystacks.extend([str(proc.get("cmdline", "")), str(proc.get("exe", "")), str(proc.get("cwd", ""))])
        matched: set[str] = set()
        for text in haystacks:
            matched.update(source_references(text, root, paths, by_name))
        roots.update(matched)
        compact.append({
            "unit": row.get("Id"),
            "fragment": row.get("FragmentPath"),
            "exec_start": row.get("ExecStart"),
            "main_pid": row.get("MainPID"),
            "matched_repo_roots": sorted(matched),
            "processes": row.get("processes", []),
        })
    return roots, compact


def shortest_path(graph: dict[str, set[str]], starts: set[str], target: str, max_depth: int) -> list[str] | None:
    if target in starts:
        return [target]
    queue = deque((start, [start]) for start in starts)
    seen = set(starts)
    while queue:
        node, chain = queue.popleft()
        if len(chain) - 1 >= max_depth:
            continue
        for nxt in graph.get(node, set()):
            if nxt in seen:
                continue
            new_chain = chain + [nxt]
            if nxt == target:
                return new_chain
            seen.add(nxt)
            queue.append((nxt, new_chain))
    return None


def normalize_candidate_path(raw: str, root: Path, paths: set[str], by_name: dict[str, list[str]]) -> str | None:
    value = raw.strip()
    if value.startswith(str(root) + "/"):
        value = value[len(str(root)) + 1:]
    value = value.lstrip("./")
    if value in paths:
        return value
    matches = by_name.get(Path(value).name, [])
    return matches[0] if len(matches) == 1 else None


def candidate_proof(
    candidate: dict[str, Any], strategy_id: str, root: Path, paths: set[str], by_name: dict[str, list[str]],
    blobs: dict[str, str], graph: dict[str, set[str]], roots: set[str], runtime_rows: list[dict[str, Any]], max_depth: int,
) -> dict[str, Any]:
    raw_path = str(candidate.get("implementation_path") or "")
    path = normalize_candidate_path(raw_path, root, paths, by_name)
    callable_name = str(candidate.get("callable") or "")
    binding_refs = [row for row in candidate.get("binding_refs", []) if isinstance(row, dict)]
    explicit = bool(candidate.get("explicit_binding")) or any(row.get("explicit_config_binding") for row in binding_refs)
    chain = shortest_path(graph, roots, path, max_depth) if path else None
    absolute = str(root / path) if path else ""
    exact_runtime = []
    for row in runtime_rows:
        text = json.dumps(row, ensure_ascii=False)
        if path and (absolute in text or path in text):
            exact_runtime.append(row.get("unit"))
    direct = bool(candidate.get("direct_name_match"))
    hard_reasons = []
    if path and exact_runtime:
        hard_reasons.append("ACTIVE_EXACT_PATH")
    if path and chain and explicit:
        hard_reasons.append("ACTIVE_IMPORT_CHAIN_PLUS_EXPLICIT_BINDING")
    if path and chain and direct:
        hard_reasons.append("ACTIVE_IMPORT_CHAIN_PLUS_DIRECT_NAME")
    hard = bool(hard_reasons and path and callable_name)
    return {
        "strategy_id": strategy_id,
        "implementation_path": path or raw_path,
        "callable": callable_name,
        "binding_kind": candidate.get("binding_kind"),
        "git_path_exists": bool(path),
        "git_blob_sha": blobs.get(path or ""),
        "candidate_source_blob_sha": candidate.get("source_blob_sha"),
        "explicit_binding": explicit,
        "direct_name_match": direct,
        "active_exact_units": sorted(set(x for x in exact_runtime if x)),
        "active_import_chain": chain,
        "hard_proven": hard,
        "hard_proof_reasons": hard_reasons,
        "binding_refs": binding_refs[:12],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load(Path(args.contract))
    expected = int(contract.get("expected_strategy_count", 25))
    expected_unresolved = int(contract.get("expected_prior_unresolved_count", 23))
    a3d = load(root / contract["prior_a3d_status_path"])
    prior_status = load(root / contract["prior_a3d3_status_path"])
    prior_proposal = load(root / contract["prior_a3d3_proposal_path"])
    blockers: list[str] = []
    if not (prior_status.get("state") == "PASS" and prior_status.get("strategy_count") == expected):
        blockers.append("PRIOR_A3D3_INVALID")
    if prior_status.get("unresolved_mapping_count") != expected_unresolved:
        blockers.append("PRIOR_A3D3_UNRESOLVED_COUNT_MISMATCH")
    mappings = [row for row in prior_proposal.get("mappings", []) if isinstance(row, dict)]
    if len(mappings) != expected:
        blockers.append("PRIOR_A3D3_MAPPING_COUNT_NOT_25")

    before = {path: sha256(path) for path in contract.get("protected_paths", [])}
    try:
        commit, blobs = git_tree(root, args.target_sha)
    except Exception as exc:
        commit, blobs = "", {}
        blockers.append(str(exc))

    audit_rows = {str(row.get("strategy_id")): row for row in a3d.get("mappings", []) if isinstance(row, dict)}
    resolved_rows = []
    runtime = systemd_inventory()
    with tempfile.TemporaryDirectory(prefix="r7a3d3b.") as tmp:
        snapshot = Path(tmp)
        if commit:
            try:
                extract_archive(root, commit, snapshot)
            except Exception as exc:
                blockers.append(str(exc))
        graph = build_graph(snapshot, root, blobs) if commit and not blockers else {}
        roots, runtime_rows = active_roots(runtime, root, set(blobs)) if blobs else (set(), [])
        by_name: dict[str, list[str]] = defaultdict(list)
        for path in blobs:
            by_name[Path(path).name].append(path)

        for mapping in mappings:
            strategy_id = str(mapping.get("strategy_id") or "")
            if mapping.get("resolved") is True and mapping.get("canonical_mapping_proposal"):
                resolved_rows.append({
                    "strategy_id": strategy_id,
                    "resolution": "PRIOR_RESOLVED",
                    "resolved": True,
                    "canonical_mapping": mapping.get("canonical_mapping_proposal"),
                    "candidate_proofs": [],
                })
                continue
            candidates = [row for row in mapping.get("top_candidates", []) if isinstance(row, dict)]
            proofs = [
                candidate_proof(
                    candidate, strategy_id, root, set(blobs), by_name, blobs, graph, roots, runtime_rows,
                    int(contract.get("maximum_import_depth", 12)),
                )
                for candidate in candidates[: int(contract.get("candidate_limit", 6))]
            ]
            hard = [row for row in proofs if row["hard_proven"]]
            unique = len(hard) == 1
            resolved_rows.append({
                "strategy_id": strategy_id,
                "resolution": "RUNTIME_LINEAGE_PROVEN" if unique else "UNRESOLVED",
                "resolved": unique,
                "canonical_mapping": hard[0] if unique else None,
                "candidate_proofs": proofs,
                "test_refs": audit_rows.get(strategy_id, {}).get("test_refs", []),
                "unresolved_reason": None if unique else (
                    "MULTIPLE_RUNTIME_LINEAGES" if len(hard) > 1 else "NO_UNIQUE_RUNTIME_LINEAGE"
                ),
            })

    total_resolved = sum(bool(row.get("resolved")) for row in resolved_rows)
    prior_resolved = sum(row.get("resolution") == "PRIOR_RESOLVED" for row in resolved_rows)
    newly_resolved = sum(row.get("resolution") == "RUNTIME_LINEAGE_PROVEN" for row in resolved_rows)
    unresolved = expected - total_resolved
    proof = {
        "schema": "r7a3d3b_strategy25_runtime_lineage_proof_v1",
        "official_stage": "R7.A3D3B",
        "read_only": True,
        "target_commit": commit,
        "strategy_count": len(resolved_rows),
        "prior_resolved_mapping_count": prior_resolved,
        "newly_resolved_mapping_count": newly_resolved,
        "resolved_mapping_count": total_resolved,
        "unresolved_mapping_count": unresolved,
        "active_runtime_unit_count": len(runtime),
        "active_process_count": sum(len(row.get("processes", [])) for row in runtime),
        "active_repo_root_count": len(roots) if commit and not blockers else 0,
        "active_repo_roots": sorted(roots) if commit and not blockers else [],
        "runtime_inventory": runtime_rows if commit and not blockers else [],
        "mappings": resolved_rows,
    }
    atomic(root / contract["proof_path"], proof)

    after = {path: sha256(path) for path in contract.get("protected_paths", [])}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED")
    blockers = list(dict.fromkeys(blockers))
    state = "PASS" if not blockers else "HOLD"
    if blockers:
        next_stage = contract["next_stage_fail"]
    elif total_resolved == expected:
        next_stage = contract["next_stage_all_resolved"]
    else:
        next_stage = contract["next_stage_unresolved"]
    status = {
        "official_stage": "R7.A3D3B",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": len(resolved_rows),
        "prior_resolved_mapping_count": prior_resolved,
        "newly_resolved_mapping_count": newly_resolved,
        "resolved_mapping_count": total_resolved,
        "unresolved_mapping_count": unresolved,
        "active_runtime_unit_count": len(runtime),
        "canonical_mapping_mutation_count": 0,
        "service_mutation_count": 0,
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "performance_s_promoted_count": 0,
        "proof_path": str(root / contract["proof_path"]),
        "next_stage": next_stage,
    }
    atomic(root / contract["status_path"], status)
    for key in (
        "state", "blocker_count", "strategy_count", "prior_resolved_mapping_count",
        "newly_resolved_mapping_count", "resolved_mapping_count", "unresolved_mapping_count",
        "active_runtime_unit_count", "canonical_mapping_mutation_count", "protected_change_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("UNRESOLVED=" + json.dumps([
        {"strategy_id": row["strategy_id"], "reason": row.get("unresolved_reason"), "candidate_count": len(row.get("candidate_proofs", []))}
        for row in resolved_rows if not row.get("resolved")
    ], ensure_ascii=False))
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
