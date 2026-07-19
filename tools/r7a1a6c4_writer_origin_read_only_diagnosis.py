#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from r7a1a6c4_diag_common import DEFAULT_PRIOR, OUT_REL, PROTECTED, TARGETS, atomic_json, contract_valid, diff, fp, historical, journal_units, now_iso, prior_valid, proc_snapshot, scan_refs, snap, systemd_inventory, terms
from r7a1a6c4_diag_runtime import correlate, fetch_http, find_origin, observe, route_evidence


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='/home/z/z'); ap.add_argument('--contract',required=True); ap.add_argument('--observe-seconds',type=int); ap.add_argument('--poll-ms',type=int); args=ap.parse_args()
    root=Path(args.root).resolve()
    try: contract=json.loads(Path(args.contract).read_text())
    except Exception: contract={}
    observe_seconds=max(int(contract.get('minimum_observe_seconds',120)),int(args.observe_seconds or contract.get('observe_seconds',180)))
    poll_ms=int(args.poll_ms or contract.get('poll_interval_ms',50)); blockers=[]
    try: prior=json.loads(DEFAULT_PRIOR.read_text())
    except Exception: prior={}
    prior_ok=prior_valid(prior)
    if not contract_valid(contract): blockers.append('CONTRACT_INVALID')
    if not prior_ok: blockers.append('PRIOR_C3B_HOLD_NOT_CONFIRMED')

    protected_before=snap(PROTECTED); needles=terms()
    refs=scan_refs((Path(x) for x in contract.get('reference_scan_roots',[])),needles)
    historic=historical(prior,needles)
    systemd=systemd_inventory(refs,needles,journal_units(historic))
    process_before=proc_snapshot(needles)
    watched=observe(observe_seconds,poll_ms,needles)
    process_after=proc_snapshot(needles)
    http,http_raw=fetch_http()
    origin=find_origin(http_raw,(Path(x) for x in contract.get('origin_search_roots',[])))
    route=route_evidence(needles)
    candidates=correlate(refs,systemd,process_before+process_after,watched,historic)
    protected_changes=diff(protected_before,snap(PROTECTED))
    if protected_changes: blockers.append('PROTECTED_CHANGE_DETECTED')

    local_view=fp(TARGETS[0]); parity=bool(http.get('sha256') and http.get('sha256')==local_view.sha256)
    proof=len(candidates['proven']); strong=len(candidates['strong']); exact=len(origin['exact_sha_matches']); normalized=len(origin['normalized_json_matches'])
    writer_narrowed=proof>0 or strong>0; origin_narrowed=exact>0 or normalized>0 or bool(route['records'])
    if not refs: blockers.append('NO_EXACT_TARGET_REFERENCES_FOUND')
    if not writer_narrowed: blockers.append('ACTIVE_WRITER_NOT_NARROWED')
    if not origin_narrowed: blockers.append('HTTP_ORIGIN_NOT_NARROWED')
    if http.get('status')!=200: blockers.append('HTTP_STATUS_NOT_200')
    blockers=list(dict.fromkeys(blockers)); state='DIAGNOSED' if not blockers and proof>0 and exact>0 else 'HOLD'
    payload={
        'schema':'r7a1a6c4_writer_origin_read_only_diagnosis_status_v1','official_stage':'R7.A1A6C4','generated_at':now_iso(),'state':state,'blocker_count':len(blockers),'blockers':blockers,'read_only':True,
        'prior_c3b_hold_confirmed':prior_ok,'prior_c3b_summary':{k:prior.get(k) for k in ('generated_at','state','blockers','target_change_count','fanotify_event_count','writer_identified_count','protected_change_count')},
        'observe_seconds':observe_seconds,'poll_interval_ms':poll_ms,'reference_hit_count':len(refs),'reference_hits':refs,'historical_change_evidence':historic,'systemd':systemd,'process_before':process_before,'process_after':process_after,'observation':watched,
        'writer_candidates':candidates,'writer_proof_count':proof,'writer_strong_candidate_count':strong,'writer_narrowed':writer_narrowed,'http':http,'local_view_fingerprint':asdict(local_view),'http_local_view_parity':parity,
        'origin_search':origin,'http_origin_exact_match_count':exact,'http_origin_normalized_match_count':normalized,'http_origin_narrowed':origin_narrowed,'route_runtime_evidence':route,
        'protected_change_count':len(protected_changes),'protected_changes':protected_changes,'paper_mutation_count':0,'live_mutation_count':0,'order_mutation_count':0,'service_mutation_count':0,'repair_invocation_count':0,'value_exposure_count':0,
        'next_stage':'R7.A1A6C5_MINIMAL_SINGLE_OWNER_ROUTE_CORRECTION_PLAN' if state=='DIAGNOSED' else 'R7.A1A6C4B_TARGETED_ACTIVE_WRITER_TRACE',
    }
    status=root/OUT_REL; atomic_json(status,payload)
    lines={
        'STATE':state,'BLOCKER_COUNT':len(blockers),'BLOCKERS':json.dumps(blockers,ensure_ascii=False),'PRIOR_C3B_HOLD_CONFIRMED':str(prior_ok).lower(),'OBSERVE_SECONDS':observe_seconds,'POLL_INTERVAL_MS':poll_ms,
        'INOTIFY_AVAILABLE':str(watched['inotify_available']).lower(),'OBSERVED_CHANGE_EVENT_COUNT':watched['change_event_count'],'REFERENCE_HIT_COUNT':len(refs),'ACTIVE_UNIT_CANDIDATE_COUNT':sum(1 for x in systemd['units'] if x.get('ActiveState')=='active'),
        'ACTIVE_PROCESS_CANDIDATE_COUNT':len(process_before+process_after),'WRITER_PROOF_COUNT':proof,'WRITER_STRONG_CANDIDATE_COUNT':strong,'WRITER_NARROWED':str(writer_narrowed).lower(),'HTTP_STATUS':http.get('status',0),
        'HTTP_LOCAL_VIEW_PARITY':str(parity).lower(),'HTTP_ORIGIN_EXACT_MATCH_COUNT':exact,'HTTP_ORIGIN_NORMALIZED_MATCH_COUNT':normalized,'HTTP_ORIGIN_NARROWED':str(origin_narrowed).lower(),'PROTECTED_CHANGE_COUNT':len(protected_changes),
        'PAPER_MUTATION_COUNT':0,'LIVE_MUTATION_COUNT':0,'ORDER_MUTATION_COUNT':0,'SERVICE_MUTATION_COUNT':0,'REPAIR_INVOCATION_COUNT':0,'VALUE_EXPOSURE_COUNT':0,'NEXT_STAGE':payload['next_stage'],'EVIDENCE_JSON':status,'RC':0 if state=='DIAGNOSED' else 2,
    }
    print('R7A1A6C4_WRITER_ORIGIN_READ_ONLY_DIAGNOSIS_COMPLETE')
    for k,v in lines.items(): print(f'{k}={v}')
    return 0 if state=='DIAGNOSED' else 2


if __name__=='__main__': raise SystemExit(main())
