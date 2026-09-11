"""Inherited normalized campaign money plus risk-repair report adapters."""
from math import fsum
from backend.research.rebuild import c70_profitlock_v1 as e
from backend.research.rebuild import c70_profitlock_dd_v1 as dd

cap=dd.cap;a=dd.a;OUT=dd.OUT


def campaign(raw,symbol,packet):
    status,row=cap.campaign(raw,symbol,packet)
    row['candidate']=e.RULE;row['evidence_type']='ZEL_POST_PARTIAL_RISK_ENVELOPE'
    row.pop('trade_sha256',None);row.pop('observation_sha256',None)
    row['trade_sha256' if status=='C' else 'observation_sha256']=a.p.sha(row)
    return status,row


def charge(raw_by,packet,cal):
    result=dict(trades=[],open_observations=[],events=[],trace=[],group_trace=[],audit={},candidate=e.RULE,
                independent=False,formal_credit=0,operating_adoption=False)
    for symbol,rr in sorted(raw_by.items()):
        for raw in rr['trades']+rr['open_positions']:
            status,row=campaign(raw,symbol,packet);result['trades' if status=='C' else 'open_observations'].append(row)
        for name in ('events','trace','group_trace'):result[name].extend(dict(x,symbol=symbol) for x in rr[name])
        result['audit'][symbol]=rr['audit']
    result['metrics']=a.metrics(result,packet,cal)
    return result


def snapshot(result,baseline):
    value=cap.snapshot(result,baseline)
    value['profitlock_trigger_count']=sum(r.get('profitlock_triggers',0) for r in result.get('audit',{}).values() if isinstance(r,dict))
    value['profitlock_exited_campaigns']=sum(t.get('risk_envelope_exit',False) for t in result['trades'])
    return value


def risk_bridge(parent,child):
    old=a.bridge._index(parent['trades'],parent['open_observations']);new=a.bridge._index(child['trades'],child['open_observations'])
    totals=dict(reduced_runner_reuse_giveback_gross_bps=0.,cut_later_winner_gross_bps=0.,
                common_quantity_interaction_gross_bps=0.,additional_common_cost_bps=0.,followup_new_excluded_net_bps=0.)
    details=[]
    for k in sorted(old.keys()|new.keys()):
        pv=a.bridge._values(old.get(k));cv=a.bridge._values(new.get(k));dg=cv['gross_bps']-pv['gross_bps'];dn=cv['net_bps']-pv['net_bps']
        if k not in old or k not in new:
            group='FOLLOWUP_NEW_EXCLUDED';totals['followup_new_excluded_net_bps']+=dn
        else:
            totals['additional_common_cost_bps']+=cv['cost_bps']-pv['cost_bps']
            if old[k][1].get('assembled_qty',1.)!=new[k][1].get('assembled_qty',1.):
                group='COMMON_QUANTITY_INTERACTION';totals['common_quantity_interaction_gross_bps']+=dg
            elif dg>=0:
                group='REDUCED_GIVEBACK_OR_LOSS';totals['reduced_runner_reuse_giveback_gross_bps']+=dg
            else:
                group='CUT_LATER_WIN_OR_ADDED_LOSS';totals['cut_later_winner_gross_bps']-=dg
        details.append(dict(origin_key=k,group=group,delta_gross_bps=dg,delta_net_bps=dn,delta_cost_bps=cv['cost_bps']-pv['cost_bps']))
    summed=totals['reduced_runner_reuse_giveback_gross_bps']-totals['cut_later_winner_gross_bps']+totals['common_quantity_interaction_gross_bps']-totals['additional_common_cost_bps']+totals['followup_new_excluded_net_bps']
    delta=fsum(a.bridge._values(v)['net_bps'] for v in new.values())-fsum(a.bridge._values(v)['net_bps'] for v in old.values())
    assert abs(summed-delta)<1e-7
    return dict(totals=totals,details=details,terminal_delta_bps=delta,residual_bps=summed-delta,
                note='Positive/negative common gross differences include loss changes; new/excluded use net. Quantity interactions are explicit, never mislabeled as pure runner management.')
