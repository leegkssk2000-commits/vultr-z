from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

EXPECTED_STRATEGY_COUNT = 25
EXPECTED_METHODS = (
    "scalp_first/revert",
    "scalp_first/continuation",
    "scalp_first/liquidity_reclaim",
    "intraday/breakout_probe",
    "intraday/rescue",
    "tactical_swing/continuation",
)
EXPECTED_SKILL_COUNT = 18
PROTECTED_RELATIVE_PATHS = (
    "backend/contracts/ZOS_SKILL_REGISTRY_v1.json",
    "backend/engine/skill_resolver.py",
    "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json",
    "backend/trade_methods/policy.py",
    "backend/trade_methods/profiles.py",
    "tools/q4r3_exact25_dedicated_shadow_producer.py",
    "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def protected_hashes(root: Path) -> dict[str, str | None]:
    return {rel: sha256_file(root / rel) for rel in PROTECTED_RELATIVE_PATHS}


def validate_owner_manifest(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("strategies")
    if not isinstance(rows, list):
        raise ValueError("OWNER_MANIFEST_STRATEGIES_REQUIRED")
    if len(rows) != EXPECTED_STRATEGY_COUNT:
        raise ValueError(f"OWNER_MANIFEST_NOT_EXACT25:{len(rows)}")
    ids: list[str] = []
    clean: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("OWNER_MANIFEST_ROW_INVALID")
        strategy_id = str(row.get("strategy_id") or "").strip()
        owner_path = str(row.get("owner_path") or "").strip()
        owner_module = str(row.get("owner_module") or "").strip()
        owner_sha256 = str(row.get("owner_sha256") or "").strip()
        if not all((strategy_id, owner_path, owner_module, owner_sha256)):
            raise ValueError(f"OWNER_MANIFEST_FIELDS_MISSING:{strategy_id or 'unknown'}")
        ids.append(strategy_id)
        clean.append(dict(row))
    if len(set(ids)) != EXPECTED_STRATEGY_COUNT:
        raise ValueError("OWNER_MANIFEST_DUPLICATE_STRATEGY")
    if manifest.get("dynamic_fallback_allowed") is not False:
        raise ValueError("OWNER_MANIFEST_DYNAMIC_FALLBACK_UNSAFE")
    return clean


def validate_candidate_registry(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    if registry.get("activation_allowed") is not False:
        raise ValueError("CANDIDATE_REGISTRY_ACTIVATION_UNSAFE")
    if registry.get("runtime_mutation_allowed") is not False:
        raise ValueError("CANDIDATE_REGISTRY_RUNTIME_MUTATION_UNSAFE")
    if registry.get("order_authority") != "blocked":
        raise ValueError("CANDIDATE_REGISTRY_ORDER_AUTHORITY_UNSAFE")
    if registry.get("execution_authority") != "none":
        raise ValueError("CANDIDATE_REGISTRY_EXECUTION_AUTHORITY_UNSAFE")
    rows = registry.get("skills")
    if not isinstance(rows, list) or len(rows) != EXPECTED_SKILL_COUNT:
        raise ValueError(f"CANDIDATE_REGISTRY_NOT_EXACT18:{len(rows) if isinstance(rows, list) else 'invalid'}")
    ids = [str(row.get("skill_id") or "") for row in rows if isinstance(row, dict)]
    if len(set(ids)) != EXPECTED_SKILL_COUNT or any(not value for value in ids):
        raise ValueError("CANDIDATE_REGISTRY_DUPLICATE_OR_EMPTY_ID")
    known = set(ids)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("CANDIDATE_REGISTRY_ROW_INVALID")
        for field in ("dependencies", "conflicts"):
            refs = row.get(field) or []
            if not isinstance(refs, list) or not set(refs) <= known:
                raise ValueError(f"CANDIDATE_REGISTRY_UNKNOWN_{field.upper()}:{row.get('skill_id')}")
        if row.get("state") != "observer_only":
            raise ValueError(f"CANDIDATE_SKILL_NOT_OBSERVER_ONLY:{row.get('skill_id')}")
    return [dict(row) for row in rows]


def parse_source(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def source_tokens(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    return {token for token in _tokenize(text) if len(token) >= 3}


def _tokenize(text: str) -> list[str]:
    token = ""
    out: list[str] = []
    for char in text.lower():
        if char.isalnum() or char == "_":
            token += char
        elif token:
            out.append(token)
            token = ""
    if token:
        out.append(token)
    return out


def skill_tokens(skill: Mapping[str, Any]) -> set[str]:
    values: list[str] = [
        str(skill.get("skill_id") or ""),
        str(skill.get("label_ko") or ""),
        str(skill.get("category") or ""),
        str(skill.get("position_delta_direction") or ""),
    ]
    for key in ("required_inputs", "trigger_contract", "outputs", "performance_metrics"):
        raw = skill.get(key) or []
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    ignored = {"skill", "entry", "exit", "risk", "position", "strategy", "method", "true", "false"}
    return {token for token in _tokenize(" ".join(values)) if len(token) >= 4 and token not in ignored}


def explicit_hook_score(source_token_set: set[str], skill: Mapping[str, Any]) -> tuple[int, list[str]]:
    hits = sorted(source_token_set & skill_tokens(skill))
    exact_id = str(skill.get("skill_id") or "").lower()
    score = len(hits)
    if exact_id and exact_id in source_token_set:
        score += 100
    return score, hits[:20]


def import_candidate_resolver(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("q4r3_skill_resolver_v2_candidate_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"RESOLVER_IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def probe_strategy_subprocess(active_root: Path, owner_module: str, timeout_s: int = 15) -> dict[str, Any]:
    code = r'''
import importlib, inspect, json, os, sys
os.environ["Q4R3_AUDIT_MODE"] = "1"
os.environ["Q4R3_ORDER_ENABLED"] = "0"
os.environ["Q4R3_PAPER_ENABLED"] = "0"
os.environ["Q4R3_LIVE_ENABLED"] = "0"
module_name = sys.argv[1]
result = {"module": module_name, "import_ok": False, "callable_ok": False, "empty_call_ok": False}
try:
    module = importlib.import_module(module_name)
    result["import_ok"] = True
    fn = getattr(module, "strategy", None)
    result["callable_ok"] = callable(fn)
    if callable(fn):
        sig = inspect.signature(fn)
        result["signature"] = str(sig)
        try:
            import pandas as pd
            frame = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            positional = [p for p in sig.parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            if any(p.kind == p.VAR_POSITIONAL for p in sig.parameters.values()) or len(positional) >= 3:
                output = fn(frame, {}, {"action": "hold", "blocked": True})
            elif len(positional) == 2:
                output = fn(frame, {})
            elif len(positional) == 1:
                output = fn(frame)
            else:
                output = fn()
            result["empty_call_ok"] = True
            result["output_type"] = type(output).__name__
            if isinstance(output, dict):
                result["output_keys"] = sorted(str(key) for key in output.keys())[:40]
        except Exception as exc:
            result["call_error"] = f"{type(exc).__name__}:{exc}"[:500]
except Exception as exc:
    result["import_error"] = f"{type(exc).__name__}:{exc}"[:500]
print(json.dumps(result, sort_keys=True))
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(active_root)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, owner_module],
            cwd=str(active_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"module": owner_module, "import_ok": False, "callable_ok": False, "empty_call_ok": False, "timeout": True}
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return {
            "module": owner_module,
            "import_ok": False,
            "callable_ok": False,
            "empty_call_ok": False,
            "returncode": completed.returncode,
            "stderr": completed.stderr[-500:],
        }
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        payload = {
            "module": owner_module,
            "import_ok": False,
            "callable_ok": False,
            "empty_call_ok": False,
            "stdout_tail": completed.stdout[-500:],
            "stderr": completed.stderr[-500:],
        }
    payload["returncode"] = completed.returncode
    return payload


def probe_method_module(active_root: Path, module_name: str, timeout_s: int = 15) -> dict[str, Any]:
    code = "import importlib,json,sys; m=importlib.import_module(sys.argv[1]); print(json.dumps({'module':sys.argv[1],'import_ok':True,'public_names':sorted(x for x in dir(m) if not x.startswith('_'))[:100]}))"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(active_root)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, module_name],
            cwd=str(active_root), env=env, capture_output=True, text=True,
            timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"module": module_name, "import_ok": False, "timeout": True}
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or not lines:
        return {"module": module_name, "import_ok": False, "returncode": completed.returncode, "stderr": completed.stderr[-500:]}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"module": module_name, "import_ok": False, "stdout_tail": completed.stdout[-500:]}


def method_declared(method_id: str, method_text: str) -> bool:
    method, subtype = method_id.split("/", 1)
    lowered = method_text.lower()
    return method.lower() in lowered and subtype.lower() in lowered


def resolver_probe(resolver: Any, registry: Mapping[str, Any], skill: Mapping[str, Any]) -> dict[str, Any]:
    skill_id = str(skill["skill_id"])
    requested: list[str] = [skill_id]
    requested.extend(str(value) for value in skill.get("dependencies") or [])
    context = {
        "strategy_id": "trend_rider",
        "method_id": "intraday/breakout_probe",
        "bot_family": (skill.get("family_scope") or ["L"])[0],
        "regime": "trend_long",
        "deploy_stage": "shadow",
        "market": "BTCUSDT",
        "position_id": "audit-position",
    }
    try:
        result = resolver.resolve_skills(requested, context, registry=dict(registry))
        return {
            "resolver_ok": True,
            "state": result.get("state"),
            "runtime_mutation_allowed": result.get("runtime_mutation_allowed"),
            "order_authority": result.get("order_authority"),
            "blocked_reason": result.get("blocked_reason") or {},
        }
    except Exception as exc:
        return {"resolver_ok": False, "error": f"{type(exc).__name__}:{exc}"[:500]}


def run(active_root: Path, candidate_root: Path, output: Path, matrix_output: Path) -> dict[str, Any]:
    active_root = active_root.resolve()
    candidate_root = candidate_root.resolve()
    before = protected_hashes(active_root)

    registry_path = candidate_root / "backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json"
    resolver_path = candidate_root / "backend/engine/skill_resolver_v2_candidate.py"
    manifest_path = active_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
    registry = read_json(registry_path)
    skills = validate_candidate_registry(registry)
    resolver = import_candidate_resolver(resolver_path)
    if hasattr(resolver, "validate_registry"):
        resolver.validate_registry(dict(registry))
    owners = validate_owner_manifest(read_json(manifest_path))

    strategy_probes: dict[str, dict[str, Any]] = {}
    strategy_tokens: dict[str, set[str]] = {}
    owner_hash_gaps: list[str] = []
    for owner in owners:
        strategy_id = str(owner["strategy_id"])
        owner_path = active_root / str(owner["owner_path"])
        if sha256_file(owner_path) != owner["owner_sha256"]:
            owner_hash_gaps.append(strategy_id)
        parse_source(owner_path)
        strategy_tokens[strategy_id] = source_tokens(owner_path)
        strategy_probes[strategy_id] = probe_strategy_subprocess(active_root, str(owner["owner_module"]))

    method_files = [
        active_root / "backend/trade_methods/policy.py",
        active_root / "backend/trade_methods/profiles.py",
    ]
    for path in method_files:
        parse_source(path)
    method_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in method_files)
    method_tokens = set().union(*(source_tokens(path) for path in method_files))
    method_imports = [
        probe_method_module(active_root, "backend.trade_methods.policy"),
        probe_method_module(active_root, "backend.trade_methods.profiles"),
    ]
    method_declarations = {method_id: method_declared(method_id, method_text) for method_id in EXPECTED_METHODS}
    resolver_results = {str(skill["skill_id"]): resolver_probe(resolver, registry, skill) for skill in skills}

    matrix_output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "strategy_id", "method_id", "skill_id", "strategy_import_ok", "strategy_empty_call_ok",
        "method_declared", "strategy_hook_score", "method_hook_score", "resolver_ok",
        "runtime_trigger_proven", "runtime_outcome_join_proven", "grade", "next_gate",
    ]
    rows_written = 0
    explicit_strategy_hook_rows = 0
    explicit_method_hook_rows = 0
    with matrix_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for owner in owners:
            strategy_id = str(owner["strategy_id"])
            probe = strategy_probes[strategy_id]
            for method_id in EXPECTED_METHODS:
                for skill in skills:
                    strategy_score, _ = explicit_hook_score(strategy_tokens[strategy_id], skill)
                    method_score, _ = explicit_hook_score(method_tokens, skill)
                    explicit_strategy_hook_rows += int(strategy_score > 0)
                    explicit_method_hook_rows += int(method_score > 0)
                    resolver_result = resolver_results[str(skill["skill_id"])]
                    writer.writerow({
                        "strategy_id": strategy_id,
                        "method_id": method_id,
                        "skill_id": skill["skill_id"],
                        "strategy_import_ok": bool(probe.get("import_ok")),
                        "strategy_empty_call_ok": bool(probe.get("empty_call_ok")),
                        "method_declared": method_declarations[method_id],
                        "strategy_hook_score": strategy_score,
                        "method_hook_score": method_score,
                        "resolver_ok": bool(resolver_result.get("resolver_ok")),
                        "runtime_trigger_proven": False,
                        "runtime_outcome_join_proven": False,
                        "grade": "UNKNOWN_REQUIRES_FORWARD_TRIGGER_AND_OUTCOME_EVIDENCE",
                        "next_gate": "INSTALL_READONLY_SKILL_TRIGGER_LINEAGE_OBSERVER",
                    })
                    rows_written += 1

    after = protected_hashes(active_root)
    import_pass_count = sum(bool(row.get("import_ok")) for row in strategy_probes.values())
    call_pass_count = sum(bool(row.get("empty_call_ok")) for row in strategy_probes.values())
    method_import_pass_count = sum(bool(row.get("import_ok")) for row in method_imports)
    method_declaration_count = sum(method_declarations.values())
    resolver_pass_count = sum(bool(row.get("resolver_ok")) for row in resolver_results.values())
    protected_unchanged = before == after

    hard_gaps: list[str] = []
    if owner_hash_gaps:
        hard_gaps.append(f"OWNER_HASH_GAPS:{','.join(owner_hash_gaps)}")
    if import_pass_count != EXPECTED_STRATEGY_COUNT:
        hard_gaps.append(f"STRATEGY_IMPORT_GAPS:{EXPECTED_STRATEGY_COUNT-import_pass_count}")
    if call_pass_count != EXPECTED_STRATEGY_COUNT:
        hard_gaps.append(f"STRATEGY_EMPTY_CALL_GAPS:{EXPECTED_STRATEGY_COUNT-call_pass_count}")
    if method_import_pass_count != 2:
        hard_gaps.append(f"METHOD_IMPORT_GAPS:{2-method_import_pass_count}")
    if method_declaration_count != len(EXPECTED_METHODS):
        hard_gaps.append(f"METHOD_DECLARATION_GAPS:{len(EXPECTED_METHODS)-method_declaration_count}")
    if resolver_pass_count != EXPECTED_SKILL_COUNT:
        hard_gaps.append(f"RESOLVER_GAPS:{EXPECTED_SKILL_COUNT-resolver_pass_count}")
    if not protected_unchanged:
        hard_gaps.append("PROTECTED_SURFACE_HASH_CHANGED")

    state = "PASS" if not hard_gaps else "HOLD"
    verdict = (
        "ACTIVE_IMPORT_CALL_SURFACE_PASS_TRIGGER_LINEAGE_NOT_YET_PROVEN"
        if state == "PASS"
        else "ACTIVE_IMPORT_CALL_OR_INTEGRITY_GAPS_REMAIN"
    )
    summary: dict[str, Any] = {
        "schema": "q4r3_exact25_skill_active_lineage_audit_v1",
        "generated_at": utc_now(),
        "state": state,
        "verdict": verdict,
        "action": "hold",
        "next_action": "INSTALL_READONLY_SKILL_TRIGGER_LINEAGE_OBSERVER" if state == "PASS" else "REPAIR_ONLY_REPORTED_HARD_GAPS",
        "strategy_count": len(owners),
        "method_count": len(EXPECTED_METHODS),
        "skill_count": len(skills),
        "compatibility_matrix_rows": rows_written,
        "strategy_import_pass_count": import_pass_count,
        "strategy_empty_call_pass_count": call_pass_count,
        "method_import_pass_count": method_import_pass_count,
        "method_declaration_count": method_declaration_count,
        "resolver_pass_count": resolver_pass_count,
        "explicit_strategy_hook_rows": explicit_strategy_hook_rows,
        "explicit_method_hook_rows": explicit_method_hook_rows,
        "runtime_trigger_proven_count": 0,
        "runtime_outcome_join_proven_count": 0,
        "hard_gaps": hard_gaps,
        "owner_hash_gaps": owner_hash_gaps,
        "method_declarations": method_declarations,
        "strategy_probes": strategy_probes,
        "method_imports": method_imports,
        "resolver_results": resolver_results,
        "protected_hashes_before": before,
        "protected_hashes_after": after,
        "protected_surfaces_unchanged": protected_unchanged,
        "matrix_path": str(matrix_output),
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "strategy_modified": False,
        "trade_method_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
    }
    atomic_json(output, summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--matrix-output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = run(args.active_root, args.candidate_root, args.output, args.matrix_output)
    print(
        "Q4R3_EXACT25_SKILL_ACTIVE_LINEAGE_AUDIT "
        f"state={summary['state']} verdict={summary['verdict']} "
        f"strategies={summary['strategy_import_pass_count']}/{EXPECTED_STRATEGY_COUNT} "
        f"calls={summary['strategy_empty_call_pass_count']}/{EXPECTED_STRATEGY_COUNT} "
        f"matrix_rows={summary['compatibility_matrix_rows']}"
    )
    return 0 if summary["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
