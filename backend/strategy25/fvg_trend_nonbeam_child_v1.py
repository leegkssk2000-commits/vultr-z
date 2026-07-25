from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from backend.strategy25.indicator_contract_repair_loader_v1 import load_repaired_strategy


STRATEGY_ID = "fvg_revert"
POLICY_ID = "FVG_LONG_ENTRY_TREND_ALIGNED_NONBEAM_V1"


CHILD_MANIFEST: Mapping[str, Any] = MappingProxyType(
    {
        "schema_version": "1.0",
        "strategy_id": STRATEGY_ID,
        "policy_id": POLICY_ID,
        "parent": "indicator_contract_repair_loader_v1:fvg_revert",
        "read_only_child": True,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "scope": "LONG_ENTER_ONLY",
        "condition": "indicators.trend_long is true and indicators.long_beam is false",
        "failure_action": "hold",
        "lineage": "trend_alignment_v1 plus one incremental beam-veto condition",
    }
)


def apply_fvg_trend_nonbeam(result: Mapping[str, Any]) -> dict[str, Any]:
    """Allow repaired FVG long entries only when trend-aligned and not beam-classified."""
    if not isinstance(result, Mapping):
        raise TypeError("FVG_RESULT_MAPPING_REQUIRED")

    output = deepcopy(dict(result))
    action = str(output.get("action") or "hold").lower()
    side = str(output.get("side") or "").lower()
    indicators = output.get("indicators") if isinstance(output.get("indicators"), Mapping) else {}
    trend_long = indicators.get("trend_long") is True
    long_beam = indicators.get("long_beam") is True
    blocked = side == "long" and action == "enter" and (not trend_long or long_beam)

    if blocked:
        original_tags = [str(item) for item in (output.get("tags") or [])]
        original_why = str(output.get("why") or "unknown")
        original_skill = str(output.get("skill") or "none")
        output.update(
            {
                "side": None,
                "action": "hold",
                "size": 0.0,
                "why": "fvg_trend_nonbeam_gate",
                "skill": "none",
                "confidence": 0.0,
                "tags": original_tags + ["trend_nonbeam_gate", "child_only"],
            }
        )
        output["indicators"] = {
            **dict(indicators),
            "trend_alignment_gate_blocked": True,
            "trend_nonbeam_gate_blocked": True,
            "pre_gate_side": side,
            "pre_gate_action": action,
            "pre_gate_why": original_why,
            "pre_gate_skill": original_skill,
            "policy_id": POLICY_ID,
        }
    else:
        output["indicators"] = dict(indicators)
        output["indicators"]["trend_alignment_gate_blocked"] = False
        output["indicators"]["trend_nonbeam_gate_blocked"] = False
        output["indicators"]["policy_id"] = POLICY_ID

    return output


def load_fvg_trend_aligned_strategy(root: str | Path) -> Callable[..., dict[str, Any]]:
    repaired = load_repaired_strategy(root, STRATEGY_ID)

    def strategy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return apply_fvg_trend_nonbeam(repaired(*args, **kwargs))

    strategy.__name__ = "fvg_trend_nonbeam_child_strategy_v1"
    strategy.__qualname__ = strategy.__name__
    return strategy
