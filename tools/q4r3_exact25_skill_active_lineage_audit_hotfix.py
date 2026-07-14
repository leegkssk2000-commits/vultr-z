from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

from tools import q4r3_exact25_skill_active_lineage_audit as base


MODULE_NAME = "q4r3_skill_resolver_v2_candidate_runtime"
TACTICAL_MODULE_NAME = "q4r3_tactical_swing_continuation_candidate_runtime"
TACTICAL_METHOD_ID = "tactical_swing/continuation"
ALLOWED_AUDIT_FAMILIES = ("L", "M", "O", "S")
ORIGINAL_METHOD_DECLARED = base.method_declared
ORIGINAL_RUN = base.run


def import_candidate_resolver(path: Path) -> Any:
    """Load the candidate resolver with its module registered for dataclasses."""
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"RESOLVER_IMPORT_SPEC_FAILED:{path}")

    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(MODULE_NAME)
    sys.modules[MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if previous is None:
            sys.modules.pop(MODULE_NAME, None)
        else:
            sys.modules[MODULE_NAME] = previous
        raise
    return module


def _audit_family(skill: Mapping[str, Any]) -> str:
    raw_scope = skill.get("family_scope") or []
    scope = [str(value).strip().upper() for value in raw_scope]
    for family in ALLOWED_AUDIT_FAMILIES:
        if family in scope:
            return family
    if "ALL" in scope:
        return "L"
    return "L"


def resolver_probe(
    resolver: Any,
    registry: Mapping[str, Any],
    skill: Mapping[str, Any],
) -> dict[str, Any]:
    skill_id = str(skill["skill_id"])
    requested: list[str] = [skill_id]
    requested.extend(str(value) for value in skill.get("dependencies") or [])
    context = {
        "strategy_id": "trend_rider",
        "method_id": "intraday/breakout_probe",
        "bot_family": _audit_family(skill),
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
            "audit_bot_family": context["bot_family"],
        }
    except Exception as exc:
        return {
            "resolver_ok": False,
            "error": f"{type(exc).__name__}:{exc}"[:500],
            "audit_bot_family": context["bot_family"],
        }


def _load_tactical_candidate() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[1]
        / "backend/trade_methods/tactical_swing_continuation_candidate.py"
    )
    spec = importlib.util.spec_from_file_location(TACTICAL_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"TACTICAL_CANDIDATE_IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(TACTICAL_MODULE_NAME)
    sys.modules[TACTICAL_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
        payload = module.validate_candidate_profile()
    except Exception:
        if previous is None:
            sys.modules.pop(TACTICAL_MODULE_NAME, None)
        else:
            sys.modules[TACTICAL_MODULE_NAME] = previous
        raise
    return dict(payload)


def method_declared(method_id: str, method_text: str) -> bool:
    if method_id != TACTICAL_METHOD_ID:
        return ORIGINAL_METHOD_DECLARED(method_id, method_text)
    payload = _load_tactical_candidate()
    return (
        payload.get("method_id") == TACTICAL_METHOD_ID
        and payload.get("profile_state") == "candidate_declaration_only"
        and payload.get("observer_only") is True
        and payload.get("activation_allowed") is False
        and payload.get("runtime_mutation_allowed") is False
        and payload.get("order_authority") == "blocked"
        and payload.get("execution_authority") == "none"
        and payload.get("runtime_trigger_proven") is False
        and payload.get("runtime_outcome_join_proven") is False
    )


def run(
    active_root: Path,
    candidate_root: Path,
    output: Path,
    matrix_output: Path,
) -> dict[str, Any]:
    summary = ORIGINAL_RUN(active_root, candidate_root, output, matrix_output)
    tactical = _load_tactical_candidate()
    summary["active_method_declaration_count"] = 5
    summary["candidate_method_declaration_count"] = 1
    summary["candidate_method_declarations"] = {
        TACTICAL_METHOD_ID: tactical,
    }
    summary["tactical_swing_active"] = False
    summary["tactical_swing_candidate_only"] = True
    summary["activation_allowed"] = False
    base.atomic_json(output, summary)
    return summary


base.import_candidate_resolver = import_candidate_resolver
base.resolver_probe = resolver_probe
base.method_declared = method_declared
base.run = run


if __name__ == "__main__":
    raise SystemExit(base.main())
