#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

UTC = timezone.utc
COMPONENTS = [
    "LBot", "MBot", "OBot", "SBot",
    "AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam",
    "ZBot", "Zico", "Lico", "Zlice",
]
TEAM_COMPONENTS = {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}
TEXT_SUFFIXES = {".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".service", ".timer", ".md", ".txt"}
ROLE_KEYS = {"team_id", "main_bot", "support_bot", "watchers", "watcher_bots", "helper_bot", "helper_trigger"}
CONTRACT_FIELDS = {
    "position_id", "decision_id", "event_id", "parent_event_id", "symbol", "side",
    "strategy_id", "method_id", "skill_id", "team_id", "event_ts", "source_ids",
    "contract_version", "decision", "confidence", "abstain", "reason_codes",
    "freshness_ms", "latency_ms", "evidence_ids",
}
SENSITIVE_NAME = re.compile(r"(?i)(api[_-]?key|secret|token|password|passphrase|private[_-]?key)")
LEGACY_OUTPUT_NAMES = {"ZICO", "LiCo", "LICO"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, path)


def sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def run(command: Sequence[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    except Exception as exc:
        return subprocess.CompletedProcess(command, 125, "", f"{type(exc).__name__}:{exc}")


def canonical_component(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    mapping = {
        "lbot": "LBot", "mbot": "MBot", "obot": "OBot", "sbot": "SBot",
        "alphateam": "AlphaTeam", "betateam": "BetaTeam", "gammateam": "GammaTeam", "deltateam": "DeltaTeam",
        "zbot": "ZBot", "zico": "Zico", "lico": "Lico", "zlice": "Zlice",
    }
    return mapping.get(normalized, value)


def normalize_path(path: Path) -> str:
    try:
        return str(path.resolve(strict=False))
    except OSError:
        return str(path)


def git_metadata(root: Path, path: Path) -> dict[str, Any]:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except Exception:
        return {"tracked": False, "relative_path": None, "commit": None, "commit_at": None}
    rel = str(relative)
    tracked = run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel]).returncode == 0
    if not tracked:
        return {"tracked": False, "relative_path": rel, "commit": None, "commit_at": None}
    commit = run(["git", "-C", str(root), "log", "-1", "--format=%H|%cI", "--", rel])
    commit_id = None
    commit_at = None
    if commit.returncode == 0 and commit.stdout.strip():
        parts = commit.stdout.strip().split("|", 1)
        commit_id = parts[0]
        commit_at = parts[1] if len(parts) > 1 else None
    return {"tracked": True, "relative_path": rel, "commit": commit_id, "commit_at": commit_at}


def extract_root_assignments(exec_start: str, working_directory: str | None, default_root: Path) -> dict[str, str]:
    values: dict[str, str] = {"Q4R3_ROOT": str(default_root)}
    if working_directory and working_directory.startswith("/"):
        values["PWD"] = working_directory
    for name, raw in re.findall(r"(?:^|[ ;])(ROOT|Q4R3_ROOT|Z_ROOT)=([^ ;]+)", exec_start or ""):
        value = raw.strip("'\"")
        if value.startswith("/"):
            values[name] = value
    values.setdefault("ROOT", str(default_root))
    values.setdefault("Z_ROOT", values.get("ROOT", str(default_root)))
    return values


def expand_shell_vars(value: str, variables: Mapping[str, str]) -> str:
    result = value
    for name, replacement in variables.items():
        result = result.replace("${" + name + "}", replacement)
        result = result.replace("$" + name, replacement)
    return result


def script_paths_from_unit(record: Mapping[str, Any], root: Path) -> list[str]:
    exec_start = str(record.get("exec_start") or "")
    working_directory = str(record.get("working_directory") or "")
    variables = extract_root_assignments(exec_start, working_directory, root)
    expanded = expand_shell_vars(exec_start, variables)
    candidates: set[str] = set()

    for raw in record.get("resolved_script_paths", []) or []:
        value = expand_shell_vars(str(raw), variables)
        candidates.add(value)
    for raw in re.findall(r"(/[A-Za-z0-9_+.,@%:=/\-]+\.(?:py|sh))", expanded):
        candidates.add(raw)

    normalized: set[str] = set()
    for raw in candidates:
        path = Path(raw)
        if path.exists():
            normalized.add(normalize_path(path))
            continue
        # Prior R0 parsing could turn $ROOT/scripts/x.py into /scripts/x.py.
        if raw.startswith("/scripts/"):
            fixed = root / raw.lstrip("/")
            if fixed.exists():
                normalized.add(normalize_path(fixed))
                continue
        if not path.is_absolute() and working_directory:
            fixed = Path(working_directory) / path
            if fixed.exists():
                normalized.add(normalize_path(fixed))
                continue
        normalized.add(str(path))
    return sorted(normalized)


def safe_constant(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool)) or node.value is None:
            if isinstance(node.value, str) and SENSITIVE_NAME.search(node.value):
                return "<sensitive-name-redacted>"
            return node.value
    if isinstance(node, ast.List):
        return [safe_constant(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return [safe_constant(item) for item in node.elts]
    if isinstance(node, ast.Dict):
        result: dict[str, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            key = safe_constant(key_node) if key_node is not None else None
            if not isinstance(key, (str, int, float, bool)):
                continue
            key_text = str(key)
            if SENSITIVE_NAME.search(key_text):
                result[key_text] = "<redacted>"
            else:
                result[key_text] = safe_constant(value_node)
        return result
    if isinstance(node, ast.Name):
        return {"name_ref": node.id}
    if isinstance(node, ast.Attribute):
        return {"attribute_ref": dotted_name(node)}
    return None


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def role_assignments(tree: ast.AST) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        value = safe_constant(node)
        if not isinstance(value, dict):
            continue
        keys = {str(key).lower() for key in value}
        if not keys.intersection(ROLE_KEYS):
            continue
        compact = {key: val for key, val in value.items() if str(key).lower() in ROLE_KEYS}
        compact["line"] = getattr(node, "lineno", 0)
        found.append(compact)
    return found[:100]


def contract_fields_from_tree(tree: ast.AST) -> list[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in CONTRACT_FIELDS:
            found.add(node.value)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in CONTRACT_FIELDS:
                    found.add(target.id)
    return sorted(found)


def source_manifest(path: Path, root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": normalize_path(path),
        "exists": path.is_file(),
        "sha256": sha256(path),
        "size_bytes": None,
        "line_count": None,
        "git": git_metadata(root, path),
        "classes": [],
        "functions": [],
        "imports": [],
        "role_assignments": [],
        "contract_fields": [],
        "has_main_guard": False,
        "parse_error": None,
        "source_text_included": False,
    }
    if not path.is_file():
        return result
    try:
        stat = path.stat()
        result["size_bytes"] = stat.st_size
        text = path.read_text(encoding="utf-8", errors="replace")
        result["line_count"] = len(text.splitlines())
    except OSError as exc:
        result["parse_error"] = f"READ_ERROR:{type(exc).__name__}"
        return result
    if path.suffix.lower() != ".py":
        return result
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        result["parse_error"] = f"SYNTAX_ERROR:{exc.lineno}:{exc.msg}"
        return result

    result["classes"] = sorted({node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)})[:200]
    result["functions"] = sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})[:300]
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
        elif isinstance(node, ast.If):
            try:
                rendered = ast.unparse(node.test)
            except Exception:
                rendered = ""
            if "__name__" in rendered and "__main__" in rendered:
                result["has_main_guard"] = True
    result["imports"] = sorted(imports)[:300]
    result["role_assignments"] = role_assignments(tree)
    result["contract_fields"] = contract_fields_from_tree(tree)
    return result


def package_key(component: str, path: str, root: Path) -> str:
    value = Path(path)
    try:
        rel = value.resolve(strict=False).relative_to(root.resolve(strict=False))
        parts = rel.parts
        if len(parts) >= 2:
            return f"repo:{'/'.join(parts[:-1])}:{component.lower()}"
        return f"repo:{rel.parent}:{component.lower()}"
    except Exception:
        return f"external:{value.parent}:{component.lower()}"


def group_candidates(component: str, rows: Sequence[Mapping[str, Any]], root: Path) -> list[dict[str, Any]]:
    groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        path = str(row.get("path") or "")
        if path:
            groups[package_key(component, path, root)].append(row)
    output: list[dict[str, Any]] = []
    for key, values in groups.items():
        values = sorted(values, key=lambda item: (-int(item.get("score") or 0), str(item.get("path") or "")))
        output.append({
            "package_key": key,
            "candidate_count": len(values),
            "paths": [str(item.get("path")) for item in values],
            "active_paths": [str(item.get("path")) for item in values if item.get("active_units")],
            "tracked_count": sum(bool(item.get("git", {}).get("tracked")) for item in values),
            "contract_version_count": sum(bool(item.get("contract_version")) for item in values),
            "max_score": max((int(item.get("score") or 0) for item in values), default=0),
            "classification_counts": dict(Counter(str(item.get("classification_recommendation") or "UNKNOWN") for item in values)),
        })
    return sorted(output, key=lambda item: (-int(item["max_score"]), str(item["package_key"])))


def candidate_reference_counts(root: Path, candidate_paths: Sequence[str]) -> dict[str, int]:
    stems = {Path(path).stem: path for path in candidate_paths if Path(path).stem}
    if not stems:
        return {}
    regex = re.compile(r"\b(" + "|".join(re.escape(stem) for stem in sorted(stems, key=len, reverse=True)) + r")\b")
    counts = Counter({path: 0 for path in candidate_paths})
    roots = [root / "backend", root / "scripts", root / "tools", Path("/usr/local/bin")]
    seen: set[str] = set()
    for scan_root in roots:
        if not scan_root.exists():
            continue
        iterator: Iterable[Path] = [scan_root] if scan_root.is_file() else scan_root.rglob("*")
        for file_path in iterator:
            try:
                if not file_path.is_file() or file_path.suffix.lower() not in TEXT_SUFFIXES or file_path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            normalized = normalize_path(file_path)
            if normalized in seen:
                continue
            seen.add(normalized)
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in regex.finditer(text):
                target = stems.get(match.group(1))
                if target and normalized != normalize_path(Path(target)):
                    counts[target] += 1
    return dict(counts)


def component_runtime_scripts(component: str, units: Sequence[Mapping[str, Any]], root: Path) -> list[str]:
    result: set[str] = set()
    for unit in units:
        components = {canonical_component(str(value)) for value in unit.get("components", [])}
        if component not in components:
            continue
        result.update(script_paths_from_unit(unit, root))
    return sorted(result)


def active_runtime_scripts(component: str, units: Sequence[Mapping[str, Any]], root: Path) -> list[str]:
    result: set[str] = set()
    for unit in units:
        components = {canonical_component(str(value)) for value in unit.get("components", [])}
        if component not in components or unit.get("active_state") != "active":
            continue
        result.update(script_paths_from_unit(unit, root))
    return sorted(result)


def adjudication_route(
    component: str,
    owner_state: Mapping[str, Any],
    candidate_rows: Sequence[Mapping[str, Any]],
    package_groups: Sequence[Mapping[str, Any]],
    active_scripts: Sequence[str],
    runtime_manifests: Sequence[Mapping[str, Any]],
    policy_surface_pct: float | None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    proven = list(owner_state.get("proven_owners") or [])
    if component == "Zico" and proven:
        owner_path = str(proven[0].get("path") or "")
        tracked = bool(proven[0].get("git", {}).get("tracked"))
        if owner_path.startswith("/") and not tracked:
            reasons.append("active owner is external to repository and must be mirrored before lock")
            return "MIRROR_ACTIVE_RUNTIME_TO_GIT", reasons
    if component in TEAM_COMPONENTS:
        assignments = [item for manifest in runtime_manifests for item in manifest.get("role_assignments", [])]
        if assignments:
            reasons.append("active Team Lane source contains explicit organizational assignment evidence")
            return "RECOVER_TEAM_PACKAGE_FROM_ACTIVE_RUNTIME", reasons
        reasons.append("no canonical Team package or explicit role assignment was proven")
        return "CREATE_CANONICAL_TEAM_PACKAGE_AFTER_ASSIGNMENT_RECOVERY", reasons
    if component == "ZBot":
        if policy_surface_pct is not None and policy_surface_pct < 100.0:
            reasons.append(f"dual-provider policy surfaces incomplete: {policy_surface_pct}%")
            return "CONSOLIDATE_ZBOT_AND_BUILD_PROVIDER_POLICY_PACKAGE", reasons
    if component == "Lico":
        reasons.append("Lico is a multi-stage source/consumption pipeline and must become one package owner")
        return "CONSOLIDATE_LICO_PIPELINE_AND_ADD_SOURCE_CONSENSUS", reasons
    if component == "Zlice":
        reasons.append("Zlice implementation and UI consumers must be separated under an evidence-core owner")
        return "SPLIT_ZLICE_EVIDENCE_CORE_FROM_UI", reasons
    if len(package_groups) > 1 or len(candidate_rows) > 1:
        reasons.append(f"{len(candidate_rows)} file candidates across {len(package_groups)} package groups")
        return "PACKAGE_CONSOLIDATION_REQUIRED", reasons
    if len(candidate_rows) == 1:
        candidate = candidate_rows[0]
        if not candidate.get("git", {}).get("tracked") or not candidate.get("contract_version"):
            reasons.append("single implementation exists but lacks tracked contract/version proof")
            return "PROMOTE_EXISTING_SOURCE_TO_CANONICAL_PACKAGE", reasons
    if not candidate_rows and active_scripts:
        reasons.append("runtime source exists but was not accepted as canonical candidate")
        return "RECOVER_RUNTIME_SOURCE_TO_CANONICAL_PACKAGE", reasons
    reasons.append("no sufficient implementation evidence")
    return "CANONICAL_IMPLEMENTATION_MISSING", reasons


def policy_pct(truth: Mapping[str, Any], component: str) -> float | None:
    surfaces = truth.get("policy_surfaces", {})
    row = surfaces.get(component) or surfaces.get(component.upper()) or surfaces.get(component.lower())
    if isinstance(row, Mapping):
        value = row.get("coverage_pct")
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def build_report(root: Path, truth: Mapping[str, Any], candidates_doc: Mapping[str, Any], units: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    inventory = truth.get("candidate_inventory") if isinstance(truth.get("candidate_inventory"), Mapping) else candidates_doc
    owner_matrix = truth.get("owner_matrix") if isinstance(truth.get("owner_matrix"), Mapping) else {}
    all_candidate_paths = [
        str(row.get("path"))
        for component in COMPONENTS
        for row in (inventory.get(component, []) if isinstance(inventory, Mapping) else [])
        if row.get("path")
    ]
    reference_counts = candidate_reference_counts(root, all_candidate_paths)

    components: dict[str, Any] = {}
    fix_queue: list[dict[str, Any]] = []
    for component in COMPONENTS:
        rows = list(inventory.get(component, []) if isinstance(inventory, Mapping) else [])
        groups = group_candidates(component, rows, root)
        runtime_scripts = component_runtime_scripts(component, units, root)
        active_scripts = active_runtime_scripts(component, units, root)
        runtime_manifests = [source_manifest(Path(path), root) for path in runtime_scripts]
        owner_state = owner_matrix.get(component, {}) if isinstance(owner_matrix, Mapping) else {}
        pct = policy_pct(truth, component)
        route, reasons = adjudication_route(component, owner_state, rows, groups, active_scripts, runtime_manifests, pct)
        candidate_summaries = []
        for row in rows:
            candidate_summaries.append({
                "path": row.get("path"),
                "sha256": row.get("sha256"),
                "score": row.get("score"),
                "owner_kind": row.get("owner_kind"),
                "classification_recommendation": row.get("classification_recommendation"),
                "active_units": row.get("active_units", []),
                "contract_version": row.get("contract_version"),
                "git": row.get("git", {}),
                "identity_evidence": row.get("identity_evidence", []),
                "reference_count": reference_counts.get(str(row.get("path")), 0),
            })
        components[component] = {
            "state": "HOLD",
            "r0_owner_state": owner_state,
            "candidate_count": len(rows),
            "candidate_packages": groups,
            "candidates": candidate_summaries,
            "runtime_scripts": runtime_scripts,
            "active_runtime_scripts": active_scripts,
            "runtime_source_manifests": runtime_manifests,
            "policy_surface_coverage_pct": pct,
            "adjudication_route": route,
            "route_reasons": reasons,
        }
        fix_queue.append({"component": component, "route": route, "reasons": reasons, "action": "hold"})

    canonical_name_violations = []
    serialized = json.dumps({"components": components}, ensure_ascii=False)
    for legacy in LEGACY_OUTPUT_NAMES:
        if f'"{legacy}"' in serialized:
            canonical_name_violations.append(legacy)

    priority = ["Zico", "AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam", "LBot", "MBot", "OBot", "SBot", "Lico", "ZBot", "Zlice"]
    order_index = {name: index for index, name in enumerate(priority)}
    fix_queue.sort(key=lambda item: order_index.get(str(item["component"]), 999))

    return {
        "schema": "q4r3_team_advisor_r01_owner_adjudication_v1",
        "generated_at": now_iso(),
        "state": "HOLD",
        "verdict": "R01_OWNER_ADJUDICATION_PLAN_READY",
        "r0_baseline": {
            "state": truth.get("state"),
            "verdict": truth.get("verdict"),
            "canonical_owner_count": truth.get("canonical_owner_count"),
            "duplicate_owner_count": truth.get("duplicate_owner_count"),
            "active_exec_mapping_pct": truth.get("active_exec_mapping_pct"),
            "complete_candidate_inventory_count": truth.get("complete_candidate_inventory_count"),
            "fix_queue_count": truth.get("fix_queue_count"),
        },
        "components": components,
        "fix_queue": fix_queue,
        "canonical_name_violations": canonical_name_violations,
        "next_patch_order": priority,
        "authority": {
            "observer_only": True,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
            "runtime_mutation_performed": False,
            "historical_backfill_performed": False,
        },
        "publication": {
            "raw_source_text_included": False,
            "credentials_included": False,
            "ast_symbol_inventory_only": True,
        },
        "action": "hold",
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    baseline = report.get("r0_baseline", {})
    lines = [
        "# Q4R3 R0.1 Owner Adjudication — Latest",
        "",
        f"- State: `{report.get('state')}`",
        f"- Verdict: `{report.get('verdict')}`",
        f"- R0 canonical owners: `{baseline.get('canonical_owner_count')}/12`",
        f"- R0 candidate inventory: `{baseline.get('complete_candidate_inventory_count')}`",
        "- Canonical display spelling: **Zico**, **Lico**",
        "",
        "## Adjudication routes",
        "",
        "| Component | Candidates | Active runtime | Route |",
        "|---|---:|---:|---|",
    ]
    components = report.get("components", {})
    for component in COMPONENTS:
        row = components.get(component, {})
        lines.append(
            f"| {component} | {row.get('candidate_count', 0)} | {len(row.get('active_runtime_scripts', []))} | `{row.get('adjudication_route')}` |"
        )
    lines.extend(["", "## Ordered fix queue", ""])
    for index, item in enumerate(report.get("fix_queue", []), 1):
        reasons = "; ".join(str(value) for value in item.get("reasons", []))
        lines.append(f"{index}. **{item.get('component')}** — `{item.get('route')}` — {reasons}")
    lines.extend([
        "",
        "## Safety",
        "",
        "- Read-only evidence collection only.",
        "- No service, Producer, Writer, Formal Ledger, Strategy, Method, Skill, Team, or Advisor mutation.",
        "- No source text or credentials are published; only hashes, AST symbols, assignments, and call-reference counts.",
        "",
    ])
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--root", type=Path, required=True)
    value.add_argument("--r0-truth", type=Path, required=True)
    value.add_argument("--r0-candidates", type=Path, required=True)
    value.add_argument("--r0-units", type=Path, required=True)
    value.add_argument("--output-json", type=Path, required=True)
    value.add_argument("--output-md", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    truth = read_json(args.r0_truth, {})
    candidates = read_json(args.r0_candidates, {})
    units = read_json(args.r0_units, [])
    if not isinstance(truth, Mapping) or not isinstance(units, list):
        raise SystemExit("R0_EVIDENCE_INVALID")
    report = build_report(args.root, truth, candidates, units)
    atomic_json(args.output_json, report)
    atomic_text(args.output_md, render_markdown(report))
    print(json.dumps({
        "state": report["state"],
        "verdict": report["verdict"],
        "component_count": len(report["components"]),
        "fix_queue_count": len(report["fix_queue"]),
        "canonical_name_violations": len(report["canonical_name_violations"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
