"""Lot money -> one campaign -> existing daily DD/accounting; no market replay."""
from copy import deepcopy
from math import fsum
from unittest.mock import patch
from backend.research.rebuild import c63_initial_failure_f_study_v1 as old
from backend.research.rebuild import parallel_exit_metrics_v1 as marks
from backend.research.rebuild import jc_lifecycle_v1 as engine
p=old.p;bridge=old.a.owner


def raw_leg(c,l,status):
    value=dict(signal_index=c['signal_index'],signal_ts=c['setup']['setup_ts'],side='long',
        entry_index=l['entry_index'],entry_price=l['entry_price'],entry_ts=l['entry_ts'],
        hold_ms=l['exit_ts']-l['entry_ts'],mfe_bps=None,mae_bps=None,
        excursion_semantics='NOT_TICK_RECONSTRUCTED',setup_id=engine.RULE_ID+':'+str(c['setup']['setup_ts']),
        exit_timestamp_semantics='OBSERVED_OPEN_OR_INTRABAR_CLOSE_UPPER_BOUND',
        original_protective_sl=c['initial_stop'])
    gross=(l['exit_price']/l['entry_price']-1)*10000
    if status=='C':value.update(exit_index=l['exit_index'],exit_ts=l['exit_ts'],exit_price=l['exit_price'],gross_bps=gross,exit_reason=l['reason'])
    else:value.update(mark_index=l['exit_index'],mark_ts=l['exit_ts'],mark_price=l['exit_price'],gross_mark_bps=gross,
        status='CENSORED',pending_exit=c['pending_exit'],terminal_liquidation=False,censor_reason='WINDOW_END')
    return value


def campaign(c,symbol,packet):
    legs=[('C',l) for l in c['legs']]
    if not c['closed']:
        for l in c['lots']:
            if l['qty']>0:legs.append(('O',dict(entry_price=l['price'],entry_ts=l['ts'],entry_index=l['index'],
                exit_price=c['mark_price'],exit_ts=c['mark_ts'],exit_index=c['mark_index'],qty=l['qty'],
                weight=l['qty']*l['price'],reason='TERMINAL_MARK')))
    charged=[]
    for status,leg in legs:
        raw=raw_leg(c,leg,status)
        unit=p.account.charge_result(dict(trades=[raw] if status=='C' else [],open_positions=[raw] if status=='O' else [],events=[],trace=[],audit={}),
            symbol,engine.LANE,engine.RULE_ID,packet['policy'],packet['costs'],packet['rows_by'][symbol])
        row=unit['trades' if status=='C' else 'open_observations'][0]
        charged.append(dict(status=status,row=row,numerator=leg['weight'],denominator=1,qty=leg['qty']))
    if not charged:raise RuntimeError('CAMPAIGN_WITHOUT_FILL')
    status='C' if c['closed'] else 'O'
    final=next(x for x in reversed(charged) if x['status']==status)
    row=deepcopy(final['row']);row.pop('trade_sha256',None);row.pop('observation_sha256',None)
    entry_price=engine.average(c)
    terminal=final['row'].get('exit_ts',final['row'].get('mark_ts'))
    row.update(entry_ts=c['first_fill_ts'],entry_index=c['first_fill_index'],entry_price=entry_price,
        entry_price_semantics='ACTUAL_QUANTITY_WEIGHTED_CAMPAIGN_AVERAGE_NOT_SINGLE_FILL',
        hold_ms=terminal-c['first_fill_ts'],weighted_legs=charged,lifecycle=deepcopy(c),
        reference_invested=c['invested'],initial_risk_distance_bps=(c['fills'][0]['price']-c['initial_stop'])/c['fills'][0]['price']*10000,
        evidence_type='CARTER_INSPIRED_CRYPTO_USED_DEV_NOT_TRADER_TRACK_RECORD',original_trader_replication=False,
        return_semantics='FIXED_REFERENCE_NOTIONAL_SUM_OF_LOT_LEGS',mfe_bps=None,mae_bps=None)
    weighted={k:fsum(bridge._values((l['status'],l['row']))[k]*l['numerator'] for l in charged) for k in bridge.VALUE_FIELDS}
    if status=='C':row.update(weighted)
    else:row.update(gross_mark_bps=weighted['gross_bps'],hypothetical_liquidation_net_mark_bps=weighted['net_bps'],
        hypothetical_liquidation_cost2x_net_mark_bps=weighted['cost2x_net_bps'],hypothetical_liquidation_cost_bps=weighted['cost_bps'],
        hypothetical_cost_components_bps={k:weighted[k] for k in bridge.COST_FIELDS})
    row['trade_sha256' if status=='C' else 'observation_sha256']=p.sha(row)
    return status,row


def metrics(result,packet,calendar):
    original=marks._boundary
    def boundary(item,ts,prices,costs,start,end):
        status,row=item
        if not row.get('weighted_legs'):return original(item,ts,prices,costs,start,end)
        legs=[(x,original((x['status'],x['row']),ts,prices,costs,start,end)) for x in row['weighted_legs']]
        return {k:fsum(v[k]*x['numerator']/x['denominator'] for x,v in legs) for k in bridge.VALUE_FIELDS}
    with patch.object(marks,'_boundary',boundary):
        out=p.old.metrics(result['trades'],result['open_observations'],calendar,packet['rows_by'],packet['costs'])
    positions=result['trades']+result['open_observations']
    out.update(reference_notional_symbol_days=fsum(l['row']['hold_ms']*l['numerator']/l['denominator'] for r in positions for l in r['weighted_legs'])/86400000,
        campaign_count=len(positions),partial_legs_not_separate_wins=True,
        ambiguity_count=sum(len(r['lifecycle']['ambiguity']) for r in positions),
        ambiguity_local_mark_impact_bps=fsum(a['difference_bps'] for r in positions for a in r['lifecycle']['ambiguity']),
        ambiguity_reference_allocations=fsum(a['reference_allocation'] for r in positions for a in r['lifecycle']['ambiguity']))
    return out


def charge(raw_by,packet,calendar):
    result=dict(trades=[],open_observations=[],events=[],trace=[],audit={},pending={})
    for symbol,raw in sorted(raw_by.items()):
        for c in raw['campaigns']:
            status,row=campaign(c,symbol,packet)
            result['trades' if status=='C' else 'open_observations'].append(row)
        result['audit'][symbol]=raw['audit'];result['pending'][symbol]=raw['pending']
        result['events']+= [dict(x,symbol=symbol) for x in raw['events']]
    result['metrics']=metrics(result,packet,calendar)
    result.update(candidate=engine.RULE_ID,variant=engine.RULE_ID,independent=False,formal_credit=0,operating_adoption=False)
    return result


def verify_money(result):
    for status,key in [('C','trades'),('O','open_observations')]:
        for r in result[key]:
            expected={k:fsum(bridge._values((l['status'],l['row']))[k]*l['numerator']/l['denominator'] for l in r['weighted_legs']) for k in bridge.VALUE_FIELDS}
            actual=bridge._values((status,r))
            for k in expected:
                if abs(expected[k]-actual[k])>1e-8:raise RuntimeError('MONEY_PARITY:'+k)
            if abs(expected['gross_bps']-expected['cost_bps']-expected['net_bps'])>1e-8:raise RuntimeError('NET_PARITY')
    return True
