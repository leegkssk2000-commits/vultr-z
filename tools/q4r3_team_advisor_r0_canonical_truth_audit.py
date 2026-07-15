#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shlex
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

UTC = timezone.utc
TEXT_SUFFIXES = {
    ".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".service", ".timer", ".md", ".txt",
}
INTERPRETER_NAMES = {"python", "python3", "bash", "sh", "env"}
DIRECT_ORDER_CALLS = {
    "create_order", "place_order", "submit_order", "send_order", "cancel_order",
    "private_api", "private_endpoint",
}
SENSITIVE_KEY = re.compile(
    r"(?:BINGX|BITGET|KRAKEN|MEXC|BYBIT|BINANCE|OKX).*(?:API[_-]?KEY|SECRET|PASSPHRASE|PRIVATE[_-]?KEY)",
    re.I,
)
CONTAMINATION_DIRS = {
    ".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", "__pycache__",
    "backup", "backups", "archive", "archives", "rollback", "restore", "quarantine", "trash",
    "release_freeze", "release-freeze", "frozen", "old_copies",
}
BACKUP_FILE = re.compile(
    r"(?:\.bak(?:\.|$)|\.old(?:\.|$)|\.orig(?:\.|$)|(?:^|[_-])backup(?:[_-]|\d|$)|"
    r"(?:^|[_-])rollback(?:[_-]|\d|$)|(?:^|[_-])archive(?:[_-]|\d|$))",
    re.I,
)
SUPPORT_DIRS = {"test", "tests", "script", "scripts"}
SUPPORT_PREFIXES = (
    "test_", "verify_", "apply_", "install_", "bootstrap_", "run_", "audit_", "probe_", "smoke_", "check_",
)
UI_MARKERS = ("frontend", "viewer", "drawer", "footer", "panel", "card", "template", "static", "ui")
CONTRACT_MARKERS = ("contract", "schema", "protocol", "envelope")
CONFIG_MARKERS = ("config", "policy", "registry", "manifest", "ssot")
API_MARKERS = ("api", "router", "endpoint")
ADAPTER_MARKERS = ("adapter", "bridge", "connector", "client")

ZBOT_SURFACES: dict[str, tuple[str, ...]] = {
    "provider_router": ("provider_router", "provider route", "route_provider", "dual_blind", "single_provider"),
    "openai_adapter": ("openai", "chatgpt", "responses.create", "chat.completions"),
    "gemini_adapter": ("gemini", "google.generativeai", "google.genai", "generate_content"),
    "model_alias_registry": ("model_alias", "model_registry", "fast_advisor", "deep_challenger"),
    "prompt_version_registry": ("prompt_version", "prompt_registry", "system_prompt_version"),
    "structured_input_schema": ("input_schema", "request_schema", "json_schema", "pydantic"),
    "structured_output_schema": ("output_schema", "response_schema", "structured_output", "response_format"),
    "call_gate_policy": ("bypass", "single", "dual_blind", "offline_batch", "call_gate"),
    "budget_policy": ("daily_budget", "monthly_budget", "max_cost", "cost_usd", "budget_guard"),
    "fallback_policy": ("fallback", "retry", "provider_failover"),
    "circuit_breaker_policy": ("circuit_breaker", "error_rate", "latency_p95", "schema_failure"),
    "evidence_sink": ("zlice", "evidence_sink", "input_hash", "output_hash", "prompt_version"),
    "ablation_policy": ("no_zbot", "openai_only", "gemini_only", "dual_blind", "ablation"),
}
ZICO_SURFACES: dict[str, tuple[str, ...]] = {
    "state_machine": ("state_machine", "lifecycle", "candidate_created", "closed_verified"),
    "idempotency": ("idempotency", "idempotency_key", "dedup"),
    "causal_ordering": ("causal", "parent_event", "ordering", "transition"),
    "permission_gate": ("permission", "capability", "authority", "order_authority"),
    "owner_lease": ("owner_lease", "lease", "one_position_one_owner", "position_owner"),
    "timeout_policy": ("timeout", "deadline", "expired"),
    "compensation_policy": ("compensation", "rollback", "reconcile"),
    "invariant_engine": ("invariant", "fail_closed", "no_order_without_authority"),
    "replay": ("replay", "event_sourced", "event_store"),
}
LICO_SURFACES: dict[str, tuple[str, ...]] = {
    "source_registry": ("source_registry", "sources", "source_id"),
    "freshness_policy": ("freshness", "stale", "age_ms", "data_age"),
    "source_consensus": ("source_consensus", "consensus", "source_confidence"),
    "execution_cost_model": ("slippage", "market_impact", "execution_cost", "spread"),
    "venue_health": ("venue_health", "bingx", "latency", "reject_rate"),
    "stress_scenarios": ("stress_scenario", "stress", "liquidation", "funding"),
    "team_context": ("team_context", "alpha", "beta", "gamma", "delta"),
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def atomic_json(path: Path, value: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


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
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:
        return subprocess.CompletedProcess(command, 125, "", f"{type(exc).__name__}:{exc}")


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def canonical_component(value: str) -> str:
    normalized = normalize(value)
    mapping = {
        "lbot": "LBot", "mbot": "MBot", "obot": "OBot", "sbot": "SBot",
        "alphateam": "AlphaTeam", "betateam": "BetaTeam", "gammateam": "GammaTeam", "deltateam": "DeltaTeam",
        "zbot": "ZBot", "zico": "Zico", "lico": "Lico", "zlice": "Zlice",
    }
    return mapping.get(normalized, value)


def path_is_contaminated(path: Path) -> tuple[bool, str | None]:
    for part in path.parts:
        if part.lower() in CONTAMINATION_DIRS:
            return True, f"directory:{part.lower()}"
    if BACKUP_FILE.search(path.name):
        return True, "backup_filename"
    return False, None


def support_surface(path: Path) -> bool:
    return any(part.lower() in SUPPORT_DIRS for part in path.parts) or path.stem.lower().startswith(SUPPORT_PREFIXES)


def file_kind(path: Path) -> str:
    lower = str(path).lower()
    stem = path.stem.lower()
    if support_surface(path):
        return "test_support"
    if path.suffix in {".service", ".timer"} or ".wants" in lower:
        return "service_wrapper"
    if any(marker in lower for marker in UI_MARKERS):
        return "ui_consumer"
    if any(marker in stem for marker in CONTRACT_MARKERS):
        return "contract"
    if any(marker in stem for marker in CONFIG_MARKERS) or path.suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}:
        return "configuration"
    if any(marker in stem for marker in API_MARKERS):
        return "api_surface"
    if any(marker in stem for marker in ADAPTER_MARKERS):
        return "adapter"
    if path.name == "__init__.py" or path.is_dir():
        return "package_core"
    return "runtime_core"


def symlink_chain(path: Path, max_depth: int = 12) -> tuple[list[str], str | None]:
    chain: list[str] = []
    current = path
    seen: set[str] = set()
    for _ in range(max_depth):
        key = str(current)
        if key in seen:
            return chain, "SYMLINK_LOOP"
        seen.add(key)
        if not current.is_symlink():
            return chain, None
        try:
            target = os.readlink(current)
            chain.append(f"{current}->{target}")
            current = (current.parent / target).resolve(strict=False) if not os.path.isabs(target) else Path(target)
        except OSError as exc:
            return chain, f"SYMLINK_READ_ERROR:{type(exc).__name__}"
    return chain, "SYMLINK_DEPTH_EXCEEDED"


def resolve_path(path: Path) -> str:
    try:
        return str(path.resolve(strict=False))
    except OSError:
        return str(path)


def parse_exec_paths(exec_start: str) -> list[str]:
    # systemctl show may return a structured string. Absolute file paths remain extractable.
    values = re.findall(r"(/[A-Za-z0-9_+.,@%:=/\-]+)", exec_start or "")
    result: list[str] = []
    for value in values:
        value = value.rstrip(";},]")
        if value not in result:
            result.append(value)
    return result


def choose_script_paths(paths: Sequence[str]) -> list[str]:
    values: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.suffix.lower() in {".py", ".sh"}:
            values.append(resolve_path(path))
    return sorted(set(values))


def read_small_text(path: Path, limit: int = 2 * 1024 * 1024) -> str:
    try:
        if not path.is_file() or path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def wrapper_references(path: Path) -> list[str]:
    text = read_small_text(path)
    if not text:
        return []
    values: set[str] = set()
    for match in re.findall(r"(/[A-Za-z0-9_+.,@%:=/\-]+\.(?:py|sh))", text):
        values.add(resolve_path(Path(match)))
    if path.suffix == ".py":
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = dotted_name(node.func).lower()
                if name.endswith(("runpy.run_path", "subprocess.run", "subprocess.call", "subprocess.popen", "os.execv", "os.execve")):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("/"):
                            values.add(resolve_path(Path(arg.value)))
    values.discard(resolve_path(path))
    return sorted(values)


def resolve_wrapper_chain(path: Path, max_depth: int = 6) -> tuple[list[str], list[str]]:
    chain: list[str] = [resolve_path(path)]
    unresolved: list[str] = []
    frontier = [Path(resolve_path(path))]
    seen = set(chain)
    for _ in range(max_depth):
        next_frontier: list[Path] = []
        for current in frontier:
            for reference in wrapper_references(current):
                if reference in seen:
                    continue
                seen.add(reference)
                chain.append(reference)
                candidate = Path(reference)
                if candidate.exists():
                    next_frontier.append(candidate)
                else:
                    unresolved.append(reference)
        if not next_frontier:
            break
        frontier = next_frontier
    return chain, sorted(set(unresolved))


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def authority_evidence(path: Path, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    order_calls: list[dict[str, Any]] = []
    credential_access: list[dict[str, Any]] = []
    if path.suffix == ".py":
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = dotted_name(node.func)
                leaf = name.rsplit(".", 1)[-1].lower()
                if leaf in DIRECT_ORDER_CALLS:
                    order_calls.append({"call": name, "line": getattr(node, "lineno", 0)})
                for arg in list(node.args) + [keyword.value for keyword in node.keywords]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and SENSITIVE_KEY.search(arg.value):
                        credential_access.append({
                            "call": name,
                            "key_name": arg.value,
                            "line": getattr(node, "lineno", 0),
                        })
    return order_calls, credential_access


def contract_version(text: str) -> str | None:
    patterns = (
        r"(?:contract_version|schema_version|version)\s*[=:]\s*[\"']([^\"']+)[\"']",
        r'"(?:contract_version|schema_version|version)"\s*:\s*"([^"]+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)[:100]
    return None


def git_metadata(root: Path, path: Path) -> dict[str, Any]:
    try:
        relative = str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return {"tracked": False, "commit": None, "commit_at": None, "relative_path": None}
    tracked = run(["git", "-C", str(root), "ls-files", "--error-unmatch", relative], timeout=8).returncode == 0
    history = run(["git", "-C", str(root), "log", "-1", "--format=%H|%cI", "--", relative], timeout=8)
    value = history.stdout.strip()
    commit = commit_at = None
    if "|" in value:
        commit, commit_at = value.split("|", 1)
    return {"tracked": tracked, "commit": commit, "commit_at": commit_at, "relative_path": relative}


def load_aliases(path: Path) -> dict[str, Any]:
    payload = read_json(path, {})
    return payload if isinstance(payload, dict) else {}


def component_from_unit(unit: str, aliases: Mapping[str, Any]) -> list[str]:
    normalized = normalize(unit)
    result: list[str] = []
    for component, config in aliases.get("components", {}).items():
        for token in config.get("unit_tokens", []):
            if normalize(str(token)) in normalized:
                result.append(canonical_component(component))
                break
    return sorted(set(result))


def exact_path_identity(path: Path, component: str, aliases: Mapping[str, Any]) -> bool:
    config = aliases.get("components", {}).get(component, {})
    tokens = [normalize(str(value)) for value in config.get("path_tokens", [])]
    identities = {normalize(path.stem)} | {normalize(part) for part in path.parts[-4:]}
    return any(token and any(token == identity or identity.startswith(token) for identity in identities) for token in tokens)


def structured_team_identity(text: str, component: str, aliases: Mapping[str, Any]) -> bool:
    if not component.endswith("Team"):
        return False
    lowered = text.lower()
    markers = aliases.get("components", {}).get(component, {}).get("structured_markers", [])
    assignment_markers = aliases.get("team_assignment_markers", [])
    return any(str(marker).lower() in lowered for marker in markers) and any(str(marker).lower() in lowered for marker in assignment_markers)


def surface_hits(text_lower: str, surfaces: Mapping[str, Sequence[str]]) -> dict[str, bool]:
    return {name: any(pattern.lower() in text_lower for pattern in patterns) for name, patterns in surfaces.items()}


def relevant_unit_names(aliases: Mapping[str, Any]) -> list[str]:
    listing = run(["systemctl", "list-unit-files", "--no-legend", "--no-pager"], timeout=30)
    names: set[str] = set()
    for line in listing.stdout.splitlines():
        fields = line.split()
        if not fields:
            continue
        unit = fields[0]
        if component_from_unit(unit, aliases):
            names.add(unit)
    active = run(["systemctl", "list-units", "--all", "--no-legend", "--no-pager"], timeout=30)
    for line in active.stdout.splitlines():
        fields = line.split()
        if not fields:
            continue
        unit = fields[0]
        if component_from_unit(unit, aliases):
            names.add(unit)
    return sorted(names)


def unit_record(unit: str, aliases: Mapping[str, Any]) -> dict[str, Any]:
    properties = [
        "Id", "LoadState", "UnitFileState", "ActiveState", "SubState", "MainPID", "Result",
        "FragmentPath", "ExecStart", "WorkingDirectory", "User", "Group",
    ]
    command = ["systemctl", "show", unit, "--no-pager"]
    for prop in properties:
        command.extend(["-p", prop])
    response = run(command, timeout=15)
    values: dict[str, str] = {}
    for line in response.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    fragment = Path(values.get("FragmentPath") or "") if values.get("FragmentPath") else None
    fragment_chain: list[str] = []
    fragment_error = None
    if fragment:
        fragment_chain, fragment_error = symlink_chain(fragment)
    exec_paths = parse_exec_paths(values.get("ExecStart", ""))
    script_paths = choose_script_paths(exec_paths)
    wrapper_chains: list[dict[str, Any]] = []
    unresolved_wrappers: list[str] = []
    for script in script_paths:
        chain, unresolved = resolve_wrapper_chain(Path(script))
        wrapper_chains.append({"entry": script, "chain": chain})
        unresolved_wrappers.extend(unresolved)
    return {
        "unit": unit,
        "components": component_from_unit(unit, aliases),
        "load_state": values.get("LoadState"),
        "unit_file_state": values.get("UnitFileState"),
        "active_state": values.get("ActiveState"),
        "sub_state": values.get("SubState"),
        "main_pid": values.get("MainPID"),
        "result": values.get("Result"),
        "fragment_path": values.get("FragmentPath"),
        "fragment_resolved": resolve_path(fragment) if fragment else None,
        "symlink_chain": fragment_chain,
        "symlink_error": fragment_error,
        "exec_start": redact(values.get("ExecStart", "")),
        "exec_paths": exec_paths,
        "resolved_script_paths": script_paths,
        "wrapper_chains": wrapper_chains,
        "unresolved_wrappers": sorted(set(unresolved_wrappers)),
        "working_directory": values.get("WorkingDirectory"),
        "user": values.get("User"),
        "group": values.get("Group"),
    }


def redact(value: str) -> str:
    value = re.sub(r"(?i)(api[_-]?key|secret|token|password|passphrase)=([^ ;]+)", r"\1=<redacted>", value)
    value = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "<redacted-key>", value)
    return value


def canonical_roots(root: Path, unit_records: Sequence[Mapping[str, Any]]) -> list[Path]:
    roots = [
        root / "backend", root / "tools", root / "services", root / "systemd", root / "config",
        root / "data", root / "skills", Path("/etc/systemd/system"), Path("/usr/local/bin"),
    ]
    for record in unit_records:
        for script in record.get("resolved_script_paths", []):
            path = Path(script)
            roots.append(path)
            roots.append(path.parent)
        for wrapper in record.get("wrapper_chains", []):
            for item in wrapper.get("chain", []):
                path = Path(item)
                roots.append(path)
                roots.append(path.parent)
    result: list[Path] = []
    seen: set[str] = set()
    for path in roots:
        if not path.exists():
            continue
        key = resolve_path(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def iter_text_files(roots: Sequence[Path]) -> Iterable[Path]:
    seen: set[str] = set()
    for root in roots:
        iterator = [root] if root.is_file() else root.rglob("*")
        for path in iterator:
            try:
                if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            key = resolve_path(path)
            if key in seen:
                continue
            seen.add(key)
            yield path


def active_bindings(unit_records: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    result: defaultdict[str, list[str]] = defaultdict(list)
    for record in unit_records:
        if record.get("active_state") != "active":
            continue
        for script in record.get("resolved_script_paths", []):
            result[resolve_path(Path(script))].append(str(record.get("unit")))
        for wrapper in record.get("wrapper_chains", []):
            for item in wrapper.get("chain", []):
                result[resolve_path(Path(item))].append(str(record.get("unit")))
    return {path: sorted(set(units)) for path, units in result.items()}


def candidate_components(
    path: Path,
    text: str,
    aliases: Mapping[str, Any],
    unit_component_map: Mapping[str, Sequence[str]],
) -> tuple[list[str], dict[str, list[str]]]:
    result: set[str] = set()
    evidence: defaultdict[str, list[str]] = defaultdict(list)
    resolved = resolve_path(path)
    for component in aliases.get("components", {}):
        canonical = canonical_component(component)
        if exact_path_identity(path, component, aliases):
            result.add(canonical)
            evidence[canonical].append("exact_path_identity")
        if structured_team_identity(text, component, aliases):
            result.add(canonical)
            evidence[canonical].append("structured_team_assignment")
    for component in unit_component_map.get(resolved, []):
        result.add(component)
        evidence[component].append("active_unit_binding")
    return sorted(result), {key: sorted(set(value)) for key, value in evidence.items()}


def candidate_score(candidate: Mapping[str, Any]) -> int:
    score = 0
    evidence = set(candidate.get("identity_evidence", []))
    if "active_unit_binding" in evidence:
        score += 60
    if "exact_path_identity" in evidence:
        score += 40
    if "structured_team_assignment" in evidence:
        score += 35
    if candidate.get("git", {}).get("tracked"):
        score += 10
    if candidate.get("contract_version"):
        score += 10
    kind = candidate.get("owner_kind")
    if kind in {"runtime_core", "package_core"}:
        score += 15
    elif kind in {"adapter", "api_surface"}:
        score += 5
    if candidate.get("direct_order_calls") or candidate.get("sensitive_credential_access"):
        score -= 80
    if kind in {"test_support", "ui_consumer", "service_wrapper"}:
        score -= 50
    return score


def classification(candidate: Mapping[str, Any]) -> tuple[str, str]:
    kind = candidate.get("owner_kind")
    active = "active_unit_binding" in set(candidate.get("identity_evidence", []))
    unsafe = bool(candidate.get("direct_order_calls") or candidate.get("sensitive_credential_access"))
    if unsafe:
        return "QUARANTINE", "Team/Advisor surface exposes direct execution or sensitive credential access"
    if kind in {"test_support", "ui_consumer", "service_wrapper"}:
        return "ARCHIVE", f"{kind} cannot be canonical implementation owner"
    if active and kind in {"runtime_core", "package_core", "adapter"}:
        return "KEEP", "active runtime-bound first-party implementation"
    if kind in {"contract", "configuration", "api_surface", "adapter"}:
        return "ABSORB", f"useful {kind} surface to retain under canonical package"
    return "RESERVE", "inactive implementation candidate pending owner decision"


def owner_proof(candidate: Mapping[str, Any]) -> bool:
    evidence = set(candidate.get("identity_evidence", []))
    kind = candidate.get("owner_kind")
    if candidate.get("direct_order_calls") or candidate.get("sensitive_credential_access"):
        return False
    if kind in {"test_support", "ui_consumer", "service_wrapper"}:
        return False
    if "active_unit_binding" in evidence and ("exact_path_identity" in evidence or kind in {"runtime_core", "package_core", "adapter"}):
        return True
    if "exact_path_identity" in evidence and candidate.get("git", {}).get("tracked") and candidate.get("contract_version"):
        return True
    if "structured_team_assignment" in evidence and candidate.get("git", {}).get("tracked") and candidate.get("contract_version"):
        return True
    return False


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    ssot = read_json(args.ssot, {})
    aliases = load_aliases(args.aliases)
    scope = [canonical_component(str(value)) for value in ssot.get("scope", [])]

    unit_names = relevant_unit_names(aliases)
    units = [unit_record(unit, aliases) for unit in unit_names]
    bindings = active_bindings(units)
    unit_component_map: defaultdict[str, list[str]] = defaultdict(list)
    for record in units:
        if record.get("active_state") != "active":
            continue
        components = [canonical_component(value) for value in record.get("components", [])]
        for script in record.get("resolved_script_paths", []):
            unit_component_map[resolve_path(Path(script))].extend(components)
        for wrapper in record.get("wrapper_chains", []):
            for item in wrapper.get("chain", []):
                unit_component_map[resolve_path(Path(item))].extend(components)

    roots = canonical_roots(args.root, units)
    files = list(iter_text_files(roots))
    excluded: list[dict[str, str]] = []
    candidates_by_component: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

    for path in files:
        contaminated, reason = path_is_contaminated(path)
        if contaminated:
            excluded.append({"path": resolve_path(path), "reason": str(reason)})
            continue
        text = read_small_text(path)
        if not text:
            continue
        components, identity = candidate_components(path, text, aliases, unit_component_map)
        if not components:
            continue
        order_calls, credentials = authority_evidence(path, text)
        lower = text.lower()
        base = {
            "path": resolve_path(path),
            "owner_kind": file_kind(path),
            "sha256": sha256(path),
            "contract_version": contract_version(text),
            "active_units": bindings.get(resolve_path(path), []),
            "direct_order_calls": order_calls,
            "sensitive_credential_access": credentials,
            "git": git_metadata(args.root, path),
            "zbot_surfaces": surface_hits(lower, ZBOT_SURFACES),
            "zico_surfaces": surface_hits(lower, ZICO_SURFACES),
            "lico_surfaces": surface_hits(lower, LICO_SURFACES),
        }
        for component in components:
            candidate = dict(base)
            candidate["component"] = component
            candidate["identity_evidence"] = identity.get(component, [])
            candidate["score"] = candidate_score(candidate)
            recommendation, recommendation_reason = classification(candidate)
            candidate["classification_recommendation"] = recommendation
            candidate["classification_reason"] = recommendation_reason
            candidates_by_component[component].append(candidate)

    owner_matrix: dict[str, Any] = {}
    duplicate_owners: list[dict[str, Any]] = []
    fix_queue: list[dict[str, Any]] = []
    canonical_owner_count = 0

    for component in scope:
        candidates = sorted(candidates_by_component.get(component, []), key=lambda item: (-int(item["score"]), item["path"]))
        proven = [candidate for candidate in candidates if owner_proof(candidate)]
        canonical = proven[0] if len(proven) == 1 else None
        if canonical:
            canonical_owner_count += 1
        if len(proven) > 1:
            duplicate_owners.append({"component": component, "paths": [value["path"] for value in proven]})
        unresolved: list[str] = []
        if not candidates:
            unresolved.append("NO_CANDIDATE_FOUND")
        if not proven:
            unresolved.append("CANONICAL_OWNER_UNPROVEN")
        if len(proven) > 1:
            unresolved.append("DUPLICATE_PROVEN_OWNERS")
        if canonical and canonical.get("contract_version") is None:
            unresolved.append("CONTRACT_VERSION_MISSING")
        if canonical and not canonical.get("git", {}).get("tracked"):
            unresolved.append("CANONICAL_OWNER_NOT_GIT_TRACKED")
        owner_matrix[component] = {
            "state": "PROVEN" if canonical and not unresolved else "UNRESOLVED",
            "canonical_owner": canonical,
            "proven_owner_count": len(proven),
            "candidate_count": len(candidates),
            "top_candidates": candidates[:15],
            "unresolved": unresolved,
        }
        for code in unresolved:
            fix_queue.append({"component": component, "code": code, "action": "hold"})

    relevant_active_scripts: set[str] = set()
    for record in units:
        if record.get("active_state") == "active":
            relevant_active_scripts.update(record.get("resolved_script_paths", []))
    mapped_active_scripts = {
        path for path in relevant_active_scripts if any(path == candidate.get("path") for values in candidates_by_component.values() for candidate in values)
    }
    unclassified_runtime = sorted(relevant_active_scripts - mapped_active_scripts)
    mapping_pct = 100.0 if not relevant_active_scripts else round(100.0 * len(mapped_active_scripts) / len(relevant_active_scripts), 4)

    unresolved_symlinks = [
        {"unit": record["unit"], "error": record["symlink_error"]}
        for record in units if record.get("symlink_error")
    ]
    unresolved_wrappers = [
        {"unit": record["unit"], "paths": record.get("unresolved_wrappers", [])}
        for record in units if record.get("unresolved_wrappers")
    ]

    def aggregate_surface(component: str, key: str, required: Sequence[str]) -> dict[str, Any]:
        candidates = candidates_by_component.get(component, [])
        found: dict[str, list[str]] = {surface: [] for surface in required}
        for candidate in candidates:
            for surface, present in candidate.get(key, {}).items():
                if present and surface in found:
                    found[surface].append(candidate["path"])
        found = {surface: sorted(set(paths)) for surface, paths in found.items()}
        missing = [surface for surface, paths in found.items() if not paths]
        return {"found": found, "missing": missing, "coverage_pct": round(100.0 * (len(required) - len(missing)) / max(1, len(required)), 4)}

    zbot_policy = aggregate_surface("ZBot", "zbot_surfaces", list(ssot.get("zbot_required_policy_surfaces", [])))
    zico_policy = aggregate_surface("Zico", "zico_surfaces", list(ssot.get("zico_required_surfaces", [])))
    lico_policy = aggregate_surface("Lico", "lico_surfaces", list(ssot.get("lico_required_surfaces", [])))

    canonical_name_violations: list[str] = []
    for component in owner_matrix:
        if component in {"ZICO", "LiCo", "LICO"}:
            canonical_name_violations.append(component)

    exit_gate = {
        "canonical_owner_count": canonical_owner_count,
        "required_canonical_owner_count": len(scope),
        "duplicate_owner_count": len(duplicate_owners),
        "unclassified_runtime_candidate_count": len(unclassified_runtime),
        "active_exec_mapping_pct": mapping_pct,
        "unresolved_symlink_count": len(unresolved_symlinks),
        "unresolved_wrapper_count": len(unresolved_wrappers),
        "canonical_name_violation_count": len(canonical_name_violations),
    }
    expected = ssot.get("exit_gate", {})
    pass_gate = (
        canonical_owner_count == int(expected.get("canonical_owner_count", len(scope)))
        and len(duplicate_owners) == int(expected.get("duplicate_owner_count", 0))
        and len(unclassified_runtime) == int(expected.get("unclassified_runtime_candidate_count", 0))
        and mapping_pct >= float(expected.get("active_exec_mapping_pct", 100))
        and len(unresolved_symlinks) == int(expected.get("unresolved_symlink_count", 0))
        and len(unresolved_wrappers) == int(expected.get("unresolved_wrapper_count", 0))
        and len(canonical_name_violations) == int(expected.get("canonical_name_violation_count", 0))
    )
    state = "PASS" if pass_gate else "HOLD"
    verdict = "R0_CANONICAL_TRUTH_LOCK_PASS" if pass_gate else "R0_CANONICAL_TRUTH_UNRESOLVED"

    result = {
        "schema": "q4r3_team_advisor_r0_canonical_truth_audit_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "canonical_name_policy": {"Zico": ["ZICO", "zico"], "Lico": ["LiCo", "LICO", "lico"]},
        "scope": scope,
        "exit_gate": exit_gate,
        "owner_matrix": owner_matrix,
        "duplicate_owners": duplicate_owners,
        "runtime": {
            "relevant_unit_count": len(units),
            "units": units,
            "relevant_active_script_count": len(relevant_active_scripts),
            "mapped_active_scripts": sorted(mapped_active_scripts),
            "unclassified_runtime_candidates": unclassified_runtime,
            "unresolved_symlinks": unresolved_symlinks,
            "unresolved_wrappers": unresolved_wrappers,
        },
        "policy_surface_coverage": {
            "ZBot": zbot_policy,
            "Zico": zico_policy,
            "Lico": lico_policy,
        },
        "scan": {
            "roots": [resolve_path(path) for path in roots],
            "text_file_count": len(files),
            "excluded_contamination_count": len(excluded),
            "excluded_contamination_reason_counts": count_reasons(excluded),
            "excluded_contamination_sample": excluded[:100],
        },
        "fix_queue": fix_queue,
        "authority": {
            "observer_only": True,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
            "historical_backfill_performed": False,
            "runtime_mutation_performed": False,
        },
        "action": "hold",
    }
    return result


def count_reasons(values: Sequence[Mapping[str, str]]) -> dict[str, int]:
    result: defaultdict[str, int] = defaultdict(int)
    for value in values:
        result[str(value.get("reason"))] += 1
    return dict(sorted(result.items()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ssot", type=Path, required=True)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--units-output", type=Path, required=True)
    parser.add_argument("--candidates-output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = analyze(args)
    atomic_json(args.output, result)
    atomic_json(args.units_output, result["runtime"]["units"])
    candidates = {
        component: value["top_candidates"] for component, value in result["owner_matrix"].items()
    }
    atomic_json(args.candidates_output, candidates)
    print(json.dumps({
        "state": result["state"],
        "verdict": result["verdict"],
        "canonical_owner_count": result["exit_gate"]["canonical_owner_count"],
        "duplicate_owner_count": result["exit_gate"]["duplicate_owner_count"],
        "active_exec_mapping_pct": result["exit_gate"]["active_exec_mapping_pct"],
        "fix_queue_count": len(result["fix_queue"]),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
