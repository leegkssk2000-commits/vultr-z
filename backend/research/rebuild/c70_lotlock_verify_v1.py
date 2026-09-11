"""Independent saved-only lot cash, source-prefix, capacity and money checks.

No strategy replay is used here. Each lot's first trigger is reconstructed
from its own saved source fills and completed prices, with independent costs.
"""
from copy import deepcopy
from fractions import Fraction
from math import fsum
import json
from backend.research.rebuild import c70_lotlock_account_v1 as c
from backend.research.rebuild import c63_c70_trader_verify_v1 as old

a=c.a;e=c.e


def qty(raw,stamp,equal=False):
    if raw['entry_ts']>stamp:return Fraction(0)
    fills=sum((Fraction(l['qty']).limit_denominator(3) for l in raw['tm_legs']
               if l['status']=='C' and (l['ts']<stamp or equal and l['ts']==stamp)),Fraction(0))
    return Fraction(raw['allocation_numerator'],raw['allocation_denominator'])*(1-fills)


def own_value(unit,clock,price,cost):
    """Unit cash from this lot alone; equal-time open fills remain unavailable."""
    realized=bank=0.;used=[];first=None
    for leg in unit['tm_legs']:
        if leg['status']!='C' or leg['ts']>=clock:continue
        net=leg['qty']*((leg['price']/unit['entry_price']-1)*10000-
                        fsum(old.independent_cost(cost,unit['entry_ts'],leg['ts']).values()))
        realized+=net;used.append(leg['qty'])
        if leg['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN':
            first=leg['ts'] if first is None else min(first,leg['ts'])
            bank+=max(0.,net)
    remaining=1-fsum(used)
    marked=remaining*((price/unit['entry_price']-1)*10000-
                      fsum(old.independent_cost(cost,unit['entry_ts'],clock).values()))
    return dict(first_partial_fill_ts=first,lot_realized_bank_net=bank,lot_realized_net=realized,
                lot_remaining_mark_net=marked,lot_marked_net=realized+marked,remaining_qty=remaining)


def verify_lots(rr,rows,cost,end):
    raws=rr['trades']+rr['open_positions'];by={r['signal_index']:r for r in raws}
    assert len(by)==len(raws),'ONE_CAMPAIGN_PER_ACTUAL_ENTRY'
    assert set(rr['source_references'])=={str(i) for i in by},'SOURCE_REFERENCE_COVERAGE'
    observations={}
    for t in rr['lot_trace']:
        assert t['kind']=='LOT_CLOSE_OBSERVATION','UNKNOWN_LOT_EVENT'
        k=(t['signal_index'],t['index'])
        assert k not in observations,'DUPLICATE_LOT_OBSERVATION'
        assert t['signal_index'] in by,'FOREIGN_LOT_OBSERVATION'
        observations[k]=t
    checked=set();triggers=0
    for i,raw in by.items():
        unit=rr['source_references'][str(i)]['raw'];peak=None;triggered=None
        q=Fraction(raw['allocation_numerator'],raw['allocation_denominator'])
        for j in range(unit['entry_index'],len(rows)):
            b=rows[j];clock=b['bar_close_ts']
            if clock>end:break
            value=own_value(unit,clock,b['close'],cost)
            if value['remaining_qty']<=0:break
            k=(i,j);assert k in observations,'MISSING_COMPLETED_LOT_OBSERVATION'
            t=observations[k];checked.add(k)
            assert t['ts']==clock and t['price']==b['close'],'COMPLETED_LOT_PRICE'
            assert (t['allocation_numerator'],t['allocation_denominator'])==(q.numerator,q.denominator),'LOT_TRACE_ALLOCATION'
            assert t['cash_semantics']=='UNIT_REFERENCE; NORMALIZED_FIELDS_ARE_ACTUAL_ALLOCATED_LOT'
            assert t['first_partial_fill_ts']==value['first_partial_fill_ts'],'ACTUAL_PARTIAL_FIRST'
            for name,v in value.items():
                if name!='first_partial_fill_ts':old.close(t[name],v,'OWN_LOT_CASH:'+name)
            if value['first_partial_fill_ts'] is not None:
                peak=value['lot_marked_net'] if peak is None else max(peak,value['lot_marked_net'])
            if peak is None:assert t['lot_peak_marked_net'] is None,'PRE_PARTIAL_PEAK'
            else:old.close(t['lot_peak_marked_net'],peak,'OWN_CAUSAL_PEAK')
            for name,unit_value in dict(value,lot_peak_marked_net=peak).items():
                if name=='first_partial_fill_ts':continue
                if unit_value is None:assert t['normalized_'+name] is None,'PRE_PARTIAL_NORMALIZED_PEAK'
                else:old.close(t['normalized_'+name],float(q)*unit_value,'NORMALIZED_OWN_LOT:'+name)
            trigger=bool(value['first_partial_fill_ts'] is not None and value['lot_realized_bank_net']>0 and
                         value['lot_marked_net']<=peak-value['lot_realized_bank_net'])
            assert t['trigger']==trigger,'OWN_LOT_FIRST_THRESHOLD'
            if not trigger:continue
            triggered=t;triggers+=1
            decision=dict(action='FINAL',reason=e.EXIT,signal_index=j,signal_ts=clock,lot_signal_index=i)
            executable=j+1<len(rows) and rows[j+1]['bar_open_ts']<end
            if executable:
                assert rows[j+1]['bar_open_ts']==clock,'NEXT_ACTUAL_OPEN_CLOCK'
                remainder=1-fsum(l['qty'] for l in unit['tm_legs'] if l['status']=='C' and l['ts']<=clock)
                if remainder>0:
                    assert raw['lot_lock_exit'] and raw['exit_trigger']==decision,'OWN_RISK_EXIT_REQUIRED'
                    assert raw['exit_ts']==clock and raw['exit_index']==j+1,'OWN_NEXT_OPEN_EXIT'
                else:
                    assert not raw['lot_lock_exit'],'SOURCE_FULL_EXIT_PRIORITY'
            else:
                assert not raw['lot_lock_exit'],'NO_UNOBSERVABLE_TERMINAL_FILL'
                assert raw['pending_lot_envelope']==decision,'TERMINAL_PENDING_LOT_DECISION'
                assert raw['tm_legs'][-1]['status']=='O','TERMINAL_MARK_RETAINED'
            break
        if triggered is None:
            assert not raw['lot_lock_exit'],'OTHER_LOT_COLLATERAL_EXIT'
            assert 'pending_lot_envelope' not in raw,'UNTRIGGERED_PENDING_EXIT'
    assert checked==set(observations),'POST_TRIGGER_OR_FOREIGN_LOT_OBSERVATION'
    assert triggers==rr['audit']['lot_lock_triggers'],'TRIGGER_COUNT'
    assert sum(r['lot_lock_exit'] for r in raws)==rr['audit']['lot_lock_exited_campaigns'],'EXIT_COUNT'
    return len(checked),triggers


def verify_source_actual(raw,trace,reference,rows,cost,end,lot_trace):
    unit=reference['raw'];source_trace=reference['trace']
    old.verify_campaign(unit,source_trace,rows,cost,end)
    q=Fraction(raw['allocation_numerator'],raw['allocation_denominator'])
    assert q>0
    for t in trace:
        assert t['signal_index']==raw['signal_index'],'OTHER_LOT_TRACE'
        assert (t['allocation_numerator'],t['allocation_denominator'])==(q.numerator,q.denominator),'TRACE_ALLOCATION'
        if 'qty' in t:old.close(t['normalized_fill_qty'],float(q)*t['qty'],'NORMALIZED_FILL')
        if 'remaining_qty' in t:old.close(t['remaining_normalized_qty'],float(q)*t['remaining_qty'],'NORMALIZED_REMAINDER')
    clean=lambda t:{k:v for k,v in t.items() if k not in
                    ('allocation_numerator','allocation_denominator','normalized_fill_qty','remaining_normalized_qty')}
    actual=[clean(t) for t in trace]
    if raw['lot_lock_exit']:
        j=raw['exit_index'];stamp=raw['exit_ts'];decision=raw['exit_trigger']
        triggers=[t for t in lot_trace if t['signal_index']==raw['signal_index'] and t['trigger']]
        assert len(triggers)==1,'EACH_RISK_EXIT_HAS_OWN_FIRST_TRIGGER'
        trigger=triggers[0]
        assert decision==dict(action='FINAL',reason=e.EXIT,signal_index=j-1,signal_ts=stamp,
                              lot_signal_index=raw['signal_index']),'NO_OTHER_LOT_DECISION'
        assert trigger['index']==j-1 and trigger['ts']==stamp,'TRIGGER_TO_FILL'
        assert rows[j]['bar_open_ts']==stamp<end and raw['exit_price']==rows[j]['open'],'OBSERVABLE_GAP_FILL'
        expected=[deepcopy(l) for l in unit['tm_legs'] if l['status']=='C' and l['ts']<=stamp]
        remainder=1-fsum(l['qty'] for l in expected);assert remainder>0,'SOURCE_FULL_EXIT_PRIORITY'
        expected.append(dict(status='C',qty=remainder,index=j,ts=stamp,price=rows[j]['open'],reason=e.EXIT+'_NEXT_OPEN'))
        assert raw['tm_legs']==expected and raw['remaining_qty']==0,'ONLY_OWN_REMAINDER_CLOSED'
        prefix=[t for t in source_trace if t['index']<j or t['index']==j and t['kind']=='PARTIAL_FILL']
        assert actual[:-1]==prefix,'SOURCE_PREFIX_CHANGED'
        final=dict(kind='FINAL_FILL',ts=stamp,index=j,price=rows[j]['open'],remaining_qty=0.,decision=decision,
                   slot_released=True,signal_index=raw['signal_index'],lot_lock_exit=True)
        assert actual[-1]==final,'ONE_OWN_FINAL_FILL'
        assert raw['partial_count']==sum(l['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' for l in expected)
        assert raw['runner_activated']==bool(raw['partial_count']) and raw['partial_count']>0,'ACTUAL_PARTIAL_BEFORE_RISK'
        assert raw['hold_ms']==stamp-raw['entry_ts']
        entry=raw['entry_price'];held=rows[raw['entry_index']:j]
        old.close(raw['gross_bps'],fsum(l['qty']*(l['price']/entry-1)*10000 for l in expected),'CUT_GROSS')
        old.close(raw['mfe_bps'],max([0.,(rows[j]['open']/entry-1)*10000]+[(b['high']/entry-1)*10000 for b in held]),'CUT_MFE_PREFIX')
        old.close(raw['mae_bps'],min([0.,(rows[j]['open']/entry-1)*10000]+[(b['low']/entry-1)*10000 for b in held]),'CUT_MAE_PREFIX')
        for name in ('signal_index','signal_ts','entry_index','entry_ts','entry_price','fixed_floor',
                     'fixed_target','setup_id','assembled_qty','side'):
            assert raw[name]==unit[name],'ORIGINAL_ENTRY_CHANGED:'+name
    else:
        for name,value in unit.items():
            if name=='censor_reason' and raw.get('pending_lot_envelope'):continue
            assert raw[name]==value,'UNCUT_SOURCE_LIFECYCLE_CHANGED:'+name
        assert actual==source_trace,'OTHER_LOT_SOURCE_PATH_CHANGED'
    old.close(fsum(l['qty'] for l in raw['tm_legs']),1.,'LOT_QUANTITY_CONSERVATION')


def verify_period(per,spec):
    folder=c.OUT/per;packet=a.gz(a.INPUTS/(per+'.json.gz'));cal=spec['periods'][per]
    raw=a.gz(folder/'RAW.json.gz');result=a.gz(folder/'RESULT.json.gz');ctrl=c.parents(per,packet,cal)
    parent_raw=a.gz(c.cap.OUT/per/'RAW.json.gz')
    positions={a.key(t):(status,t) for status,name in [('C','trades'),('O','open_observations')] for t in result[name]}
    assert len(positions)==len(result['trades'])+len(result['open_observations']),'UNIQUE_CAMPAIGN_RESULTS'
    checked=set();traces=lot_observations=trigger_count=0;maximum=0.
    for symbol,rr in raw.items():
        rows=packet['rows_by'][symbol];cost=packet['costs'][symbol];seen=[];symbol_traces=0
        by={r['signal_index']:r for r in rr['trades']+rr['open_positions']}
        obs,trig=verify_lots(rr,rows,cost,cal['runoff_end_ms']);lot_observations+=obs;trigger_count+=trig
        assert len(rr['events'])==len(parent_raw[symbol]['events'])
        for event,parent in zip(rr['events'],parent_raw[symbol]['events'],strict=True):
            i=event['signal_index'];stamp=event['signal_ts']
            for name in ('signal_index','signal_ts','episode_start','floor','target','expiry','er_context'):
                assert event[name]==parent[name],'EXACT_REG71_SIGNAL:'+name
            active=sum((qty(r,stamp) for r in seen),Fraction(0));available=1-active;assert 0<=active<=1
            old.close(event['active_normalized_qty'],float(active),'DECISION_CAPACITY')
            old.close(event['available_capacity'],float(available),'AVAILABLE_CAPACITY')
            assert event['available_fraction']==[available.numerator,available.denominator]
            assert event['decision_phase']=='CLOSE_BEFORE_EQUAL_TIMESTAMP_OPEN_FILLS'
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
            old.close(event['entry_normalized_qty'],float(q),'RESERVED_ENTRY_QTY')
            old.close(r['allocated_normalized_qty'],float(q),'ACTUAL_ENTRY_QTY')
            before=sum((qty(t,stamp,True) for t in seen),Fraction(0))
            old.close(event['active_after_entry'],float(before+q),'NO_EQUAL_OPEN_UPSIZE')
            trace=[t for t in rr['trace'] if t['signal_index']==i];traces+=len(trace);symbol_traces+=len(trace)
            verify_source_actual(r,trace,rr['source_references'][str(i)],rows,cost,cal['runoff_end_ms'],rr['lot_trace'])
            k=(symbol,i,stamp);checked.add(k);status,row=positions[k]
            assert c.campaign(r,symbol,packet)==(status,row),'SAVED_CAMPAIGN_EXPORT'
            assert event['status']==('COMPLETED' if status=='C' else 'CENSORED'),'ACTUAL_CAMPAIGN_STATUS'
            values=dict.fromkeys(a.bridge.VALUE_FIELDS,0.)
            for leg,weighted in zip(r['tm_legs'],row['weighted_legs'],strict=True):
                w=float(q)*leg['qty'];old.close(weighted['qty'],w,'WEIGHTED_LEG_QUANTITY')
                parts=old.independent_cost(cost,r['entry_ts'],leg['ts']);paid=fsum(parts.values())
                gross=(leg['price']/r['entry_price']-1)*10000
                for name,value in dict(gross_bps=gross,cost_bps=paid,net_bps=gross-paid,cost2x_net_bps=gross-2*paid,**parts).items():values[name]+=w*value
            for name,value in a.bridge._values((status,row)).items():old.close(value,values[name],'CASH:'+name)
            seen.append(r)
        assert symbol_traces==len(rr['trace']),'ACTUAL_TRACE_COVERAGE'
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
    assert checked==set(positions),'CAMPAIGN_COVERAGE'
    assert a.metrics(result,packet,cal)==result['metrics'],'ALL_DAILY_CASH_MARKS'
    for name in ('events','trace','lot_trace'):
        assert result[name]==[dict(t,symbol=symbol) for symbol,rr in sorted(raw.items()) for t in rr[name]],'RESULT_TRACE_COVERAGE:'+name
    results=dict(ctrl,LOTLOCK=result)
    assert a.canon(c.attribution(ctrl,packet,cal))==a.canon(a.gz(folder/'PARENT_DD_ATTRIBUTION.json.gz'))
    assert a.canon(c.attribution(results,packet,cal))==a.canon(a.gz(folder/'DD_ATTRIBUTION.json.gz'))
    for name,parent,child in [('A',ctrl['C70_LOCAL'],ctrl['C70_TM']),('B',ctrl['C70_TM'],ctrl['CAPREUSE']),
                              ('C',ctrl['CAPREUSE'],result),('D',ctrl['C70_LOCAL'],result)]:
        assert a.decomposition(parent,child)==a.read(folder/('DECOMPOSITION_'+name+'.json'))
    assert c.risk_bridge(ctrl['CAPREUSE'],result)==a.read(folder/'RISK_BRIDGE.json')
    assert c.snapshot(result,ctrl['C70_LOCAL'])==a.read(folder/'SNAPSHOT.json')
    return dict(status='PASS',campaigns=len(positions),actual_trace_events=traces,lot_close_observations=lot_observations,
                lot_lock_triggers=trigger_count,max_same_symbol_normalized_qty=maximum,
                other_lot_collateral_exit_qty=0.,other_lot_collateral_pnl_bps=0.,
                source_lifecycle_prefix='PASS',capacity_reuse='PASS',independent_lot_risk='PASS',
                parent_replays=0,economic_replays=0)


def verify_history(spec,prior,budget):
    q=budget['c70_lotlock_allocation']
    assert spec['scope']==e.SCOPE and spec['candidate']==e.RULE,'NEW_SCOPE_ONLY'
    assert spec['max_candidates']==q['max_candidates']==1 and spec['max_FULL']==q['max_executions']==2
    assert q['scope']==e.SCOPE and q['retry'] is False
    for name,value in prior.items():
        if name not in ('candidate_trials','trials','cumulative_actual','cumulative_actual_evaluations'):
            assert budget[name]==value,'INHERITED_BUDGET_PRESERVED:'+name
    assert budget['candidate_trials'][:len(prior['candidate_trials'])]==prior['candidate_trials']
    assert budget['trials'][:len(prior['trials'])]==prior['trials']
    assert budget['cumulative_actual']==spec['candidate_ordinal'] and budget['cumulative_actual_evaluations']==spec['plan'][-1]['evaluation_ordinal']
    assert budget['cumulative_actual']==prior['cumulative_actual']+1
    assert budget['cumulative_actual_evaluations']==prior['cumulative_actual_evaluations']+2
    assert len(budget['candidate_trials'])==len(prior['candidate_trials'])+1
    assert len(budget['trials'])==len(prior['trials'])+2
    assert q['started']==q['completed']==q['reserved']==2 and q['remaining']==q['failed']==0
    candidate=budget['candidate_trials'][-1]
    assert candidate==dict(candidate=e.RULE,first_evaluation=spec['plan'][0]['evaluation_ordinal'],
                           ordinal=spec['candidate_ordinal'],scope=e.SCOPE),'ONE_NEW_CANDIDATE'
    assert [p['period'] for p in spec['plan']]==list(a.PERIODS),'TWO_EXISTING_WINDOWS_ONCE'
    assert q['candidate_ordinal']==spec['candidate_ordinal']
    assert q['evaluation_ordinals']==[p['evaluation_ordinal'] for p in spec['plan']]
    frozen=set()
    for planned,trial in zip(spec['plan'],budget['trials'][-2:],strict=True):
        assert trial['status']=='COMPLETED' and trial['scope']==e.SCOPE and trial['variant']==e.RULE
        assert trial['execution_mode']=='LOCAL_WORK_FIRST_FULL'
        for name in ('period','candidate_ordinal','evaluation_ordinal'):assert trial[name]==planned[name]
        assert trial['actual_experiment_ordinal']==trial['evaluation_ordinal']
        assert trial['spec_sha256']==a.h(c.OUT/'SPEC.json'),'FROZEN_SPEC_RECEIPT'
        started=a.read(c.OUT/trial['period']/'EXECUTION_STARTED.json')
        attempt=a.read(c.OUT/trial['period']/'ATTEMPT.json')
        assert attempt==trial,'ATTEMPT_LEDGER_PARITY'
        assert started==dict({k:v for k,v in trial.items() if k!='finished_ns'},status='STARTED'),'START_RESERVATION_PARITY'
        assert spec['frozen_ns']<=trial['started_ns']<trial['finished_ns'],'FREEZE_BEFORE_EXECUTION'
        frozen.add(trial['frozen_commit'])
    assert len(frozen)==1,'SAME_FROZEN_CANDIDATE_BOTH_WINDOWS'


def verify():
    spec=a.read(c.OUT/'SPEC.json')
    for group in ('source_files_sha256','preserved_files_sha256'):
        for name,digest in spec[group].items():assert a.h(a.ROOT/name)==digest,group+':'+name
    for per,digest in spec['input_packet_sha256'].items():assert a.h(a.INPUTS/(per+'.json.gz'))==digest
    if (c.OUT/'EVIDENCE_HASHES.json').exists():
        for name,digest in a.read(c.OUT/'EVIDENCE_HASHES.json').items():assert a.h(c.OUT/name)==digest,'EVIDENCE:'+name
    verify_history(spec,a.read(c.OUT/'HISTORY_PRIOR.json'),a.read(c.OUT/'BUDGET.json'))
    assert a.read(c.cap.OUT/'STATUS.json')['status']=='REPORT_ONLY'
    assert a.read(c.dd.OUT/'STATUS.json')['status']=='REPORT_ONLY'
    return dict(status='PASS_SAVED_ONLY',periods={per:verify_period(per,spec) for per in a.PERIODS},
                parent_replays=0,economic_replays=0,history_preserved=True)


if __name__=='__main__':print(json.dumps(verify(),indent=2))
