from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tools import zel_manual_multiaxis_gemini_v2 as helper

VERSION = "ZEL_TRADE_METHODS_SEMANTIC_GEMINI_V1"
ROLES = {
    "PLAN_TYPE",
    "RESOLVER",
    "SKILL_TYPE",
    "RISK_MODE",
    "EXIT_POLICY",
    "RISK_POLICY",
    "SIZING_POLICY",
    "COMBO_POLICY",
}
SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "shadow_start_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "action": "hold",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def evidence_view(inventory: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "state": inventory.get("state"),
        "inventory_sha256": inventory.get("inventory_sha256"),
        "python_file_count": inventory.get("python_file_count"),
        "symbol_count": inventory.get("symbol_count"),
        "role_candidates": inventory.get("role_candidates"),
        "runtime_import": inventory.get("runtime_import"),
        "personal_method_candidates": inventory.get("personal_method_candidates"),
        "component_candidates": inventory.get("component_candidates"),
        "blockers": inventory.get("blockers"),
        "interpretation": inventory.get("interpretation"),
    }


def prompt(inventory: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "role_mappings": [
            {
                "role": "PLAN_TYPE|RESOLVER|SKILL_TYPE|RISK_MODE|EXIT_POLICY|RISK_POLICY|SIZING_POLICY|COMBO_POLICY",
                "verdict": "EXACT_CANDIDATE|POSSIBLE_ALIAS|NO_MATCH",
                "candidates": [
                    {
                        "name": "exact inventory symbol name",
                        "kind": "class|function|constant|export",
                        "path": "exact inventory path",
                        "confidence": 0.0,
                        "required_deterministic_test": "specific signature/type/behavior test"
                    }
                ],
                "reason": "why names and signatures do or do not support the role"
            }
        ],
        "component_location_review": [
            {
                "component": "zbot|zico|lico|zlice|lbot|mbot|obot|sbot|skill|team",
                "verdict": "LIKELY_CANONICAL|LIKELY_ADAPTER|UNRESOLVED",
                "paths": ["exact inventory paths"],
                "required_test": "specific import/SHA/behavior check"
            }
        ],
        "personal_source_review": {
            "verdict": "EXACT_NAME_FOUND|CANDIDATES_ONLY|NOT_FOUND",
            "candidate_paths": ["exact inventory paths"],
            "reason": "metadata-only conclusion"
        },
        "adapter_plan": [
            {
                "target_export": "expected compatibility name",
                "source_symbol": "exact candidate symbol or null",
                "allowed_now": False,
                "required_before_adapter": ["deterministic tests"]
            }
        ],
        "blockers": ["remaining blockers"]
    }
    return (
        "You are reviewing a read-only AST and runtime-symbol inventory for a quantitative trading method package. "
        "Do not infer implementation equivalence from similar names alone. A Gemini mapping is a hypothesis, never patch or promotion authority. "
        "Use only exact symbol names and paths present in the inventory. Return exactly one role_mappings row for every required role. "
        "Mark EXACT_CANDIDATE only when class/function kind and visible signature/fields directly support the role. Otherwise use POSSIBLE_ALIAS or NO_MATCH. "
        "For each candidate specify a deterministic type, signature, import or replay test that could falsify the mapping. "
        "Review actual component paths because the earlier /canonical assumption may be wrong. Personal-method source conclusions must use filename/path/SHA metadata only; do not claim file contents. "
        "No source mutation, no adapter creation, no Shadow start. Return strict JSON only.\n"
        f"SEMANTIC_INVENTORY={canonical(evidence_view(inventory))}\n"
        f"OUTPUT_SCHEMA={canonical(schema)}"
    )


def valid_symbol_index(inventory: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    rows: set[tuple[str, str, str]] = set()
    for candidates in (inventory.get("role_candidates") or {}).values():
        if not isinstance(candidates, list):
            continue
        for row in candidates:
            if isinstance(row, Mapping):
                rows.add((str(row.get("name")), str(row.get("kind")), str(row.get("path"))))
    return rows


def valid_component_paths(inventory: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for component, rows in (inventory.get("component_candidates") or {}).items():
        result[str(component)] = {
            str(row.get("path")) for row in rows if isinstance(row, Mapping) and row.get("path")
        }
    return result


def normalize(response: Mapping[str, Any], inventory: Mapping[str, Any]) -> dict[str, Any]:
    status = str(response.get("status") or "HOLD").upper()
    if status not in {"PASS", "HOLD"}:
        raise RuntimeError(f"STATUS_INVALID:{status}")
    symbol_index = valid_symbol_index(inventory)
    mappings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in response.get("role_mappings") or []:
        if not isinstance(raw, Mapping):
            continue
        role = str(raw.get("role") or "").upper()
        if role not in ROLES or role in seen:
            continue
        verdict = str(raw.get("verdict") or "NO_MATCH").upper()
        if verdict not in {"EXACT_CANDIDATE", "POSSIBLE_ALIAS", "NO_MATCH"}:
            verdict = "NO_MATCH"
        candidates: list[dict[str, Any]] = []
        for candidate in raw.get("candidates") or []:
            if not isinstance(candidate, Mapping):
                continue
            key = (str(candidate.get("name")), str(candidate.get("kind")), str(candidate.get("path")))
            if key not in symbol_index:
                continue
            try:
                confidence = float(candidate.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            candidates.append({
                "name": key[0],
                "kind": key[1],
                "path": key[2],
                "confidence": max(0.0, min(confidence, 1.0)),
                "required_deterministic_test": str(candidate.get("required_deterministic_test") or "").strip(),
            })
            if len(candidates) == 2:
                break
        if verdict != "NO_MATCH" and not candidates:
            verdict = "NO_MATCH"
        seen.add(role)
        mappings.append({
            "role": role,
            "verdict": verdict,
            "candidates": candidates,
            "reason": str(raw.get("reason") or "").strip(),
        })
    for role in sorted(ROLES - seen):
        mappings.append({"role": role, "verdict": "NO_MATCH", "candidates": [], "reason": "GEMINI_ROLE_ROW_MISSING"})
    mappings.sort(key=lambda row: row["role"])

    path_index = valid_component_paths(inventory)
    component_rows: list[dict[str, Any]] = []
    for raw in response.get("component_location_review") or []:
        if not isinstance(raw, Mapping):
            continue
        component = str(raw.get("component") or "").lower()
        if component not in path_index:
            continue
        paths = [str(path) for path in raw.get("paths") or [] if str(path) in path_index[component]][:10]
        verdict = str(raw.get("verdict") or "UNRESOLVED").upper()
        if verdict not in {"LIKELY_CANONICAL", "LIKELY_ADAPTER", "UNRESOLVED"}:
            verdict = "UNRESOLVED"
        if verdict != "UNRESOLVED" and not paths:
            verdict = "UNRESOLVED"
        component_rows.append({
            "component": component,
            "verdict": verdict,
            "paths": paths,
            "required_test": str(raw.get("required_test") or "").strip(),
        })

    personal_paths = {
        str(row.get("path")) for row in inventory.get("personal_method_candidates") or [] if isinstance(row, Mapping)
    }
    personal_raw = response.get("personal_source_review") if isinstance(response.get("personal_source_review"), Mapping) else {}
    personal_candidates = [str(path) for path in personal_raw.get("candidate_paths") or [] if str(path) in personal_paths][:20]
    personal_verdict = str(personal_raw.get("verdict") or "NOT_FOUND").upper()
    if personal_verdict not in {"EXACT_NAME_FOUND", "CANDIDATES_ONLY", "NOT_FOUND"}:
        personal_verdict = "NOT_FOUND"
    if personal_verdict != "NOT_FOUND" and not personal_candidates:
        personal_verdict = "NOT_FOUND"

    adapter_plan: list[dict[str, Any]] = []
    allowed_sources = {candidate["name"] for row in mappings for candidate in row["candidates"]}
    for raw in response.get("adapter_plan") or []:
        if not isinstance(raw, Mapping):
            continue
        source = raw.get("source_symbol")
        if source is not None and str(source) not in allowed_sources:
            source = None
        adapter_plan.append({
            "target_export": str(raw.get("target_export") or "").strip(),
            "source_symbol": str(source) if source is not None else None,
            "allowed_now": False,
            "required_before_adapter": [str(value) for value in raw.get("required_before_adapter") or []][:10],
        })
        if len(adapter_plan) == 20:
            break

    blockers = [str(value) for value in response.get("blockers") or []][:50]
    return {
        "status": status,
        "role_mappings": mappings,
        "component_location_review": component_rows,
        "personal_source_review": {
            "verdict": personal_verdict,
            "candidate_paths": personal_candidates,
            "reason": str(personal_raw.get("reason") or "").strip(),
        },
        "adapter_plan": adapter_plan,
        "blockers": blockers,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    inventory = read_json(args.inventory)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        result = {
            "schema_version": "zel.trade_methods.semantic_gemini.v1",
            "version": VERSION,
            "state": "HOLD_GEMINI_API_KEY_MISSING",
            "GEMINI_USED": False,
            "inventory_sha256": inventory.get("inventory_sha256"),
            "role_mappings": [],
            "component_location_review": [],
            "personal_source_review": {"verdict": "NOT_FOUND", "candidate_paths": [], "reason": "GEMINI_NOT_RUN"},
            "adapter_plan": [],
            "blockers": ["GEMINI_API_KEY_MISSING"],
            **SAFE,
        }
        result["receipt_sha256"] = stable_sha(result)
        write_json(args.out, result)
        return result
    research_prompt = prompt(inventory)
    model, text = helper.call_generate(key, research_prompt, source=None, max_output_tokens=12288)
    try:
        parsed = helper.parse_json(text)
        normalized = normalize(parsed, inventory)
    except Exception:
        repair = research_prompt + "\nYour previous response violated the strict schema. Return one JSON object using only exact inventory symbols and paths."
        model, text = helper.call_generate(key, repair, source=None, max_output_tokens=12288)
        parsed = helper.parse_json(text)
        normalized = normalize(parsed, inventory)
    exact_or_alias = sum(row["verdict"] != "NO_MATCH" for row in normalized["role_mappings"])
    state = "PASS_GEMINI_SEMANTIC_MAPPING_HYPOTHESES" if exact_or_alias else "HOLD_GEMINI_NO_SEMANTIC_MAPPING"
    result = {
        "schema_version": "zel.trade_methods.semantic_gemini.v1",
        "version": VERSION,
        "state": state,
        "GEMINI_USED": True,
        "actual_model": model,
        "inventory_sha256": inventory.get("inventory_sha256"),
        "prompt_sha256": hashlib.sha256(research_prompt.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        **normalized,
        "mapping_is_hypothesis_only": True,
        "adapter_creation_allowed": False,
        "next": "DETERMINISTIC_SIGNATURE_AND_BEHAVIOR_PROBES_BEFORE_MINIMAL_COMPATIBILITY_ADAPTER",
        **SAFE,
    }
    result["receipt_sha256"] = stable_sha(result)
    write_json(args.out, result)
    return result


def self_test() -> None:
    inventory = {
        "role_candidates": {
            "PLAN_TYPE": [{"name": "MethodPlan", "kind": "class", "path": "backend/trade_methods/types.py"}],
        },
        "component_candidates": {"zbot": [{"path": "/x/zbot.py"}]},
        "personal_method_candidates": [{"path": "/x/trade_methods_personal.txt"}],
    }
    response = {
        "status": "PASS",
        "role_mappings": [{
            "role": "PLAN_TYPE", "verdict": "EXACT_CANDIDATE",
            "candidates": [{"name": "MethodPlan", "kind": "class", "path": "backend/trade_methods/types.py", "confidence": 0.9, "required_deterministic_test": "instantiate"}],
            "reason": "fields",
        }],
        "component_location_review": [{"component": "zbot", "verdict": "LIKELY_CANONICAL", "paths": ["/x/zbot.py"], "required_test": "import"}],
        "personal_source_review": {"verdict": "CANDIDATES_ONLY", "candidate_paths": ["/x/trade_methods_personal.txt"], "reason": "name"},
    }
    normalized = normalize(response, inventory)
    assert len(normalized["role_mappings"]) == len(ROLES)
    assert next(row for row in normalized["role_mappings"] if row["role"] == "PLAN_TYPE")["verdict"] == "EXACT_CANDIDATE"
    assert normalized["component_location_review"][0]["paths"] == ["/x/zbot.py"]
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.inventory or not args.out:
        parser.error("--inventory and --out are required")
    result = run(args)
    print(json.dumps({"state": result["state"], "GEMINI_USED": result["GEMINI_USED"], "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
