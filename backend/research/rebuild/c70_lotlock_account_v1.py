"""Per-lot money, exact capacity interaction bridge and saved DD windows."""
from math import fsum
from backend.research.rebuild import c70_lotlock_v1 as e
from backend.research.rebuild import c70_tm_capreuse_account_v1 as cap
from backend.research.rebuild import c70_profitlock_dd_v1 as dd

a=cap.a
OUT=a.ROOT/'research/development_evidence'/e.SCOPE


def parents(per,packet,cal):
    result=dd.parents(per,packet,cal)
    result['PROFITLOCK']=a.gz(dd.OUT/per/'RESULT.json.gz')
    return result


def campaign(raw,symbol,packet):
    status,row=cap.campaign(raw,symbol,packet)
    row.update(candidate=e.RULE,evidence_type='ZEL_LOT_LEVEL_POST_PARTIAL_RISK_ENVELOPE',
               lot_lock_exit=raw.get('lot_lock_exit',False))
    row.pop('trade_sha256',None);row.pop('observation_sha256',None)
    row['trade_sha256' if status=='C' else 'observation_sha256']=a.p.sha(row)
    return status,row


def charge(raw_by,packet,cal):
    result=dict(trades=[],open_observations=[],events=[],trace=[],lot_trace=[],audit={},candidate=e.RULE,
                independent=False,formal_credit=0,operating_adoption=False)
    for symbol,rr in sorted(raw_by.items()):
        for raw in rr['trades']+rr['open_positions']:
            status,row=campaign(raw,symbol,packet)
            result['trades' if status=='C' else 'open_observations'].append(row)
        for name in ('events','trace','lot_trace'):
            result[name].extend(dict(x,symbol=symbol) for x in rr[name])
        result['audit'][symbol]=rr['audit']
    result['metrics']=a.metrics(result,packet,cal)
    return result


def snapshot(result,baseline):
    s=cap.snapshot(result,baseline)
    s['lot_lock_trigger_count']=sum(r.get('lot_lock_triggers',0) for r in result.get('audit',{}).values() if isinstance(r,dict))
    s['lot_lock_exited_campaigns']=sum(r.get('lot_lock_exit',False) for r in result['trades'])
    s['lot_lock_exit_normalized_qty']=fsum(l['qty'] for r in result['trades'] for l in r.get('weighted_legs',[]) if l['row'].get('exit_reason')==e.EXIT+'_NEXT_OPEN')
    s['other_lot_collateral_exit_qty']=fsum(l['qty'] for r in result['trades'] for l in r.get('weighted_legs',[])
        if l['row'].get('exit_reason')==e.EXIT+'_NEXT_OPEN' and r['exit_trigger']['lot_signal_index']!=r['signal_index'])
    s['profitlock_trigger_count']=sum(r.get('profitlock_triggers',0) for r in result.get('audit',{}).values() if isinstance(r,dict))
    return s


def risk_bridge(parent,child):
    old=a.bridge._index(parent['trades'],parent['open_observations'])
    new=a.bridge._index(child['trades'],child['open_observations'])
    totals=dict(reduced_own_lot_giveback_gross_bps=0.,cut_later_winner_or_added_loss_gross_bps=0.,
                capacity_followup_gross_bps=0.,additional_total_cost_bps=0.,other_lot_collateral_net_bps=0.)
    details=[]
    for key in sorted(old.keys()|new.keys()):
        pv=a.bridge._values(old.get(key));cv=a.bridge._values(new.get(key))
        direct=interaction=collateral=0.
        if key in old and key in new:
            qp=old[key][1].get('assembled_qty',1.);qc=new[key][1].get('assembled_qty',1.)
            direct=qp*cv['gross_bps']/qc-pv['gross_bps']
            interaction=(qc-qp)*cv['gross_bps']/qc
            if not new[key][1].get('lot_lock_exit',False):
                collateral=qp*cv['net_bps']/qc-pv['net_bps']
                assert abs(collateral)<1e-7,'OTHER_LOT_SOURCE_PATH_CHANGED'
            totals['reduced_own_lot_giveback_gross_bps']+=max(0.,direct)
            totals['cut_later_winner_or_added_loss_gross_bps']+=max(0.,-direct)
        else:
            interaction=cv['gross_bps']-pv['gross_bps']
        dc=cv['cost_bps']-pv['cost_bps']
        totals['capacity_followup_gross_bps']+=interaction
        totals['additional_total_cost_bps']+=dc
        totals['other_lot_collateral_net_bps']+=collateral
        details.append(dict(origin_key=key,direct_own_lot_gross_bps=direct,capacity_followup_gross_bps=interaction,
            additional_cost_bps=dc,other_lot_collateral_net_bps=collateral,delta_net_bps=cv['net_bps']-pv['net_bps']))
    summed=totals['reduced_own_lot_giveback_gross_bps']-totals['cut_later_winner_or_added_loss_gross_bps']+totals['capacity_followup_gross_bps']-totals['additional_total_cost_bps']
    delta=fsum(a.bridge._values(v)['net_bps'] for v in new.values())-fsum(a.bridge._values(v)['net_bps'] for v in old.values())
    assert abs(summed-delta)<1e-7
    return dict(totals=totals,details=details,terminal_delta_bps=delta,residual_bps=summed-delta,
        note='Common own-lot unit-path change at parent quantity; quantity interaction at child unit path plus new/excluded gross; all-union cost delta once. Other uncut unit paths must preserve net. This is an accounting bridge, not an additional strategy counterfactual.')


def attribution(results,packet,cal):
    own={label:dd.own_window(result,packet,cal) for label,result in results.items()}
    pairs=[('C70_LOCAL','C70_TM'),('C70_TM','CAPREUSE'),('CAPREUSE','LOTLOCK'),('C70_LOCAL','LOTLOCK'),('CAPREUSE','PROFITLOCK')]
    adjacent={p+'__'+c:dd.compare(results[p],results[c],packet,cal,own[p],own[c]) for p,c in pairs if p in results and c in results}
    return dict(own=own,adjacent=adjacent,failed_reference_only='PROFITLOCK',
                semantics='SAVED_LOT_ROLE_CASH; OWN_MAXIMA_AND_MATCHED_CHILD_WINDOW_PLUS_RELOCATION; NO_ECONOMIC_REPLAY')
