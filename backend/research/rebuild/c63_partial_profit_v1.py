"""One C63 partial-realization hypothesis; never changes admission or final exit.

Source-derived fraction: one ORIGINAL-position third, as mapped in PR1238.
Trigger is an explicit ZEL adaptation, not Carter's exact option/high/Fib rule:
first native held close with 0 < momentum < previous completed momentum AND
original accrued modeled net > 0, provided no native exit has precedence.
Remaining two thirds keep native floor/momentum/20-bar exit, no new stop/BE.
No I/O, numeric sweep, provider, actual order or fractional-lot execution claim.
"""
from copy import deepcopy
from math import isfinite
from unittest.mock import patch

RULE_ID='C63_ONE_THIRD_FIRST_PROFITABLE_MOMENTUM_DECELERATION_V1'
REASON='ONE_THIRD_PROFITABLE_MOMENTUM_DECELERATION_CLOSE'


def qualifies(momentum, previous, net_mark, native_reason):
    for v in (momentum, previous, net_mark):
        if type(v) not in (float,int) or not isfinite(v):
            raise ValueError('INVALID_PARTIAL_OBSERVATION')
    return native_reason is None and 0 < momentum < previous and net_mark > 0


def select_partial(bars, signal, features, path_trace, end, decision_cost):
    """Each row uses only contemporaneous information. End excludes next open."""
    ei=signal['signal_index']+1;entry=bars[ei]
    evidence=[];selected=None;fill=None
    for row in path_trace:
        if row['kind']!='HELD_CLOSE_OBSERVATION':continue
        j=row['index'];stamp=row['ts']
        if j<ei or stamp!=bars[j].open_ts+(bars[ei].open_ts-bars[ei-1].open_ts):
            raise ValueError('PARTIAL_DECISION_CLOCK')
        current=features[j]['momentum'];previous=features[j-1]['momentum']
        cost=decision_cost(entry.open_ts,stamp)
        net=(row['close']/entry.open-1.)*10000-cost
        met=qualifies(current,previous,net,row['exit_reason'])
        evidence.append(dict(index=j,available_at=stamp,close=row['close'],momentum=current,
            previous_momentum=previous,decision_cost_bps=cost,net_mark_bps=net,
            native_reason=row['exit_reason'],eligible=met))
        if not met:continue
        selected=dict(reason=REASON,index=j,signal_index=j,signal_ts=stamp,observed_close=row['close'],decision_ts=stamp,fraction=[1,3],observation=evidence[-1])
        if j+1<len(bars) and bars[j+1].open_ts<end:
            nxt=bars[j+1]
            fill=dict(index=j+1,ts=nxt.open_ts,price=nxt.open,trigger=selected,
                      fill_semantics='NEXT_OBSERVED_OPEN_MODEL_NOT_EXCHANGE_ACK')
        break
    return dict(decisions=evidence,trigger=selected,fill=fill,
        pending_at_end=selected is not None and fill is None,
        lot_semantics='EXACT_REFERENCE_FRACTION_NOT_EXCHANGE_LOT_AUTHORITY')


def position(bars,signal,variant,features,end,cost_model,original_path):
    if variant!='M1':raise ValueError('C63_PARTIAL_VARIANT')
    from backend.research.rebuild.kr3_profit_zone_exit_v1 import decision_cost
    trade,opened,trace=original_path(bars,signal,variant,features,end)
    split=select_partial(bars,signal,features,trace,end,
                         lambda a,b:decision_cost(a,b,cost_model)['cost_bps'])
    value=trade if trade is not None else opened
    if split['fill'] is not None:
        final=value.get('exit_ts',value.get('mark_ts'))
        if split['fill']['ts']>=final:raise RuntimeError('NATIVE_EXIT_PRIORITY_OR_WINDOW')
    value['partial_realization']=split
    return trade,opened,trace+[dict(kind='PARTIAL_REALIZATION_AUDIT',signal_index=signal['signal_index'],**split)]


def replay(rows,*,eval_start_ms,eval_end_ms,cost_model,enabled=True):
    from backend.research.rebuild import m1_er_range_rescue_v1 as parent
    if type(enabled) is not bool:raise ValueError('ENABLED_BOOL')
    if not enabled:return parent.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    engine=parent.er.parent;original=engine._position
    def path(b,s,v,f,e):return position(b,s,v,f,e,deepcopy(cost_model),original)
    with patch.object(engine,'_position',path):
        result=parent.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    result['audit'].update(rule=RULE_ID,direct_parent=parent.RULE_ID,change_axis='ONE_PARTIAL_ONLY',
        original_entry_unchanged=True,original_final_exit_unchanged=True,partial_slot_release=False,
        original_M1_exits_unchanged=False,exit_model='ONE_THIRD_THEN_NATIVE_TWO_THIRDS',
        partial_filled_T=sum(x['partial_realization']['fill'] is not None for k in ('trades','open_positions') for x in result[k]))
    return result


def aggregate_values(final_values,partial_values):
    """Fixed original-notional basis: entry fee allocated once, not twice."""
    if set(final_values)!=set(partial_values):raise ValueError('VALUE_FIELDS')
    return {k:partial_values[k]/3+final_values[k]*2/3 for k in final_values}


def charge_and_mark(raw_by,packet,calendar):
    """Reuse native unit cost/metrics owners, aggregate legs BEFORE win counting.

Daily native boundary function is locally wrapped to value each known leg at
its actual timestamp. No weighted exit price is passed off as an actual fill.
The wrapper is restored even on failure. Reference amount accounting only.
"""
    from backend.research.rebuild import m1_er_range_rescue_study_v1 as old
    from backend.research.rebuild import parallel_exit_metrics_v1 as marks
    p=old.p;bridge=old.a.owner
    result={k:[] for k in ('trades','open_observations','events','trace')}
    result.update(audit={},setup_events={},pending_entries={},reference_states={})
    for symbol,raw in sorted(raw_by.items()):
        charged=p.account.charge_result(raw,symbol,'source_squeeze_momentum_long',RULE_ID,
                                       packet['policy'],packet['costs'],packet['rows_by'][symbol])
        by_signal={x['signal_index']:x for k in ('trades','open_positions') for x in raw[k]}
        for status,key,seal in [('C','trades','trade_sha256'),('O','open_observations','observation_sha256')]:
            for value in charged[key]:
                native=by_signal[value['signal_index']];part=native['partial_realization'];fill=part['fill']
                value.pop(seal,None)
                value.update(evidence_type='C63_PARTIAL_REFERENCE_NOTIONAL_USED_DEV',
                    original_trader_replication=False,partial_realization=deepcopy(part),
                    return_semantics='ORIGINAL_NOTIONAL_WEIGHTED_LEGS',
                    exit_price_semantics='ACTUAL_LAST_RESIDUAL_OPEN_NOT_WEIGHTED_FAKE_FILL')
                if fill is not None:
                    one=deepcopy(native);one.pop('partial_realization',None)
                    for k in list(one):
                        if k.startswith('mark_') or k.startswith('gross_mark') or k.startswith('pending_exit') or k in ('status','terminal_liquidation','censor_reason'):
                            one.pop(k,None)
                    one.update(exit_index=fill['index'],exit_ts=fill['ts'],exit_price=fill['price'],
                        gross_bps=(fill['price']/one['entry_price']-1.)*10000,
                        hold_ms=fill['ts']-one['entry_ts'],exit_reason=REASON+'_NEXT_OPEN',
                        exit_trigger=deepcopy(fill['trigger']),exit_timestamp_semantics='OBSERVED_4H_OPEN')
                    partial=p.account.charge_result(dict(trades=[one],open_positions=[],events=[],trace=[],audit={}),
                        symbol,'source_squeeze_momentum_long',RULE_ID,packet['policy'],packet['costs'],packet['rows_by'][symbol])['trades'][0]
                    # No post-partial excursion is claimed as partial-leg MFE/MAE.
                    for name in ('mfe_bps','mae_bps'):partial.pop(name,None)
                    final=deepcopy(value);final.pop('partial_realization',None)
                    pv=bridge._values(('C',partial));fv=bridge._values((status,final));weighted=aggregate_values(fv,pv)
                    value['weighted_legs']=[dict(numerator=1,denominator=3,status='C',row=partial),
                                            dict(numerator=2,denominator=3,status=status,row=final)]
                    if status=='C':value.update(weighted)
                    else:
                        value.update(gross_mark_bps=weighted['gross_bps'],
                            hypothetical_liquidation_net_mark_bps=weighted['net_bps'],
                            hypothetical_liquidation_cost2x_net_mark_bps=weighted['cost2x_net_bps'],
                            hypothetical_liquidation_cost_bps=weighted['cost_bps'],
                            hypothetical_cost_components_bps={k:weighted[k] for k in bridge.COST_FIELDS},
                            realized_partial_net_bps=pv['net_bps']/3,
                            realized_partial_cost2x_net_bps=pv['cost2x_net_bps']/3,
                            remaining_hypothetical_net_mark_bps=fv['net_bps']*2/3)
                value[seal]=p.sha(value)
        for k in ('trades','open_observations','events','trace'):result[k].extend(charged[k])
        result['audit'][symbol]=raw['audit'];result['setup_events'][symbol]=raw.get('setup_events',[])
        result['pending_entries'][symbol]=raw.get('pending_entries',[])
    original_boundary=marks._boundary
    def boundary(item,ts,prices,costs,start,end):
        status,row=item;legs=row.get('weighted_legs')
        if not legs:return original_boundary(item,ts,prices,costs,start,end)
        values=[(x,original_boundary((x['status'],x['row']),ts,prices,costs,start,end)) for x in legs]
        return {k:sum(v[k]*x['numerator']/x['denominator'] for x,v in values) for k in bridge.VALUE_FIELDS}
    with patch.object(marks,'_boundary',boundary):
        result['metrics']=p.old.metrics(result['trades'],result['open_observations'],calendar,packet['rows_by'],packet['costs'])
    positions=result['trades']+result['open_observations']
    weighted_ms=0
    for x in positions:
        if 'weighted_legs' in x:
            weighted_ms+=sum(t['row']['hold_ms']*t['numerator']/t['denominator'] for t in x['weighted_legs'])
        else:weighted_ms+=x['hold_ms']
    result['metrics'].update(reference_notional_symbol_days=weighted_ms/86400000,
        partial_completed_T=sum(x['partial_realization']['fill'] is not None for x in positions),
        realized_partial_net_in_unfinished_bps=sum(x.get('realized_partial_net_bps',0) for x in result['open_observations']),
        remaining_only_open_mark_bps=sum(x.get('remaining_hypothetical_net_mark_bps',x['hypothetical_liquidation_net_mark_bps']) for x in result['open_observations']),
        open_mark_semantics='INCLUDES_REALIZED_PARTIAL_PLUS_RESIDUAL_HYPOTHETICAL_COST_MARK',
        full_equals_fixed_when_same_final_occupancy=True)
    result.update(candidate=RULE_ID,variant='C65',independent=False,formal_credit=0,operating_adoption=False)
    return result
