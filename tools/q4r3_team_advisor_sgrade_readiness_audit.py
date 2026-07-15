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
from typing import Any, Iterable, Mapping

UTC = timezone.utc
TEXT_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".service", ".timer", ".sh"}
CONTAMINATION_PARTS = {
    ".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", "__pycache__",
    "backup", "backups", "archive", "archives", "rollback", "restore", "snapshot", "snapshots",
    "quarantine", "trash", "release_freeze", "release-freeze", "freeze", "frozen", "old", "copies",
}
CONTAMINATION_FRAGMENT = re.compile(
    r"(^|[._/-])(backup|backups|restore|rollback|archive|snapshot|quarantine|trash|release[_-]?freeze|"
    r"golden[_-]?backup|locked[_-]?baseline|live[_-]?backup|patch[_-]?backup|old|copy)([._/-]|$)",
    re.I,
)
SUPPORT_PARTS = {"test", "tests", "script", "scripts"}
SUPPORT_PREFIXES = ("test_", "verify_", "apply_", "install_", "bootstrap_", "run_", "audit_", "probe_", "smoke_", "check_")
ORDER_CALLS = {"create_order", "place_order", "cancel_order", "submit_order", "send_order", "private_api", "private_endpoint"}
SENSITIVE_KEY = re.compile(r"(?:BINGX|BITGET|KRAKEN|MEXC|BYBIT|BINANCE|OKX).*(?:API[_-]?KEY|SECRET|PASSPHRASE|PRIVATE[_-]?KEY)", re.I)

ALIASES: dict[str, tuple[str, ...]] = {
    "LBot": ("lbot", "leadbot", "lead_bot"),
    "MBot": ("mbot", "methodbot", "method_bot"),
    "OBot": ("obot", "observerbot", "observer_bot"),
    "SBot": ("sbot", "safetybot", "safety_bot"),
    "ZBot": ("zbot", "advisorbot", "advisor_bot"),
    "ZICO": ("zico",),
    "LiCo": ("lico",),
    "Zlice": ("zlice",),
    "AlphaTeam": ("alphateam", "alpha_team", "alpha lane", "alpha_lane"),
    "BetaTeam": ("betateam", "beta_team", "beta lane", "beta_lane"),
    "GammaTeam": ("gammateam", "gamma_team", "gamma lane", "gamma_lane"),
    "DeltaTeam": ("deltateam", "delta_team", "delta lane", "delta_lane"),
}
TEAM_COMPONENTS = {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}

CAPABILITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "typed_input_contract": ("input_schema", "input_contract", "request_model", "basemodel", "typedinput"),
    "typed_output_contract": ("output_schema", "output_contract", "response_model", "typedoutput"),
    "owner_sha_or_version": ("contract_version", "schema_version", "version", "owner_sha", "sha256"),
    "deterministic_reason_codes": ("reason_code", "reason_codes", "decision_reason", "reasons"),
    "confidence_and_abstain": ("confidence", "abstain", "unknown", "insufficient"),
    "stale_and_missing_input_policy": ("stale", "freshness", "missing_input", "fail_closed", "data_age"),
    "latency_and_freshness_output": ("latency_ms", "freshness_ms", "age_ms", "generated_at"),
    "failure_isolation": ("try:", "except", "fallback", "degraded", "fail_closed", "circuit"),
    "status_and_violation_output": ("status_latest", "violations", "violation", "health", "status"),
    "counterfactual_or_ablation_trace": ("counterfactual", "ablation", "without_", "avoided_loss", "missed_profit"),
    "no_private_execution_authority": (),
    "unit_contract_failure_tests": (),
}

ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "LBot": ("trend", "primary", "lead", "hold", "reduce"),
    "MBot": ("method", "range", "confirm", "helper", "reduce"),
    "OBot": ("breakout", "observe", "observer", "anomaly"),
    "SBot": ("safety", "guard", "veto", "risk", "stale"),
    "ZBot": ("advisor", "advice", "counterfactual", "alternative", "decision_trace"),
    "ZICO": ("intent", "lifecycle", "control", "context"),
    "LiCo": ("liquidity", "macro", "fx", "freshness"),
    "Zlice": ("evidence", "lineage", "lifecycle", "trace"),
    "AlphaTeam": ("alpha", "team", "lane", "vote", "weight"),
    "BetaTeam": ("beta", "team", "lane", "vote", "weight"),
    "GammaTeam": ("gamma", "team", "lane", "vote", "weight"),
    "DeltaTeam": ("delta", "team", "lane", "vote", "weight"),
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contaminated(path: Path) -> tuple[bool, str | None]:
    lower_parts = {part.lower() for part in path.parts}
    hit = sorted(lower_parts.intersection(CONTAMINATION_PARTS))
    if hit:
        return True, f"exact_part:{hit[0]}"
    match = CONTAMINATION_FRAGMENT.search(str(path).replace("\\", "/"))
    if match:
        return True, f"fragment:{match.group(2).lower()}"
    return False, None


def support_surface(path: Path) -> bool:
    return any(part.lower() in SUPPORT_PARTS for part in path.parts) or path.stem.lower().startswith(SUPPORT_PREFIXES)


def canonical_roots(root: Path) -> list[Path]:
    roots = [root / "backend", root / "tools", root / "services", root / "systemd", root / "config", Path("/etc/systemd/system")]
    return [path for path in roots if path.exists()]


def iter_files(root: Path) -> Iterable[Path]:
    seen: set[str] = set()
    for base in canonical_roots(root):
        iterator = [base] if base.is_file() else base.rglob("*")
        for path in iterator:
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
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


def parse_python(text: str, path: Path) -> tuple[ast.AST | None, str | None]:
    try:
        return ast.parse(text, filename=str(path)), None
    except SyntaxError as exc:
        return None, f"SyntaxError:{exc.lineno}:{exc.msg}"


def identity_tokens(path: Path, tree: ast.AST | None) -> set[str]:
    tokens = {normalize(path.stem)}
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                tokens.add(normalize(node.name))
    return tokens


def component_affiliation(path: Path, tree: ast.AST | None, text_lower: str) -> list[str]:
    tokens = identity_tokens(path, tree)
    result: list[str] = []
    for component, aliases in ALIASES.items():
        identity_match = any(normalize(alias) and any(normalize(alias) in token for token in tokens) for alias in aliases)
        if identity_match:
            result.append(component)
            continue
        if component in TEAM_COMPONENTS:
            plain = component.removesuffix("Team").lower()
            if plain in text_lower and ("team" in text_lower or "lane" in text_lower) and path.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}:
                result.append(component)
    return sorted(set(result))


def ast_authority(tree: ast.AST | None) -> tuple[list[str], list[str]]:
    order_calls: list[str] = []
    sensitive_access: list[str] = []
    if tree is None:
        return order_calls, sensitive_access
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_name(node.func)
        leaf = name.rsplit(".", 1)[-1].lower()
        if leaf in ORDER_CALLS:
            order_calls.append(f"{name}:{getattr(node, 'lineno', 0)}")
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and SENSITIVE_KEY.search(arg.value):
                sensitive_access.append(f"{name}:{arg.value}:{getattr(node, 'lineno', 0)}")
    return sorted(set(order_calls)), sorted(set(sensitive_access))


def git_metadata(root: Path, path: Path) -> dict[str, Any]:
    try:
        relative = str(path.relative_to(root))
    except ValueError:
        return {"tracked": False, "last_commit": None, "last_commit_at": None}
    command = ["git", "-C", str(root), "log", "-1", "--format=%H|%cI", "--", relative]
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=5)
    value = result.stdout.strip()
    if not value or "|" not in value:
        return {"tracked": False, "last_commit": None, "last_commit_at": None}
    commit, commit_at = value.split("|", 1)
    return {"tracked": True, "last_commit": commit, "last_commit_at": commit_at}


def detect_capabilities(text_lower: str, direct_order_calls: list[str], sensitive_access: list[str], test_count: int) -> dict[str, bool]:
    values: dict[str, bool] = {}
    for capability, patterns in CAPABILITY_PATTERNS.items():
        if capability == "no_private_execution_authority":
            values[capability] = not direct_order_calls and not sensitive_access
        elif capability == "unit_contract_failure_tests":
            values[capability] = test_count > 0
        else:
            values[capability] = any(pattern in text_lower for pattern in patterns)
    return values


def score_candidate(path: Path, component: str, tree: ast.AST | None, text_lower: str, capabilities: Mapping[str, bool], active_exec: bool) -> int:
    tokens = identity_tokens(path, tree)
    aliases = ALIASES[component]
    score = 0
    if any(normalize(alias) == token for alias in aliases for token in tokens if normalize(alias)):
        score += 40
    elif any(normalize(alias) in token for alias in aliases for token in tokens if normalize(alias)):
        score += 25
    if active_exec:
        score += 30
    score += min(20, 2 * sum(bool(value) for value in capabilities.values()))
    role_hits = sum(pattern in text_lower for pattern in ROLE_PATTERNS[component])
    score += min(15, 3 * role_hits)
    if support_surface(path):
        score -= 50
    return score


def load_units(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, [])
    return payload if isinstance(payload, list) else []


def unit_exec_paths(units: list[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    path_pattern = re.compile(r"(/[A-Za-z0-9_./-]+\.(?:py|sh))")
    for unit in units:
        if str(unit.get("ActiveState") or "") != "active":
            continue
        for match in path_pattern.findall(str(unit.get("ExecStart") or "")):
            values.add(match)
    return values


def tests_for_component(files: list[Path], component: str) -> list[str]:
    needles = [alias.lower().replace("_", "") for alias in ALIASES[component]]
    matches: list[str] = []
    for path in files:
        if not support_surface(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower().replace("_", "")
        except OSError:
            continue
        if any(needle and needle in text for needle in needles):
            matches.append(str(path))
    return sorted(set(matches))[:20]


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    ssot = read_json(args.ssot, {})
    units = load_units(args.units)
    active_exec_paths = unit_exec_paths(units)
    all_files = list(iter_files(args.root))
    excluded: list[dict[str, str]] = []
    semantic_files: list[Path] = []
    for path in all_files:
        bad, reason = contaminated(path)
        if bad:
            excluded.append({"path": str(path), "reason": str(reason)})
        else:
            semantic_files.append(path)

    candidate_map: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in semantic_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text_lower = text.lower()
        tree, parse_error = parse_python(text, path) if path.suffix.lower() == ".py" else (None, None)
        components = component_affiliation(path, tree, text_lower)
        if not components:
            continue
        order_calls, sensitive_access = ast_authority(tree)
        for component in components:
            tests = tests_for_component(semantic_files, component)
            capabilities = detect_capabilities(text_lower, order_calls, sensitive_access, len(tests))
            role_hits = [pattern for pattern in ROLE_PATTERNS[component] if pattern in text_lower]
            lineage_fields = [field for field in ssot.get("required_lineage_fields", []) if str(field).lower() in text_lower]
            active_exec = str(path) in active_exec_paths
            candidate_map[component].append({
                "path": str(path),
                "sha256": sha256(path),
                "support_surface": support_surface(path),
                "active_exec": active_exec,
                "parse_error": parse_error,
                "direct_order_calls": order_calls,
                "sensitive_credential_access": sensitive_access,
                "capabilities": capabilities,
                "role_signal_hits": role_hits,
                "lineage_fields_present": lineage_fields,
                "test_paths": tests,
                "git": git_metadata(args.root, path),
                "score": score_candidate(path, component, tree, text_lower, capabilities, active_exec),
            })

    components_result: dict[str, Any] = {}
    s0_ready_count = 0
    critical_gap_total = 0
    for component in ssot.get("scope", []):
        candidates = sorted(candidate_map.get(component, []), key=lambda row: (-int(row["score"]), str(row["path"])))
        runtime_candidates = [row for row in candidates if not row["support_surface"]]
        top = runtime_candidates[0] if runtime_candidates else None
        second_score = int(runtime_candidates[1]["score"]) if len(runtime_candidates) > 1 else -999
        unique_owner = bool(top and int(top["score"]) >= 35 and int(top["score"]) - second_score >= 10)
        capability_missing = [] if not top else [name for name, value in top["capabilities"].items() if not value]
        lineage_required = list(ssot.get("required_lineage_fields", []))
        lineage_missing = lineage_required if not top else [field for field in lineage_required if field not in top["lineage_fields_present"]]
        role_required = list(ROLE_PATTERNS.get(component, ()))
        role_missing = role_required if not top else [field for field in role_required if field not in top["role_signal_hits"]]
        critical_gaps: list[str] = []
        if not top:
            critical_gaps.append("CANONICAL_OWNER_NOT_FOUND")
        if top and (top["direct_order_calls"] or top["sensitive_credential_access"]):
            critical_gaps.append("PRIVATE_EXECUTION_AUTHORITY_PRESENT")
        if not unique_owner:
            critical_gaps.append("UNIQUE_CANONICAL_OWNER_UNPROVEN")
        if lineage_missing:
            critical_gaps.append("STRATEGY_METHOD_SKILL_LINEAGE_INCOMPLETE")
        if capability_missing:
            critical_gaps.append("CONTRACT_CAPABILITIES_INCOMPLETE")
        if role_missing:
            critical_gaps.append("ROLE_CONTRACT_INCOMPLETE")
        s0_ready = not critical_gaps
        if s0_ready:
            s0_ready_count += 1
        critical_gap_total += len(critical_gaps)
        components_result[component] = {
            "s_grade_claim": "UNPROVEN",
            "s0_structure_ready": s0_ready,
            "unique_owner_confirmed": unique_owner,
            "owner_candidate": top,
            "candidate_count": len(runtime_candidates),
            "top_candidates": runtime_candidates[:5],
            "missing_capabilities": capability_missing,
            "missing_lineage_fields": lineage_missing,
            "missing_role_signals": role_missing,
            "critical_gaps": critical_gaps,
            "latest_update_required": not s0_ready,
            "performance_efficacy": "UNPROVEN_FORWARD_DATA_REQUIRED",
        }

    scope_count = len(ssot.get("scope", []))
    all_s0 = scope_count > 0 and s0_ready_count == scope_count
    verdict = "TEAM_ADVISOR_S0_STRUCTURE_READY_FORWARD_GATES_REQUIRED" if all_s0 else "TEAM_ADVISOR_SGRADE_UPDATE_REQUIRED"
    return {
        "schema": "q4r3_team_advisor_sgrade_readiness_audit_v1",
        "generated_at": now_iso(),
        "state": "PASS" if all_s0 else "HOLD",
        "verdict": verdict,
        "current_s_grade_claim_allowed": False,
        "current_s_grade_reason": "S-grade cannot be inferred from file presence, ALIMI display, or a running adapter; S0 structure plus S1/S2/S3 forward gates are required.",
        "scope_component_count": scope_count,
        "s0_ready_component_count": s0_ready_count,
        "s0_not_ready_component_count": max(0, scope_count - s0_ready_count),
        "critical_gap_count": critical_gap_total,
        "components": components_result,
        "compatibility": {
            "strategy_method_skill_team_advisor_full_lineage_required": True,
            "new_integrated_epoch_required_after_s0_and_lineage_repair": True,
            "existing_raw_baseline_preserved": True,
            "existing_raw_baseline_usable_for_team_advisor_performance": False,
        },
        "scan": {
            "semantic_file_count": len(semantic_files),
            "excluded_contamination_count": len(excluded),
            "excluded_contamination_sample": excluded[:100],
            "active_exec_path_count": len(active_exec_paths),
            "active_exec_paths": sorted(active_exec_paths),
        },
        "policy": ssot.get("non_negotiable_policy", {}),
        "next_route": "PATCH_COMPONENT_CONTRACTS_IN_DEPENDENCY_ORDER_LMOS_THEN_TEAMS_THEN_ADVISORS",
        "action": "hold",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ssot", type=Path, required=True)
    parser.add_argument("--units", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = analyze(args)
    atomic_json(args.output, result)
    print(json.dumps({
        "state": result["state"],
        "verdict": result["verdict"],
        "s0_ready": result["s0_ready_component_count"],
        "s0_not_ready": result["s0_not_ready_component_count"],
        "critical_gaps": result["critical_gap_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
