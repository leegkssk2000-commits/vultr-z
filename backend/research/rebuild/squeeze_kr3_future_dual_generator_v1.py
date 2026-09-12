"""Future-causal generator binding for Squeeze-KR3 Unified v1.

This module does not read saved historical campaign membership. It binds the
already-frozen CAPREUSE core and C54 mode-B donor generators to the exact
chronological core-priority arbiter used by Squeeze-KR3 Unified v1.

No network, persistence, economic selection, order or deployment authority.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from backend.research.rebuild import c70_tm_capreuse_v1 as capreuse
from backend.research.rebuild import kr3_c51_entry_context_v1 as c54
from backend.research.rebuild import kr3_profit_zone_study_v1 as krstudy
from backend.research.rebuild import squeeze_kr3_native_sleeve_v1 as arbiter

RULE_ID = "SQUEEZE_KR3_UNIFIED_V1_FUTURE_DUAL_GENERATOR"
CORE_RULE = capreuse.RULE
DONOR_RULE = c54.RULES["B"]
ARCHITECTURE = (
    "CAPREUSE82_CAUSAL_CORE_PRIORITY OR C54_B_CAUSAL_DONOR_WHEN_CORE_FLAT; "
    "LATER_CORE_ENTRY_PREEMPTS_DONOR_AT_OBSERVABLE_OPEN"
)


def _tag(rows: Sequence[Mapping[str, Any]], symbol: str, component: str) -> list[dict[str, Any]]:
    out=[]
    for row in rows:
        item=deepcopy(dict(row))
        item["symbol"]=symbol
        item["unified_component"]=component
        item["unified_rule_id"]=RULE_ID
        out.append(item)
    return out


def generate_symbol_campaigns(
    rows: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    eval_start_ms: int,
    eval_end_ms: int,
    cost_model: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate both frozen component streams from the same completed-bar packet.

    Returned campaigns are causal generator outputs. Nothing here grants G5
    credit; the caller must separately enforce the post-merge qualification
    boundary, source/cost persistence and lifecycle completeness.
    """
    core_raw=capreuse.replay(
        rows,
        eval_start_ms=eval_start_ms,
        eval_end_ms=eval_end_ms,
        cost=deepcopy(cost_model),
        enabled=True,
    )
    bundle=krstudy.p.d.build_bundle(
        rows,
        krstudy.p.d.PARENT_SPEC,
        eval_start_ms=eval_start_ms,
        eval_end_ms=eval_end_ms,
    )
    donor_raw=c54.replay(
        rows,
        bundle,
        eval_start_ms=eval_start_ms,
        eval_end_ms=eval_end_ms,
        cost_model=deepcopy(cost_model),
        mode="B",
        enabled=True,
        reference_checkpoint=None,
    )
    core_rows=_tag(core_raw.get("trades",[])+core_raw.get("open_positions",[]),symbol,"CAPREUSE82_CORE")
    donor_rows=_tag(donor_raw.get("trades",[])+donor_raw.get("open_positions",[]),symbol,"C54_B_DONOR")
    plan=arbiter.chronological_plan(core_rows,donor_rows)
    return {
        "schema":"zel.squeeze_kr3.future_dual_generator.symbol.v1",
        "rule_id":RULE_ID,
        "architecture":ARCHITECTURE,
        "symbol":symbol,
        "core_rule":CORE_RULE,
        "donor_rule":DONOR_RULE,
        "core_raw":core_raw,
        "donor_raw":donor_raw,
        "core_campaigns":core_rows,
        "donor_campaigns":donor_rows,
        "arbitration_plan":plan,
        "historical_membership_runtime_dependency":False,
        "future_bar_access":False,
        "formal_credit":0,
        "execution_authority":"NONE",
        "order_authority":"BLOCKED",
        "live_trade_authority":"BLOCKED",
    }


def invariant_receipt() -> dict[str, Any]:
    return {
        "schema":"zel.squeeze_kr3.future_dual_generator.invariant.v1",
        "rule_id":RULE_ID,
        "architecture":ARCHITECTURE,
        "core_module":"c70_tm_capreuse_v1",
        "core_rule":CORE_RULE,
        "donor_module":"kr3_c51_entry_context_v1",
        "donor_rule":DONOR_RULE,
        "donor_mode":"B",
        "donor_exact_rule":"0 < (close-EMA20)/prior_ATR14 <= 1",
        "arbiter_module":"squeeze_kr3_native_sleeve_v1",
        "core_priority":True,
        "donor_requires_core_flat":True,
        "later_core_entry_preempts_donor":True,
        "saved_campaign_membership_input":False,
        "threshold_retune":False,
        "symbol_year_exception":False,
        "paid_ai":0,
        "formal_credit":0,
        "execution_authority":"NONE",
        "orders":0,
        "live":0,
    }


def self_test() -> int:
    r=invariant_receipt()
    assert r["core_rule"]=="C70_TM_CAPREUSE_V1"
    assert r["donor_rule"]=="KR3_C51_ENTRY_CONTEXT_B_V1"
    assert r["core_priority"] and r["donor_requires_core_flat"] and r["later_core_entry_preempts_donor"]
    assert r["saved_campaign_membership_input"] is False
    assert r["threshold_retune"] is False and r["formal_credit"]==0
    print("PASS_SQUEEZE_KR3_FUTURE_DUAL_GENERATOR_BINDING")
    return 0


if __name__=="__main__":
    raise SystemExit(self_test())
