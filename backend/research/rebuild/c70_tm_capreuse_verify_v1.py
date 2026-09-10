"""Saved-only independent capacity ledger, frozen lifecycle and cash checks."""
from copy import deepcopy
from fractions import Fraction
from math import fsum
import json
from backend.research.rebuild import c70_tm_capreuse_account_v1 as c
from backend.research.rebuild import c63_c70_trader_verify_v1 as old

a=c.a


def verify_period(per,spec):
    folder=c.OUT/per;cal=spec['periods'][per];packet=a.gz(a.INPUTS/(per+'.json.gz'))
    raw=a.gz(folder/'RAW.json.gz');result=a.gz(folder/'RESULT.json.gz');ctrl=c.parents(per,packet,cal)
    parent_raw=a.gz(a.OUT/'C70_TM'/per/'RAW.json.gz')
    positions={a.key(t):(status,t) for status,name in [('C','trades'),('O','open_observations')] for t in result[name]}
    checked=set();trace_count=0;max_active=Fraction(0);common_exact=0
    for symbol,rr in raw.items():
        rows=packet['rows_by'][symbol]
        parent_events={x['signal_index']:x for x in parent_raw[symbol]['events']}
        prior_raw={t['signal_index']:t for t in parent_raw[symbol]['trades']+parent_raw[symbol]['open_positions']}
        by={t['signal_index']:t for t in rr['trades']+rr['open_positions']}
        assert len(by)==len(rr['trades'])+len(rr['open_positions'])
        assert [e['signal_index'] for e in rr['events']]==[e['signal_index'] for e in parent_raw[symbol]['events']]
        admitted=[];ledger=[]
        for event in rr['events']:
            i=event['signal_index'];stamp=event['signal_ts'];parent=parent_events[i]
            for name in ('signal_index','signal_ts','episode_start','floor','target','expiry','er_context'):
                assert event[name]==parent[name],'FROZEN_REG71_ENTRY:'+name
            # Independent reconstruction at close: equal-time next-open fills
            # cannot finance this decision. Only earlier admitted lots count.
            active=Fraction(0)
            for r in admitted:
                q=Fraction(r['allocation_numerator'],r['allocation_denominator'])
                released=sum((Fraction(1,3) if l['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' else
                              Fraction(2,3) if r['partial_count'] else Fraction(1))
                             for l in r['tm_legs'] if l['status']=='C' and l['ts']<stamp)
                active+=q*(1-released)
            available=1-active;assert 0<=active<=1
            old.close(event['active_normalized_qty'],float(active),'DECISION_ACTIVE_QTY')
            old.close(event['available_capacity'],float(available),'DECISION_AVAILABLE_CAPACITY')
            assert event['available_fraction']==[available.numerator,available.denominator]
            if available<=0:reason=c.engine.OCCUPIED
            elif event['expiry'] is not None and stamp>=event['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
            elif not event['er_context']['eligible']:reason=event['er_context']['reason']
            elif i+1>=len(rows) or rows[i+1]['bar_open_ts']>=cal['runoff_end_ms']:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
            elif rows[i+1]['open']<=event['floor'] or event['target'] is not None and rows[i+1]['open']>=event['target']:reason='GAP_INVALIDATES_FIXED_SETUP'
            else:reason=None
            assert event['admission']==(reason is None) and event['exclusion_reason']==reason,'CAPACITY_ADMISSION'
            if reason is not None:
                assert i not in by;continue
            r=by[i];q=Fraction(r['allocation_numerator'],r['allocation_denominator'])
            assert q==min(Fraction(1),available) and event['capacity_reuse_entry']==(active>0)==r['capacity_reuse_entry']
            old.close(event['entry_normalized_qty'],float(q),'ENTRY_RESERVED_QTY')
            trace=[t for t in rr['trace'] if t['signal_index']==i]
            trace_count+=old.verify_campaign(r,trace,rows,packet['costs'][symbol],cal['runoff_end_ms'])
            if i in prior_raw:
                for name,value in prior_raw[i].items():assert r[name]==value,'COMMON_UNIT_LIFECYCLE_CHANGED:'+name
                common_exact+=1
            ledger.append((r['entry_ts'],2,i,q))
            for leg in r['tm_legs']:
                if leg['status']=='C':
                    lq=Fraction(1,3) if leg['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' else Fraction(2,3) if r['partial_count'] else Fraction(1)
                    ledger.append((leg['ts'],1,i,-q*lq))
            k=(symbol,i,stamp);checked.add(k);status,row=positions[k]
            expected_status,expected=c.campaign(r,symbol,packet)
            assert (status,row)==(expected_status,expected),'CAMPAIGN_EXPORT'
            totals=dict.fromkeys(a.bridge.VALUE_FIELDS,0.)
            for leg,weighted in zip(r['tm_legs'],row['weighted_legs'],strict=True):
                qty=float(q)*leg['qty'];old.close(weighted['qty'],qty,'WEIGHTED_QUANTITY')
                parts=old.independent_cost(packet['costs'][symbol],r['entry_ts'],leg['ts']);cost=fsum(parts.values())
                gross=(leg['price']/r['entry_price']-1)*10000
                values=dict(gross_bps=gross,cost_bps=cost,net_bps=gross-cost,cost2x_net_bps=gross-2*cost,**parts)
                for name,value in values.items():totals[name]+=qty*value
            aggregate=a.bridge._values((status,row))
            for name,value in totals.items():old.close(aggregate[name],value,'NORMALIZED_CASH:'+name)
            admitted.append(r)
        current=Fraction(0);last_ts=None;timeline=[]
        for stamp,phase,i,delta in sorted(ledger):
            if last_ts is not None and last_ts!=stamp:timeline.append(dict(ts=last_ts,active_after_open=float(current)))
            current+=delta;assert 0<=current<=1,'EVERY_FILL_SAME_SYMBOL_CAP'
            max_active=max(max_active,current);last_ts=stamp
        if last_ts is not None:timeline.append(dict(ts=last_ts,active_after_open=float(current)))
        assert timeline==rr['capacity_timeline'],'SAVED_CAPACITY_TIMELINE'
        open_quantity=sum(Fraction(r['allocation_numerator'],r['allocation_denominator'])*
                          (Fraction(2,3) if r['partial_count'] else Fraction(1)) for r in rr['open_positions'])
        assert current==open_quantity,'TERMINAL_CAPACITY_CONSERVATION'
    assert checked==set(positions),'CAMPAIGN_COVERAGE'
    assert a.metrics(result,packet,cal)==result['metrics'],'ALL_DAILY_CASH_MARKS'
    expected_events=[dict(e,symbol=symbol) for symbol,rr in sorted(raw.items()) for e in rr['events']]
    assert result['events']==expected_events
    for name,parent,child in [('A',ctrl['C70_LOCAL'],ctrl['C70_TM']),('B',ctrl['C70_TM'],result),('C',ctrl['C70_LOCAL'],result)]:
        assert a.decomposition(parent,child)==a.read(folder/('DECOMPOSITION_'+name+'.json'))
    assert c.repair_bridge(ctrl['C70_TM'],result,ctrl['C70_LOCAL'])==a.read(folder/'REPAIR_BRIDGE.json')
    assert a.canon(c.diagnose(per,packet,cal,ctrl))==a.canon(a.read(folder/'OCCUPANCY_DIAGNOSTIC.json'))
    assert c.snapshot(result,ctrl['C70_LOCAL'])==a.read(folder/'SNAPSHOT.json')
    return dict(status='PASS',campaigns=len(positions),trace_events=trace_count,
                unchanged_common_unit_lifecycles=common_exact,max_same_symbol_normalized_qty=float(max_active),
                source_conformance='PR1260_PRESERVED_PASS',ZEL_occupancy_repair='PASS',economic_replays=0)


def verify():
    spec=a.read(c.OUT/'SPEC.json')
    correction=a.read(c.OUT/'VERIFIER_CORRECTION.json')
    assert a.h(c.OUT/'FROZEN_VERIFIER.py.txt')==correction['frozen_sha256']
    for group in ('source_files_sha256','preserved_files_sha256'):
        for name,digest in spec[group].items():
            if group=='source_files_sha256' and name==correction['path']:
                assert digest==correction['frozen_sha256'];digest=correction['corrected_sha256']
            assert a.h(a.ROOT/name)==digest,group+':'+name
    for per,digest in spec['input_packet_sha256'].items():assert a.h(a.INPUTS/(per+'.json.gz'))==digest,'INPUT_HASH'
    if (c.OUT/'EVIDENCE_HASHES.json').exists():
        for name,digest in a.read(c.OUT/'EVIDENCE_HASHES.json').items():assert a.h(c.OUT/name)==digest,'EVIDENCE_HASH:'+name
    budget=a.read(c.OUT/'BUDGET.json');prior=a.read(c.OUT/'HISTORY_PRIOR.json');q=budget['c70_tm_capreuse_allocation']
    assert budget['candidate_trials'][:len(prior['candidate_trials'])]==prior['candidate_trials']
    assert budget['trials'][:len(prior['trials'])]==prior['trials']
    assert (budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(82,148)
    assert q['started']==q['completed']==q['reserved']==2 and q['remaining']==q['failed']==0
    assert a.read(a.OUT/'STATUS.json')['status']=='REPORT_ONLY'
    return dict(status='PASS_SAVED_ONLY',periods={per:verify_period(per,spec) for per in a.PERIODS},
                parent_replays=0,economic_replays=0,history_preserved=True)


if __name__=='__main__':print(json.dumps(verify(),indent=2))
