#!/usr/bin/env python3
"""Pinned saved-ledger diagnostics. No prices, signals, allocation or execution.

Inputs describe one position lifecycle per row. Execution/management event rows
must reference that lifecycle and never add an opportunity or a second PnL.
Raw separately generated strategy ledgers remain separately generated ledgers.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import itertools
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
SCHEMA = "zel.work_d.contribution.v1"
EVENTS = {"partial_fill", "partial_exit", "dca", "handoff"}


def timestamp(value):
    if isinstance(value, bool):
        raise ValueError("boolean timestamp")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timestamp requires UTC offset")
        return int(dt.timestamp() * 1000)
    raise ValueError("timestamp must be integer milliseconds or offset ISO8601")


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


def date_at(ms, zone):
    return datetime.fromtimestamp(ms / 1000, ZoneInfo(zone)).date().isoformat()


def finite(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid finite " + name)
    return float(value)


def validate_manifest(manifest):
    if manifest.get("schema") != "zel.work_d.input.v1":
        raise ValueError("unsupported manifest schema")
    start, end = map(timestamp, manifest["window_utc"])
    if end <= start:
        raise ValueError("non-positive window")
    labels = []
    for source in manifest["sources"]:
        for field in ("label", "identity", "identity_field", "ref", "path", "sha256", "array", "partition", "cost", "row_semantics"):
            if not source.get(field):
                raise ValueError("missing source binding: " + field)
        if not re.fullmatch("[0-9a-f]{40}", source["ref"]) or not re.fullmatch("[0-9a-f]{64}", source["sha256"]):
            raise ValueError("source requires immutable ref and SHA256")
        if source["row_semantics"] != "one_position_lifecycle":
            raise ValueError("unsupported row semantics; owner must export lifecycle rows")
        if source["label"] == "UNCONSTRAINED_UNION":
            raise ValueError("reserved source label")
        if "evaluated_window_utc" in source and list(map(timestamp,source["evaluated_window_utc"])) != [start,end]:
            raise ValueError("source evaluated window differs from comparison window")
        cost = source["cost"]
        for field in ("model", "source_ref", "source_path", "source_sha256", "unit", "net_formula"):
            if not cost.get(field):
                raise ValueError("missing cost binding: " + field)
        if cost["unit"] != "equal_notional_trade_bps" or cost["net_formula"] != "gross_bps - multiplier * cost_bps":
            raise ValueError("incompatible cost units/formula")
        if not re.fullmatch("[0-9a-f]{40}", cost["source_ref"]) or not re.fullmatch("[0-9a-f]{64}", cost["source_sha256"]):
            raise ValueError("invalid immutable cost binding")
        labels.append(source["label"])
    if len(set(labels)) != len(labels) or not labels:
        raise ValueError("empty or duplicate source labels")
    baseline = manifest.get("baseline_labels", labels)
    if not baseline or len(baseline) != len(set(baseline)):
        raise ValueError("baseline labels must be nonempty and unique")
    if not set(baseline) <= set(labels):
        raise ValueError("unknown baseline label")
    return start, end


def normalize(source, payload):
    """Validate lifecycle records and collapse exact duplicate representations."""
    array = source["array"]
    if array not in payload or not isinstance(payload[array], list):
        raise ValueError("missing ledger array " + array)
    raw = list(payload[array])
    # Saved unresolved positions are distinct from closed rows. Never lose them.
    if array != "unresolved":
        unresolved = payload.get("unresolved", [])
        if not isinstance(unresolved, list):
            raise ValueError("invalid unresolved array")
        raw.extend(unresolved)
    for row in raw:
        if not isinstance(row, dict) or row.get("partition") not in {source["partition"], "rolling", "validation"}:
            raise ValueError("missing or unsupported partition; cannot silently drop a position")
    selected = [r for r in raw if r.get("partition") == source["partition"]]
    if "expected_rows" in source and len([r for r in payload[array] if r.get("partition") == source["partition"]]) != source["expected_rows"]:
        raise ValueError("selected source row count differs from binding")
    positions, events, duplicate_count = {}, [], 0
    for index, row in enumerate(selected):
        if row.get(source["identity_field"]) != source["identity"]:
            raise ValueError("identity mismatch for " + source["label"])
        if source.get("lineage_identity") and row.get("identity") != source["lineage_identity"]:
            raise ValueError("parent lineage identity mismatch")
        if source.get("source_execution_profile") and row.get("execution_profile") != source["source_execution_profile"]:
            raise ValueError("execution profile mismatch")
        event = row.get("event_type", "lifecycle")
        if event in EVENTS:
            if not row.get("parent_position_id"):
                raise ValueError("management event lacks parent_position_id")
            events.append(row)
            continue
        if event not in {"lifecycle", "pending"}:
            raise ValueError("unsupported event_type: " + str(event))
        symbol, side = row.get("symbol"), row.get("side")
        if not isinstance(symbol, str) or not symbol or isinstance(side, bool) or side not in (-1, 1):
            raise ValueError("symbol/side binding missing")
        signal = timestamp(row["signal_ts_ms"])
        nested = row.get("signal")
        if nested is not None:
            if not isinstance(nested, dict):
                raise ValueError("invalid nested signal")
            for field, expected in (("symbol", symbol), ("side", side), ("signal_ts_ms", signal)):
                if nested.get(field) != expected:
                    raise ValueError("nested signal mismatch: " + field)
            if "timeframe_min" in row and nested.get("timeframe_min") != row["timeframe_min"]:
                raise ValueError("nested signal timeframe mismatch")
            expected_identity = source.get("lineage_identity", source["identity"])
            if nested.get("identity") != expected_identity:
                raise ValueError("nested signal identity mismatch")
            meta = nested.get("meta", {})
            if not isinstance(meta, dict):
                raise ValueError("invalid signal metadata")
            available = meta.get("feature_available_ts_ms")
            if available is not None and timestamp(available) > signal:
                raise ValueError("future feature availability")
        entry = timestamp(row["entry_ts_ms"]) if row.get("entry_ts_ms") is not None else None
        exit_ts = timestamp(row["exit_ts_ms"]) if row.get("exit_ts_ms") is not None else None
        outcome = timestamp(row["outcome_available_ts_ms"]) if row.get("outcome_available_ts_ms") is not None else None
        if entry is None and (exit_ts is not None or outcome is not None):
            raise ValueError("unentered position cannot have exit/outcome")
        if entry is not None and signal > entry:
            raise ValueError("future signal timestamp")
        if exit_ts is not None and (entry is None or exit_ts < entry):
            raise ValueError("exit precedes entry")
        if outcome is not None and (exit_ts is None or outcome < exit_ts):
            raise ValueError("outcome precedes exit")
        gross, cost = finite(row.get("gross_bps"), "gross"), finite(row.get("cost_bps"), "cost")
        if cost is not None and cost < 0:
            raise ValueError("negative cost")
        supplied = finite(row.get("net_bps"), "net")
        if supplied is not None and gross is not None and cost is not None and not math.isclose(supplied, gross - cost, abs_tol=1e-7, rel_tol=1e-10):
            raise ValueError("net is inconsistent with gross minus cost")
        opportunity = row.get("opportunity_id")
        if opportunity is not None and (not isinstance(opportunity, str) or not opportunity.strip()):
            raise ValueError("opportunity_id must be a nonempty stable source string or null")
        position_id = row.get("position_id") or "|".join(map(str, (symbol, side, signal, entry)))
        key = source["label"] + ":" + str(position_id)
        item = dict(key=key, position_id=str(position_id), label=source["label"], identity=source["identity"],
                    symbol=symbol, side=side, signal_ts_ms=signal, entry_ts_ms=entry, exit_ts_ms=exit_ts,
                    outcome_available_ts_ms=outcome, gross_bps=gross, cost_bps=cost,
                    net1x=(gross-cost if gross is not None and cost is not None else None),
                    net2x=(gross-2*cost if gross is not None and cost is not None else None),
                    opportunity_id=opportunity, regime=row.get("regime", "UNKNOWN"))
        if key in positions:
            if positions[key] != item:
                raise ValueError("conflicting duplicate lifecycle " + key)
            duplicate_count += 1
        else:
            positions[key] = item
    ids = {p["position_id"] for p in positions.values()}
    if any(str(e["parent_position_id"]) not in ids for e in events):
        raise ValueError("management event has no authoritative lifecycle")
    return list(positions.values()), dict(raw_array_rows=len(payload[array]), partition_selected_rows=len(selected),
        excluded_partition_rows=len(raw)-len(selected), duplicate_lifecycle_rows=duplicate_count,
        management_event_rows=len(events), management_events_by_type=dict(Counter(r["event_type"] for r in events)))


def calendar_bins(start, end, zone):
    tz = ZoneInfo(zone)
    day = datetime.fromtimestamp(start / 1000, tz).date()
    last = datetime.fromtimestamp((end - 1) / 1000, tz).date()
    result = []
    while day <= last:
        a = datetime.combine(day, datetime.min.time(), tzinfo=tz)
        b = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        am, bm = int(a.timestamp()*1000), int(b.timestamp()*1000)
        lo, hi = max(start, am), min(end, bm)
        result.append(dict(date=day.isoformat(), start_ms=lo, end_ms=hi, start_utc=iso(lo), end_utc=iso(hi),
            covered_hours=(hi-lo)/3600000, nominal_day_hours=(bm-am)/3600000, partial_day=lo!=am or hi!=bm))
        day += timedelta(days=1)
    return result


def economics(rows, start, end):
    """Outcome-known window, equal-notional statistics. Never an allocation rule."""
    cohort = [r for r in rows if r["entry_ts_ms"] is not None and start <= r["entry_ts_ms"] < end]
    known = [r for r in cohort if r["outcome_available_ts_ms"] is not None and start <= r["outcome_available_ts_ms"] < end]
    missing = [r for r in known if r["net1x"] is None]
    complete = len(known) == len(cohort) and not missing
    answer = {"unit":"equal_notional_trade_bps", "state":"COMPLETE_SAVED_CLOSED_COHORT" if complete else "INCOMPLETE_UNKNOWN",
              "entered_positions":len(cohort), "outcomes_known":len(known), "missing_cost_or_gross":len(missing),
              "withheld_or_open_positions":len(cohort)-len(known), "net1x_trade_bps":None,"net2x_trade_bps":None,
              "known_subtotal_net1x_trade_bps":sum(r["net1x"] for r in known if r["net1x"] is not None),
              "known_subtotal_net2x_trade_bps":sum(r["net2x"] for r in known if r["net2x"] is not None)}
    for mult in (1, 2):
        field = f"net{mult}x"
        values = [r[field] for r in known if r[field] is not None]
        total = math.fsum(values)
        if complete:
            answer[f"net{mult}x_trade_bps"] = total
        by_outcome = defaultdict(float)
        for r in known:
            if r[field] is not None:
                by_outcome[r["outcome_available_ts_ms"]] += r[field]
        equity, peak, dd = 0.0, 0.0, 0.0
        for _, value in sorted(by_outcome.items()):
            equity += value; peak = max(peak, equity); dd = max(dd, peak-equity)
        answer[f"realized_dd{mult}x_trade_bps"] = dd if complete else None
        answer[f"pf{mult}x"] = (sum(x for x in values if x > 0) / -sum(x for x in values if x < 0)) if complete and any(x < 0 for x in values) else None
    answer["dd_kind"] = "simultaneous outcome cohorts netted; realized equal-notional trade-bps, NOT account or MTM DD"
    return answer


def coverage(rows, start, end, zone):
    bins = calendar_bins(start, end, zone)
    entries = Counter(date_at(r["entry_ts_ms"], zone) for r in rows if r["entry_ts_ms"] is not None and start <= r["entry_ts_ms"] < end)
    counts = [entries[b["date"]] for b in bins]
    best = {"days":0, "start_date":None, "end_date":None}
    run = 0
    for index, (b, count) in enumerate(zip(bins, counts)):
        if count == 0:
            run += 1
            if run > best["days"]:
                best = dict(days=run,start_date=bins[index-run+1]["date"],end_date=b["date"])
        else:
            run = 0
    n, total = len(counts), sum(counts)
    return {"calendar_days":n, "elapsed_24h_days":(end-start)/86400000,
        "entries":total,"entries_per_calendar_date":total/n,"entries_per_day":total/n,
        "entries_per_elapsed_24h":total/((end-start)/86400000),"median_entries_per_day":statistics.median(counts),
        "entry_days":sum(x>0 for x in counts),"zero_days":counts.count(0),"days_ge3":sum(x>=3 for x in counts),
        "days_ge4":sum(x>=4 for x in counts),"days_lt3":sum(x<3 for x in counts),"max_entries_per_day":max(counts),
        "zero_day_fraction":counts.count(0)/n,"days_ge3_fraction":sum(x>=3 for x in counts)/n,
        "days_ge4_fraction":sum(x>=4 for x in counts)/n,"longest_zero_entry_run":best,
        "entry_dates":sorted(entries),"zero_entry_dates":[b["date"] for b in bins if entries[b["date"]]==0],
        "partial_dates":[b for b in bins if b["partial_day"]],
        "dst_days":[b for b in bins if b["nominal_day_hours"]!=24],
        "denominator":"ALL intersected calendar dates, including zero-entry and partial edge dates; elapsed-24h rate also disclosed"}


def opportunity_stats(rows, start, end):
    signals = [r for r in rows if start <= r["signal_ts_ms"] < end]
    proxy = {(r["symbol"], r["side"], r["signal_ts_ms"]) for r in signals}
    complete = bool(signals) and all(r["opportunity_id"] is not None for r in signals)
    return {"independent_count":len({r["opportunity_id"] for r in signals}) if complete else None,
        "status":"EXPLICIT_SOURCE_IDS" if complete else "UNKNOWN_NO_COMPLETE_INDEPENDENT_OPPORTUNITY_IDS",
        "proxy_cluster_count":len(proxy),"saved_signal_rows":len(signals),
        "proxy_key":["symbol","side","signal_ts_ms"],
        "limitation":"Same-symbol/side/time clusters ignore strategy names. Saved admitted/closed rows do not enumerate rejected, unavailable or counterfactual opportunities."}


def summary(rows, start, end):
    entered = [r for r in rows if r["entry_ts_ms"] is not None and start <= r["entry_ts_ms"] < end]
    return {"coverage":{zone:coverage(rows,start,end,zone) for zone in ("UTC","Europe/Berlin")},
        "lifecycle":{"entries_in_window":len(entered),
            "completed_in_window":sum(r["exit_ts_ms"] is not None and start<=r["exit_ts_ms"]<end for r in rows),
            "outcomes_known_in_window":sum(r["outcome_available_ts_ms"] is not None and start<=r["outcome_available_ts_ms"]<end for r in rows),
            "pending_positions":sum(r["entry_ts_ms"] is None and start<=r["signal_ts_ms"]<end for r in rows),
            "open_at_end":sum(r["entry_ts_ms"] is not None and r["entry_ts_ms"]<end and (r["exit_ts_ms"] is None or r["exit_ts_ms"]>=end) for r in rows),
            "carry_in_positions":sum(r["entry_ts_ms"] is not None and r["entry_ts_ms"]<start and (r["exit_ts_ms"] is None or r["exit_ts_ms"]>start) for r in rows)},
        "economics":economics(rows,start,end),"opportunities":opportunity_stats(rows,start,end),
        "directions":{name:{"entries":sum(r["side"]==side for r in entered),"economics":economics([r for r in rows if r["side"]==side],start,end)} for name,side in (("long",1),("short",-1))}}


def ref_row(r):
    return {k:r[k] for k in ("key","label","identity","symbol","side","signal_ts_ms","entry_ts_ms","exit_ts_ms","outcome_available_ts_ms")}


def collisions(rows, start, end):
    active = [r for r in rows if r["entry_ts_ms"] is not None and r["entry_ts_ms"] < end and (r["exit_ts_ms"] is None or r["exit_ts_ms"] > start)]
    pairs, losses, occupancy = [], [], defaultdict(list)
    for r in active:
        occupancy[r["symbol"]].append((max(start,r["entry_ts_ms"]), min(end,r["exit_ts_ms"] if r["exit_ts_ms"] is not None else end)))
    for a,b in itertools.combinations(active, 2):
        lo=max(start,a["entry_ts_ms"],b["entry_ts_ms"])
        hi=min(end,a["exit_ts_ms"] if a["exit_ts_ms"] is not None else end,b["exit_ts_ms"] if b["exit_ts_ms"] is not None else end)
        if lo >= hi:
            continue
        detail={"a":ref_row(a),"b":ref_row(b),"labels":[a["label"],b["label"]],
            "side_relation":"same" if a["side"]==b["side"] else "opposite", "start_ms":lo,"end_ms":hi,
            "overlap_minutes":(hi-lo)/60000,"cross_strategy":a["label"]!=b["label"]}
        if a["symbol"] == b["symbol"]:
            pairs.append(detail)
        if all(r["net1x"] is not None and r["net1x"]<0 and r["outcome_available_ts_ms"] is not None and r["outcome_available_ts_ms"]<end for r in (a,b)):
            losses.append({**detail,"sum_final_net1x_trade_bps":a["net1x"]+b["net1x"],"same_symbol":a["symbol"]==b["symbol"]})
    occupied = {}
    for symbol, intervals in sorted(occupancy.items()):
        merged=[]
        for lo,hi in sorted(intervals):
            if merged and lo <= merged[-1][1]: merged[-1][1]=max(hi,merged[-1][1])
            else: merged.append([lo,hi])
        events=defaultdict(int)
        for lo,hi in intervals:events[lo]+=1;events[hi]-=1
        cur=maximum=0
        for ts in sorted(events):cur+=events[ts];maximum=max(maximum,cur)
        occupied[symbol]={"union_occupied_minutes":sum(hi-lo for lo,hi in merged)/60000,
            "sum_position_minutes":sum(hi-lo for lo,hi in intervals)/60000,"max_concurrent_positions":maximum,
            "window_minutes":(end-start)/60000,"not_capital_weighted":True}
    same_signal, same_time, same_day, loss_outcomes = defaultdict(list),defaultdict(list),{},defaultdict(list)
    for r in rows:
        if start<=r["signal_ts_ms"]<end:
            same_signal[(r["symbol"],r["side"],r["signal_ts_ms"])].append(ref_row(r))
            same_time[r["signal_ts_ms"]].append(ref_row(r))
        if r["net1x"] is not None and r["net1x"]<0 and r["outcome_available_ts_ms"] is not None and start<=r["outcome_available_ts_ms"]<end:
            loss_outcomes[r["outcome_available_ts_ms"]].append(r)
    for zone in ("UTC","Europe/Berlin"):
        days=defaultdict(list)
        for r in rows:
            if start<=r["signal_ts_ms"]<end:days[date_at(r["signal_ts_ms"],zone)].append(r)
        same_day[zone]=[{"date":d,"labels":sorted({r["label"] for r in rs}),"signal_rows":len(rs),"rows":[ref_row(r) for r in rs]} for d,rs in sorted(days.items()) if len({r["label"] for r in rs})>1]
    return {"same_symbol_holding_pairs":pairs,"cross_strategy_same_symbol_holding_pairs":[p for p in pairs if p["cross_strategy"]],
        "same_signal_clusters":[{"symbol":k[0],"side":k[1],"signal_ts_ms":k[2],"rows":v} for k,v in sorted(same_signal.items()) if len(v)>1],
        "same_timestamp_signal_groups":[{"signal_ts_ms":k,"rows":v} for k,v in sorted(same_time.items()) if len(v)>1],
        "same_day_cross_strategy_signals":same_day,"symbol_occupancy":occupied,
        "overlapping_eventual_losers":losses,
        "simultaneous_loss_outcomes":[{"outcome_available_ts_ms":t,"rows":[ref_row(r) for r in rs],"sum_net1x_trade_bps":sum(r["net1x"] for r in rs)} for t,rs in sorted(loss_outcomes.items()) if len(rs)>1],
        "loss_semantics":"EX_POST final losses among overlapping holds, and losses known at exactly the same outcome timestamp. Not intrahold MTM or pre-entry features.",
        "loss_diagnostic_cost_multiplier":1,
        "holding_interval":"[entry,exit); unresolved hold extends to window end; delayed outcome does not extend physical occupancy"}


def pair_contribution(candidate, base, start, end):
    details={}
    entered=[r for r in candidate if r["entry_ts_ms"] is not None and start<=r["entry_ts_ms"]<end]
    for zone in ("UTC","Europe/Berlin"):
        cd={date_at(r["entry_ts_ms"],zone) for r in entered}
        bd={date_at(r["entry_ts_ms"],zone) for r in base if r["entry_ts_ms"] is not None and start<=r["entry_ts_ms"]<end}
        details[zone]={"additional_entry_days":len(cd-bd),"additional_entry_dates":sorted(cd-bd),"common_entry_days":len(cd&bd),"common_entry_dates":sorted(cd&bd)}
    base_keys={r["key"] for r in base}; candidate_keys={r["key"] for r in candidate}
    all_pairs=collisions(base+candidate,start,end)["same_symbol_holding_pairs"]
    cross=[p for p in all_pairs if (p["a"]["key"] in base_keys and p["b"]["key"] in candidate_keys) or (p["b"]["key"] in base_keys and p["a"]["key"] in candidate_keys)]
    blocked={k for p in cross for k in (p["a"]["key"],p["b"]["key"]) if k in candidate_keys}
    nonoverlap=[r for r in entered if r["key"] not in blocked]
    return {"date_coverage":details,"same_symbol_overlap_pairs":len(cross),
        "same_side_overlap_pairs":sum(p["side_relation"]=="same" for p in cross),
        "opposite_side_overlap_pairs":sum(p["side_relation"]=="opposite" for p in cross),
        "candidate_positions_overlapping_base":len(blocked),"nonoverlap_saved_entries":len(nonoverlap),
        "nonoverlap_saved_entries_economics":economics(nonoverlap,start,end),
        "raw_additive_economics":economics(entered,start,end),"shared_incremental_net1x_trade_bps":None,
        "limitation":"No selection or greedy merge. Nonoverlap refers only to saved same-symbol holding intervals; capital, cross-symbol risk, missed/new entries and shared-state exits remain unmeasured."}


def daily_rows(groups, start, end):
    output=[]
    for zone in ("UTC","Europe/Berlin"):
        for b in calendar_bins(start,end,zone):
            for label, rows in groups.items():
                lo,hi=b["start_ms"],b["end_ms"]
                entries=[r for r in rows if r["entry_ts_ms"] is not None and lo<=r["entry_ts_ms"]<hi]
                known=[r for r in rows if r["outcome_available_ts_ms"] is not None and lo<=r["outcome_available_ts_ms"]<hi]
                output.append({"timezone":zone,"date":b["date"],"scope":label,"start_utc":b["start_utc"],"end_utc":b["end_utc"],
                    "covered_hours":b["covered_hours"],"nominal_day_hours":b["nominal_day_hours"],"partial_day":b["partial_day"],
                    "entries":len(entries),"long_entries":sum(r["side"]==1 for r in entries),"short_entries":sum(r["side"]==-1 for r in entries),
                    "completed":sum(r["exit_ts_ms"] is not None and lo<=r["exit_ts_ms"]<hi for r in rows),
                    "outcomes_known":len(known),"proxy_entry_clusters":len({(r["symbol"],r["side"],r["signal_ts_ms"]) for r in entries}),
                    "known_net1x_trade_bps":math.fsum(r["net1x"] for r in known) if all(r["net1x"] is not None for r in known) else None,
                    "known_net2x_trade_bps":math.fsum(r["net2x"] for r in known) if all(r["net2x"] is not None for r in known) else None})
    return output


def analyze_sources(manifest, payloads):
    start,end=validate_manifest(manifest)
    groups={}; diagnostics={}
    for source in manifest["sources"]:
        label=source["label"]
        if label not in payloads:raise ValueError("missing payload "+label)
        groups[label],diagnostics[label]=normalize(source,payloads[label])
        diagnostics[label]["signals_outside_window"] = sum(not start <= r["signal_ts_ms"] < end for r in groups[label])
        diagnostics[label]["entries_outside_window"] = sum(r["entry_ts_ms"] is not None and not start <= r["entry_ts_ms"] < end for r in groups[label])
        diagnostics[label]["outcomes_not_known_before_end"] = sum(r["outcome_available_ts_ms"] is None or r["outcome_available_ts_ms"] >= end for r in groups[label])
    rows=[r for group in groups.values() for r in group]
    labels=list(groups)
    report={"schema":SCHEMA,"classification":"SAVED_LEDGER_DIAGNOSTIC_ONLY_NO_NEW_SIGNAL_OR_FULL_REPLAY",
        "input_manifest":manifest,"integrity":"PASS_SCHEMA_IDENTITY_PARTITION_COST_AND_TIME; file hashes checked by CLI",
        "source_row_audit":diagnostics,"standalone":{k:summary(v,start,end) for k,v in groups.items()},
        "unconstrained_union_not_portfolio":summary(rows,start,end),"opportunities":opportunity_stats(rows,start,end),
        "collisions":collisions(rows,start,end),"pairwise_contribution":{},"candidate_contribution":{},
        "shared_account":{"status":"UNKNOWN","net1x_trade_bps":None,"net2x_trade_bps":None,"nav":None,"mtm_dd":None,
            "reason":"Capital, exposure, risk SSOT, equity/mark path and common state replay not bound. No arbitrator or future-PnL selection is run."},
        "candidate_slots":manifest.get("candidate_slots",[]),"new_economic_full_runs":0,"orders":0,
        "authority":{"promotion":False,"live":"BLOCKED","order":"BLOCKED"}}
    for a,b in itertools.permutations(labels,2):
        report["pairwise_contribution"][a+"_versus_"+b]=pair_contribution(groups[a],groups[b],start,end)
    base_labels=manifest.get("baseline_labels",labels)
    base=[r for label in base_labels for r in groups[label]]
    for label in labels:
        if label not in base_labels:report["candidate_contribution"][label]=pair_contribution(groups[label],base,start,end)
    days=(end-start)/86400000
    count=summary(base,start,end)["lifecycle"]["entries_in_window"]
    report["baseline_opportunity_shortfall"]={"elapsed_24h_days":days,"unconstrained_saved_entries":count,
        "required_entries_for_mean_3":math.ceil(3*days),"required_entries_for_mean_4":math.ceil(4*days),
        "additional_entries_for_mean_3":max(0,math.ceil(3*days)-count),"additional_entries_for_mean_4":max(0,math.ceil(4*days)-count),
        "not_daily_minimum_or_shared_executable_count":True}
    entered=[r for r in rows if r["entry_ts_ms"] is not None and start<=r["entry_ts_ms"]<end]
    report["descriptive_distribution"]={"regime_entry_rows":dict(sorted(Counter(r["regime"] for r in entered).items())),
        "utc_hour_entries":{str(h):sum(datetime.fromtimestamp(r["entry_ts_ms"]/1000,UTC).hour==h for r in entered) for h in range(24)},
        "monthly_utc":[],"regime_zero_day_denominator":"UNKNOWN: no full-market regime timeline in trade-only ledgers",
        "not_tuning_whitelist":True}
    months=defaultdict(list)
    for b in calendar_bins(start,end,"UTC"):months[b["date"][:7]].append(b)
    for month,bins in sorted(months.items()):
        cs=coverage(rows,bins[0]["start_ms"],bins[-1]["end_ms"],"UTC")
        report["descriptive_distribution"]["monthly_utc"].append({"month":month,**{k:cs[k] for k in ("calendar_days","entries","entry_days","zero_days","days_ge3","days_ge4")}})
    report["limitations"]=["151-row style union is a count of stored lifecycle entries, not jointly executable opportunities.",
        "Daily known-Net bins include outcomes of carry-in positions; summary economics use entries inside the window and wait for outcomes. Current baseline has no carry-ins.",
        "Concurrent-loss details use cost1x; cost2x economics and realized DD are separate, without a cost2x concurrent-loss claim.",
        "No source-price download or price-path replay; empty dates mean no saved entries, not proved absence of tradable signals.",
        "Explicit independent opportunity IDs are required to certify independent counts; names/time clusters alone are proxies.",
        "Cost1x/2x are inherited frozen cost/reserve scenarios, not verified historical funding or account returns.",
        "Zero/negative periods retained. Descriptive months, hours and regimes must not become retrospective winner whitelists.",
        "Candidate ranking requires standalone cost-adjusted economics/independent validation, shared additional Net/entries/dates and loss/DD; no invented weighted score or correlation cutoff."]
    report["_daily_rows"]=daily_rows({**groups,"UNCONSTRAINED_UNION":rows},start,end)
    matrix=[]
    for zone in ("UTC","Europe/Berlin"):
        for b in calendar_bins(start,end,zone):
            for label,rs in groups.items():
                for symbol in sorted(set(manifest.get("symbols",[]))|{r["symbol"] for r in rs}):
                    selected=[r for r in rs if r["symbol"]==symbol and r["entry_ts_ms"] is not None and b["start_ms"]<=r["entry_ts_ms"]<b["end_ms"]]
                    matrix.append({"timezone":zone,"date":b["date"],"strategy":label,"symbol":symbol,"entries":len(selected),
                        "long_entries":sum(r["side"]==1 for r in selected),"short_entries":sum(r["side"]==-1 for r in selected)})
    report["_matrix_rows"]=matrix
    return report


def checked_path(root, name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError("input escapes repo root")
    return path


def load_sources(manifest, repo_root):
    validate_manifest(manifest)
    payloads={}
    root=Path(repo_root)
    for source in manifest["sources"]:
        path=checked_path(root,source["path"])
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=source["sha256"]:
            raise ValueError("ledger SHA256 mismatch for "+source["label"])
        cost = source["cost"]
        bindings = [(cost["source_path"], cost["source_sha256"])]
        reserve = cost.get("additional_reserve_source")
        if reserve:
            if not re.fullmatch("[0-9a-f]{40}", reserve.get("ref", "")):
                raise ValueError("additional reserve requires immutable ref")
            bindings.append((reserve["path"], reserve["sha256"]))
        for name, sha in bindings:
            if hashlib.sha256(checked_path(root,name).read_bytes()).hexdigest() != sha:
                raise ValueError("cost source SHA256 mismatch: " + name)
        payloads[source["label"]]=json.loads(gzip.decompress(raw) if path.suffix==".gz" else raw)
    return payloads


def write_csv(path, rows):
    with path.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]) if rows else [])
        writer.writeheader();writer.writerows(rows)


def run(manifest, repo_root, out_dir):
    if isinstance(manifest,(str,Path)):manifest=json.loads(Path(manifest).read_text())
    result=analyze_sources(manifest,load_sources(manifest,repo_root))
    result["integrity"]="PASS_LEDGER_SHA256_SCHEMA_IDENTITY_PARTITION_COST_AND_TIME"
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    write_csv(out/"DAILY_COVERAGE.csv",result.pop("_daily_rows"))
    write_csv(out/"STRATEGY_DAY_SYMBOL.csv",result.pop("_matrix_rows"))
    (out/"CONTRIBUTION.json").write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--repo-root",default=".")
    parser.add_argument("--out-dir",required=True)
    args=parser.parse_args()
    result=run(args.manifest,args.repo_root,args.out_dir)
    print(json.dumps({"classification":result["classification"],"entries":result["unconstrained_union_not_portfolio"]["lifecycle"]["entries_in_window"],"output":args.out_dir,"new_full":0}))


if __name__=="__main__":main()
