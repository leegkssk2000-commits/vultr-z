from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_FULL_ARCHITECTURE_CENSUS_V1"
TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".toml", ".ini", ".cfg",
    ".yaml", ".yml", ".sh", ".service", ".timer", ".md", ".txt", ".html",
    ".css", ".scss", ".sql", ".env", ".conf", ".caddy", ".nginx",
}
CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".sh"}
SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__"}
GENERATED_PARTS = {
    "runtime_results", "artifacts", "artifact", "out", "output", "outputs", "cache",
    ".cache", "tmp", "temp", "coverage", "dist", "build",
}

LAYER_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("workflow_ci", (".github/workflows/", "workflow")),
    ("ops_deploy", ("systemd", ".service", ".timer", "deploy", "bootstrap", "caddy", "nginx", "docker", "compose")),
    ("surfaces", ("telegram", "alimi", "frontend", "z-os-app", "dashboard", "/view", "web/", "app/", "ui/")),
    ("ledger_pnl", ("ledger", "pnl", "journal", "writer", "recent_trace", "trade_log")),
    ("position_state", ("position", "lifecycle", "close_writer", "open_writer", "state_store", "state_machine")),
    ("execution", ("oms", "order", "execution", "exchange", "bingx", "fill", "intent_gate")),
    ("router", ("router", "route_", "routing")),
    ("signal_admission", ("signal", "admission", "candidate", "gate", "selector")),
    ("registry_config", ("registry", "config", "contract", "ssot", "policy")),
    ("canonical_strategy", ("backend/strategies/", "backend/strategy25/", "canonical25", "strategy25")),
    ("research", ("backend/research/", "research/", "replay", "simulation", "strategy11")),
    ("tests", ("tests/", "test_", "fixture")),
]

CHAIN = [
    "canonical_strategy", "registry_config", "signal_admission", "router", "execution",
    "position_state", "ledger_pnl", "surfaces",
]

PATH_REF_RE = re.compile(r"(?:(?:backend|frontend|tools|scripts|research|tests|\.github)/[A-Za-z0-9_./\-]+)")
SHELL_WRITE_RE = re.compile(r"(?:>|>>|tee\s+(?:-a\s+)?|cp\s+\S+\s+|install\s+\S+\s+)([A-Za-z0-9_./\-]+)")
AUTHORITY_PATTERNS = {
    "canonical_mutation": re.compile(r"canonical_mutated|canonical_mutation", re.I),
    "registry_mutation": re.compile(r"registry_mutated|registry_mutation", re.I),
    "execution_authority": re.compile(r"execution_allowed|execution_authority", re.I),
    "order_authority": re.compile(r"order_authority", re.I),
    "paper_live": re.compile(r"paper_allowed|live_allowed|real_order|live_enabled", re.I),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256_bytes(raw)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def git_files(root: Path) -> list[Path]:
    try:
        raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        names = [part.decode("utf-8", errors="surrogateescape") for part in raw.split(b"\0") if part]
        return [root / name for name in names if not any(part in SKIP_PARTS for part in Path(name).parts)]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in root.rglob("*") if p.is_file() and not any(part in SKIP_PARTS for part in p.relative_to(root).parts)]


def is_text(path: Path, data: bytes) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Dockerfile", "Caddyfile", "Procfile", "package.json"}:
        return b"\0" not in data[:8192]
    return False


def classify(relative: str) -> str:
    low = relative.casefold()
    for layer, needles in LAYER_RULES:
        if any(needle.casefold() in low for needle in needles):
            return layer
    return "other"


def module_names(relative: str) -> set[str]:
    path = Path(relative)
    if path.suffix != ".py":
        return set()
    parts = list(path.with_suffix("").parts)
    names = {".".join(parts)}
    if parts and parts[-1] == "__init__":
        names.add(".".join(parts[:-1]))
    return {name for name in names if name}


def resolve_import(name: str, module_to_path: Mapping[str, str]) -> str | None:
    current = name
    while current:
        if current in module_to_path:
            return module_to_path[current]
        current = current.rpartition(".")[0]
    return None


def literal_path(node: ast.AST, constants: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
        return literal_path(node.args[0], constants)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = literal_path(node.left, constants)
        right = literal_path(node.right, constants)
        if left is not None and right is not None:
            return str(Path(left) / right)
    return None


def analyze_python(text: str, relative: str, module_to_path: Mapping[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {"imports": [], "write_targets": [], "ast_sha256": None, "parse_error": None}
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as exc:
        result["parse_error"] = f"{exc.msg}:{exc.lineno}"
        return result

    result["ast_sha256"] = sha256_bytes(ast.dump(tree, include_attributes=False).encode("utf-8"))
    constants: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: list[ast.AST]
            value = node.value
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                targets = [node.target]
            path_value = literal_path(value, constants) if value is not None else None
            if path_value is not None:
                for target in targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = path_value

    imports: set[str] = set()
    writes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = resolve_import(alias.name, module_to_path)
                if target:
                    imports.add(target)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            target = resolve_import(module, module_to_path)
            if target:
                imports.add(target)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "open" and node.args:
                mode = literal_path(node.args[1], constants) if len(node.args) > 1 else "r"
                for keyword in node.keywords:
                    if keyword.arg == "mode":
                        mode = literal_path(keyword.value, constants)
                if mode and any(flag in mode for flag in ("w", "a", "x", "+")):
                    target = literal_path(node.args[0], constants)
                    if target:
                        writes.add(target)
            elif isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr in {"write_text", "write_bytes", "touch", "unlink", "mkdir"}:
                    target = literal_path(node.func.value, constants)
                    if target:
                        writes.add(target)
                elif attr in {"replace", "rename"} and node.args:
                    target = literal_path(node.args[0], constants)
                    if target:
                        writes.add(target)
                elif attr in {"copy", "copy2", "move"} and len(node.args) >= 2:
                    target = literal_path(node.args[1], constants)
                    if target:
                        writes.add(target)
    result["imports"] = sorted(imports)
    result["write_targets"] = sorted(writes)
    return result


def normalize_target(value: str) -> str:
    value = value.strip().replace("\\", "/")
    value = re.sub(r"^\./", "", value)
    value = re.sub(r"/+", "/", value)
    return value


def github_open_prs(repo: str, token: str) -> list[dict[str, Any]]:
    if not repo or not token:
        return []
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "zel-full-architecture-census-v1",
    }
    rows: list[dict[str, Any]] = []
    for page in range(1, 6):
        query = urllib.parse.urlencode({"state": "open", "per_page": 100, "page": page})
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/pulls?{query}", headers=headers)
        with urllib.request.urlopen(req, timeout=45) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            break
        rows.extend(row for row in batch if isinstance(row, dict))
        if len(batch) < 100:
            break
    return rows


def normalized_pr_key(title: str, body: str) -> str:
    text = f"{title} {body}"
    markers = re.findall(r"\b[A-Z][A-Z0-9_]{5,}\b", text)
    preferred = [m for m in markers if any(token in m for token in ("W1", "STRATEGY11", "GEMINI", "SEALED", "CLASSIFIER", "REPLAY"))]
    if preferred:
        return preferred[0]
    cleaned = re.sub(r"\bv?\d+(?:\.\d+)*\b", "", title.casefold())
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return " ".join(cleaned.split())


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--github-repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    tracked = git_files(root)
    relative_paths = [p.relative_to(root).as_posix() for p in tracked]
    path_set = set(relative_paths)

    module_to_path: dict[str, str] = {}
    for relative in relative_paths:
        for module in module_names(relative):
            module_to_path[module] = relative

    inventory: list[dict[str, Any]] = []
    edges: set[tuple[str, str, str]] = set()
    incoming: defaultdict[str, set[str]] = defaultdict(set)
    writer_map: defaultdict[str, set[str]] = defaultdict(set)
    exact_groups: defaultdict[str, list[str]] = defaultdict(list)
    ast_groups: defaultdict[str, list[str]] = defaultdict(list)
    entrypoint_refs: set[str] = set()
    parse_errors: list[dict[str, str]] = []
    authority_files: list[dict[str, Any]] = []

    contents: dict[str, str] = {}
    for path, relative in zip(tracked, relative_paths):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        layer = classify(relative)
        row: dict[str, Any] = {
            "path": relative,
            "layer": layer,
            "suffix": path.suffix.lower(),
            "size_bytes": len(data),
            "sha256": sha256_bytes(data),
            "text": False,
            "parse_error": "",
            "incoming_count": 0,
            "outgoing_count": 0,
            "writer_target_count": 0,
            "generated_path_candidate": any(part.casefold() in GENERATED_PARTS for part in Path(relative).parts),
        }
        if is_text(path, data):
            row["text"] = True
            text = data.decode("utf-8", errors="replace")
            contents[relative] = text
            if path.suffix.lower() in CODE_SUFFIXES | {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".service", ".timer"}:
                exact_groups[row["sha256"]].append(relative)
            if path.suffix.lower() == ".py":
                analysis = analyze_python(text, relative, module_to_path)
                row["parse_error"] = analysis["parse_error"] or ""
                if analysis["parse_error"]:
                    parse_errors.append({"path": relative, "error": analysis["parse_error"]})
                if analysis["ast_sha256"]:
                    ast_groups[str(analysis["ast_sha256"])].append(relative)
                for target in analysis["imports"]:
                    edges.add((relative, target, "python_import"))
                    incoming[target].add(relative)
                for target in analysis["write_targets"]:
                    writer_map[normalize_target(target)].add(relative)
            for match in PATH_REF_RE.findall(text):
                candidate = match.rstrip(".,:;)]}'\"")
                if candidate in path_set and candidate != relative:
                    edges.add((relative, candidate, "literal_path_ref"))
                    incoming[candidate].add(relative)
            if layer in {"workflow_ci", "ops_deploy"} or path.suffix.lower() in {".sh", ".service", ".timer"}:
                for candidate in PATH_REF_RE.findall(text):
                    candidate = candidate.rstrip(".,:;)]}'\"")
                    if candidate in path_set:
                        entrypoint_refs.add(candidate)
                for match in SHELL_WRITE_RE.findall(text):
                    writer_map[normalize_target(match)].add(relative)
            flags = [name for name, pattern in AUTHORITY_PATTERNS.items() if pattern.search(text)]
            if flags:
                authority_files.append({"path": relative, "layer": layer, "flags": flags})
        inventory.append(row)

    outgoing: defaultdict[str, set[str]] = defaultdict(set)
    for source, target, _kind in edges:
        outgoing[source].add(target)
    inv_by_path = {row["path"]: row for row in inventory}
    for path, row in inv_by_path.items():
        row["incoming_count"] = len(incoming.get(path, set()))
        row["outgoing_count"] = len(outgoing.get(path, set()))
        row["writer_target_count"] = sum(1 for owners in writer_map.values() if path in owners)

    writer_conflicts = [
        {"target": target, "owners": sorted(owners), "owner_count": len(owners), "severity": "HIGH" if len(owners) >= 3 else "MEDIUM"}
        for target, owners in sorted(writer_map.items()) if len(owners) > 1
    ]
    exact_duplicates = [
        {"sha256": digest, "paths": sorted(paths), "count": len(paths)}
        for digest, paths in exact_groups.items() if len(paths) > 1
    ]
    ast_duplicates = [
        {"ast_sha256": digest, "paths": sorted(paths), "count": len(paths)}
        for digest, paths in ast_groups.items() if len(paths) > 1
    ]

    cleanup_candidates: list[dict[str, Any]] = []
    for row in inventory:
        relative = str(row["path"])
        layer = str(row["layer"])
        reasons: list[str] = []
        confidence = "LOW"
        if row["generated_path_candidate"]:
            reasons.append("TRACKED_GENERATED_OR_RUNTIME_PATH")
            confidence = "HIGH"
        if (
            row["text"] and row["incoming_count"] == 0 and relative not in entrypoint_refs
            and layer not in {"workflow_ci", "ops_deploy", "tests", "research", "registry_config"}
            and Path(relative).name != "__init__.py"
        ):
            reasons.append("NO_STATIC_INCOMING_REFERENCE")
        if reasons:
            cleanup_candidates.append({
                "path": relative,
                "layer": layer,
                "reasons": reasons,
                "confidence": confidence,
                "action": "REVIEW_ONLY_NO_DELETE",
            })

    layer_counts: defaultdict[str, int] = defaultdict(int)
    for row in inventory:
        layer_counts[str(row["layer"])] += 1
    layer_edges: defaultdict[tuple[str, str], int] = defaultdict(int)
    for source, target, _kind in edges:
        source_layer = str(inv_by_path.get(source, {}).get("layer", "other"))
        target_layer = str(inv_by_path.get(target, {}).get("layer", "other"))
        if source_layer != target_layer:
            layer_edges[(source_layer, target_layer)] += 1

    integration_gaps: list[dict[str, Any]] = []
    for left, right in zip(CHAIN, CHAIN[1:]):
        direct = layer_edges.get((left, right), 0) + layer_edges.get((right, left), 0)
        if layer_counts[left] and layer_counts[right] and direct == 0:
            integration_gaps.append({
                "from_layer": left,
                "to_layer": right,
                "static_edge_count": 0,
                "severity": "REVIEW",
                "note": "Static scan found no direct edge; dynamic loading or deployment binding must be verified before patching.",
            })

    open_prs: list[dict[str, Any]] = []
    pr_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    try:
        open_prs = github_open_prs(args.github_repo, token)
    except Exception as exc:  # network evidence is optional; fail closed into explicit blocker
        open_prs = [{"number": None, "title": "GITHUB_PR_FETCH_FAILED", "body": str(exc)[:300], "draft": None, "head": {}}]
    for row in open_prs:
        number = row.get("number")
        if number is None:
            continue
        key = normalized_pr_key(str(row.get("title") or ""), str(row.get("body") or ""))
        pr_groups[key].append({
            "number": number,
            "title": row.get("title"),
            "draft": row.get("draft"),
            "head_ref": (row.get("head") or {}).get("ref"),
            "head_sha": (row.get("head") or {}).get("sha"),
        })
    duplicate_pr_groups = [
        {"key": key, "prs": sorted(rows, key=lambda x: int(x["number"])), "count": len(rows), "action": "KEEP_ONE_AUTHORITY_CLOSE_SUPERSEDED"}
        for key, rows in pr_groups.items() if key and len(rows) > 1
    ]

    blockers: list[str] = []
    if parse_errors:
        blockers.append("PYTHON_PARSE_ERRORS_PRESENT")
    if writer_conflicts:
        blockers.append("MULTI_WRITER_TARGETS_REQUIRE_REVIEW")
    if duplicate_pr_groups:
        blockers.append("DUPLICATE_OPEN_PR_GROUPS_REQUIRE_REVIEW")

    summary = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_CENSUS_WITH_REVIEW_ITEMS" if not blockers else "HOLD_REVIEW_REQUIRED",
        "root_head_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "tracked_file_count": len(inventory),
        "text_file_count": sum(bool(row["text"]) for row in inventory),
        "layer_counts": dict(sorted(layer_counts.items())),
        "static_edge_count": len(edges),
        "writer_target_count": len(writer_map),
        "writer_conflict_count": len(writer_conflicts),
        "exact_duplicate_group_count": len(exact_duplicates),
        "ast_duplicate_group_count": len(ast_duplicates),
        "cleanup_candidate_count": len(cleanup_candidates),
        "integration_gap_count": len(integration_gaps),
        "python_parse_error_count": len(parse_errors),
        "open_pr_count": sum(1 for row in open_prs if row.get("number") is not None),
        "duplicate_open_pr_group_count": len(duplicate_pr_groups),
        "blockers": blockers,
        "safety": {
            "read_only": True,
            "deletion_performed": False,
            "canonical_mutated": False,
            "registry_mutated": False,
            "runtime_mutated": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        },
        "next": "VERIFY_HIGH_CONFIDENCE_WRITER_AND_DEPLOYMENT_BINDINGS_THEN_MINIMAL_CLEANUP",
    }

    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "summary.json", summary)
    atomic_json(out / "writer_conflicts.json", {"rows": writer_conflicts})
    atomic_json(out / "duplicate_groups.json", {"exact": exact_duplicates, "python_ast": ast_duplicates})
    atomic_json(out / "cleanup_candidates.json", {"rows": cleanup_candidates})
    atomic_json(out / "integration_gaps.json", {"rows": integration_gaps})
    atomic_json(out / "authority_files.json", {"rows": authority_files})
    atomic_json(out / "open_pr_topology.json", {"open_prs": open_prs, "duplicate_groups": duplicate_pr_groups})
    atomic_json(out / "parse_errors.json", {"rows": parse_errors})
    write_csv(
        out / "file_inventory.csv",
        ["path", "layer", "suffix", "size_bytes", "sha256", "text", "parse_error", "incoming_count", "outgoing_count", "writer_target_count", "generated_path_candidate"],
        inventory,
    )
    write_csv(
        out / "static_edges.csv",
        ["source", "target", "kind"],
        ({"source": source, "target": target, "kind": kind} for source, target, kind in sorted(edges)),
    )

    md = [
        "# ZEL full architecture census v1",
        "",
        f"- State: **{summary['state']}**",
        f"- Git head: `{summary['root_head_sha']}`",
        f"- Tracked files: `{summary['tracked_file_count']}`",
        f"- Static edges: `{summary['static_edge_count']}`",
        f"- Writer conflicts: `{summary['writer_conflict_count']}`",
        f"- Cleanup candidates: `{summary['cleanup_candidate_count']}` (review only)",
        f"- Integration gaps: `{summary['integration_gap_count']}`",
        f"- Duplicate open PR groups: `{summary['duplicate_open_pr_group_count']}`",
        "",
        "## Layer counts",
        "",
    ]
    for layer, count in sorted(layer_counts.items()):
        md.append(f"- `{layer}`: {count}")
    md.extend(["", "## Safety", "", "No files, services, registry entries, runtime state, Shadow/Paper/Live authority, or orders were changed.", ""])
    (out / "architecture.md").write_text("\n".join(md), encoding="utf-8")

    print(json.dumps({
        "state": summary["state"],
        "files": summary["tracked_file_count"],
        "writer_conflicts": summary["writer_conflict_count"],
        "cleanup_candidates": summary["cleanup_candidate_count"],
        "duplicate_pr_groups": summary["duplicate_open_pr_group_count"],
        "next": summary["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
