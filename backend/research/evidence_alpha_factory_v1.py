#!/usr/bin/env python3
"""
ZEL Evidence-Derived Alpha Factory V1
Research-only control plane for five stages:
1 Evidence Harvest -> 2 Consensus Base -> 3 Incremental Micro -> 4 Full Replay -> 5 Fresh OOS.

This module does not grant execution, order, selection, or promotion authority.
It validates provenance and generates deterministic manifests. The actual replay
adapter must explicitly provide metrics before Stage 3/4/5 can advance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

SCHEMA = "zel.evidence_alpha_factory.v1"
RESEARCH_ONLY = True
EXECUTION_AUTHORITY = "NONE"
ORDER_AUTHORITY = "BLOCKED"
PROMOTION_AUTHORITY = False
SELECTION_AUTHORITY = False

CORE_COMPONENTS = {
    "htf_trend_alignment", "regime_filter", "pullback_retest", "breakout_confirmation",
    "momentum_persistence", "volatility_normalization", "volume_confirmation",
    "liquidity_confirmation", "cost_hurdle", "atr_invalidation", "time_stop",
    "no_trade_zone", "long_short_asymmetry",
}
SOURCE_WEIGHTS = {"academic": 5.0, "open_source_strategy": 3.0, "community": 1.5, "video": 1.0}
FAMILY_MIN_SAMPLES = {
    "trend_pullback_continuation": 20,
    "volatility_breakout": 20,
    "liquidity_reclaim_reversal": 16,
    "htf_structure_ltf_execution": 16,
    "cost_aware_momentum": 20,
}

@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: List[str]

def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def _sha(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()

def validate_evidence(records: List[Dict[str, Any]]) -> None:
    if len(records) < 8:
        raise SystemExit("FAIL_EVIDENCE_TOO_SMALL: need >=8 independent records")
    ids=set(); source_types=set(); academic=0
    for r in records:
        required=("id","title","source_type","url","claim","components","independent_group")
        miss=[k for k in required if not r.get(k)]
        if miss: raise SystemExit(f"FAIL_EVIDENCE_FIELDS {r.get('id')} missing={miss}")
        if r["id"] in ids: raise SystemExit(f"FAIL_DUPLICATE_EVIDENCE_ID {r['id']}")
        ids.add(r["id"])
        if r["source_type"] not in SOURCE_WEIGHTS: raise SystemExit(f"FAIL_UNKNOWN_SOURCE_TYPE {r['source_type']}")
        source_types.add(r["source_type"]); academic += int(r["source_type"]=="academic")
        unknown=set(r["components"])-CORE_COMPONENTS
        if unknown: raise SystemExit(f"FAIL_UNKNOWN_COMPONENTS {r['id']} {sorted(unknown)}")
        pop=r.get("popularity",{})
        if pop.get("verified") and pop.get("metric") not in {"views","downloads","likes","upvotes","favorites"}:
            raise SystemExit(f"FAIL_POPULARITY_METRIC {r['id']}")
    if academic < 3: raise SystemExit("FAIL_EVIDENCE_ACADEMIC_FLOOR: need >=3 academic sources")
    if len(source_types) < 3: raise SystemExit("FAIL_EVIDENCE_DIVERSITY: need >=3 source types")

def component_consensus(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups=defaultdict(set); score=Counter(); mentions=Counter()
    for r in records:
        w=SOURCE_WEIGHTS[r["source_type"]]
        for c in r["components"]:
            groups[c].add(r["independent_group"]); score[c]+=w; mentions[c]+=1
    out=[]
    for c in CORE_COMPONENTS:
        out.append({"component":c,"weighted_score":round(score[c],3),"mentions":mentions[c],
                    "independent_groups":len(groups[c]),"consensus":len(groups[c])>=2 and mentions[c]>=2})
    return sorted(out,key=lambda x:(x["consensus"],x["weighted_score"],x["independent_groups"]), reverse=True)

def validate_specs(specs: List[Dict[str, Any]], evidence_ids: set[str]) -> None:
    if not (3 <= len(specs) <= 8): raise SystemExit("FAIL_SPEC_COUNT: expected 3..8 alpha families")
    fams=set()
    for s in specs:
        req=("id","family","timeframes","side_policy","entry","regime","invalidation","exit","cost_hurdle","no_trade","provenance","calibration")
        miss=[k for k in req if not s.get(k)]
        if miss: raise SystemExit(f"FAIL_SPEC_FIELDS {s.get('id')} missing={miss}")
        if s["family"] in fams: raise SystemExit(f"FAIL_DUPLICATE_FAMILY {s['family']}")
        fams.add(s["family"])
        if s["family"] not in FAMILY_MIN_SAMPLES: raise SystemExit(f"FAIL_UNKNOWN_FAMILY {s['family']}")
        if not set(s["provenance"]).issubset(evidence_ids): raise SystemExit(f"FAIL_UNKNOWN_PROVENANCE {s['id']}")
        if len(set(s["provenance"])) < 2: raise SystemExit(f"FAIL_PROVENANCE_FLOOR {s['id']}: need >=2 independent evidence ids")
        if any(tf not in {"5m","15m","1h","4h"} for tf in s["timeframes"]): raise SystemExit(f"FAIL_TIMEFRAME {s['id']}")
        if s["calibration"] != "calibrate_micro": raise SystemExit(f"FAIL_FIXED_UNSOURCED_THRESHOLD {s['id']}: use calibrate_micro")

def micro_gate(metrics: Dict[str, Any], control: Dict[str, Any], family: str) -> GateResult:
    reasons=[]; n=int(metrics.get("sample_count",0)); floor=FAMILY_MIN_SAMPLES[family]
    if n < floor: reasons.append(f"sample_count {n} < floor {floor}")
    if float(metrics.get("net_R",-1e18)) <= 0: reasons.append("net_R <= 0")
    if float(metrics.get("expectancy_R",-1e18)) <= 0: reasons.append("expectancy_R <= 0")
    wr=float(metrics.get("win_rate_pct",-1e18)); cwr=float(control.get("win_rate_pct",-1e18))
    if wr <= cwr: reasons.append(f"WR {wr} <= control {cwr}")
    pf=metrics.get("profit_factor")
    if pf is None or float(pf) <= 1.0: reasons.append("PF <= 1.0")
    if metrics.get("costs_included") is not True: reasons.append("costs_included != true")
    if not metrics.get("cost_model_id"): reasons.append("missing cost_model_id")
    dd=float(metrics.get("max_drawdown_R",1e18)); dd_limit=float(metrics.get("dd_guard_R",1e18))
    if dd > dd_limit: reasons.append(f"DD {dd} > guard {dd_limit}")
    return GateResult(not reasons,reasons)

def stage3_plan(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    variants=["BASE","+adx","+volume","+vwap_context","+rsi_exhaustion"]; rows=[]
    for s in specs:
        for tf in [x for x in s["timeframes"] if x in {"5m","15m"}]:
            for v in variants:
                rows.append({"candidate_id":f"{s['id']}::{tf}::{v}","family":s["family"],"timeframe":tf,
                             "variant":v,"single_axis_delta":None if v=="BASE" else v[1:],
                             "symbols":["BTCUSDT","ETHUSDT"],"windows":["W1","W2","W3"],
                             "fill_model":"NEXT_BAR_OPEN","costs_required":True,"micro_only":True})
    return {"schema_version":SCHEMA,"stage":3,"state":"READY_FOR_REPLAY_ADAPTER","research_only":True,
            "hard_gate":"net_R>0 AND WR>control_WR AND expectancy_R>0 AND PF>1 AND DD<=guard AND costs_included",
            "one_axis_only":True,"rows":rows}

def build_manifests(evidence_path: Path, specs_path: Path, out_dir: Path) -> None:
    evidence=_read(evidence_path); specs=_read(specs_path); records=evidence["records"]; families=specs["families"]
    validate_evidence(records); validate_specs(families,{r["id"] for r in records}); consensus=component_consensus(records)
    stage1={"schema_version":SCHEMA,"stage":1,"state":"PASS_EVIDENCE_HARVEST","record_count":len(records),
            "consensus":consensus,"evidence_sha256":_sha(evidence),"research_only":RESEARCH_ONLY,
            "execution_authority":EXECUTION_AUTHORITY,"order_authority":ORDER_AUTHORITY,
            "promotion_authority":PROMOTION_AUTHORITY,"selection_authority":SELECTION_AUTHORITY}
    stage2={"schema_version":SCHEMA,"stage":2,"state":"PASS_CONSENSUS_BASE","family_count":len(families),
            "families":[s["id"] for s in families],"spec_sha256":_sha(specs),"research_only":True,
            "rule":"no family becomes executable/promotable before Stage3 metrics"}
    stage3=stage3_plan(families)
    stage4={"schema_version":SCHEMA,"stage":4,"state":"LOCKED_WAITING_STAGE3_SURVIVORS",
            "scope":"5m/15m multi-symbol, regime/side/cost windows",
            "unlock_requires":"stage3_survivors.json with >=1 PASS_MICRO candidate"}
    stage5={"schema_version":SCHEMA,"stage":5,"state":"LOCKED_FRESH_OOS","windows":["W4","W5"],
            "untouched_required":True,"unlock_requires":"stage4_survivor AND fresh-window fingerprint not seen in stages1-4"}
    for n,obj in ((1,stage1),(2,stage2),(3,stage3),(4,stage4),(5,stage5)): _write(out_dir/f"stage{n}_manifest.json",obj)
    print(f"PASS_STAGE1 evidence={len(records)}"); print(f"PASS_STAGE2 families={len(families)}")
    print(f"READY_STAGE3 candidates={len(stage3['rows'])}"); print("LOCK_STAGE4 waiting_stage3_survivor")
    print("LOCK_STAGE5 fresh_oos"); print("PASS_RESEARCH_ONLY execution=NONE order=BLOCKED promotion=false selection=false")

def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--evidence",required=True); p.add_argument("--specs",required=True); p.add_argument("--out",required=True); a=p.parse_args()
    build_manifests(Path(a.evidence),Path(a.specs),Path(a.out))

if __name__=="__main__": main()
