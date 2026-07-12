from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

CONTRACTS_DIR = Path("/home/z/z/backend/contracts")
SCHEMA_LOCK_PATH = CONTRACTS_DIR / "ZOS_SCHEMA_LOCK_v1.json"
SKILL_REGISTRY_PATH = CONTRACTS_DIR / "ZOS_SKILL_REGISTRY_v1.json"

MANDATORY_OS_GUARDS = [
    "SK_EXEC_SLIPPAGE_ESTIMATOR",
    "SK_EXEC_MARKOUT_GUARD",
    "SK_EXEC_ADVERSE_SELECTION",
    "SK_EXEC_PARTICIPATION_CAP",
    "SK_PORT_CORRELATION_GUARD",
    "SK_PORT_SLIPPAGE_THROTTLE",
    "SK_OPS_GLOBAL_CIRCUIT_BREAKER",
    "SK_OPS_RECONCILE",
    "SK_OPS_IDEMPOTENCY",
]


def _safe_dict(v: Any) -> Dict[str, Any]:
    return deepcopy(v) if isinstance(v, dict) else {}


def _safe_list(v: Any) -> List[Any]:
    return list(v) if isinstance(v, list) else []


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        s = str(v).strip()
        return s if s else default
    except Exception:
        return default


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def load_schema_lock() -> Dict[str, Any]:
    return _read_json(SCHEMA_LOCK_PATH)


def load_skill_registry() -> Dict[str, Any]:
    return _read_json(SKILL_REGISTRY_PATH)


def _normalize_family(raw_family: str) -> str:
    s = _safe_str(raw_family).lower()
    mapping = {
        "l": "L",
        "fallback": "L",
        "m": "M",
        "range": "M",
        "mean_revert": "M",
        "mean-revert": "M",
        "o": "O",
        "momentum": "O",
        "trend": "O",
        "breakout": "O",
        "s": "S",
        "short": "S",
    }
    return mapping.get(s, raw_family if raw_family in {"L", "M", "O", "S"} else "L")


def _skill_index(registry: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _safe_list(registry.get("skills")):
        if isinstance(row, dict):
            sid = _safe_str(row.get("skill_id"))
            if sid:
                out[sid] = deepcopy(row)
    return out


def _is_learning_only(skill_row: Dict[str, Any]) -> bool:
    return _safe_str(skill_row.get("owner")) == "learning" or not bool(skill_row.get("runtime_allowed", False))


def _family_scope_allows(skill_row: Dict[str, Any], bot_family: str) -> bool:
    scope = _safe_list(skill_row.get("family_scope"))
    if not scope:
        return True
    if "all" in scope:
        return True
    return _normalize_family(bot_family) in {_normalize_family(x) for x in scope}


def validate_strategy_skill_refs(
    strategy_doc: Dict[str, Any],
    skill_registry: Optional[Dict[str, Any]] = None,
    schema_lock: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Validation only. Does not mutate strategy doc.
    """
    registry = skill_registry or load_skill_registry()
    skills = _skill_index(registry)

    skill_refs = _safe_dict(_safe_dict(strategy_doc).get("skill_refs"))
    category_map = {
        "strategy_skills": {"1 전략 스킬"},
        "position_management_skills": {"2 포지션 관리 스킬"},
        "risk_skills": {"5 포트폴리오/멀티봇 스킬", "6 운영/안전 스킬"},
        "explain_skills": {"7 AI Advisor 스킬"},
    }

    errors: List[str] = []
    for field, allowed_cats in category_map.items():
        for sid in _safe_list(skill_refs.get(field)):
            sid = _safe_str(sid)
            row = skills.get(sid)
            if not row:
                errors.append(f"{field}:{sid}:missing_in_registry")
                continue
            cat = _safe_str(row.get("skill_category"))
            if cat not in allowed_cats:
                errors.append(f"{field}:{sid}:wrong_category:{cat}")
            if field != "risk_skills" and _is_learning_only(row):
                errors.append(f"{field}:{sid}:learning_or_runtime_forbidden")
    return {
        "ok": len(errors) == 0,
        "errors": errors,
    }


def resolve_effective_skills(
    strategy_doc: Dict[str, Any],
    bot_dna: Dict[str, Any],
    skill_registry: Optional[Dict[str, Any]] = None,
    schema_lock: Optional[Dict[str, Any]] = None,
    regime: Optional[str] = None,
    deploy_stage: Optional[str] = None,
    market: Optional[str] = None,
) -> Dict[str, Any]:
    registry = skill_registry or load_skill_registry()
    skills = _skill_index(registry)
    strategy_doc = _safe_dict(strategy_doc)
    bot_dna = _safe_dict(bot_dna)

    bot_family = _normalize_family(
        _safe_str(bot_dna.get("family_only") or _safe_dict(bot_dna.get("identity")).get("family_only"))
    )

    behavior = _safe_dict(bot_dna.get("behavior"))
    skill_refs = _safe_dict(strategy_doc.get("skill_refs"))
    bot_skill_refs = _safe_dict(bot_dna.get("skill_refs"))

    requested_strategy = [_safe_str(x) for x in _safe_list(skill_refs.get("strategy_skills"))]
    requested_position = [_safe_str(x) for x in _safe_list(skill_refs.get("position_management_skills"))]
    requested_risk = [_safe_str(x) for x in _safe_list(skill_refs.get("risk_skills"))]
    requested_explain = [_safe_str(x) for x in _safe_list(skill_refs.get("explain_skills"))]

    bot_direct = [_safe_str(x) for x in _safe_list(bot_skill_refs.get("bot_skills"))]
    bot_exec = [_safe_str(x) for x in _safe_list(bot_skill_refs.get("execution_skills"))]
    bot_port = [_safe_str(x) for x in _safe_list(bot_skill_refs.get("portfolio_interaction_skills"))]

    effective_strategy: List[str] = []
    effective_bot: List[str] = []
    active_os_guards: Set[str] = set(MANDATORY_OS_GUARDS)
    learning_only: Set[str] = set()
    blocked: List[str] = []
    blocked_reason: Dict[str, str] = {}

    def add_blocked(skill_id: str, reason: str) -> None:
        if skill_id not in blocked:
            blocked.append(skill_id)
        blocked_reason[skill_id] = reason

    # strategy skills
    for sid in requested_strategy:
        row = skills.get(sid)
        if not row:
            add_blocked(sid, "missing_in_registry")
            continue
        if not _family_scope_allows(row, bot_family):
            add_blocked(sid, "family_scope_mismatch")
            continue
        if _is_learning_only(row):
            learning_only.add(sid)
            add_blocked(sid, "learning_only_or_runtime_disallowed")
            continue
        effective_strategy.append(sid)

    # position-management: strategy wants it, bot capability decides
    capability_map = {
        "SK_POS_SCALE_IN": bool(behavior.get("allow_dca")),
        "SK_POS_SCALE_OUT": True,
        "SK_POS_TIME_STOP": True,
        "SK_POS_TRAILING_STOP": True,
        "SK_POS_BREAK_EVEN_SHIFT": True,
    }
    for sid in requested_position:
        row = skills.get(sid)
        if not row:
            add_blocked(sid, "missing_in_registry")
            continue
        if not _family_scope_allows(row, bot_family):
            add_blocked(sid, "family_scope_mismatch")
            continue
        if _is_learning_only(row):
            learning_only.add(sid)
            add_blocked(sid, "learning_only_or_runtime_disallowed")
            continue
        if sid in capability_map and not capability_map[sid]:
            add_blocked(sid, "bot_capability_false")
            continue
        effective_bot.append(sid)

    # direct bot skills
    for sid in bot_direct:
        row = skills.get(sid)
        if not row:
            add_blocked(sid, "missing_in_registry")
            continue
        if not _family_scope_allows(row, bot_family):
            add_blocked(sid, "family_scope_mismatch")
            continue
        if _is_learning_only(row):
            learning_only.add(sid)
            add_blocked(sid, "learning_only_or_runtime_disallowed")
            continue
        effective_bot.append(sid)

    # execution / portfolio / ops become OS guards
    for sid in requested_risk + bot_exec + bot_port:
        row = skills.get(sid)
        if not row:
            add_blocked(sid, "missing_in_registry")
            continue
        if not _family_scope_allows(row, bot_family):
            add_blocked(sid, "family_scope_mismatch")
            continue
        active_os_guards.add(sid)
        if _is_learning_only(row):
            learning_only.add(sid)

    # explain and advisor skills are read-only, not live write
    for sid in requested_explain:
        row = skills.get(sid)
        if not row:
            add_blocked(sid, "missing_in_registry")
            continue
        learning_only.add(sid)

    # collect all explicit learning skills from registry references that slipped in
    for sid in list(effective_strategy) + list(effective_bot) + list(active_os_guards):
        row = skills.get(sid)
        if row and _is_learning_only(row):
            learning_only.add(sid)

    # dedupe preserve order
    def dedupe(seq: List[str]) -> List[str]:
        out: List[str] = []
        seen: Set[str] = set()
        for x in seq:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {
        "effective_strategy_skill_ids": dedupe(effective_strategy),
        "effective_bot_skill_ids": dedupe(effective_bot),
        "active_os_guard_skill_ids": dedupe(list(active_os_guards)),
        "learning_only_skill_ids": dedupe(list(learning_only)),
        "blocked_skill_ids": blocked,
        "blocked_reason": blocked_reason,
        "meta": {
            "bot_family": bot_family,
            "regime": _safe_str(regime),
            "deploy_stage": _safe_str(deploy_stage),
            "market": _safe_str(market),
        },
    }


__all__ = [
    "load_schema_lock",
    "load_skill_registry",
    "validate_strategy_skill_refs",
    "resolve_effective_skills",
    "MANDATORY_OS_GUARDS",
]
