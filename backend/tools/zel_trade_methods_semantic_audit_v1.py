from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_TRADE_METHODS_SEMANTIC_AUDIT_V1"
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__",
    "runtime", "runtime_results", "data", "backups", "backup", "archive",
    "quarantine", "_quarantine", "imported_zips", ".cache",
}
PERSONAL_EXTENSIONS = {".txt", ".md", ".json", ".yaml", ".yml", ".pdf", ".docx"}
PERSONAL_EXACT_NAMES = {
    "트레이딩 방법론.txt",
    "trade_methods_personal.md",
    "trade_methods_personal.txt",
}
PERSONAL_TOKENS = (
    "트레이딩", "매매", "방법론", "매매방법", "trade_method", "trade-method",
    "trading_method", "trading-method", "personal_method", "playbook",
)
COMPONENT_TOKENS = ("zbot", "zico", "lico", "zlice", "lbot", "mbot", "obot", "sbot", "skill", "team")
ROLE_RULES: dict[str, tuple[str, ...]] = {
    "PLAN_TYPE": ("plan", "methodplan", "tradeplan", "profile"),
    "RESOLVER": ("resolve", "resolver", "select", "build", "compose"),
    "SKILL_TYPE": ("skill", "permission", "capability"),
    "RISK_MODE": ("riskmode", "risk_mode", "riskprofile", "risk_profile"),
    "EXIT_POLICY": ("exit", "takeprofit", "take_profit", "tp", "partial", "trail", "runner", "mfe", "breakeven", "time_stop"),
    "RISK_POLICY": ("risk", "drawdown", "stop", "loss", "cost", "slippage", "funding"),
    "SIZING_POLICY": ("size", "sizing", "scale", "pyramid", "dca", "average", "water"),
    "COMBO_POLICY": ("combo", "filter", "admission", "confirm", "veto"),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def annotation(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def decorators(nodes: Iterable[ast.expr]) -> list[str]:
    return [annotation(node) or "unknown" for node in nodes]


def literal_strings(node: ast.AST) -> list[str]:
    try:
        value = ast.literal_eval(node)
    except Exception:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def function_view(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    positional = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args)]
    return {
        "name": node.name,
        "async": isinstance(node, ast.AsyncFunctionDef),
        "positional_args": positional,
        "keyword_only_args": [arg.arg for arg in node.args.kwonlyargs],
        "vararg": node.args.vararg.arg if node.args.vararg else None,
        "kwarg": node.args.kwarg.arg if node.args.kwarg else None,
        "default_count": len(node.args.defaults),
        "return_annotation": annotation(node.returns),
        "decorators": decorators(node.decorator_list),
    }


def class_view(node: ast.ClassDef) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    enum_members: list[str] = []
    methods: list[dict[str, Any]] = []
    for child in node.body:
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            fields.append({"name": child.target.id, "annotation": annotation(child.annotation), "has_default": child.value is not None})
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    enum_members.append(target.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(function_view(child))
    return {
        "name": node.name,
        "bases": [annotation(base) or "unknown" for base in node.bases],
        "decorators": decorators(node.decorator_list),
        "fields": fields,
        "enum_members": sorted(set(enum_members)),
        "methods": methods,
    }


def inspect_python_file(path: Path, package_root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    relative = str(path.relative_to(package_root.parent.parent)) if package_root.parent.parent in path.parents else str(path)
    result: dict[str, Any] = {
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_path(path),
        "parse_ok": False,
        "classes": [],
        "functions": [],
        "constants": [],
        "exports": [],
        "imports": [],
        "parse_error": None,
    }
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        result["parse_error"] = f"SyntaxError:{exc.lineno}:{exc.msg}"
        return result
    result["parse_ok"] = True
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            result["classes"].append(class_view(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].append(function_view(node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id == "__all__":
                        result["exports"] = literal_strings(node.value)
                    elif target.id.isupper():
                        result["constants"].append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id.isupper():
            result["constants"].append(node.target.id)
        elif isinstance(node, ast.Import):
            result["imports"].extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            result["imports"].extend(f"{module}.{alias.name}" for alias in node.names)
    result["constants"] = sorted(set(result["constants"]))
    result["imports"] = sorted(set(result["imports"]))
    return result


def symbol_rows(files: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file_row in files:
        path = str(file_row["path"])
        for class_row in file_row.get("classes", []):
            rows.append({"kind": "class", "name": class_row["name"], "path": path, "detail": class_row})
        for function_row in file_row.get("functions", []):
            rows.append({"kind": "function", "name": function_row["name"], "path": path, "detail": function_row})
        for constant in file_row.get("constants", []):
            rows.append({"kind": "constant", "name": constant, "path": path, "detail": {}})
        for export in file_row.get("exports", []):
            rows.append({"kind": "export", "name": export, "path": path, "detail": {}})
    return rows


def role_candidates(symbols: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for role, tokens in ROLE_RULES.items():
        candidates: list[dict[str, Any]] = []
        for row in symbols:
            compact = str(row["name"]).replace("_", "").lower()
            hits = [token for token in tokens if token.replace("_", "").lower() in compact]
            if not hits:
                continue
            score = len(hits) * 10
            if row["kind"] == "class" and role in {"PLAN_TYPE", "SKILL_TYPE", "RISK_MODE"}:
                score += 5
            if row["kind"] == "function" and role == "RESOLVER":
                score += 5
            candidates.append({
                "name": row["name"],
                "kind": row["kind"],
                "path": row["path"],
                "matched_tokens": hits,
                "score": score,
                "detail": row.get("detail", {}),
            })
        candidates.sort(key=lambda item: (-int(item["score"]), str(item["path"]), str(item["name"])))
        result[role] = candidates[:20]
    return result


def bounded_files(roots: Iterable[Path], max_files: int = 50_000) -> Iterable[Path]:
    seen = 0
    for root in roots:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
            for name in files:
                seen += 1
                if seen > max_files:
                    return
                yield Path(current) / name


def personal_candidates(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    roots = [root, Path("/opt/zel"), Path("/var/www"), Path("/root")]
    exact = {value.casefold() for value in PERSONAL_EXACT_NAMES}
    for path in bounded_files(roots):
        if path.suffix.casefold() not in PERSONAL_EXTENSIONS:
            continue
        lowered = path.name.casefold()
        score = 100 if lowered in exact else 0
        hits = [token for token in PERSONAL_TOKENS if token.casefold() in lowered]
        score += len(hits) * 10
        if score == 0:
            continue
        try:
            stat = path.stat()
            rows.append({
                "path": str(path),
                "name": path.name,
                "suffix": path.suffix.casefold(),
                "size_bytes": stat.st_size,
                "sha256": sha256_path(path),
                "matched_tokens": hits,
                "score": score,
            })
        except OSError:
            continue
    rows.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
    return rows[:200]


def component_candidates(root: Path) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {token: [] for token in COMPONENT_TOKENS}
    roots = [root / "backend", root / "canonical", Path("/opt/zel")]
    for path in bounded_files(roots, max_files=80_000):
        lowered = str(path).casefold()
        for token in COMPONENT_TOKENS:
            if token not in lowered:
                continue
            try:
                result[token].append({
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_path(path),
                })
            except OSError:
                pass
    for token in result:
        unique = {row["path"]: row for row in result[token]}
        result[token] = [unique[key] for key in sorted(unique)][:100]
    return result


def runtime_import_view(root: Path) -> dict[str, Any]:
    python = root / ".venv" / "bin" / "python"
    if not python.is_file():
        python = root / "venv" / "bin" / "python"
    if not python.is_file():
        return {"state": "HOLD_PYTHON_ENV_MISSING", "returncode": 127, "symbols": [], "output_tail": ""}
    code = r'''
import inspect,json
import backend.trade_methods as m
rows=[]
for name in sorted(value for value in dir(m) if not value.startswith('_')):
    obj=getattr(m,name)
    kind='other'
    signature=None
    if inspect.isclass(obj): kind='class'
    elif inspect.isfunction(obj): kind='function'
    elif name.isupper(): kind='constant'
    if callable(obj):
        try: signature=str(inspect.signature(obj))
        except Exception: signature=None
    rows.append({'name':name,'kind':kind,'signature':signature,'module':getattr(obj,'__module__',None)})
print(json.dumps({'state':'PASS_RUNTIME_IMPORT','symbols':rows},sort_keys=True))
'''
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(root),
        "Q4R3_SHADOW_ONLY": "1",
        "Q4R3_PAPER_ENABLED": "0",
        "Q4R3_LIVE_ENABLED": "0",
        "Q4R3_ORDER_ENABLED": "0",
    })
    process = subprocess.run(
        [str(python), "-c", code],
        cwd=str(root),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )
    tail = process.stdout[-8000:]
    if process.returncode != 0:
        return {"state": "HOLD_RUNTIME_IMPORT_FAIL", "returncode": process.returncode, "symbols": [], "output_tail": tail}
    try:
        payload = json.loads(process.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return {"state": "HOLD_RUNTIME_IMPORT_JSON_FAIL", "returncode": process.returncode, "symbols": [], "output_tail": f"{type(exc).__name__}:{exc}:{tail}"}
    payload["returncode"] = process.returncode
    payload["output_tail"] = ""
    return payload


def audit(root: Path) -> dict[str, Any]:
    package = root / "backend" / "trade_methods"
    files: list[dict[str, Any]] = []
    if package.is_dir():
        for path in sorted(package.rglob("*.py")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            files.append(inspect_python_file(path, package))
    symbols = symbol_rows(files)
    roles = role_candidates(symbols)
    runtime = runtime_import_view(root)
    personal = personal_candidates(root)
    components = component_candidates(root)
    blockers: list[str] = []
    if not package.is_dir():
        blockers.append("TRADE_METHODS_PACKAGE_MISSING")
    if files and any(not row["parse_ok"] for row in files):
        blockers.append("TRADE_METHODS_AST_PARSE_FAILURE")
    if runtime.get("state") != "PASS_RUNTIME_IMPORT":
        blockers.append(str(runtime.get("state")))
    if not personal:
        blockers.append("PERSONAL_METHOD_SOURCE_CANDIDATE_NOT_FOUND")
    missing_roles = [role for role, candidates in roles.items() if not candidates]
    if missing_roles:
        blockers.append("SEMANTIC_ROLE_CANDIDATES_MISSING:" + ",".join(missing_roles))
    state = "PASS_TRADE_METHODS_SEMANTIC_INVENTORY" if not blockers else "HOLD_TRADE_METHODS_SEMANTIC_GAPS"
    payload = {
        "schema_version": "zel.trade_methods.semantic_auditor.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "root": str(root),
        "package_path": str(package),
        "python_file_count": len(files),
        "files": files,
        "symbol_count": len(symbols),
        "role_candidates": roles,
        "runtime_import": runtime,
        "personal_method_candidates": personal,
        "component_candidates": components,
        "blockers": blockers,
        "interpretation": {
            "marker_absence_does_not_prove_implementation_absence": True,
            "semantic_alias_requires_exact_type_signature_and_behavior_replay": True,
            "gemini_mapping_is_hypothesis_only": True,
            "canonical_patch_allowed": False,
        },
        "canonical_strategy_files_mutated": False,
        "canonical_trade_methods_mutated": False,
        "canonical_registry_mutated": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "shadow_start_allowed": False,
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
    }
    payload["inventory_sha256"] = stable_sha(payload)
    return payload


def self_test() -> None:
    tree = ast.parse("from dataclasses import dataclass\n@dataclass\nclass MethodPlan:\n    risk: str = 'x'\ndef resolve_method(plan: MethodPlan) -> MethodPlan:\n    return plan\nBASE_TP = 2.5\n__all__=['MethodPlan','resolve_method']\n")
    assert isinstance(tree.body[1], ast.ClassDef)
    class_row = class_view(tree.body[1])
    assert class_row["name"] == "MethodPlan" and class_row["fields"][0]["name"] == "risk"
    fn = function_view(tree.body[2])
    assert fn["name"] == "resolve_method" and fn["positional_args"] == ["plan"]
    candidates = role_candidates([
        {"kind": "class", "name": "MethodPlan", "path": "x.py", "detail": class_row},
        {"kind": "function", "name": "resolve_method", "path": "x.py", "detail": fn},
    ])
    assert candidates["PLAN_TYPE"] and candidates["RESOLVER"]
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.out:
        parser.error("--out is required")
    result = audit(Path(args.root).resolve())
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "blockers": result["blockers"], "inventory_sha256": result["inventory_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
