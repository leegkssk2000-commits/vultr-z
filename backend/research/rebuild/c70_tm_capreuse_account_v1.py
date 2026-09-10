"""Normalized capacity accounting and saved-parent diagnostics. No replay CLI."""
from copy import deepcopy
from math import fsum
from backend.research.rebuild import c63_c70_trader_account_v1 as a
from backend.research.rebuild import c70_tm_capreuse_v1 as engine

OUT=a.ROOT/'research/development_evidence'/engine.SCOPE


def parents(per, packet, cal):
    return {'C70_LOCAL':a.parents(per,packet,cal)['C70_LOCAL'],
            'C70_TM':a.gz(a.OUT/'C70_TM'/per/'RESULT.json.gz')}


def campaign(raw, symbol, packet):
    status,row=a.campaign(raw,symbol,'C70_TM',packet)
    q=float(engine.allocation(raw))
    for leg in row['weighted_legs']:
        leg['qty']*=q;leg['numerator']=leg['qty']
    values={k:fsum(a.bridge._values((l['status'],l['row']))[k]*l['qty'] for l in row['weighted_legs'])
            for k in a.bridge.VALUE_FIELDS}
    row.update(candidate=engine.RULE,assembled_qty=q,remaining_qty=q*raw['remaining_qty'],
               allocation_numerator=raw['allocation_numerator'],allocation_denominator=raw['allocation_denominator'],
               capacity_reuse_entry=raw['capacity_reuse_entry'],
               evidence_type='ZEL_OCCUPANCY_REPAIR_OF_FROZEN_SOURCE_MANAGER',
               return_semantics='BPS_PER_ORIGINAL_FULL_ENTRY_REFERENCE_WEIGHTED_BY_ALLOCATED_CAPACITY')
    row.pop('trade_sha256',None);row.pop('observation_sha256',None)
    if status=='C':row.update(values)
    else:
        row.update(gross_mark_bps=values['gross_bps'],hypothetical_liquidation_net_mark_bps=values['net_bps'],
                   hypothetical_liquidation_cost2x_net_mark_bps=values['cost2x_net_bps'],
                   hypothetical_liquidation_cost_bps=values['cost_bps'],
                   hypothetical_cost_components_bps={k:values[k] for k in a.bridge.COST_FIELDS})
    row['trade_sha256' if status=='C' else 'observation_sha256']=a.p.sha(row)
    return status,row


def charge(raw_by, packet, cal):
    result=dict(trades=[],open_observations=[],events=[],trace=[],audit={},candidate=engine.RULE,
                independent=False,formal_credit=0,operating_adoption=False)
    for symbol,rr in sorted(raw_by.items()):
        for raw in rr['trades']+rr['open_positions']:
            status,row=campaign(raw,symbol,packet)
            result['trades' if status=='C' else 'open_observations'].append(row)
        for name in ('events','trace'):result[name].extend(dict(x,symbol=symbol) for x in rr[name])
        result['audit'][symbol]=rr['audit']
    result['metrics']=a.metrics(result,packet,cal)
    return result


def diagnose(per, packet, cal, ctrl):
    """Sealed parent records only; no blocked signal's future PnL is inspected."""
    raw=a.gz(a.OUT/'C70_TM'/per/'RAW.json.gz')
    base={a.key(t):t for t in ctrl['C70_LOCAL']['trades']+ctrl['C70_LOCAL']['open_observations']}
    details=[]
    for symbol,rr in sorted(raw.items()):
        for event in rr['events']:
            if event['exclusion_reason']!=engine.OCCUPIED:continue
            stamp=event['signal_ts'];i=event['signal_index'];active=[]
            for r in rr['trades']+rr['open_positions']:
                if r['entry_ts']>stamp:continue
                qty=engine.remaining(r,stamp)
                if qty<=0:continue
                partial=fsum(l['qty'] for l in r['tm_legs'] if l['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' and l['ts']<stamp)
                active.append(dict(origin=[symbol,r['signal_index'],r['signal_ts']],active_qty=float(qty),
                                   filled_partial_qty=partial,runner_active=partial>0))
            total=fsum(r['active_qty'] for r in active)
            rows=packet['rows_by'][symbol];nextopen=i+1<len(rows) and rows[i+1]['bar_open_ts']<cal['runoff_end_ms']
            key=(symbol,i,stamp)
            details.append(dict(origin=key,exclusion_ts=stamp,active_campaigns=active,
                active_runner_qty=fsum(r['active_qty'] for r in active if r['runner_active']),
                already_filled_partial_qty=fsum(r['filled_partial_qty'] for r in active),
                available_capacity=max(0.,1-total),next_open_available=nextopen,
                original_eligible=event['er_context']['eligible'],
                gap_valid=bool(nextopen and rows[i+1]['open']>event['floor']),
                baseline_campaign_origin=key if key in base else None))
    return dict(kind='SAVED_LEDGER_DIAGNOSTIC_NOT_OUTCOME_FILTER',period=per,details=details,
                occupancy_exclusions=len(details),positive_released_capacity=sum(d['available_capacity']>0 for d in details),
                lost_baseline_campaigns=sum(d['baseline_campaign_origin'] is not None for d in details),
                parent_replays=0,blocked_future_pnl_read=False)


def snapshot(result, baseline):
    s=a.snapshot(result,baseline)
    s['capacity_reuse_entry_count']=sum(t.get('capacity_reuse_entry',False) for t in result['trades']+result['open_observations'])
    s['occupancy_lost_count']=s['exclusions'].get(engine.OCCUPIED,0)
    return s


def repair_bridge(parent, child, baseline):
    old=a.bridge._index(parent['trades'],parent['open_observations'])
    new=a.bridge._index(child['trades'],child['open_observations'])
    base=a.bridge._index(baseline['trades'],baseline['open_observations'])
    buckets={name:dict.fromkeys(a.bridge.VALUE_FIELDS,0.) for name in
             ('COMMON_CAMPAIGN_CAPACITY_CHANGE','RESTORED_BASELINE_CAMPAIGN','NEW_OCCUPANCY_INTERACTION','EXCLUDED_TM_CAMPAIGN')}
    details=[]
    for k in sorted(old.keys()|new.keys()):
        group=('COMMON_CAMPAIGN_CAPACITY_CHANGE' if k in old and k in new else
               'EXCLUDED_TM_CAMPAIGN' if k not in new else
               'RESTORED_BASELINE_CAMPAIGN' if k in base else 'NEW_OCCUPANCY_INTERACTION')
        pv=a.bridge._values(old.get(k));cv=a.bridge._values(new.get(k))
        delta={field:cv[field]-pv[field] for field in a.bridge.VALUE_FIELDS}
        for field,value in delta.items():buckets[group][field]+=value
        details.append(dict(origin=k,group=group,delta=delta))
    delta=a.decomposition(parent,child)['terminal_delta_bps']
    residual=fsum(v['gross_bps']-v['cost_bps'] for v in buckets.values())-delta
    assert abs(residual)<1e-7
    return dict(buckets=buckets,details=details,terminal_delta_bps=delta,residual_bps=residual,
                same_origin_source_lifecycle_unchanged=True,costs_include_fee_funding_and_floor_reserve=True)
