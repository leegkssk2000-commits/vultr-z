"""Independent saved-only group envelope, source-prefix, capacity and money."""
from copy import deepcopy
from fractions import Fraction
from math import fsum
import json
from backend.research.rebuild import c70_profitlock_account_v1 as c
from backend.research.rebuild import c63_c70_trader_verify_v1 as old

a=c.a;e=c.e


def qty(raw,stamp,equal=False):
    if raw['entry_ts']>stamp:return Fraction(0)
    fills=sum((Fraction(l['qty']).limit_denominator(3) for l in raw['tm_legs'] if l['status']=='C' and
               (l['ts']<stamp or equal and l['ts']==stamp)),Fraction(0))
    return Fraction(raw['allocation_numerator'],raw['allocation_denominator'])*(1-fills)


def verify_groups(rr,rows,cost,end):
    raw=rr['trades']+rr['open_positions'];entries={r['entry_index']:r for r in raw}
    observations={t['index']:t for t in rr['group_trace'] if t['kind']=='GROUP_CLOSE_OBSERVATION'}
    assert len(observations)==sum(t['kind']=='GROUP_CLOSE_OBSERVATION' for t in rr['group_trace'])
    members=[];gid=None;peak=None;count=0;triggers=0;roots=[];resets=[];expected_fills=[]
    for j,b in enumerate(rows):
        stamp=b['bar_open_ts']
        if gid is not None and not any(qty(r,stamp,True)>0 for r in members):
            resets.append((stamp,gid));members=[];gid=None;peak=None
        if j in entries:
            raw=entries[j]
            if gid is None:gid='ROOT:'+str(raw['signal_index']);roots.append((stamp,gid))
            assert raw['group_id']==gid,'GROUP_MEMBERSHIP_AND_RESET';members.append(raw)
        if gid is None:
            assert j not in observations;continue
        t=observations[j];count+=1;clock=b['bar_close_ts'];assert t['ts']==clock and t['group_id']==gid and t['price']==b['close']
        realized=marked=bank=gross=paid=0.;first=None;active=[]
        for raw in members:
            q=float(Fraction(raw['allocation_numerator'],raw['allocation_denominator']));used=0.
            for leg in raw['tm_legs']:
                if leg['status']!='C' or leg['ts']>=clock:continue
                w=q*leg['qty'];g=w*(leg['price']/raw['entry_price']-1)*10000
                cost_value=w*fsum(old.independent_cost(cost,raw['entry_ts'],leg['ts']).values());net=g-cost_value
                realized+=net;gross+=g;paid+=cost_value;used+=leg['qty']
                if leg['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN':
                    first=leg['ts'] if first is None else min(first,leg['ts']);bank+=max(0.,net)
            remaining=q*(1-used)
            if remaining>0:
                g=remaining*(b['close']/raw['entry_price']-1)*10000
                cost_value=remaining*fsum(old.independent_cost(cost,raw['entry_ts'],clock).values())
                marked+=g-cost_value;gross+=g;paid+=cost_value
                active.append(dict(signal_index=raw['signal_index'],qty=remaining))
        if first is not None:peak=realized+marked if peak is None else max(peak,realized+marked)
        trigger=bool(first is not None and bank>0 and realized+marked<=peak-bank)
        assert t['first_partial_fill_ts']==first and t['active_lots']==active and t['trigger']==trigger
        if peak is None:assert t['peak_group_marked_net'] is None
        else:old.close(t['peak_group_marked_net'],peak,'CAUSAL_GROUP_PEAK')
        for name,value in dict(realized_bank_net=bank,realized_net=realized,remaining_mark_net=marked,
                               group_marked_net=realized+marked,gross_bps=gross,cost_bps=paid).items():
            old.close(t[name],value,'GROUP_CASH:'+name)
        if trigger:
            triggers+=1
            decision=dict(action='FINAL',reason=e.EXIT,signal_index=j,signal_ts=clock,group_id=gid)
            if clock<end:
                expected_fills.append((clock,gid,decision))
                for raw in members:
                    if qty(raw,clock)>0:assert raw.get('exit_ts')==clock,'GROUP_NEXT_OPEN_EXIT_MISSING'
            else:
                for raw in members:
                    if qty(raw,clock)>0:assert raw['pending_risk_envelope']==decision and raw['tm_legs'][-1]['status']=='O'
    assert count==len(observations)
    assert [(t['ts'],t['group_id']) for t in rr['group_trace'] if t['kind']=='GROUP_ROOT_ENTRY']==roots
    assert [(t['ts'],t['group_id']) for t in rr['group_trace'] if t['kind']=='GROUP_FLAT_RESET']==resets
    assert [(t['ts'],t['group_id'],t['decision']) for t in rr['group_trace'] if t['kind']=='GROUP_EXIT_FILL']==expected_fills
    assert triggers==rr['audit']['profitlock_triggers']
    return count,triggers


def verify_source_actual(raw,trace,reference,rows,cost,end,groups):
    unit=reference['raw'];source_trace=reference['trace']
    old.verify_campaign(unit,source_trace,rows,cost,end)
    clean=lambda t:{k:v for k,v in t.items() if k not in ('allocation_numerator','allocation_denominator','normalized_fill_qty','remaining_normalized_qty')}
    actual=[clean(t) for t in trace]
    if raw['risk_envelope_exit']:
        j=raw['exit_index'];stamp=raw['exit_ts'];decision=raw['exit_trigger']
        trigger=next(t for t in groups if t.get('trigger') and t['group_id']==raw['group_id'] and t['ts']==stamp)
        assert decision==dict(action='FINAL',reason=e.EXIT,signal_index=j-1,signal_ts=stamp,group_id=raw['group_id'])
        assert trigger['index']==j-1 and rows[j]['bar_open_ts']==stamp<end and raw['exit_price']==rows[j]['open']
        expected=[deepcopy(l) for l in unit['tm_legs'] if l['status']=='C' and l['ts']<=stamp]
        remainder=1-fsum(l['qty'] for l in expected);assert remainder>0
        expected.append(dict(status='C',qty=remainder,index=j,ts=stamp,price=rows[j]['open'],reason=e.EXIT+'_NEXT_OPEN'))
        assert raw['tm_legs']==expected and raw['remaining_qty']==0
        prefix=[t for t in source_trace if t['index']<j or t['index']==j and t['kind']=='PARTIAL_FILL']
        assert actual[:-1]==prefix,'SOURCE_PREFIX_CHANGED'
        final=dict(kind='FINAL_FILL',ts=stamp,index=j,price=rows[j]['open'],remaining_qty=0.,decision=decision,
                   slot_released=True,signal_index=raw['signal_index'],risk_envelope_exit=True)
        assert actual[-1]==final
        assert raw['partial_count']==sum(l['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' for l in expected)
        assert raw['runner_activated']==bool(raw['partial_count'])
        assert raw['hold_ms']==stamp-raw['entry_ts']
        for name in ('signal_index','signal_ts','entry_index','entry_ts','entry_price','fixed_floor','fixed_target','setup_id','assembled_qty','side'):
            assert raw[name]==unit[name],'ORIGINAL_ENTRY_CHANGED:'+name
    else:
        for name,value in unit.items():
            if name=='censor_reason' and raw.get('pending_risk_envelope'):continue
            assert raw[name]==value,'UNCUT_SOURCE_LIFECYCLE_CHANGED:'+name
        assert actual==source_trace


def verify_period(per,spec):
    folder=c.OUT/per;packet=a.gz(a.INPUTS/(per+'.json.gz'));cal=spec['periods'][per]
    raw=a.gz(folder/'RAW.json.gz');result=a.gz(folder/'RESULT.json.gz');ctrl=c.dd.parents(per,packet,cal)
    parent_raw=a.gz(c.cap.OUT/per/'RAW.json.gz')
    positions={a.key(t):(status,t) for status,name in [('C','trades'),('O','open_observations')] for t in result[name]}
    checked=set();traces=group_observations=trigger_count=0;maximum=0.
    for symbol,rr in raw.items():
        rows=packet['rows_by'][symbol];cost=packet['costs'][symbol];seen=[]
        by={r['signal_index']:r for r in rr['trades']+rr['open_positions']}
        assert set(rr['source_references'])=={str(k) for k in by}
        assert len(rr['events'])==len(parent_raw[symbol]['events'])
        for event,parent in zip(rr['events'],parent_raw[symbol]['events'],strict=True):
            i=event['signal_index'];stamp=event['signal_ts']
            for name in ('signal_index','signal_ts','episode_start','floor','target','expiry','er_context'):
                assert event[name]==parent[name],'EXACT_REG71_SIGNAL:'+name
            active=sum((qty(r,stamp) for r in seen),Fraction(0));available=1-active;assert 0<=active<=1
            old.close(event['active_normalized_qty'],float(active),'DECISION_CAPACITY')
            assert event['available_fraction']==[available.numerator,available.denominator]
            if available<=0:reason=e.cap.OCCUPIED
            elif event['expiry'] is not None and stamp>=event['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
            elif not event['er_context']['eligible']:reason=event['er_context']['reason']
            elif i+1>=len(rows) or rows[i+1]['bar_open_ts']>=cal['runoff_end_ms']:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
            elif rows[i+1]['open']<=event['floor'] or event['target'] is not None and rows[i+1]['open']>=event['target']:reason='GAP_INVALIDATES_FIXED_SETUP'
            else:reason=None
            assert event['admission']==(reason is None) and event['exclusion_reason']==reason,'ADMISSION'
            if reason is not None:assert i not in by;continue
            r=by[i];q=Fraction(r['allocation_numerator'],r['allocation_denominator']);assert q==min(Fraction(1),available)
            assert r['capacity_reuse_entry']==event['capacity_reuse_entry']==(active>0)
            trace=[t for t in rr['trace'] if t['signal_index']==i];traces+=len(trace)
            verify_source_actual(r,trace,rr['source_references'][str(i)],rows,cost,cal['runoff_end_ms'],rr['group_trace'])
            k=(symbol,i,stamp);checked.add(k);status,row=positions[k]
            assert c.campaign(r,symbol,packet)==(status,row),'SAVED_CAMPAIGN_EXPORT'
            values=dict.fromkeys(a.bridge.VALUE_FIELDS,0.)
            for leg in r['tm_legs']:
                w=float(q)*leg['qty'];parts=old.independent_cost(cost,r['entry_ts'],leg['ts']);paid=fsum(parts.values())
                gross=(leg['price']/r['entry_price']-1)*10000
                for name,value in dict(gross_bps=gross,cost_bps=paid,net_bps=gross-paid,cost2x_net_bps=gross-2*paid,**parts).items():values[name]+=w*value
            for name,value in a.bridge._values((status,row)).items():old.close(value,values[name],'CASH:'+name)
            seen.append(r)
        ledger=[]
        for r in seen:
            q=Fraction(r['allocation_numerator'],r['allocation_denominator']);ledger.append((r['entry_ts'],2,r['signal_index'],q))
            for l in r['tm_legs']:
                if l['status']=='C':ledger.append((l['ts'],1,r['signal_index'],-q*Fraction(l['qty']).limit_denominator(3)))
        current=Fraction(0);states={}
        for ts,phase,i,delta in sorted(ledger):
            current+=delta;assert 0<=current<=1,'ALL_FILL_CAP';maximum=max(maximum,float(current));states[ts]=float(current)
        assert rr['capacity_timeline']==[dict(ts=t,active_after_open=v) for t,v in states.items()]
        assert current==sum((qty(r,cal['runoff_end_ms'],True) for r in seen),Fraction(0))
        obs,trig=verify_groups(rr,rows,cost,cal['runoff_end_ms']);group_observations+=obs;trigger_count+=trig
    assert checked==set(positions)
    assert a.metrics(result,packet,cal)==result['metrics'],'ALL_DAILY_CASH_MARKS'
    results=dict(ctrl,PROFITLOCK=result)
    assert a.canon(c.dd.attribution(ctrl,packet,cal))==a.canon(a.gz(folder/'PARENT_DD_ATTRIBUTION.json.gz'))
    assert a.canon(c.dd.attribution(results,packet,cal))==a.canon(a.gz(folder/'DD_ATTRIBUTION.json.gz'))
    for name,parent,child in [('A',ctrl['C70_LOCAL'],ctrl['C70_TM']),('B',ctrl['C70_TM'],ctrl['CAPREUSE']),('C',ctrl['CAPREUSE'],result),('D',ctrl['C70_LOCAL'],result)]:
        assert a.decomposition(parent,child)==a.read(folder/('DECOMPOSITION_'+name+'.json'))
    assert c.risk_bridge(ctrl['CAPREUSE'],result)==a.read(folder/'RISK_BRIDGE.json')
    assert c.snapshot(result,ctrl['C70_LOCAL'])==a.read(folder/'SNAPSHOT.json')
    return dict(status='PASS',campaigns=len(positions),actual_trace_events=traces,group_close_observations=group_observations,
                profitlock_triggers=trigger_count,max_same_symbol_normalized_qty=maximum,
                source_lifecycle_prefix='PASS',capacity_reuse='PASS',risk_envelope='PASS',parent_replays=0,economic_replays=0)


def verify():
    spec=a.read(c.OUT/'SPEC.json')
    for group in ('source_files_sha256','preserved_files_sha256'):
        for name,digest in spec[group].items():assert a.h(a.ROOT/name)==digest,group+':'+name
    for per,digest in spec['input_packet_sha256'].items():assert a.h(a.INPUTS/(per+'.json.gz'))==digest
    if (c.OUT/'EVIDENCE_HASHES.json').exists():
        for name,digest in a.read(c.OUT/'EVIDENCE_HASHES.json').items():assert a.h(c.OUT/name)==digest,'EVIDENCE:'+name
    prior=a.read(c.OUT/'HISTORY_PRIOR.json');budget=a.read(c.OUT/'BUDGET.json');q=budget['c70_profitlock_allocation']
    assert budget['candidate_trials'][:len(prior['candidate_trials'])]==prior['candidate_trials']
    assert budget['trials'][:len(prior['trials'])]==prior['trials']
    assert budget['cumulative_actual']==spec['candidate_ordinal'] and budget['cumulative_actual_evaluations']==spec['plan'][-1]['evaluation_ordinal']
    assert q['started']==q['completed']==q['reserved']==2 and q['remaining']==q['failed']==0
    assert a.read(c.cap.OUT/'STATUS.json')['status']=='REPORT_ONLY'
    return dict(status='PASS_SAVED_ONLY',periods={per:verify_period(per,spec) for per in a.PERIODS},
                parent_replays=0,economic_replays=0,history_preserved=True)


if __name__=='__main__':print(json.dumps(verify(),indent=2))
