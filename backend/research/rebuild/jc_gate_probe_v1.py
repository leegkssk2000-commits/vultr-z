"""Signal-only USED_DEV funnel diagnostics; no replay, cost, fill, PnL or slots."""
from collections import Counter
from dataclasses import asdict
import gzip,json
from backend.research.rebuild import jc_lifecycle_study_v1 as prior
from backend.research.rebuild import jc_lifecycle_v1 as native
from backend.research.rebuild import jc_boundary_context_v1 as context
from backend.research.rebuild import jc_repaired_v1 as repair
GATES=('history365','recent_high20','squeeze3','EMA21','ATR21','HLHL_pivots','cup_geometry','extra_confirmation_wait','target_geometry','below_first_target')
SCOPE='JC_BOUNDARY_FUNNEL_REPAIR_AFTER_PR1251_V1'
OUT=prior.ROOT/'research/development_evidence'/SCOPE


def scope_guard(state):
    if state is not None and (state.get('scope')!=SCOPE or state.get('status')!='PREPARED_DIAGNOSTIC'):
        raise RuntimeError('CURRENT_SCOPE_CLOSED_OR_MISMATCH')


def observe(days,i,features,tick):
    normalized,sq,e8,e21,atr=features;b=days[i]
    high_events=[j for j in range(max(364,i-19),i+1) if days[j].high>=max(x.high for x in days[j-364:j+1])]
    pivots=native.f.confirmed_pivots(normalized,i,2);alternating=[];counts=Counter(x['index'] for x in pivots)
    for p in pivots:
        if counts[p['index']]>1:continue
        if alternating and alternating[-1]['kind']==p['kind']:alternating[-1]=p
        else:alternating.append(p)
    abcd=alternating[-4:];hlhl=len(abcd)==4 and [p['kind'] for p in abcd]==['HIGH','LOW','HIGH','LOW']
    geometry=wait=target_geom=below=None;targets=None
    if hlhl:
        a,bp,c,d=[p['price'] for p in abcd]
        geometry=bp<a and .9*a<=c<=1.1*a and bp<d<c
        wait=abcd[-1]['known_index']<=i-2
        targets=[c-tick,d+1.272*(c-d),d+1.618*(c-d)]
        target_geom=0<d<targets[0]<targets[1]<targets[2]
        below=b.close<targets[0]
    flags=dict(history365=i>=364,recent_high20=bool(high_events),
        squeeze3=i>=2 and all(sq[j] and sq[j]['squeeze_on'] for j in range(i-2,i+1)),
        EMA21=None if e21[i] is None else b.close>e21[i],ATR21=None if atr[i] is None else atr[i]>0,
        HLHL_pivots=hlhl,cup_geometry=geometry,extra_confirmation_wait=wait,target_geometry=target_geom,below_first_target=below)
    flags={k:(None if v is None else bool(v)) for k,v in flags.items()}
    complete=all(v is True for v in flags.values())
    no_extra=all(v is True for k,v in flags.items() if k!='extra_confirmation_wait') and hlhl and abcd[-1]['known_index']<=i
    return dict(available_at=days[i].open_ts+native.DAY,day_open_ts=days[i].open_ts,index=i,conditions=flags,
        first_fail=next((k for k in GATES if flags[k] is not True),None),all_pass=complete,no_extra_wait_pass=bool(no_extra),
        wait_only_witness=bool(no_extra and not complete),
        observations=dict(close=days[i].close,EMA8=e8[i],EMA21=e21[i],ATR21=atr[i],tick=tick,
            squeeze3=[None if sq[j] is None else sq[j]['squeeze_on'] for j in range(max(0,i-2),i+1)],
            rolling_high_event_utc=[days[j].open_ts+native.DAY for j in high_events],targets=targets,
            pivots=[dict(kind=p['kind'],index=p['index'],price=p['price'],known_index=p['known_index'],
                available_at=days[p['known_index']].open_ts+native.DAY) for p in abcd]))


def probe(days,tick,start,end):
    rows=[];parity=0;no_wait_parity=0
    for piece in context.segments(days):
        features=native.daily_features(piece)
        for i,b in enumerate(piece):
            if not start<=b.open_ts+native.DAY<=end:continue
            row=observe(piece,i,features,tick)
            truth=native.setup_at(piece,i,features,tick) is not None
            if row['all_pass']!=truth:raise RuntimeError('NATIVE_SETUP_BOOLEAN_PARITY')
            no_wait=repair.setup_at(piece,i,features,tick,remove_extra_wait=True) is not None
            if row['no_extra_wait_pass']!=no_wait:raise RuntimeError('REPAIRED_SETUP_BOOLEAN_PARITY')
            parity+=1;no_wait_parity+=1;rows.append(row)
    cumulative={k:0 for k in GATES};independent={k:dict(pass_count=0,evaluable=0) for k in GATES};first=Counter()
    for row in rows:
        carry=True
        for k in GATES:
            v=row['conditions'][k]
            if v is not None:independent[k]['evaluable']+=1;independent[k]['pass_count']+=int(v)
            carry=carry and v is True;cumulative[k]+=int(carry)
        first[row['first_fail'] or 'PASS']+=1
    return dict(decisions=len(rows),cumulative=cumulative,independent=independent,first_fail=dict(first),
        native_boolean_parity_checked=parity,repaired_boolean_parity_checked=no_wait_parity,
        original_setups=sum(x['all_pass'] for x in rows),no_extra_wait_setups=sum(x['no_extra_wait_pass'] for x in rows),
        wait_only_witnesses=[x for x in rows if x['wait_only_witness']],observations=rows,
        coverage=context.coverage(days,start,end),interpretation='ORDERED_CUMULATIVE_NOT_INDEPENDENT_CAUSAL_ATTRIBUTION')


def inputs(per,symbol):
    packet=prior.packet(per);rows=packet['rows_by'][symbol];cal=prior.CAL[per]
    warm=[native.f.Bar(**x) for x in prior.read(prior.OUT/'SOURCE/daily'/(symbol+'.json'))] if per=='DEV2025' else []
    boundary=None;receipt=None
    if per=='DEV2025':
        path=prior.OUT/'SOURCE/raw'/(symbol+'.json');raw=prior.read(path)
        rec=next(x for x in prior.read(prior.OUT/'SOURCE/REQUESTS.json') if x['symbol']==symbol)
        boundary,receipt=context.bind_boundary(raw,rec,rows,cal['start_ms'],raw_sha256=prior.h(path))
    tick=prior.read(prior.OUT/'SOURCE_BINDING.json')['ticks'][symbol]['increment']
    return packet,rows,warm,boundary,receipt,tick


def original_days(rows,warm,end):
    bars=context.rows_to_bars(rows,end)
    full=[b for b in bars if b.open_ts>=((bars[0].open_ts+native.DAY-1)//native.DAY)*native.DAY]
    combined=warm+native.f.completed_utc_days(full,end)
    last_gap=max((i for i in range(1,len(combined)) if combined[i].open_ts-combined[i-1].open_ts!=native.DAY),default=0)
    return combined[last_gap:]


def run():
    scope_guard(prior.read(OUT/'STATUS.json') if (OUT/'STATUS.json').exists() else None)
    prior.check() # All immutable PR1251 code, input, cost, source and history bindings.
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'DIAGNOSTIC_SUMMARY.json').exists():raise RuntimeError('DIAGNOSTIC_ALREADY_SAVED_NO_REPEAT')
    summary=dict(scope=SCOPE,diagnostic_only=True,used_DEV_selection_history=True,economic_executions=0,new_market_GET=0,
        attached_diagnostic_package='NOT_PRESENT_IN_THIS_UPLOAD; NATIVE_CONNECTED_DIAGNOSTIC_IMPLEMENTED_FROM_WORK_NEXT',periods={},bindings={})
    witnesses=[];digests={}
    for per in prior.PERIODS:
        packet=prior.packet(per);cal=prior.CAL[per];results={};summary['periods'][per]={}
        for symbol in sorted(packet['rows_by']):
            _,rows,warm,boundary,receipt,tick=inputs(per,symbol)
            if receipt:summary['bindings'][symbol]=receipt
            old_days=original_days(rows,warm,cal['runoff_end_ms'])
            repaired=context.timeline(rows,warm,boundary,cal['runoff_end_ms'],start=cal['start_ms'])
            pair={'ORIGINAL_CONTEXT':probe(old_days,tick,cal['start_ms'],cal['runoff_end_ms']),
                  'BOUNDARY_CONNECTED':probe(repaired,tick,cal['start_ms'],cal['runoff_end_ms'])}
            if pair['ORIGINAL_CONTEXT']['original_setups']!=0:raise RuntimeError('PR1251_ZERO_SETUP_PARITY')
            results[symbol]=pair
            summary['periods'][per][symbol]={k:{a:b for a,b in v.items() if a not in ('observations','wait_only_witnesses')} for k,v in pair.items()}
            witnesses.extend(dict(x,period=per,symbol=symbol) for x in pair['BOUNDARY_CONNECTED']['wait_only_witnesses'])
        path=OUT/per/'GATE_OBSERVATIONS.json.gz';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(gzip.compress(prior.p.canonical(results),mtime=0));digests[per]=prior.h(path)
    remove=bool(witnesses)
    expected={per:sum(v['BOUNDARY_CONNECTED']['no_extra_wait_setups' if remove else 'original_setups'] for v in symbols.values()) for per,symbols in summary['periods'].items()}
    summary.update(observation_sha256=digests,remove_extra_wait=remove,wait_only_witness_count=len(witnesses),expected_setups=expected,
        economic_preflight='READY_FOR_FIRST_FULL_PAIR' if any(expected.values()) else 'NO_SETUP_AFTER_BOUNDED_REPAIR')
    prior.put(OUT/'WAIT_ONLY_WITNESSES.json',witnesses)
    prior.put(OUT/'DIAGNOSTIC_SUMMARY.json',summary)
    print(json.dumps({k:summary[k] for k in ('economic_preflight','remove_extra_wait','wait_only_witness_count','expected_setups')}))
    return summary

if __name__=='__main__':run()
