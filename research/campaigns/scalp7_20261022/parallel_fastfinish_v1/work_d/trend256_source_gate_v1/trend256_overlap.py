#!/usr/bin/env python3
"""Read-only closed-row overlap; stamped intervals are not observed fill intervals.

Reuses the pinned D contribution code. Native strategy/economic code is never
imported, prices are never fetched, and no allocation or combined Net is made.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import sys
import types
from collections import defaultdict
from pathlib import Path

CONTRIBUTION_SHA256 = "1b0a7bedc97d75f14498518e5d5783a4907d1368a2d21891f98838e6ec6e8e56"
HOUR_MS = 3_600_000
LANES = ("long256", "liquid123")


def load_contribution(path):
    """Verify bytes BEFORE executing this read-only library, not a native engine."""
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONTRIBUTION_SHA256:
        raise ValueError("CONTRIBUTION_SOURCE_SHA256_MISMATCH")
    module = types.ModuleType("verified_work_d_contribution")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def attribution_module():
    path = Path(__file__).with_name("trend256_attribution.py")
    spec = importlib.util.spec_from_file_location("trend256_overlap_attribution", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def adapt_rows(receipt, lane, contribution, row_identity, exit_extra_ms=0):
    """A lossy TIME-ONLY adapter: no independent ID or available outcome invented."""
    if exit_extra_ms not in (0, HOUR_MS):
        raise ValueError("ONLY_STORED_STAMP_OR_ONE_SOURCE_BAR_MODEL")
    identity = receipt.get("challenger_id", receipt.get("candidate_id"))
    records = []
    for row in receipt["trades"]:
        records.append({"identity":identity,"partition":"rolling","symbol":row["symbol"],
            "side":1 if row["side"] == "long" else -1,
            "position_id":row_identity(row),"opportunity_id":None,
            "signal_ts_ms":row["signal_ts"],"entry_ts_ms":row["entry_ts"],
            "exit_ts_ms":row["exit_ts"]+exit_extra_ms,"outcome_available_ts_ms":None,
            "gross_bps":None,"cost_bps":None,"net_bps":None,"regime":"UNKNOWN"})
    source = {"label":lane,"identity":identity,"identity_field":"identity",
              "array":"trades","partition":"rolling","expected_rows":len(records)}
    normalized, audit = contribution.normalize(source, {"trades":records,"unresolved":[]})
    return normalized, audit


def source_windows(receipts, contribution):
    lanes = {}
    all_windows = []
    for lane, receipt in receipts.items():
        if receipt["source"]["interval"] != "1h":
            raise ValueError("SOURCE_INTERVAL_MUST_BE_FROZEN_1H")
        symbols = []
        for source in receipt["source"]["symbols"]:
            start = source["first_post_boundary_ts"]
            last = source["last_post_boundary_ts"]
            if isinstance(start,bool) or isinstance(last,bool) or not isinstance(start,int) or not isinstance(last,int) or last < start:
                raise ValueError("INVALID_SOURCE_LABEL_BOUND")
            symbols.append({"symbol":source["symbol"],"first_bar_open_ms":start,"last_bar_open_ms":last,
                "model_end_exclusive_ms":last+HOUR_MS,"first_bar_open_utc":contribution.iso(start),
                "last_bar_open_utc":contribution.iso(last),"model_end_exclusive_utc":contribution.iso(last+HOUR_MS),
                "reported_bars":source["bars_post_boundary"]})
            all_windows.append((start,last+HOUR_MS))
        lanes[lane] = {"declared_boundary_utc":receipt["boundary_utc"],
            "prospective_boundary_utc":receipt["prospective_boundary_utc"],"symbols":symbols,
            "source_envelope_utc":[contribution.iso(min(x["first_bar_open_ms"] for x in symbols)),
                                   contribution.iso(max(x["model_end_exclusive_ms"] for x in symbols))]}
    start,end = max(a for a,b in all_windows),min(b for a,b in all_windows)
    if end <= start:
        raise ValueError("NO_COMMON_SOURCE_LABEL_ENVELOPE")
    return {"lanes":lanes,"comparison_window_utc":[contribution.iso(start),contribution.iso(end)],
        "comparison_start_ms":start,"comparison_end_exclusive_ms":end,
        "derivation":"Intersection of every reported symbol envelope [first_bar_open,last_bar_open+1h).",
        "qualification":"Metadata envelope only. No OHLC byte archive, continuity, actual outcome availability or independent OOS is certified. Declared boundaries precede retained 1000-bar ranges."}


def compact_pairs(pairs):
    return [{"long256_row":p["a"] if p["a"]["label"]=="long256" else p["b"],
             "liquid123_row":p["b"] if p["b"]["label"]=="liquid123" else p["a"],
             "start_ms":p["start_ms"],"end_ms":p["end_ms"],
             "model_overlap_minutes":p["overlap_minutes"],"side_relation":p["side_relation"]} for p in pairs]


def interval_report(rows_by_lane, start, end, contribution):
    diagnostics = contribution.collisions(rows_by_lane["long256"]+rows_by_lane["liquid123"],start,end)
    pairs = diagnostics["cross_strategy_same_symbol_holding_pairs"]
    same = [p for p in pairs if p["side_relation"]=="same"]
    touched = {lane:{r["key"] for p in same for r in (p["a"],p["b"]) if r["label"]==lane} for lane in LANES}
    return {"same_symbol_same_side_pairs":len(same),
        "long256_rows_with_overlap":len(touched["long256"]),
        "liquid123_rows_with_overlap":len(touched["liquid123"]),
        "liquid123_closed_row_denominator":len(rows_by_lane["liquid123"]),
        "opposite_side_pairs":len(pairs)-len(same),"pairs":compact_pairs(pairs),
        "measured_physical_overlap":None,"measured_simultaneous_outcomes":None,
        "qualification":"Overlap in the explicitly named timestamp model, not measured execution occupancy."}


def legacy_overlap(rows_by_lane):
    """Reproduce the old predicate and expose its zero-length interval caveat."""
    pairs=[];point_pairs=[]
    for a in rows_by_lane["long256"]:
        for b in rows_by_lane["liquid123"]:
            if a["symbol"] != b["symbol"] or a["side"] != b["side"]:
                continue
            if a["entry_ts_ms"] < b["exit_ts_ms"] and b["entry_ts_ms"] < a["exit_ts_ms"]:
                detail={"long256_key":a["key"],"liquid123_key":b["key"],"symbol":a["symbol"],
                    "long256_entry_ms":a["entry_ts_ms"],"long256_exit_label_ms":a["exit_ts_ms"],
                    "liquid123_entry_ms":b["entry_ts_ms"],"liquid123_exit_label_ms":b["exit_ts_ms"]}
                pairs.append(detail)
                if max(a["entry_ts_ms"],b["entry_ts_ms"]) >= min(a["exit_ts_ms"],b["exit_ts_ms"]):
                    point_pairs.append(detail)
    return {"predicate":"A.entry < B.exit_stamp AND B.entry < A.exit_stamp; assumes nonempty intervals",
        "pairs":len(pairs),"long256_rows_with_overlap":len({p["long256_key"] for p in pairs}),
        "liquid123_rows_with_overlap":len({p["liquid123_key"] for p in pairs}),
        "liquid123_closed_row_denominator":len(rows_by_lane["liquid123"]),
        "zero_span_pairs_not_strict_positive_intersections":point_pairs,
        "qualification":"Historical arithmetic reproduction only; zero-span stamped rows violate the nonempty-interval assumption. No physical-fill or portfolio claim."}


def pearson(x,y):
    if len(x)!=len(y) or len(x)<2:
        return None
    mx,my=math.fsum(x)/len(x),math.fsum(y)/len(y)
    xx=math.fsum((v-mx)**2 for v in x);yy=math.fsum((v-my)**2 for v in y)
    return math.fsum((a-mx)*(b-my) for a,b in zip(x,y))/math.sqrt(xx*yy) if xx and yy else None


def exit_bar_daily_diagnostic(receipts,start,end,contribution):
    values={};counts={}
    for lane,receipt in receipts.items():
        grouped=defaultdict(list)
        for row in receipt["trades"]:
            if start <= row["exit_ts"] < end:
                grouped[contribution.date_at(row["exit_ts"],"UTC")].append(row["net_bps"])
        values[lane]={d:math.fsum(vs) for d,vs in grouped.items()}
        counts[lane]={d:len(vs) for d,vs in grouped.items()}
    dates={lane:set(values[lane]) for lane in LANES}
    union=dates["long256"]|dates["liquid123"];intersection=dates["long256"]&dates["liquid123"]
    all_dates=[b["date"] for b in contribution.calendar_bins(start,end,"UTC")]
    comparisons={}
    for name,support in (("exit_date_union_zero_filled",sorted(union)),
                         ("both_have_exit_rows_intersection",sorted(intersection)),
                         ("all_common_window_calendar_dates_zero_filled",all_dates)):
        x=[values["long256"].get(d,0.0) for d in support]
        y=[values["liquid123"].get(d,0.0) for d in support]
        comparisons[name]={"days":len(support),"dates":support,"pearson":pearson(x,y),
            "both_saved_daily_net_negative_days":sum(a<0 and b<0 for a,b in zip(x,y))}
    return {"time_axis":"stored exit-bar UTC date, NOT available outcome date",
        "comparisons":comparisons,
        "daily_rows":[{"date":d,"long256_exit_rows":counts["long256"].get(d,0),
            "liquid123_exit_rows":counts["liquid123"].get(d,0),
            "long256_saved_net_trade_bps":values["long256"].get(d,0.0),
            "liquid123_saved_risk_scaled_net_bps":values["liquid123"].get(d,0.0)} for d in all_dates],
        "units":"Each stream retains its own saved units. Liquid123 already has its native portfolio_risk_scale; no unscale, weighted mixture or combined Net is computed.",
        "use":"Retrospective co-movement only, no fitted cutoff, allocation rule, causal feature or evidence of independent opportunity.",
        "measured_simultaneous_losses":None}


def build_report(receipts,contribution,attribution):
    windows=source_windows(receipts,contribution)
    start,end=windows["comparison_start_ms"],windows["comparison_end_exclusive_ms"]
    conventions={};audits={}
    for name,extra in (("stored_exit_stamp_half_open",0),("exit_bar_end_upper_model",HOUR_MS)):
        rows={}
        for lane in LANES:
            rows[lane],audit=adapt_rows(receipts[lane],lane,contribution,attribution.identity,extra)
            if not extra:audits[lane]=audit
        conventions[name]={"rows":rows,"report":interval_report(rows,start,end,contribution)}
    stored=conventions["stored_exit_stamp_half_open"]["rows"]
    exact=[]
    for a in stored["long256"]:
        for b in stored["liquid123"]:
            if (a["symbol"],a["side"],a["entry_ts_ms"]) == (b["symbol"],b["side"],b["entry_ts_ms"]):
                exact.append({"long256_key":a["key"],"liquid123_key":b["key"]})
    coverage={lane:{zone:contribution.coverage(stored[lane],start,end,zone) for zone in ("UTC","Europe/Berlin")} for lane in LANES}
    additions={}
    for zone in ("UTC","Europe/Berlin"):
        a=set(coverage["long256"][zone]["entry_dates"]);b=set(coverage["liquid123"][zone]["entry_dates"])
        additions[zone]={"liquid123_entry_dates_outside_long256":sorted(b-a),
            "long256_entry_dates_outside_liquid123":sorted(a-b),"shared_entry_dates":sorted(a&b)}
    inherited=receipts["long256"]["native_policy_ownership"]
    return {"schema_version":"zel.d.trend256.saved_overlap.v1", "state":"SOURCE_FEATURE_BLOCKED",
        "classification":"SAVED_CLOSED_ROW_DIAGNOSTIC_NO_PORTFOLIO_OR_NEW_ECONOMICS",
        "reused_module":{"file":"contribution_report.py","sha256":CONTRIBUTION_SHA256,
            "functions":["normalize","collisions","coverage","opportunity_stats","calendar_bins","date_at","iso"]},
        "input_bindings":{lane:copy.deepcopy(attribution.PINS[lane]) for lane in LANES},
        "source_windows":windows,"normalization_audit":audits,"coverage":coverage,
        "additional_entry_dates":additions,
        "opportunities":contribution.opportunity_stats(stored["long256"]+stored["liquid123"],start,end),
        "exact_same_symbol_side_entry_timestamp_pairs":exact,
        "holding_models":{name:v["report"] for name,v in conventions.items()},
        "legacy_stamp_predicate_reproduction":legacy_overlap(stored),
        "exit_stamp_ambiguity":{"native_clock":"exit_ts is native bar-open label; intrabar execution/availability timestamp absent",
            "stored_stamp_convention":"Strict [entry_ts,exit_ts); zero-span labels have empty intervals, not proved zero holding time.",
            "upper_model":"[entry_ts,exit_ts+1h); one frozen source interval, an upper model only within that exit bar. No latency/delivery or cross-bar physical bound asserted.",
            "zero_span_closed_rows":{lane:sum(r["entry_ts"]==r["exit_ts"] for r in receipts[lane]["trades"]) for lane in LANES},
            "outcome_available_ts":None,"measured_simultaneous_outcomes":None},
        "exit_bar_daily_diagnostic":exit_bar_daily_diagnostic(receipts,start,end,contribution),
        "inherited_parent_scope_excluded_from_closed_comparison":{
            "long256_parent_admitted_completed":inherited["admitted_completed_trade_count"],
            "long256_parent_open":len(receipts["long256"]["open_intents"]),
            "long256_parent_rejected":len(receipts["long256"]["ownership_rejected_intents"]),
            "not_child_admission_or_occupancy_counts":True,
            "reason":"Long-only256 is a closed-row parent subset. Copied parent open/rejected records cannot be allocated to it or counted as additional opportunities."},
        "shared_account":{"status":"UNKNOWN","NAV":None,"MTM_DD":None,"incremental_net":None,
            "independent_eligible_entries":None,"combined_net":None,"allocation_run":False,
            "reason":"No shared-state replay, capital/mark path or observed outcome clock; different saved risk units remain separate."},
        "activity":{"market_API_calls":0,"native_strategy_imports":0,"strategy_replays":0,"new_FULL":0,"orders":0},
        "limitations":["Neither 106/123 legacy overlap nor correlations select a strategy or prove portfolio suitability.",
            "Saved closed rows omit changed admission/occupancy opportunities; a zero-entry date is not proof of absent signals.",
            "The common source-envelope denominator includes all intersected UTC/Berlin dates and partial edge dates; exit-active-date correlation is separately labelled.",
            "No output adds or averages the two saved economic streams, invents 50:50 sizing, or promotes trading authority."]}


def run(long_only_receipt,liquid_receipt,contribution_module,output=None):
    contribution=load_contribution(contribution_module)
    attribution=attribution_module()
    receipts={"long256":attribution.load_verified(long_only_receipt,"long256"),
              "liquid123":attribution.load_verified(liquid_receipt,"liquid123")}
    report=build_report(receipts,contribution,attribution)
    if output is not None:
        with Path(output).open("x",encoding="utf-8") as handle:
            json.dump(report,handle,indent=2,sort_keys=True,allow_nan=False)
            handle.write("\n")
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long-only-receipt",required=True)
    parser.add_argument("--liquid-receipt",required=True)
    parser.add_argument("--contribution-module",required=True)
    parser.add_argument("--output",help="New JSON path only; existing files are never overwritten")
    args=parser.parse_args(argv)
    report=run(args.long_only_receipt,args.liquid_receipt,args.contribution_module,args.output)
    print(json.dumps(report,indent=2,sort_keys=True,allow_nan=False))


if __name__=="__main__":main()
