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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "ZEL_FULL_ARCHITECTURE_CENSUS_V2"
TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".toml", ".ini", ".cfg",
    ".yaml", ".yml", ".sh", ".service", ".timer", ".md", ".txt", ".html",
    ".css", ".scss", ".sql", ".env", ".conf", ".caddy", ".nginx",
}
CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".sh"}
SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__"}
GENERATED_PARTS = {"runtime_results", "artifacts", "artifact", "out", "output", "outputs", "cache", ".cache", "tmp", "temp", "coverage", "dist", "build"}
LEGACY_NAME_RE = re.compile(r"(?:^|[._-])(?:disabled|bak|backup|old|legacy|tmp|copy|restore)(?:[._-]|$)|(?:19|20)\d{6,12}", re.I)
ABS_PATH_RE = re.compile(r"/(?:home/z/z|var/www|etc/systemd/system|opt|srv)/[A-Za-z0-9_./@\-]+")
REPO_PATH_RE = re.compile(r"(?:(?:backend|frontend|engine|strategies|tools|scripts|research|tests|config|\.github)/[A-Za-z0-9_./\-]+)")
ROUTE_DECORATORS = {"route", "get", "post", "put", "patch", "delete"}

LAYER_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("workflow_ci", (".github/workflows/",)),
    ("ops_deploy", ("systemd", ".service", ".timer", "deploy", "bootstrap", "caddy", "nginx", "docker", "compose", "gunicorn")),
    ("api_surface", ("app.py", "wsgi.py", "backend/routers/", "frontend/dashboard.py", "webhook")),
    ("surfaces", ("telegram", "alimi", "frontend/", "z-os-app", "dashboard", "/view", "web/", "ui/", "static/", "templates/")),
    ("ledger_pnl", ("ledger", "pnl", "journal", "writer", "recent_trace", "trade_log", "logs.db")),
    ("position_state", ("position", "lifecycle", "close_writer", "open_writer", "state_store", "state.py", "utils/state", "util/state")),
    ("execution", ("oms", "order", "execution", "exec_live", "exec_shadow", "exchange", "bingx", "fill", "intent_gate")),
    ("router", ("router", "route_", "routing")),
    ("signal_admission", ("signal", "admission", "candidate", "gate", "selector", "risk_unit")),
    ("registry_config", ("registry", "config/", "contract", "ssot", "policy", "settings")),
    ("canonical_strategy", ("backend/strategies/", "backend/strategy25/", "strategies/", "canonical25", "strategy25")),
    ("research", ("backend/research/", "research/", "replay", "simulation", "strategy11")),
    ("tests", ("tests/", "test_", "fixture")),
]

CRITICAL_CHAIN = [
    "canonical_strategy", "registry_config", "signal_admission", "router", "execution",
    "position_state", "ledger_pnl", "api_surface", "surfaces",
]

ROLE_BASENAMES = {"state.py", "router.py", "selector.py", "writer.py", "registry.py", "settings.py", "config.py", "app.py", "dashboard.py"}


@dataclass(frozen=True)
class PyInfo:
    imports: tuple[str, ...]
    imported_symbols: tuple[tuple[str, str], ...]
    writes: tuple[str, ...]
    definitions: tuple[str, ...]
    called_names: tuple[str, ...]
    duplicate_defs: tuple[str, ...]
    routes: tuple[tuple[str, str], ...]
    module_calls: tuple[str, ...]
    module_scheduler_jobs: int
    ast_sha256: str | None
    parse_error: str | None


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


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def git_files(root: Path) -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    names = [part.decode("utf-8", errors="surrogateescape") for part in raw.split(b"\0") if part]
    return [root / name for name in names if not any(part in SKIP_PARTS for part in Path(name).parts)]


def is_text(path: Path, data: bytes) -> bool:
    return (path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Dockerfile", "Caddyfile", "Procfile", "package.json"}) and b"\0" not in data[:8192]


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


def resolve_module(name: str, module_to_path: Mapping[str, str]) -> str | None:
    current = name
    while current:
        if current in module_to_path:
            return module_to_path[current]
        current = current.rpartition(".")[0]
    return None


def literal_string(node: ast.AST, constants: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
        return literal_string(node.args[0], constants)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = literal_string(node.left, constants)
        right = literal_string(node.right, constants)
        if left is not None and right is not None:
            return str(Path(left) / right)
    if isinstance(node, ast.JoinedStr):
        values: list[str] = []
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.append(item.value)
            else:
                values.append("{dynamic}")
        return "".join(values)
    return None


def plausible_write_target(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().replace("\\", "/")
    if value in {"/dev/null", "NUL", "nul", "-"}:
        return None
    if not ("/" in value or value.startswith(".") or Path(value).suffix.lower() in {".json", ".csv", ".db", ".sqlite", ".txt", ".log", ".html", ".yaml", ".yml"}):
        return None
    return re.sub(r"/+", "/", value)


def decorator_route(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr not in ROUTE_DECORATORS or not node.args:
        return None
    if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def analyze_python(text: str, relative: str, module_to_path: Mapping[str, str]) -> PyInfo:
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as exc:
        return PyInfo((), (), (), (), (), (), (), (), 0, None, f"{exc.msg}:{exc.lineno}")

    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value = literal_string(node.value, constants)
            if value is not None:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = literal_string(node.value, constants) if node.value else None
            if value is not None:
                constants[node.target.id] = value

    imports: set[str] = set()
    imported_symbols: set[tuple[str, str]] = set()
    definitions: list[str] = []
    duplicate_defs: set[str] = set()
    seen_defs: set[str] = set()
    routes: list[tuple[str, str]] = []
    module_calls: list[str] = []
    module_scheduler_jobs = 0
    writes: set[str] = set()
    called_names: set[str] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in seen_defs:
                duplicate_defs.add(node.name)
            seen_defs.add(node.name)
            definitions.append(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    route = decorator_route(dec)
                    if route is not None:
                        routes.append((route, node.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target = resolve_module(alias.name, module_to_path)
                if target:
                    imports.add(target)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            target = resolve_module(module, module_to_path)
            if target:
                imports.add(target)
                for alias in node.names:
                    imported_symbols.add((target, alias.name))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name):
                module_calls.append(call.func.id)
            elif isinstance(call.func, ast.Attribute):
                module_calls.append(call.func.attr)
                if call.func.attr == "add_job":
                    module_scheduler_jobs += 1

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called_names.add(node.func.id)
            if node.func.id == "open" and node.args:
                mode = "r"
                if len(node.args) > 1:
                    mode = literal_string(node.args[1], constants) or "r"
                for keyword in node.keywords:
                    if keyword.arg == "mode":
                        mode = literal_string(keyword.value, constants) or mode
                if any(flag in mode for flag in ("w", "a", "x", "+")):
                    target = plausible_write_target(literal_string(node.args[0], constants))
                    if target:
                        writes.add(target)
        elif isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in {"write_text", "write_bytes", "touch"}:
                target = plausible_write_target(literal_string(node.func.value, constants))
                if target:
                    writes.add(target)
            elif attr in {"rename", "replace"} and node.args:
                source = plausible_write_target(literal_string(node.func.value, constants))
                target = plausible_write_target(literal_string(node.args[0], constants))
                if source and target:
                    writes.add(target)
            elif attr in {"copy", "copy2", "move"} and len(node.args) >= 2:
                target = plausible_write_target(literal_string(node.args[1], constants))
                if target:
                    writes.add(target)

    return PyInfo(
        tuple(sorted(imports)), tuple(sorted(imported_symbols)), tuple(sorted(writes)), tuple(sorted(set(definitions))),
        tuple(sorted(called_names)), tuple(sorted(duplicate_defs)), tuple(sorted(routes)), tuple(module_calls),
        module_scheduler_jobs, sha256_bytes(ast.dump(tree, include_attributes=False).encode("utf-8")), None,
    )


def github_open_prs(repo: str, token: str) -> list[dict[str, Any]]:
    if not repo or not token:
        return []
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "zel-full-architecture-census-v2"}
    rows: list[dict[str, Any]] = []
    for page in range(1, 6):
        query = urllib.parse.urlencode({"state": "open", "per_page": 100, "page": page})
        request = urllib.request.Request(f"https://api.github.com/repos/{repo}/pulls?{query}", headers=headers)
        with urllib.request.urlopen(request, timeout=45) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            break
        rows.extend(row for row in batch if isinstance(row, dict))
        if len(batch) < 100:
            break
    return rows


def title_tokens(title: str) -> set[str]:
    low = title.casefold().replace("multobjective", "multiobjective").replace("alpha_combo", "alpha")
    low = re.sub(r"\bv?\d+(?:\.\d+)*\b", " ", low)
    tokens = set(re.findall(r"[a-z0-9]+", low))
    return tokens - {"strategy11", "r7a4d", "clean", "child", "v"}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, len(a | b))


def duplicate_pr_groups(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        if row.get("number") is None:
            continue
        records.append({
            "number": int(row["number"]),
            "title": str(row.get("title") or ""),
            "draft": row.get("draft"),
            "base_ref": str((row.get("base") or {}).get("ref") or ""),
            "head_ref": str((row.get("head") or {}).get("ref") or ""),
            "head_sha": str((row.get("head") or {}).get("sha") or ""),
            "tokens": title_tokens(str(row.get("title") or "")),
        })
    parent = list(range(len(records)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(records)):
        for k in range(i + 1, len(records)):
            left, right = records[i], records[k]
            if left["base_ref"] != right["base_ref"]:
                continue
            similarity = jaccard(left["tokens"], right["tokens"])
            exact_core = left["tokens"] == right["tokens"] and len(left["tokens"]) >= 3
            if exact_core or (similarity >= 0.82 and len(left["tokens"] & right["tokens"]) >= 4):
                union(i, k)

    groups: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for idx, row in enumerate(records):
        clean = {key: value for key, value in row.items() if key != "tokens"}
        groups[find(idx)].append(clean)
    return [
        {"count": len(group), "prs": sorted(group, key=lambda row: row["number"]), "action": "KEEP_STRONGEST_AUTHORITY_CLOSE_TRUE_DUPLICATES"}
        for group in groups.values() if len(group) > 1
    ]


def route_duplicates(py_infos: Mapping[str, PyInfo]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, info in py_infos.items():
        by_route: defaultdict[str, list[str]] = defaultdict(list)
        for route, function in info.routes:
            by_route[route].append(function)
        for route, functions in by_route.items():
            if len(functions) > 1:
                rows.append({"path": path, "route": route, "functions": functions, "severity": "HIGH", "code": "DUPLICATE_ROUTE_IN_MODULE"})
    return rows


def imported_symbol_defects(py_infos: Mapping[str, PyInfo]) -> list[dict[str, Any]]:
    definitions = {path: set(info.definitions) for path, info in py_infos.items()}
    rows: list[dict[str, Any]] = []
    for source, info in py_infos.items():
        for target, symbol in info.imported_symbols:
            if symbol == "*" or target not in definitions:
                continue
            if symbol not in definitions[target]:
                rows.append({"path": source, "target": target, "symbol": symbol, "severity": "CRITICAL", "code": "IMPORTED_SYMBOL_MISSING"})
    return rows


def app_factory_defects(py_infos: Mapping[str, PyInfo], contents: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    info = py_infos.get("app.py")
    text = contents.get("app.py", "")
    if info:
        if "create_app" in info.definitions:
            try:
                tree = ast.parse(text)
                create_nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "create_app"]
                has_return = bool(create_nodes and any(isinstance(node, ast.Return) for node in ast.walk(create_nodes[0])))
                if not has_return:
                    rows.append({"path": "app.py", "severity": "CRITICAL", "code": "APP_FACTORY_NO_RETURN", "evidence": "create_app has no return statement"})
            except SyntaxError:
                pass
        if "start_core" in info.module_calls:
            rows.append({"path": "app.py", "severity": "HIGH", "code": "IMPORT_TIME_CORE_START", "evidence": "start_core() runs at module import"})
        if info.module_scheduler_jobs:
            rows.append({"path": "app.py", "severity": "HIGH", "code": "IMPORT_TIME_JOB_REGISTRATION", "evidence": f"module-level add_job count={info.module_scheduler_jobs}"})
        for name in info.duplicate_defs:
            rows.append({"path": "app.py", "severity": "HIGH", "code": "DUPLICATE_DEFINITION", "evidence": name})
    if "if app is None" in contents.get("wsgi.py", ""):
        rows.append({"path": "wsgi.py", "severity": "HIGH", "code": "APP_FACTORY_FAILURE_MASKED", "evidence": "WSGI falls back to blank Flask app when create_app returns None"})
    return rows


def unresolved_name_defects(contents: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = contents.get("frontend/dashboard.py", "")
    if "def _conn(" in text and re.search(r"\bwith\s+conn\(\)\s+as\s+", text):
        rows.append({"path": "frontend/dashboard.py", "severity": "CRITICAL", "code": "UNDEFINED_DB_CONNECTION_CALL", "evidence": "ensure_schema calls conn() but only _conn() is defined"})
    return rows


def deployment_topology(contents: Mapping[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    target_owners: defaultdict[str, list[str]] = defaultdict(list)
    for path, text in contents.items():
        if classify(path) not in {"ops_deploy", "workflow_ci", "surfaces"}:
            continue
        absolute = sorted(set(match.rstrip(".,:;)]}'\"") for match in ABS_PATH_RE.findall(text)))
        deploy_targets = [value for value in absolute if value.startswith("/var/www/") or value == "/var/www/html"]
        roots = [value for value in absolute if value.startswith("/home/z/z/frontend/")]
        if absolute:
            rows.append({"path": path, "absolute_paths": absolute, "deploy_targets": deploy_targets, "source_roots": roots})
        for target in deploy_targets:
            target_owners[target].append(path)
    conflicts = [
        {"deploy_target": target, "owners": sorted(set(owners)), "owner_count": len(set(owners)), "severity": "HIGH"}
        for target, owners in target_owners.items() if len(set(owners)) > 1
    ]
    legacy = [
        {"path": row["path"], "reason": "MULTI_ROOT_OR_NONCANONICAL_FRONTEND_DEPLOY", "source_roots": row["source_roots"], "deploy_targets": row["deploy_targets"], "action": "VERIFY_AND_QUARANTINE_IF_UNREFERENCED"}
        for row in rows
        if any("z-os-pwa" in value for value in row["source_roots"]) or len(row["deploy_targets"]) > 1
    ]
    return {"rows": rows, "target_conflicts": conflicts, "legacy_candidates": legacy}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--github-repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    tracked = git_files(root)
    relative_paths = [path.relative_to(root).as_posix() for path in tracked]
    path_set = set(relative_paths)
    module_to_path: dict[str, str] = {}
    for relative in relative_paths:
        for module in module_names(relative):
            module_to_path[module] = relative

    contents: dict[str, str] = {}
    inventory: list[dict[str, Any]] = []
    py_infos: dict[str, PyInfo] = {}
    edges: set[tuple[str, str, str]] = set()
    incoming: defaultdict[str, set[str]] = defaultdict(set)
    writer_map: defaultdict[str, set[str]] = defaultdict(set)
    exact_groups: defaultdict[str, list[str]] = defaultdict(list)
    ast_groups: defaultdict[str, list[str]] = defaultdict(list)
    entrypoint_refs: set[str] = set()
    parse_errors: list[dict[str, str]] = []
    authority_files: list[dict[str, Any]] = []
    db_path_owners: defaultdict[str, set[str]] = defaultdict(set)

    for path, relative in zip(tracked, relative_paths):
        data = path.read_bytes()
        layer = classify(relative)
        row: dict[str, Any] = {
            "path": relative, "layer": layer, "suffix": path.suffix.lower(), "size_bytes": len(data),
            "sha256": sha256_bytes(data), "text": False, "parse_error": "", "incoming_count": 0,
            "outgoing_count": 0, "writer_target_count": 0,
            "generated_path_candidate": any(part.casefold() in GENERATED_PARTS for part in Path(relative).parts),
            "legacy_name_candidate": bool(LEGACY_NAME_RE.search(Path(relative).name)),
        }
        if is_text(path, data):
            row["text"] = True
            text = data.decode("utf-8", errors="replace")
            contents[relative] = text
            if path.suffix.lower() in CODE_SUFFIXES | {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".service", ".timer"}:
                exact_groups[row["sha256"]].append(relative)
            for db_path in re.findall(r"/[A-Za-z0-9_./\-]+\.(?:db|sqlite)", text):
                db_path_owners[db_path].add(relative)
            for match in REPO_PATH_RE.findall(text):
                candidate = match.rstrip(".,:;)]}'\"")
                if candidate in path_set and candidate != relative:
                    edges.add((relative, candidate, "literal_path_ref"))
                    incoming[candidate].add(relative)
                    if layer in {"workflow_ci", "ops_deploy"} or path.suffix.lower() == ".sh":
                        entrypoint_refs.add(candidate)
            if path.suffix.lower() == ".py":
                info = analyze_python(text, relative, module_to_path)
                py_infos[relative] = info
                row["parse_error"] = info.parse_error or ""
                if info.parse_error:
                    parse_errors.append({"path": relative, "error": info.parse_error})
                if info.ast_sha256:
                    ast_groups[info.ast_sha256].append(relative)
                for target in info.imports:
                    edges.add((relative, target, "python_import"))
                    incoming[target].add(relative)
                for target in info.writes:
                    writer_map[target].add(relative)
            flags = []
            for name, pattern in {
                "canonical_mutation": r"canonical_mutated|canonical_mutation",
                "registry_mutation": r"registry_mutated|registry_mutation",
                "execution_authority": r"execution_allowed|execution_authority",
                "order_authority": r"order_authority",
                "paper_live": r"paper_allowed|live_allowed|real_order|live_enabled",
            }.items():
                if re.search(pattern, text, re.I):
                    flags.append(name)
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
        {"target": target, "owners": sorted(owners), "owner_count": len(owners), "severity": "CRITICAL" if len(owners) >= 3 else "HIGH"}
        for target, owners in sorted(writer_map.items()) if len(owners) > 1
    ]
    exact_duplicates = [{"sha256": digest, "paths": sorted(paths), "count": len(paths)} for digest, paths in exact_groups.items() if len(paths) > 1]
    ast_duplicates = [{"ast_sha256": digest, "paths": sorted(paths), "count": len(paths)} for digest, paths in ast_groups.items() if len(paths) > 1]

    role_groups: defaultdict[str, list[str]] = defaultdict(list)
    for relative in relative_paths:
        if Path(relative).name in ROLE_BASENAMES:
            role_groups[Path(relative).name].append(relative)
    role_collisions = [
        {"role_basename": name, "paths": sorted(paths), "count": len(paths), "severity": "REVIEW", "action": "MAP_RUNTIME_OWNER_BEFORE_CONSOLIDATION"}
        for name, paths in role_groups.items() if len(paths) > 1
    ]

    cleanup_candidates: list[dict[str, Any]] = []
    duplicate_paths = {path for group in exact_duplicates for path in group["paths"]}
    for row in inventory:
        relative = str(row["path"])
        reasons: list[str] = []
        confidence = "LOW"
        action = "REVIEW_ONLY_NO_DELETE"
        if row["legacy_name_candidate"]:
            reasons.append("LEGACY_OR_DISABLED_FILENAME")
            confidence = "HIGH"
        if row["generated_path_candidate"]:
            reasons.append("TRACKED_GENERATED_OR_RUNTIME_PATH")
            confidence = "MEDIUM"
            if "/dist/" in f"/{relative}/" and relative in duplicate_paths:
                reasons.append("EXACT_BASELINE_TO_DIST_MIRROR")
                action = "KEEP_UNTIL_DEPLOY_CONTRACT_PROVES_REBUILD_ONLY"
        if (
            row["text"] and row["suffix"] in CODE_SUFFIXES and row["incoming_count"] == 0 and relative not in entrypoint_refs
            and row["layer"] not in {"workflow_ci", "ops_deploy", "tests", "research", "canonical_strategy"}
            and Path(relative).name != "__init__.py"
        ):
            reasons.append("UNREFERENCED_EXECUTABLE_STATIC_SCAN")
        if reasons:
            cleanup_candidates.append({"path": relative, "layer": row["layer"], "reasons": reasons, "confidence": confidence, "action": action})

    defects: list[dict[str, Any]] = []
    defects.extend(app_factory_defects(py_infos, contents))
    defects.extend(unresolved_name_defects(contents))
    defects.extend(route_duplicates(py_infos))
    defects.extend(imported_symbol_defects(py_infos))
    for path, info in py_infos.items():
        for name in info.duplicate_defs:
            if not (path == "app.py" and name == "heartbeat"):
                defects.append({"path": path, "severity": "HIGH", "code": "DUPLICATE_DEFINITION", "evidence": name})
    if len(db_path_owners) > 1:
        defects.append({
            "path": "MULTIPLE", "severity": "HIGH", "code": "SPLIT_DATABASE_AUTHORITY",
            "evidence": {path: sorted(owners) for path, owners in sorted(db_path_owners.items())},
        })

    deployment = deployment_topology(contents)
    for row in deployment["legacy_candidates"]:
        defects.append({"path": row["path"], "severity": "HIGH", "code": "LEGACY_OR_MULTI_ROOT_DEPLOY_PATH", "evidence": row})

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
    for left, right in zip(CRITICAL_CHAIN, CRITICAL_CHAIN[1:]):
        direct = layer_edges.get((left, right), 0) + layer_edges.get((right, left), 0)
        if layer_counts[left] and layer_counts[right] and direct == 0:
            integration_gaps.append({"from_layer": left, "to_layer": right, "static_edge_count": 0, "severity": "REVIEW", "note": "No static direct edge; verify dynamic binding/service deployment before patching."})

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    pr_fetch_error = None
    try:
        open_prs = github_open_prs(args.github_repo, token)
    except Exception as exc:
        open_prs = []
        pr_fetch_error = str(exc)[:500]
    pr_duplicates = duplicate_pr_groups(open_prs)
    pr_rows = [{
        "number": row.get("number"), "title": row.get("title"), "draft": row.get("draft"),
        "base_ref": (row.get("base") or {}).get("ref"), "head_ref": (row.get("head") or {}).get("ref"),
        "head_sha": (row.get("head") or {}).get("sha"),
    } for row in open_prs]

    critical = [row for row in defects if row.get("severity") == "CRITICAL"]
    high = [row for row in defects if row.get("severity") == "HIGH"]
    blockers: list[str] = []
    if parse_errors:
        blockers.append("PYTHON_PARSE_ERRORS_PRESENT")
    if critical:
        blockers.append("CRITICAL_ARCHITECTURE_DEFECTS_PRESENT")
    if writer_conflicts:
        blockers.append("MULTI_WRITER_TARGETS_REQUIRE_REVIEW")
    if pr_duplicates:
        blockers.append("DUPLICATE_OPEN_PR_GROUPS_REQUIRE_REVIEW")
    if pr_fetch_error:
        blockers.append("GITHUB_PR_TOPOLOGY_FETCH_FAILED")

    summary = {
        "schema_version": "2.0", "version": VERSION,
        "state": "HOLD_REVIEW_REQUIRED" if blockers else "PASS_CENSUS_WITH_REVIEW_ITEMS",
        "root_head_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "tracked_file_count": len(inventory), "text_file_count": sum(bool(row["text"]) for row in inventory),
        "layer_counts": dict(sorted(layer_counts.items())), "static_edge_count": len(edges),
        "writer_target_count": len(writer_map), "writer_conflict_count": len(writer_conflicts),
        "exact_duplicate_group_count": len(exact_duplicates), "ast_duplicate_group_count": len(ast_duplicates),
        "role_collision_count": len(role_collisions), "cleanup_candidate_count": len(cleanup_candidates),
        "integration_gap_count": len(integration_gaps), "python_parse_error_count": len(parse_errors),
        "architecture_defect_count": len(defects), "critical_defect_count": len(critical), "high_defect_count": len(high),
        "open_pr_count": len(pr_rows), "duplicate_open_pr_group_count": len(pr_duplicates),
        "blockers": blockers,
        "safety": {"read_only": True, "deletion_performed": False, "canonical_mutated": False, "registry_mutated": False, "runtime_mutated": False, "protected_mutations": 0, "execution_allowed": False, "order_authority": "BLOCKED"},
        "next": "REPAIR_CONFIRMED_CRITICAL_APP_LIFECYCLE_DEFECTS_THEN_VERIFY_RUNTIME_DEPLOYMENT_PARITY",
    }

    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "summary.json", summary)
    atomic_json(out / "architecture_defects.json", {"rows": defects})
    atomic_json(out / "writer_conflicts.json", {"rows": writer_conflicts})
    atomic_json(out / "duplicate_groups.json", {"exact": exact_duplicates, "python_ast": ast_duplicates})
    atomic_json(out / "role_collisions.json", {"rows": role_collisions})
    atomic_json(out / "cleanup_candidates.json", {"rows": cleanup_candidates})
    atomic_json(out / "integration_gaps.json", {"rows": integration_gaps})
    atomic_json(out / "authority_files.json", {"rows": authority_files})
    atomic_json(out / "deployment_topology.json", deployment)
    atomic_json(out / "database_authority.json", {"paths": {path: sorted(owners) for path, owners in sorted(db_path_owners.items())}})
    atomic_json(out / "open_pr_topology.json", {"open_prs": pr_rows, "duplicate_groups": pr_duplicates, "fetch_error": pr_fetch_error})
    atomic_json(out / "parse_errors.json", {"rows": parse_errors})
    atomic_json(out / "critical_path_map.json", {"chain": CRITICAL_CHAIN, "layer_counts": dict(layer_counts), "layer_edges": [{"from": left, "to": right, "count": count} for (left, right), count in sorted(layer_edges.items())]})
    write_csv(out / "file_inventory.csv", ["path", "layer", "suffix", "size_bytes", "sha256", "text", "parse_error", "incoming_count", "outgoing_count", "writer_target_count", "generated_path_candidate", "legacy_name_candidate"], inventory)
    write_csv(out / "static_edges.csv", ["source", "target", "kind"], ({"source": source, "target": target, "kind": kind} for source, target, kind in sorted(edges)))

    md = [
        "# ZEL full architecture census v2", "", f"- State: **{summary['state']}**", f"- Git head: `{summary['root_head_sha']}`",
        f"- Files: `{summary['tracked_file_count']}`", f"- Critical defects: `{summary['critical_defect_count']}`",
        f"- High defects: `{summary['high_defect_count']}`", f"- Writer conflicts: `{summary['writer_conflict_count']}`",
        f"- Cleanup candidates: `{summary['cleanup_candidate_count']}` (review only)", f"- Duplicate open PR groups: `{summary['duplicate_open_pr_group_count']}`",
        "", "## Layer counts", "",
    ]
    md.extend(f"- `{layer}`: {count}" for layer, count in sorted(layer_counts.items()))
    md.extend(["", "## Safety", "", "No deletion, canonical/registry/runtime mutation, Shadow/Paper/Live activation, or order authority change was performed.", ""])
    (out / "architecture.md").write_text("\n".join(md), encoding="utf-8")

    print(json.dumps({"state": summary["state"], "files": summary["tracked_file_count"], "critical": len(critical), "high": len(high), "writer_conflicts": len(writer_conflicts), "cleanup_candidates": len(cleanup_candidates), "duplicate_pr_groups": len(pr_duplicates), "next": summary["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
