#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

TEXT_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".toml", ".service", ".sh", ".md", ".txt"}
MAX_BYTES = 2_000_000
ID_FIELDS = ("strategy_id", "id", "name")
CONFIG_FIELDS = {
    "trigger", "entry", "entry_rule", "invalidation", "exit", "exit_rule",
    "risk", "risk_rule", "side", "regime", "signal", "filters", "parameters",
}


def run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprints(paths: Iterable[str]) -> dict[str, str | None]:
    return {path: sha256_file(Path(path)) for path in paths}


def normalize_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def dotted_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return None


def list_tree(repo: Path, target_sha: str) -> tuple[str, dict[str, dict[str, Any]]]:
    resolved = run(["git", "-C", str(repo), "rev-parse", f"{target_sha}^{{commit}}"])
    if resolved.returncode != 0:
        raise RuntimeError("TARGET_SHA_NOT_RESOLVED")
    commit = resolved.stdout.strip()
    listed = run(["git", "-C", str(repo), "ls-tree", "-r", "--long", commit])
    if listed.returncode != 0:
        raise RuntimeError("GIT_TREE_LIST_FAILED")
    tree: dict[str, dict[str, Any]] = {}
    for line in listed.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        fields = meta.split()
        if len(fields) < 4:
            continue
        try:
            size = int(fields[3])
        except ValueError:
            size = 0
        tree[path] = {"blob_sha": fields[2], "size": size}
    return commit, tree


def git_text(repo: Path, commit: str, path: str, tree: dict[str, dict[str, Any]]) -> str:
    meta = tree.get(path)
    if not meta or int(meta.get("size", 0) or 0) > MAX_BYTES:
        return ""
    shown = run(["git", "-C", str(repo), "show", f"{commit}:{path}"])
    return shown.stdout if shown.returncode == 0 else ""


def strategy_rows(a3: dict[str, Any], expected: int) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    rows = a3.get("strategies")
    if not isinstance(rows, list):
        return [], ["A3_STRATEGIES_NOT_LIST"]
    ids: list[str] = []
    for row in rows:
        if isinstance(row, dict) and str(row.get("strategy_id", "")).strip():
            ids.append(str(row["strategy_id"]).strip())
    if len(ids) != expected:
        blockers.append(f"A3_STRATEGY_COUNT_{len(ids)}_NE_{expected}")
    if len(set(ids)) != len(ids):
        blockers.append("A3_DUPLICATE_STRATEGY_ID")
    return sorted(set(ids)), blockers


def callable_inventory(module: ast.Module, preferred_names: tuple[str, ...]) -> dict[str, Any]:
    functions = [
        node.name for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]
    class_methods: list[str] = []
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
                class_methods.append(f"{node.name}.{child.name}")
    preferred = [name for name in functions if name in preferred_names]
    preferred += [name for name in class_methods if name.rsplit(".", 1)[-1] in preferred_names]
    return {
        "functions": sorted(set(functions)),
        "class_methods": sorted(set(class_methods)),
        "preferred": sorted(set(preferred)),
    }


def dict_items(node: ast.Dict) -> dict[str, ast.AST]:
    result: dict[str, ast.AST] = {}
    for key, value in zip(node.keys, node.values):
        raw = literal_string(key)
        if raw is not None:
            result[raw] = value
    return result


def extract_target(node: ast.AST, implementation_fields: set[str]) -> dict[str, Any]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.strip()
        return {
            "target": value,
            "target_path": value if value.endswith(".py") else None,
            "target_callable": None if value.endswith(".py") else value,
            "config_keys": [],
        }
    symbol = dotted_name(node)
    if symbol:
        return {"target": symbol, "target_path": None, "target_callable": symbol, "config_keys": []}
    if isinstance(node, ast.Dict):
        items = dict_items(node)
        config_keys = sorted(set(items) & CONFIG_FIELDS)
        for field in implementation_fields:
            if field in items:
                nested = extract_target(items[field], implementation_fields)
                nested["config_keys"] = sorted(set(nested.get("config_keys", [])) | set(config_keys))
                return nested
        return {"target": None, "target_path": None, "target_callable": None, "config_keys": config_keys}
    if isinstance(node, (ast.List, ast.Tuple)):
        targets = [extract_target(item, implementation_fields) for item in node.elts]
        targets = [item for item in targets if item.get("target")]
        if len(targets) == 1:
            return targets[0]
    return {"target": None, "target_path": None, "target_callable": None, "config_keys": []}


def evidence_token(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(key) or "") for key in ("target_path", "target_callable", "source_path", "callable"))


def analyze_python(
    path: str,
    text: str,
    blob_sha: str,
    strategy_ids: list[str],
    tree: dict[str, dict[str, Any]],
    preferred_names: tuple[str, ...],
    implementation_fields: set[str],
    registry_tokens: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        module = ast.parse(text, filename=path)
    except Exception:
        return output
    inventory = callable_inventory(module, preferred_names)
    preferred = inventory["preferred"]
    normalized_path = normalize_id(Path(path).stem)
    id_by_norm = {normalize_id(sid): sid for sid in strategy_ids}

    direct_sid = id_by_norm.get(normalized_path)
    if direct_sid and len(preferred) == 1:
        output[direct_sid].append({
            "kind": "DIRECT_STRATEGY_MODULE",
            "strength": "strong",
            "source_path": path,
            "source_blob_sha": blob_sha,
            "target_path": path,
            "target_callable": preferred[0],
            "callable": preferred[0],
            "inventory": inventory,
        })
    elif direct_sid and preferred:
        output[direct_sid].append({
            "kind": "DIRECT_STRATEGY_MODULE_AMBIGUOUS",
            "strength": "conflict",
            "source_path": path,
            "source_blob_sha": blob_sha,
            "target_path": path,
            "target_callable": None,
            "callable_candidates": preferred,
            "inventory": inventory,
        })

    def append_mapping(sid: str, value: ast.AST, kind: str, line: int) -> None:
        target = extract_target(value, implementation_fields)
        target_path = target.get("target_path")
        target_exists = bool(target_path and target_path in tree)
        target_callable = target.get("target_callable")
        config_keys = target.get("config_keys", [])
        shared_engine = preferred[0] if len(preferred) == 1 else None
        strong = bool(target_exists or target_callable or (len(config_keys) >= 2 and shared_engine))
        callable_name = target_callable or shared_engine
        output[sid].append({
            "kind": kind,
            "strength": "strong" if strong else "partial",
            "source_path": path,
            "source_blob_sha": blob_sha,
            "line": line,
            "target": target.get("target"),
            "target_path": target_path,
            "target_path_exists_in_git": target_exists,
            "target_callable": target_callable,
            "callable": callable_name,
            "config_keys": config_keys,
            "shared_engine_candidates": preferred,
            "registry_like_path": any(token in path.lower() for token in registry_tokens),
        })

    for node in ast.walk(module):
        if isinstance(node, ast.Dict):
            items = dict_items(node)
            for key, value in items.items():
                sid = id_by_norm.get(normalize_id(key))
                if sid:
                    append_mapping(sid, value, "PYTHON_LITERAL_REGISTRY_KEY", getattr(node, "lineno", 0))
            sid_value = None
            for field in ID_FIELDS:
                if field in items:
                    sid_value = literal_string(items[field])
                    if sid_value:
                        break
            sid = id_by_norm.get(normalize_id(sid_value or ""))
            if sid:
                append_mapping(sid, node, "PYTHON_STRATEGY_OBJECT", getattr(node, "lineno", 0))
        elif isinstance(node, ast.Call):
            keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
            sid_value = None
            for field in ID_FIELDS:
                if field in keywords:
                    sid_value = literal_string(keywords[field])
                    if sid_value:
                        break
            sid = id_by_norm.get(normalize_id(sid_value or ""))
            if sid:
                synthetic = ast.Dict(keys=[ast.Constant(value=key) for key in keywords], values=list(keywords.values()))
                append_mapping(sid, synthetic, "PYTHON_FACTORY_CALL", getattr(node, "lineno", 0))

    return output


def walk_json(value: Any, location: str = "$") -> Iterable[tuple[str, Any]]:
    yield location, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_json(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_json(child, f"{location}[{index}]")


def analyze_json(
    path: str,
    text: str,
    blob_sha: str,
    strategy_ids: list[str],
    implementation_fields: set[str],
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        value = json.loads(text)
    except Exception:
        return output
    id_by_norm = {normalize_id(sid): sid for sid in strategy_ids}
    for location, node in walk_json(value):
        if not isinstance(node, dict):
            continue
        for key, child in node.items():
            sid = id_by_norm.get(normalize_id(str(key)))
            if sid:
                config_keys = sorted(set(child) & CONFIG_FIELDS) if isinstance(child, dict) else []
                target = None
                if isinstance(child, str):
                    target = child
                elif isinstance(child, dict):
                    for field in implementation_fields:
                        if isinstance(child.get(field), str):
                            target = child[field]
                            break
                output[sid].append({
                    "kind": "JSON_LITERAL_REGISTRY_KEY",
                    "strength": "partial",
                    "source_path": path,
                    "source_blob_sha": blob_sha,
                    "json_path": location,
                    "target": target,
                    "target_path": target if isinstance(target, str) and target.endswith(".py") else None,
                    "target_callable": target if isinstance(target, str) and not target.endswith(".py") else None,
                    "callable": None,
                    "config_keys": config_keys,
                })
        sid_value = next((node.get(field) for field in ID_FIELDS if isinstance(node.get(field), str)), None)
        sid = id_by_norm.get(normalize_id(str(sid_value or "")))
        if sid:
            target = next((node.get(field) for field in implementation_fields if isinstance(node.get(field), str)), None)
            output[sid].append({
                "kind": "JSON_STRATEGY_OBJECT",
                "strength": "partial",
                "source_path": path,
                "source_blob_sha": blob_sha,
                "json_path": location,
                "target": target,
                "target_path": target if isinstance(target, str) and target.endswith(".py") else None,
                "target_callable": target if isinstance(target, str) and not target.endswith(".py") else None,
                "callable": None,
                "config_keys": sorted(set(node) & CONFIG_FIELDS),
            })
    return output


def text_references(texts: dict[str, str], needles: set[str], path_filter: callable) -> list[str]:
    result = []
    lowered = {needle.lower() for needle in needles if needle}
    for path, text in texts.items():
        if not path_filter(path):
            continue
        low = text.lower()
        if any(needle in low for needle in lowered):
            result.append(path)
    return sorted(set(result))


def classify_strategy(
    sid: str,
    evidence: list[dict[str, Any]],
    texts: dict[str, str],
) -> dict[str, Any]:
    strong = [row for row in evidence if row.get("strength") == "strong"]
    conflict_rows = [row for row in evidence if row.get("strength") == "conflict"]
    tokens = sorted(set(evidence_token(row) for row in strong if evidence_token(row).strip("|")))
    if conflict_rows or len(tokens) > 1:
        status = "CONFLICT"
    elif len(tokens) == 1:
        status = "PROVEN"
    elif evidence:
        status = "PARTIAL"
    else:
        status = "UNPROVEN"

    primary = strong[0] if status == "PROVEN" and strong else None
    needles = {sid}
    if primary:
        needles.update({str(primary.get("source_path") or ""), str(primary.get("target_path") or ""), str(primary.get("callable") or "")})
    runtime_refs = text_references(
        texts,
        needles,
        lambda path: path.endswith((".service", ".sh", ".py")) and path.startswith(("systemd/", "services/", "scripts/", "tools/")),
    )
    test_refs = text_references(
        texts,
        needles,
        lambda path: path.startswith(("tests/", "test/")) or "/tests/" in path or path.endswith("_test.py"),
    )
    return {
        "strategy_id": sid,
        "lineage_status": status,
        "canonical_token": tokens[0] if len(tokens) == 1 else None,
        "strong_evidence_count": len(strong),
        "evidence_count": len(evidence),
        "runtime_owner_refs": runtime_refs[:30],
        "test_refs": test_refs[:30],
        "runtime_owner_proven": bool(runtime_refs),
        "test_binding_proven": bool(test_refs),
        "evidence": evidence[:60],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected = int(contract.get("expected_strategy_count", 25))
    a3_path = root / str(contract.get("prior_a3_status_path"))
    a3c2_path = root / str(contract.get("prior_a3c2_status_path"))
    status_path = root / str(contract.get("status_path"))
    protected_paths = [str(path) for path in contract.get("protected_paths", [])]
    before = fingerprints(protected_paths)
    blockers: list[str] = []

    a3 = load_json(a3_path)
    a3c2 = load_json(a3c2_path)
    ids, row_blockers = strategy_rows(a3, expected)
    blockers.extend(row_blockers)
    if a3.get("state") != "PASS" or int(a3.get("blocker_count", -1)) != 0:
        blockers.append("PRIOR_A3_INVALID")

    try:
        commit, tree = list_tree(root, args.target_sha)
    except Exception as exc:
        commit, tree = "", {}
        blockers.append(str(exc))

    texts: dict[str, str] = {}
    if commit:
        for path, meta in tree.items():
            if Path(path).suffix.lower() not in TEXT_EXTENSIONS:
                continue
            if int(meta.get("size", 0) or 0) > MAX_BYTES:
                continue
            text = git_text(root, commit, path, tree)
            if text:
                texts[path] = text

    preferred_names = tuple(str(x) for x in contract.get("entrypoint_names", []))
    implementation_fields = {str(x) for x in contract.get("implementation_fields", [])}
    registry_tokens = tuple(str(x).lower() for x in contract.get("strong_registry_tokens", []))
    evidence_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for path, text in texts.items():
        blob_sha = str(tree.get(path, {}).get("blob_sha") or "")
        suffix = Path(path).suffix.lower()
        found: dict[str, list[dict[str, Any]]] = {}
        if suffix == ".py":
            found = analyze_python(path, text, blob_sha, ids, tree, preferred_names, implementation_fields, registry_tokens)
        elif suffix == ".json":
            found = analyze_json(path, text, blob_sha, ids, implementation_fields)
        for sid, rows in found.items():
            evidence_by_id[sid].extend(rows)

    mappings = [classify_strategy(sid, evidence_by_id.get(sid, []), texts) for sid in ids]
    counts = defaultdict(int)
    for row in mappings:
        counts[row["lineage_status"]] += 1
    proven = int(counts["PROVEN"])
    conflicts = int(counts["CONFLICT"])
    partial = int(counts["PARTIAL"])
    unproven = int(counts["UNPROVEN"])

    after = fingerprints(protected_paths)
    protected_changes = [
        {"path": path, "before": before.get(path), "after": after.get(path)}
        for path in protected_paths if before.get(path) != after.get(path)
    ]
    if protected_changes:
        blockers.append("PROTECTED_PATH_CHANGED")

    blockers = list(dict.fromkeys(blockers))
    state = "PASS" if not blockers else "HOLD"
    if state != "PASS":
        next_stage = contract.get("next_stage_fail")
    elif proven == expected and conflicts == 0:
        next_stage = contract.get("next_stage_all_proven")
    else:
        next_stage = contract.get("next_stage_gaps")

    payload = {
        "schema": "r7a3d_strategy25_canonical_implementation_lineage_audit_status_v1",
        "official_stage": "R7.A3D",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "read_only": True,
        "target_commit": commit,
        "strategy_count": len(ids),
        "lineage_counts": dict(sorted(counts.items())),
        "proven_lineage_count": proven,
        "partial_lineage_count": partial,
        "unproven_lineage_count": unproven,
        "conflict_lineage_count": conflicts,
        "mappings": mappings,
        "prior_a3c2_state": a3c2.get("state"),
        "prior_a3c2_blockers": a3c2.get("blockers", []),
        "false_implementation_ref_model_rejected": True,
        "performance_s_promoted_count": 0,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "runtime_mutation_count": 0,
        "next_stage": next_stage,
    }
    atomic_json(status_path, payload)

    print("R7A3D_STRATEGY25_CANONICAL_IMPLEMENTATION_LINEAGE_AUDIT_COMPLETE")
    for key, value in (
        ("STATE", state),
        ("BLOCKER_COUNT", len(blockers)),
        ("BLOCKERS", json.dumps(blockers, ensure_ascii=False)),
        ("STRATEGY_COUNT", len(ids)),
        ("PROVEN_LINEAGE_COUNT", proven),
        ("PARTIAL_LINEAGE_COUNT", partial),
        ("UNPROVEN_LINEAGE_COUNT", unproven),
        ("CONFLICT_LINEAGE_COUNT", conflicts),
        ("FALSE_IMPLEMENTATION_REF_MODEL_REJECTED", "true"),
        ("PROTECTED_CHANGE_COUNT", len(protected_changes)),
        ("RUNTIME_MUTATION_COUNT", 0),
        ("NEXT_STAGE", next_stage),
        ("EVIDENCE_JSON", str(status_path)),
        ("RC", 0 if state == "PASS" else 2),
    ):
        print(f"{key}={value}")
    unresolved = [
        {"strategy_id": row["strategy_id"], "status": row["lineage_status"], "evidence_count": row["evidence_count"]}
        for row in mappings if row["lineage_status"] != "PROVEN"
    ]
    print("UNRESOLVED_LINEAGE=" + json.dumps(unresolved, ensure_ascii=False))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
