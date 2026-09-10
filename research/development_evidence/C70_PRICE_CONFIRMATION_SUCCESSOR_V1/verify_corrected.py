"""Post-measurement event metadata correction; zero strategy/economic replay.

Use load_corrected_summary() and SUMMARY_CORRECTION.json, not the frozen SUMMARY's imported
C70_LOCAL event counters. Financial fields and all original seals are retained.
"""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import argparse,json,hashlib
import verify_saved as v
HERE=Path(__file__).resolve().parent
EVENT_SHA='7d6f0e8ec1d82d605a3a1e55405e22c7dc0d369a4abbb3179c99343ffd437e5f'
SUMMARY_SHA='57217ba4c44daadfed90c76f5efd25e207efa58a8832ee9b1e2e9cd38a4f5b5f'
PERIODS=('DEV2025','SEEN2026')
EVENT_FIELDS=('raw','exclusions','waiting_at_end')
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def event_counters(rows,fields):
    events=[dict(zip(fields,row)) for row in rows]
    v.check(len(fields)==6 and all(len(row)==6 for row in rows),'PROJECTION_COLUMNS')
    return dict(raw=len(events),exclusions=dict(Counter(e['exclusion_reason'] for e in events if e['exclusion_reason'])),waiting_at_end=sum(e['exclusion_reason']=='PENDING_WAIT_AT_END' for e in events))
def verify_decisions(per,projection,packet,parent,meta):
    fields=projection['fields'];records=projection['periods'][per];rows=records['rows']
    v.check(fields==['symbol','signal_index','signal_ts','admission','status','exclusion_reason'],'EVENT_COLUMNS')
    v.check(hashlib.sha256(canon(rows)).hexdigest()==records['projection_sha256'],'PROJECTION_DIGEST')
    v.check(records['source_result_sha256']==meta['periods'][per]['source_result_sha256'],'ORIGINAL_RESULT_ID')
    events=[dict(zip(fields,x)) for x in rows];actual={v.key(e):e for e in events}
    native={v.key(e):e for e in parent['events']};wanted={tuple(x) for x in meta['periods'][per]['admitted']}
    v.check(len(actual)==len(events) and set(actual)==set(native),'COMPLETE_ORIGINAL_EVENT_POOL')
    positions={v.key(t):(state,t) for state,t in v.pos(parent) if v.key(t) in wanted}
    v.check(set(positions)==wanted,'ORIGINAL_POSITION_SUBSET')
    admitted=set();end=v.read(HERE/'SPEC.json')['periods'][per]['runoff_end_ms']
    for symbol in sorted(packet['rows_by']):
        bars=packet['rows_by'][symbol];last=-1;tail=False
        for key in sorted((k for k in actual if k[0]==symbol),key=lambda k:k[1]):
            old=native[key];e=actual[key];i=e['signal_index'];x=v.expected_context(bars,old)
            eligible=bool(x['original'] and x['ema'] is not None and (x['dailygood'] or x['sma'] is not None and x['previous_sma'] is not None and bars[i]['close']>x['sma'] and x['sma']>=x['previous_sma'] and x['escape']))
            if tail or e['signal_ts']<=last:reason='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
            elif old['expiry'] is not None and e['signal_ts']>=old['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
            elif not x['original']:reason=old['er_context']['reason']
            elif x['ema'] is None:reason='COMPLETED_DAILY_EMA21_HISTORY_UNAVAILABLE'
            elif not eligible:reason='DAILY21_VETO_WITHOUT_SMA5_RANGE_CONFIRMATION'
            elif i+1>=len(bars) or bars[i+1]['bar_open_ts']>=end:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
            elif bars[i+1]['open']<=old['floor'] or old['target'] is not None and bars[i+1]['open']>=old['target']:reason='GAP_INVALIDATES_FIXED_SETUP'
            else:reason=None
            v.check(type(e['admission']) is bool and e['admission']==(reason is None),'IMPORTED_ADMISSION')
            v.check(e['exclusion_reason']==reason,'IMPORTED_EXCLUSION_REASON')
            if reason is None:
                v.check(key in positions,'UNMATCHED_IMPORTED_ADMISSION');admitted.add(key);state,t=positions[key]
                expected_status='COMPLETED' if state=='C' else 'CENSORED'
                if state=='C':last=t['exit_ts']
                else:tail=True
            else:expected_status='EXCLUDED'
            v.check(e['status']==expected_status,'IMPORTED_EVENT_STATUS')
    v.check(admitted==wanted,'ALL_IMPORTED_POSITIONS_ACCOUNTED')
    counters=event_counters(rows,fields)
    v.check(counters['raw']==len(wanted)+sum(counters['exclusions'].values()),'EVENT_COUNT_RECONCILIATION')
    return counters

def corrected_summary(original,projection,meta):
    result=deepcopy(original);changes={}
    for per in PERIODS:
        rows=projection['periods'][per]['rows'];values=event_counters(rows,projection['fields'])
        before=original['periods'][per]['snapshots']['C70_LOCAL'];result['periods'][per]['snapshots']['C70_LOCAL'].update(values)
        changes[per]={k:dict(before=before[k],after=value) for k,value in values.items() if before[k]!=value}
        result['periods'][per]['C70_LOCAL_event_source']=dict(projection='C70_LOCAL_EVENT_DECISIONS.json.gz',source_result_sha256=meta['periods'][per]['source_result_sha256'],admission_count=sum(row[3] for row in rows),economic_reruns=0)
    result['post_measurement_correction']=dict(supersedes_only='C70_LOCAL.raw/exclusions/waiting_at_end in frozen SUMMARY.json and IMPORT_ARITHMETIC.json; unsupported waiting_setup_no_candidate is NOT invented',original_summary_sha256=SUMMARY_SHA,kind='REPORTING_METADATA_ONLY',unchanged=['all financial fields','C63 C69 C72 snapshots','checks and verdict','source SPEC and original evidence seals','candidate/evaluation history'],changes=changes,original_summary_retained=True)
    return result

def load_corrected_summary():
    original=v.read(HERE/'SUMMARY.json');projection=v.gz(HERE/'C70_LOCAL_EVENT_DECISIONS.json.gz');meta=v.read(HERE/'LOCAL_C70_IMPORT.json')
    v.check(v.sha(HERE/'SUMMARY.json')==SUMMARY_SHA,'HISTORICAL_SUMMARY_DRIFT')
    v.check(v.sha(HERE/'C70_LOCAL_EVENT_DECISIONS.json.gz')==EVENT_SHA,'EVENT_EXPORT_PIN')
    expected=corrected_summary(original,projection,meta)
    correction=deepcopy(expected['post_measurement_correction'])
    correction['corrected_summary_sha256']=hashlib.sha256(canon(expected)).hexdigest()
    v.check(v.read(HERE/'SUMMARY_CORRECTION.json')==correction,'CORRECTION_OR_FINANCIAL_DRIFT')
    return expected

def verify(inputs):
    v.check(v.sha(HERE/'C70_LOCAL_EVENT_DECISIONS.json.gz')==EVENT_SHA,'EVENT_EXPORT_PIN')
    v.check(v.sha(HERE/'SUMMARY.json')==SUMMARY_SHA,'HISTORICAL_SUMMARY_DRIFT')
    projection=v.gz(HERE/'C70_LOCAL_EVENT_DECISIONS.json.gz');meta=v.read(HERE/'LOCAL_C70_IMPORT.json');spec=v.read(HERE/'SPEC.json')
    v.check(projection['source_archive_sha256']==meta['original_archive_sha256'],'ORIGINAL_ARCHIVE_BINDING')
    counts={}
    for per in PERIODS:
        file=Path(inputs)/(per+'.json.gz');v.check(v.sha(file)==spec['input_packet_sha256'][per],'UNCHANGED_INPUT_HASH')
        parent=v.gz(v.ROOT/'research/development_evidence/M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'/per/'RESULT.json.gz')
        counts[per]=verify_decisions(per,projection,v.gz(file),parent,meta)
    corrected=load_corrected_summary()
    return dict(status='PASS_IMPORTED_EVENTS_AND_UNCHANGED_ECONOMICS',events_checked=sum(c['raw'] for c in counts.values()),counters=counts,new_economic_replays=0,verdict=corrected['status'])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path);args=p.parse_args();print(json.dumps(verify(args.inputs),indent=2))
    if args.output:
        with args.output.open('x',encoding='utf-8') as output:output.write(canon(load_corrected_summary()).decode()+'\n')
