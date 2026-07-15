#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

UTC = timezone.utc
COMPONENTS = ("LBot", "MBot", "OBot", "SBot", "ZBot", "ZICO", "LiCo", "Zlice")
ALIASES = {
    "LBot": ("lbot", "leadbot"), "MBot": ("mbot", "methodbot"),
    "OBot": ("obot", "observerbot"), "SBot": ("sbot", "safetybot"),
    "ZBot": ("zbot", "advisorbot"), "ZICO": ("zico",),
    "LiCo": ("lico",), "Zlice": ("zlice",),
}
TEXT_SUFFIXES = {".py", ".service", ".timer", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sh"}
EXACT_CONTAMINATION_PARTS = {
    ".git", "node_modules", "vendor", "dist", "build", "__pycache__", ".venv", "venv",
    "backup", "backups", "archive", "archives", "rollback", "restore", "snapshot", "snapshots",
    "quarantine", "trash", "release_freeze", "release-freeze", "freeze", "frozen", "old", "copies",
}
CONTAMINATION_FRAGMENT = re.compile(
    r"(^|[._/-])(backup|backups|restore|rollback|archive|snapshot|quarantine|trash|release[_-]?freeze|"
    r"golden[_-]?backup|locked[_-]?baseline|live[_-]?backup|patch[_-]?backup|old|copy)([._/-]|$)", re.I
)
SUPPORT_PARTS = {"test", "tests", "script", "scripts"}
SUPPORT_PREFIXES = ("test_", "verify_", "apply_", "install_", "bootstrap_", "run_", "audit_", "probe_", "smoke_", "check_")
ORDER_CALLS = {"create_order", "place_order", "cancel_order", "submit_order", "send_order", "private_api", "private_endpoint"}
SECRET_ACCESSORS = {"getenv", "get_secret", "get_secrets", "get_credential", "get_credentials", "get_password"}
SENSITIVE_KEY = re.compile(r"(?:BINGX|BITGET|KRAKEN|MEXC|BYBIT|BINANCE|OKX).*(?:API[_-]?KEY|SECRET|PASSPHRASE|PRIVATE[_-]?KEY)|^(?:API[_-]?KEY|API[_-]?SECRET)$", re.I)
EXCHANGE_CONSTRUCTORS = re.compile(r"(?:bingx|exchange|ccxt|client|adapter)", re.I)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def contaminated(path: Path) -> tuple[bool, str | None]:
    parts = {part.lower() for part in path.parts}
    hit = sorted(parts.intersection(EXACT_CONTAMINATION_PARTS))
    if hit:
        return True, f"exact_part:{hit[0]}"
    text = str(path).replace("\\", "/")
    match = CONTAMINATION_FRAGMENT.search(text)
    if match:
        return True, f"fragment:{match.group(2).lower()}"
    return False, None


def support_surface(path: Path) -> bool:
    return any(part.lower() in SUPPORT_PARTS for part in path.parts) or path.stem.lower().startswith(SUPPORT_PREFIXES)


def canonical_roots(root: Path) -> list[Path]:
    values = [root / "backend", root / "tools", root / "services", root / "systemd", root / "config", Path("/etc/systemd/system")]
    return [path for path in values if path.exists()]


def iter_files(root: Path) -> Iterable[Path]:
    for base in canonical_roots(root):
        iterator = [base] if base.is_file() else base.rglob("*")
        for path in iterator:
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            yield path


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def component_affiliation(path: Path, tree: ast.AST | None, text: str) -> list[str]:
    tokens = {normalize(path.stem)}
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                tokens.add(normalize(node.name))
    result = []
    for component, aliases in ALIASES.items():
        if any(normalize(alias) in token for alias in aliases for token in tokens):
            result.append(component)
    return sorted(set(result))


def analyze_python(path: Path, text: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text, filename=str(path))
        parse_error = None
    except SyntaxError as exc:
        tree = None
        parse_error = f"SyntaxError:{exc.lineno}:{exc.msg}"

    components = component_affiliation(path, tree, text)
    imports: list[str] = []
    direct_order_calls: list[dict[str, Any]] = []
    credential_accesses: list[dict[str, Any]] = []
    generic_env_accesses: list[dict[str, Any]] = []
    exchange_constructors: list[dict[str, Any]] = []
    output_writes: list[dict[str, Any]] = []

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
            elif isinstance(node, ast.Call):
                name = dotted_name(node.func)
                leaf = name.rsplit(".", 1)[-1]
                line = getattr(node, "lineno", 0)
                if leaf in ORDER_CALLS:
                    direct_order_calls.append({"line": line, "call": name})
                if leaf in {"write_text", "write_bytes", "append_jsonl"} or leaf == "open":
                    output_writes.append({"line": line, "call": name})
                if EXCHANGE_CONSTRUCTORS.search(name) and leaf[:1].isupper():
                    exchange_constructors.append({"line": line, "call": name})

                accessor = leaf in SECRET_ACCESSORS or name in {"os.environ.get", "os.getenv", "keyring.get_password"}
                if accessor:
                    strings = [literal_string(arg) for arg in node.args]
                    strings = [value for value in strings if value]
                    sensitive = [value for value in strings if SENSITIVE_KEY.search(value)]
                    row = {"line": line, "call": name, "keys": strings[:5]}
                    if sensitive:
                        row["sensitive_keys"] = sensitive[:5]
                        credential_accesses.append(row)
                    else:
                        generic_env_accesses.append(row)

    direct_execution = bool(direct_order_calls or (credential_accesses and exchange_constructors))
    return {
        "path": str(path), "sha256": sha256(path), "components": components,
        "kind": "support" if support_surface(path) else "python",
        "parse_error": parse_error, "imports": sorted(set(imports))[:100],
        "direct_order_calls": direct_order_calls[:20],
        "credential_accesses": credential_accesses[:20],
        "generic_env_accesses": generic_env_accesses[:20],
        "exchange_constructors": exchange_constructors[:20],
        "output_writes": output_writes[:20],
        "direct_execution_semantic": direct_execution,
    }


def analyze_text(path: Path, text: str) -> dict[str, Any]:
    components = [component for component, aliases in ALIASES.items() if any(re.search(rf"\b{re.escape(alias)}\b", text, re.I) for alias in aliases)]
    order = [match.group(1) for match in re.finditer(r"\b(create_order|place_order|cancel_order|submit_order|send_order|private_api|private_endpoint)\s*\(", text, re.I)]
    sensitive = [match.group(0) for match in re.finditer(r"(?:os\.getenv|os\.environ\.get|get_secret|get_credentials?)\s*\([^\n]{0,160}(?:BINGX|BITGET|KRAKEN|MEXC)[^\n]{0,100}(?:API_KEY|SECRET|PASSPHRASE)", text, re.I)]
    exchange = bool(re.search(r"\b(?:BingX|Exchange|Client|ccxt)\s*\(", text))
    return {
        "path": str(path), "sha256": sha256(path), "components": sorted(set(components)),
        "kind": "support" if support_surface(path) else "text",
        "direct_order_calls": order[:20], "credential_accesses": sensitive[:20],
        "generic_env_accesses": [], "exchange_constructors": ["text_match"] if exchange else [],
        "output_writes": [], "imports": [],
        "direct_execution_semantic": bool(order or (sensitive and exchange)),
    }


def systemd_units() -> list[dict[str, Any]]:
    result = subprocess.run(["systemctl", "list-units", "--all", "--no-legend", "--no-pager"], capture_output=True, text=True, check=False)
    units = []
    for line in result.stdout.splitlines():
        name = line.split(maxsplit=1)[0] if line.strip() else ""
        if not name.endswith((".service", ".timer")):
            continue
        if not re.search(r"bot|team|advisor|zico|lico|zlice|exact25", name, re.I):
            continue
        show = subprocess.run(["systemctl", "show", name, "--no-pager", "-p", "ActiveState", "-p", "SubState", "-p", "MainPID", "-p", "ExecStart", "-p", "FragmentPath"], capture_output=True, text=True, check=False)
        fields = {}
        for row in show.stdout.splitlines():
            if "=" in row:
                key, value = row.split("=", 1)
                fields[key] = value
        units.append({"unit": name, **fields})
    return units


def audit(root: Path) -> dict[str, Any]:
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for path in iter_files(root):
        is_bad, reason = contaminated(path)
        if is_bad:
            excluded.append({"path": str(path), "reason": reason})
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        row = analyze_python(path, text) if path.suffix.lower() == ".py" else analyze_text(path, text)
        if row["components"] or row["direct_execution_semantic"]:
            included.append(row)

    units = systemd_units()
    active_exec_text = "\n".join(str(unit.get("ExecStart") or "") for unit in units if unit.get("ActiveState") == "active")
    module_to_rows: defaultdict[str, list[str]] = defaultdict(list)
    for row in included:
        path = Path(row["path"])
        try:
            relative = path.relative_to(root)
            module = ".".join(relative.with_suffix("").parts)
            if module.startswith("backend."):
                module = module[len("backend."):]
            module_to_rows[module].append(row["path"])
        except ValueError:
            pass

    direct_candidates = []
    for row in included:
        if row["kind"] == "support" or not row["direct_execution_semantic"]:
            continue
        active_exec = row["path"] in active_exec_text
        callers = []
        stem = Path(row["path"]).stem
        for other in included:
            if other["path"] == row["path"]:
                continue
            if any(stem in item.split(".") for item in other.get("imports", [])):
                callers.append(other["path"])
        direct_candidates.append({
            "path": row["path"], "components": row["components"], "active_exec": active_exec,
            "direct_order_calls": row["direct_order_calls"], "credential_accesses": row["credential_accesses"],
            "exchange_constructors": row["exchange_constructors"], "caller_paths": sorted(set(callers))[:30],
        })

    contamination_included = [row["path"] for row in included if contaminated(Path(row["path"]))[0]]
    generic_env_count = sum(len(row.get("generic_env_accesses", [])) for row in included)
    active_direct = [row for row in direct_candidates if row["active_exec"]]
    state = "HOLD" if active_direct else "PASS"
    verdict = "TB12_ACTIVE_DIRECT_AUTHORITY_PRESENT" if active_direct else "TB12_CONTAMINATION_ERADICATED_DIRECT_AUTHORITY_BOUNDED"
    return {
        "schema": "q4r3_team_advisor_tb12_contamination_eradication_v1",
        "generated_at": now_iso(), "state": state, "verdict": verdict,
        "scan": {
            "included_semantic_file_count": len(included),
            "excluded_contamination_file_count": len(excluded),
            "excluded_contamination_reason_counts": dict(sorted(__import__('collections').Counter(row["reason"] for row in excluded).items())),
            "excluded_contamination_sample": excluded[:100],
            "contamination_included_count": len(contamination_included),
            "contamination_included_paths": contamination_included,
        },
        "authority": {
            "direct_execution_candidate_count": len(direct_candidates),
            "active_direct_execution_candidate_count": len(active_direct),
            "direct_execution_candidates": direct_candidates,
            "generic_environment_access_excluded_count": generic_env_count,
            "generic_environment_access_counts_as_private_execution": False,
            "credential_access_requires_sensitive_key": True,
            "credential_only_requires_exchange_constructor": True,
        },
        "units": units,
        "policy": {
            "observer_only": True, "team_advisor_binding_enabled": False,
            "paper_enabled": False, "live_enabled": False, "order_enabled": False,
            "order_authority": "blocked", "execution_authority": "none", "action": "hold",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, args.output)
    print(json.dumps({
        "state": result["state"], "verdict": result["verdict"],
        "excluded_contamination": result["scan"]["excluded_contamination_file_count"],
        "contamination_included": result["scan"]["contamination_included_count"],
        "direct_candidates": result["authority"]["direct_execution_candidate_count"],
        "active_direct_candidates": result["authority"]["active_direct_execution_candidate_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
