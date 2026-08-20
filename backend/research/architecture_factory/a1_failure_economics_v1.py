#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Mapping


def analyze(dev: Mapping[str, Any], queue: list[Mapping[str, Any]], repair_budget: int = 3) -> dict[str, Any]:
    by_id = {str(x.get("candidate_id") or ""): x for x in queue}
    rows: list[dict[str, Any]] = []
    for r in dev.get("rows") or []:
        if r.get("state") != "FAIL_DEVELOPMENT_ECONOMICS":
            continue
        m = r.get("metrics") if isinstance(r.get("metrics"), Mapping) else {}
        gross = float(m.get("gross_expectancy_bps") or 0.0)
        net = float(m.get("net_expectancy_bps") or 0.0)
        pf = float(m.get("profit_factor") or 0.0)
        trades = int(m.get("trades") or 0)
        cost = float(m.get("cost_bps_per_trade") or dev.get("cost_bps_per_trade") or 0.0)
        gap = max(0.0, -net)
        if trades < 12:
            failure_class = "INSUFFICIENT_EVENTS"
            route = "NO_AI_WAIT_OR_REPLACE"
            repairable = False
        elif gross <= 0.0:
            failure_class = "NO_GROSS_EDGE"
            route = "REPLACE_ARCHITECTURE"
            repairable = False
        elif net <= 0.0:
            failure_class = "COST_DOMINATED_GROSS_POSITIVE"
            route = "ONE_CAUSAL_REPAIR_ALLOWED"
            repairable = True
        elif pf <= 1.0:
            failure_class = "TAIL_OR_PAYOFF_FAILURE"
            route = "ONE_CAUSAL_REPAIR_ALLOWED"
            repairable = True
        else:
            failure_class = "OTHER_ECONOMIC_FAIL"
            route = "NO_AI"
            repairable = False
        c = by_id.get(str(r.get("candidate_id") or ""), {})
        rows.append({
            "candidate_id": r.get("candidate_id"),
            "strategy_id": r.get("strategy_id"),
            "provider": r.get("provider"),
            "failure_class": failure_class,
            "route": route,
            "repairable": repairable,
            "required_net_improvement_bps_per_trade": round(gap + 0.01, 6),
            "gross_expectancy_bps": gross,
            "net_expectancy_bps": net,
            "profit_factor": pf,
            "trades": trades,
            "cost_bps_per_trade": cost,
            "drawdown_bps": m.get("drawdown_bps"),
            "payoff": m.get("payoff"),
            "win_rate": m.get("win_rate"),
            "executable_spec": c.get("executable_spec"),
            "required_sources": c.get("required_sources"),
            "evidence_ids": c.get("evidence_ids"),
        })
    repairable = sorted(
        [x for x in rows if x["repairable"]],
        key=lambda x: (x["required_net_improvement_bps_per_trade"], -x["gross_expectancy_bps"], -x["trades"]),
    )
    selected = repairable[: max(0, int(repair_budget))]
    return {
        "schema_version": "zel.a1_failure_economics.v1",
        "economic_fail_count": len(rows),
        "no_gross_edge_count": sum(1 for x in rows if x["failure_class"] == "NO_GROSS_EDGE"),
        "cost_dominated_count": sum(1 for x in rows if x["failure_class"] == "COST_DOMINATED_GROSS_POSITIVE"),
        "tail_or_payoff_failure_count": sum(1 for x in rows if x["failure_class"] == "TAIL_OR_PAYOFF_FAILURE"),
        "single_repair_budget": int(repair_budget),
        "selected_for_single_repair": selected,
        "rows": rows,
        "rule": "Gross<=0 => no repair API; replace architecture. Gross>0 but Net<=0/PF<=1 => at most one causal repair, ranked by smallest break-even gap.",
    }


def self_test() -> int:
    dev={"cost_bps_per_trade":14,"rows":[
        {"candidate_id":"a","state":"FAIL_DEVELOPMENT_ECONOMICS","metrics":{"trades":20,"gross_expectancy_bps":8,"net_expectancy_bps":-6,"profit_factor":0.7}},
        {"candidate_id":"b","state":"FAIL_DEVELOPMENT_ECONOMICS","metrics":{"trades":20,"gross_expectancy_bps":-2,"net_expectancy_bps":-16,"profit_factor":0.2}},
    ]}
    x=analyze(dev,[{"candidate_id":"a"},{"candidate_id":"b"}],3)
    assert x["cost_dominated_count"]==1 and x["no_gross_edge_count"]==1
    assert [r["candidate_id"] for r in x["selected_for_single_repair"]]==["a"]
    print("PASS_A1_FAILURE_ECONOMICS_V1_SELF_TEST")
    return 0

if __name__ == "__main__":
    raise SystemExit(self_test())
