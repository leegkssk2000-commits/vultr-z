"""One frozen, source-compatible candidate; ordered fast-kill with no provider calls."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
from backend.research.architecture_factory import a1_common_source_semantic_guard_v1 as semantic
from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as factory
from backend.research.architecture_factory.g5a_source_admission_v1 import ROOT, AUTH, read, seal, file_sha
from backend.research.architecture_factory import g5a_stage_admission_v1 as admission
from backend.research.architecture_factory import g5a_development_data_v1 as data

OUTPUT = ROOT / "backend/research/architecture_factory/g5a_stage_candidate_terminal_v1.json"


def session_overlap(bar, spec):
    """Only the completed signal interval; DST comes from named local time zones."""
    start = datetime.fromtimestamp(bar["bar_open_ts"] / 1000, timezone.utc)
    end = datetime.fromtimestamp(bar["bar_close_ts"] / 1000, timezone.utc)
    london = ZoneInfo("Europe/London"); ny = ZoneInfo("America/New_York")
    for day in (start.date(), end.date()):
        if spec["weekdays_only"] and day.weekday() >= 5:
            continue
        def interval(key, zone):
            return [datetime.combine(day, time.fromisoformat(v), zone).astimezone(timezone.utc) for v in spec[key]]
        left, right = interval("london_session_local", london), interval("new_york_session_local", ny)
        if max(start,left[0],right[0]) < min(end,left[1],right[1]):
            return True
    return False


def features(rows, index, spec):
    lookback = spec["lookback_bars"]
    if index < lookback:
        return None
    window = rows[index-lookback:index+1]
    data.validate_history(window, rows[index]["bar_close_ts"])
    previous = window[:-1]; current = window[-1]
    mean_volume = sum(r["volume"] for r in previous) / len(previous)
    if mean_volume <= 0:
        return None
    return {"session_overlap_state": session_overlap(current,spec),
            "relative_total_volume_activity": current["volume"] / mean_volume,
            "pre_entry_breakout_continuation_structure": current["close"] > max(r["high"] for r in previous)}


def development_cost(entry_ms, exit_ms, symbol_cost, *, multiplier=1):
    # Inherit the existing 8h settlement counter and apply the observed P95 reserve
    # to every crossed settlement. This remains an explicitly declared proxy.
    from backend.research.rebuild.a1_rebuilt_bb_revert_evaluator_v1 import expected_funding_boundaries
    funding = expected_funding_boundaries(entry_ms,exit_ms) * symbol_cost["funding_p95_per_settlement_bps"]
    return multiplier * (symbol_cost["fee_bps"]+symbol_cost["spread_bps"]+symbol_cost["impact_bps"]+funding)


def require_before_cheap(bundle):
    for fn in (alpha.evaluate_p6,alpha.evaluate_p1,alpha.evaluate_p2,alpha.evaluate_p0):
        r=fn(bundle)
        if not r["passed"]:
            raise RuntimeError("FAST_KILL_BEFORE_ECONOMICS:"+r["gate"])


def freeze_candidate(stage, root=ROOT):
    dev=admission.require_development(stage,root); contract=read(data.CONTRACT,root); spec=contract["candidate_spec"]
    original=read("backend/research/architecture_factory/g5a_alpha_factory_latest.json",root)["next_experiment_candidate"]
    candidate={"candidate_id":spec["candidate_id"],"architecture_family":spec["family"],"mode":"NEW_ARCHITECTURE",
               "mechanism":"Hypothesis: continuation after a completed price breakout is concentrated in overlapping sessions with unusually high total activity.",
               "payer":"Hypothesized late price followers after a completed breakout; causal support remains subject to P0.",
               "entry_event":"Closed session-overlap bar closes above all prior lookback highs, with total volume above its prior mean; enter next bar open.",
               "direction_rule":"long","regime_owner":"London/New York overlapping session intervals",
               "invalidation":"Continuation fails to exceed realistic costs or fails controlled comparisons.",
               "required_sources":["ohlcv","volume"],"feature_names":spec["feature_ablations"],"parameters":spec,
               "dataset_sha256":dev["dataset_sha256"],"split_sha256":alpha.sha(dev["splits"]),
               "development_cost_binding_sha256":dev["receipt_sha256"],"source_contract_sha256":contract["receipt_sha256"],
               "implementation_sha256":file_sha(Path(__file__)),"original_MA001_candidate_sha256":original["candidate_sha256"],
               "MA001_mutated_in_place":False,"research_only":True,**AUTH}
    if semantic._semantic_blockers(candidate):
        raise RuntimeError("SOURCE_SEMANTIC_REJECT")
    score=factory.cosine(factory.token_vector(candidate),factory.token_vector(original))
    if score > 0.85:
        raise RuntimeError("DUPLICATE_CAUSAL_CANDIDATE")
    candidate["candidate_sha256"]=alpha.sha(candidate)
    source_rows=[{"name":s,"available":True,"fresh":False,"historical_immutable":True,"semantic_valid":True,
                  "proxy":False,"source_sha":dev["dataset_sha256"]} for s in ("ohlcv","volume")]
    evidence=read("backend/research/architecture_factory/g5a_ma001_alpha_proof_bundle_v1.json",root)["primary_evidence"]
    # Retain the actual repository audit. Descriptive activity/price-discovery
    # evidence is not silently upgraded to proof of after-cost continuation.
    primary={"supports":evidence.get("supports",[]),"audited_references":evidence["audited_references"],
             "assessment":"The new source semantics are valid; independent causal evidence for continuation is still unestablished.",
             "prior_audit_sha256":alpha.sha(evidence)}
    feature_map=[
        {"name":"session_overlap_state","mechanism":"Test concentration of continuation in overlapping sessions","observable":"signal-bar timestamps and frozen local-time calendars","direction":"allow overlap only","invalidation":"no conditional continuation advantage","entry_time_observable":True},
        {"name":"relative_total_volume_activity","mechanism":"Test unusually high total activity","observable":"closed total volume divided by prior closed-bar mean","direction":"above frozen baseline","invalidation":"activity does not improve after-cost continuation","entry_time_observable":True},
        {"name":"pre_entry_breakout_continuation_structure","mechanism":"Test continuation after prior price range breaks","observable":"signal close exceeds preceding lookback highs","direction":"long","invalidation":"breakout mean reverts or costs consume movement","entry_time_observable":True}]
    justification={"selection":"PRE_OUTCOME_DESIGN_PRIOR","lookback":"Prior closed-bar reference only; no fit to returns.",
                   "horizon":"Reuse the existing Break 6-bar time-stop horizon as a fixed development design, without tuning exits.",
                   "relative_volume":"Ratio to the prior mean; 1.0 is the identity reference.",
                   "sessions":"Explicit local-time design windows; no optimization of clock intervals.","contract_sha256":contract["receipt_sha256"]}
    params=[{"name":k,"value":spec[k],"provenance":"PURE_DESIGN_PRIOR","source_or_test_sha":contract["receipt_sha256"],
             "development_justification_sha":alpha.sha(justification),"selected_using_holdout":False}
            for k in ("lookback_bars","relative_volume_min_exclusive","max_hold_bars","london_session_local","new_york_session_local")]
    bundle={"candidate":candidate,"primary_evidence":primary,
            "feature_causal_map":{"features":feature_map,"redundant_pairs":[],"ablation_plan_complete":True},
            "parameter_provenance":{"numeric_parameter_inventory_complete":True,"parameters":params,"design_justification":justification},
            "source_implementation_reality":{"admission_stage":"G5A_DEVELOPMENT","sources":source_rows,
              "immutable_history_verified":True,"split_frozen_before_outcomes":True,"development_cost_model_bound":True,
              "development_data_sha":dev["dataset_sha256"],"formal_production_credit":0,
              "duplicate_count":0,"leakage_count":0,"timestamp_order_error_count":0,"integrity_defect_count":0,
              "verified_round_trip_cost_bps":dev["reference_round_trip_cost_bps"],"cost_authority_sha":dev["receipt_sha256"],
              "development_cost_model":"RESEARCH_ONLY_DEVELOPMENT_COST"}}
    gates={}; sequence=[]
    for name,fn in (("P6",alpha.evaluate_p6),("P1",alpha.evaluate_p1),("P2",alpha.evaluate_p2),("P0",alpha.evaluate_p0)):
        result=fn(bundle);gates[name]="PASS" if result["passed"] else "FAIL";sequence.append(result)
        if not result["passed"]:
            break
    for name in ("P0","P1","P2","P3","P4","P5","P6"):
        gates.setdefault(name,"NOT_RUN_PRIOR_GATE_REJECT")
    if all(gates.get(k)=="PASS" for k in ("P6","P1","P2","P0")):
        raise RuntimeError("UNEXPECTED_PRIMARY_EVIDENCE_CHANGE_REQUIRES_SEPARATE_REVIEWED_CANDIDATE")
    failure=sequence[-1]
    return seal({"schema_version":"zel.g5a.stage_candidate_terminal.v1","candidate":candidate,"bundle":bundle,"gates":gates,
                 "fast_kill_sequence":sequence,"decision":"G5A_ALPHA_PROOF_REJECT","terminal":True,
                 "first_failed_gate":failure["gate"],"failure_signature":alpha.sha({"candidate_sha":candidate["candidate_sha256"],"failure":failure}),
                 "economic_state":"NOT_RUN_PRIOR_GATE_REJECT","base_net_bps":None,"expectancy_bps":None,"PF":None,"cost2x_net_bps":None,
                 "purged_OOS":"UNTOUCHED","negative_controls":"NOT_RUN_P0_REJECT","P5_paid_calls":0,
                 "family_distinct_candidates":1,"max_distinct_candidates_per_family":3,"dedup_cosine_threshold":0.85,
                 "cosine_to_original_MA001":score,"same_signature_recall":False,"paid_AI_calls":0,
                 "deterministic_full_replay_authorized":False,"G5B_boundary_created":False,"G5B_fresh_T":0,
                 "source_files_sha256":{p:file_sha(root/p) for p in [data.CONTRACT,"backend/research/architecture_factory/g5a_alpha_factory_latest.json","backend/research/architecture_factory/g5a_ma001_alpha_proof_bundle_v1.json"]},
                 "next":"ROUTE_TO_DISTINCT_CAUSAL_CANDIDATE_WITH_PRIMARY_MECHANISM_EVIDENCE",**AUTH})


def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=OUTPUT);a=p.parse_args()
    result=freeze_candidate(read(admission.OUT))
    data.write_once(a.output,result)
    print(json.dumps({"candidate":result["candidate"]["candidate_id"],"gates":result["gates"],"decision":result["decision"],"receipt_sha256":result["receipt_sha256"]}))


if __name__ == "__main__":
    main()
