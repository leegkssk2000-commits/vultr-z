from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

from tools import q4r3_exact25_skill_active_lineage_audit as base


MODULE_NAME = "q4r3_skill_resolver_v2_candidate_runtime"
ALLOWED_AUDIT_FAMILIES = ("L", "M", "O", "S")


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


base.import_candidate_resolver = import_candidate_resolver
base.resolver_probe = resolver_probe


if __name__ == "__main__":
    raise SystemExit(base.main())
