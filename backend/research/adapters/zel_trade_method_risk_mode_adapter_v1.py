from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_TRADE_METHOD_RISK_MODE_ADAPTER_V1"
WARNING_CONSECUTIVE_LOSSES = 20
BLOCK_CONSECUTIVE_LOSSES = 30
ROLLING_20_LOSS_GUARD_R = -8.0
ROLLING_50_LOSS_GUARD_R = -20.0
WARNING_SIZE_MULTIPLIER = 0.75
HIGH_RISK_SKILLS = frozenset({"short_beam", "dca_average_down", "hedge_reversal"})


class MethodRiskMode(StrEnum):
    NORMAL = "normal"
    WARNING = "warning_reduce25"
    BLOCK = "block"


@dataclass(frozen=True)
class RiskContext:
    consecutive_losses: int = 0
    rolling_20_loss_r: float = 0.0
    rolling_50_loss_r: float = 0.0
    high_risk: bool = False
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiskDecision:
    mode: MethodRiskMode
    action: str
    size_multiplier: float
    reason: str
    triggered_rules: tuple[str, ...]


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_context(value: RiskContext | Mapping[str, Any] | None) -> RiskContext:
    if isinstance(value, RiskContext):
        return value
    raw = dict(value or {})
    skills_raw = raw.get("skills") or ()
    if isinstance(skills_raw, str):
        skills = (skills_raw.strip().lower(),) if skills_raw.strip() else ()
    elif isinstance(skills_raw, Iterable):
        skills = tuple(sorted({str(item).strip().lower() for item in skills_raw if str(item).strip()}))
    else:
        skills = ()
    return RiskContext(
        consecutive_losses=max(0, int(raw.get("consecutive_losses") or 0)),
        rolling_20_loss_r=_finite(raw.get("rolling_20_loss_r"), 0.0),
        rolling_50_loss_r=_finite(raw.get("rolling_50_loss_r"), 0.0),
        high_risk=bool(raw.get("high_risk", False)),
        skills=skills,
    )


def resolve_risk_mode(value: RiskContext | Mapping[str, Any] | None) -> RiskDecision:
    context = normalize_context(value)
    high_risk_skills = sorted(HIGH_RISK_SKILLS.intersection(context.skills))
    block_rules: list[str] = []
    if context.high_risk:
        block_rules.append("HIGH_RISK_CONTEXT")
    if high_risk_skills:
        block_rules.append("HIGH_RISK_SKILL:" + ",".join(high_risk_skills))
    if context.consecutive_losses >= BLOCK_CONSECUTIVE_LOSSES:
        block_rules.append("CONSECUTIVE_LOSSES_GTE_30")
    if context.rolling_20_loss_r <= ROLLING_20_LOSS_GUARD_R:
        block_rules.append("ROLLING_20_LOSS_R_LTE_-8")
    if context.rolling_50_loss_r <= ROLLING_50_LOSS_GUARD_R:
        block_rules.append("ROLLING_50_LOSS_R_LTE_-20")
    if block_rules:
        return RiskDecision(
            mode=MethodRiskMode.BLOCK,
            action="block",
            size_multiplier=0.0,
            reason="risk_block_exact",
            triggered_rules=tuple(block_rules),
        )
    if context.consecutive_losses >= WARNING_CONSECUTIVE_LOSSES:
        return RiskDecision(
            mode=MethodRiskMode.WARNING,
            action="reduce25",
            size_multiplier=WARNING_SIZE_MULTIPLIER,
            reason="risk_warning_reduce25_exact",
            triggered_rules=("CONSECUTIVE_LOSSES_GTE_20",),
        )
    return RiskDecision(
        mode=MethodRiskMode.NORMAL,
        action="hold",
        size_multiplier=1.0,
        reason="risk_normal_exact",
        triggered_rules=(),
    )


def apply_risk_mode(base_plan: Mapping[str, Any], context: RiskContext | Mapping[str, Any] | None) -> dict[str, Any]:
    plan = dict(base_plan)
    decision = resolve_risk_mode(context)
    base_action = str(plan.get("action") or "hold").lower()
    base_size = max(0.0, _finite(plan.get("size_multiplier"), 0.0))

    if base_action in {"block", "stop"} or base_size <= 0.0:
        final_action = base_action if base_action in {"block", "stop"} else "block"
        final_size = 0.0
        reason = str(plan.get("reason") or "base_plan_blocked")
    elif decision.mode is MethodRiskMode.BLOCK:
        final_action = "block"
        final_size = 0.0
        reason = decision.reason
    elif decision.mode is MethodRiskMode.WARNING:
        final_action = "reduce25"
        final_size = base_size * decision.size_multiplier
        reason = decision.reason
    else:
        final_action = base_action
        final_size = base_size
        reason = str(plan.get("reason") or decision.reason)

    plan.update(
        {
            "action": final_action,
            "size_multiplier": round(final_size, 12),
            "risk_mode": decision.mode.value,
            "risk_reason": decision.reason,
            "risk_triggered_rules": list(decision.triggered_rules),
            "reason": reason,
            "risk_adapter": VERSION,
            "risk_policy_order": "AFTER_BASE_SKILL_AND_COST_SIZING",
            "execution_authority": "none",
            "order_authority": "blocked",
            "paper_execution_allowed": False,
            "live_execution_allowed": False,
            "promotion_authority": False,
        }
    )
    return plan


def resolve_with_active_trade_method(
    *,
    root: Path,
    strategy: str,
    skills: Iterable[str] = (),
    cost_r: float = 0.0,
    context: RiskContext | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    resolver = importlib.import_module("backend.trade_methods.resolver")
    function = getattr(resolver, "h74tm8_resolve_trade_method")
    base = function(strategy=strategy, skills=tuple(skills), cost_r=float(cost_r))
    merged_context = dict(context or {})
    merged_context.setdefault("skills", tuple(skills))
    return apply_risk_mode(base, merged_context)


def _assert_case(name: str, value: Mapping[str, Any], **expected: Any) -> dict[str, Any]:
    failures = {key: {"expected": wanted, "actual": value.get(key)} for key, wanted in expected.items() if value.get(key) != wanted}
    if failures:
        raise AssertionError(f"{name}:{json.dumps(failures, sort_keys=True)}")
    return {"case": name, "result": dict(value), "pass": True}


def run_validation(root: Path) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    normal = resolve_with_active_trade_method(root=root, strategy="trend_ma_macd", cost_r=0.1)
    cases.append(_assert_case("normal", normal, risk_mode="normal", action="hold", size_multiplier=1.0))

    warning = resolve_with_active_trade_method(
        root=root,
        strategy="trend_ma_macd",
        cost_r=0.1,
        context={"consecutive_losses": 20},
    )
    cases.append(_assert_case("warning_20", warning, risk_mode="warning_reduce25", action="reduce25", size_multiplier=0.75))

    block_30 = resolve_with_active_trade_method(
        root=root,
        strategy="trend_ma_macd",
        cost_r=0.1,
        context={"consecutive_losses": 30},
    )
    cases.append(_assert_case("block_30", block_30, risk_mode="block", action="block", size_multiplier=0.0))

    block_20r = resolve_with_active_trade_method(
        root=root,
        strategy="trend_ma_macd",
        cost_r=0.1,
        context={"rolling_20_loss_r": -8.0},
    )
    cases.append(_assert_case("block_rolling20", block_20r, risk_mode="block", action="block", size_multiplier=0.0))

    block_50r = resolve_with_active_trade_method(
        root=root,
        strategy="trend_ma_macd",
        cost_r=0.1,
        context={"rolling_50_loss_r": -20.0},
    )
    cases.append(_assert_case("block_rolling50", block_50r, risk_mode="block", action="block", size_multiplier=0.0))

    short_beam = resolve_with_active_trade_method(
        root=root,
        strategy="trend_ma_macd",
        skills=("short_beam",),
        cost_r=0.1,
    )
    cases.append(_assert_case("high_risk_short_beam", short_beam, risk_mode="block", action="block", size_multiplier=0.0))

    cost_and_warning = resolve_with_active_trade_method(
        root=root,
        strategy="trend_ma_macd",
        skills=("exit_modifier",),
        cost_r=0.35,
        context={"consecutive_losses": 20},
    )
    if cost_and_warning["size_multiplier"] > 0.375 + 1e-12:
        raise AssertionError(f"cost_and_warning_size_gt_0.375:{cost_and_warning['size_multiplier']}")
    cases.append({"case": "cost_then_warning_order", "result": cost_and_warning, "pass": True})

    return {
        "schema_version": "zel.trade_methods.risk_adapter.validation.v1",
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_ISOLATED_RISK_ADAPTER_BEHAVIOR",
        "case_count": len(cases),
        "cases": cases,
        "policy": {
            "warning_consecutive_losses": WARNING_CONSECUTIVE_LOSSES,
            "block_consecutive_losses": BLOCK_CONSECUTIVE_LOSSES,
            "rolling_20_loss_guard_r": ROLLING_20_LOSS_GUARD_R,
            "rolling_50_loss_guard_r": ROLLING_50_LOSS_GUARD_R,
            "warning_action": "reduce25",
            "warning_size_multiplier": WARNING_SIZE_MULTIPLIER,
            "block_action": "block",
            "high_risk_skills": sorted(HIGH_RISK_SKILLS),
        },
        "canonical_strategy_files_mutated": False,
        "canonical_trade_methods_mutated": False,
        "canonical_registry_mutated": False,
        "adapter_scope": "RESEARCH_ISOLATED_ONLY",
        "bundle_replay_binding_allowed": True,
        "runtime_binding_allowed": False,
        "shadow_start_allowed": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
        "next": "BIND_ADAPTER_TO_EXACT_TRADE_METHOD_REPLAY_FIXTURE",
    }


def self_test() -> None:
    assert resolve_risk_mode({"consecutive_losses": 19}).mode is MethodRiskMode.NORMAL
    assert resolve_risk_mode({"consecutive_losses": 20}).mode is MethodRiskMode.WARNING
    assert resolve_risk_mode({"consecutive_losses": 30}).mode is MethodRiskMode.BLOCK
    assert resolve_risk_mode({"rolling_20_loss_r": -8.0}).mode is MethodRiskMode.BLOCK
    assert resolve_risk_mode({"skills": ["dca_average_down"]}).mode is MethodRiskMode.BLOCK
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.out:
        parser.error("--out required")
    result = run_validation(Path(args.root).resolve())
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "cases": result["case_count"], "next": result["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
