"""Bind a single already-reserved chart FULL to existing costs and metrics.
No CLI/HTTP/files/allocator/dispatcher. Work must first freeze and persist its
runtime claim. This module never replays a parent or changes operating policy.
"""
from backend.research.rebuild import chart_mechanism_execution_v1 as engine

def charge_and_mark(raw_by_symbol,variant,packet,calendar):
    from backend.research.rebuild import kr3_c51_entry_context_study_v1 as shared
    p=shared.p
    lane='keltner_trend_main' if variant in ('T1','F1','F0') else 'source_squeeze_momentum_long' if variant=='M1' else 'source_soup_reclaim_long'
    result={k:[] for k in ('trades','open_observations','events','trace')}
    result.update(audit={},setup_events={},pending_entries={},reference_states={})
    for symbol,raw in sorted(raw_by_symbol.items()):
        charged=p.account.charge_result(raw,symbol,lane,engine.RULES[variant],packet['policy'],packet['costs'],packet['rows_by'][symbol])
        for name,hash_name in [('trades','trade_sha256'),('open_observations','observation_sha256')]:
            for row in charged[name]:
                row.pop(hash_name,None);row.update(evidence_type='SOURCE_CHART_MECHANISM_USED_DEV',chart_variant=variant,original_trader_replication=False)
                row[hash_name]=p.sha(row)
        for name in ('trades','open_observations','events','trace'):result[name].extend(charged[name])
        result['audit'][symbol]=raw['audit'];result['setup_events'][symbol]=raw.get('setup_events',[]);result['pending_entries'][symbol]=raw.get('pending_entries',[])
        if 'reference_checkpoint' in raw:result['reference_states'][symbol]=raw['reference_checkpoint']
    result.update(candidate=engine.RULES[variant],variant=variant,independent=False,formal_credit=0,operating_adoption=False)
    result['metrics']=p.old.metrics(result['trades'],result['open_observations'],calendar,packet['rows_by'],packet['costs'])
    return result

def evaluate_one(variant,period,packet,calendar,saved_c54,*,volume_bindings=None):
    """One FULL: call only AFTER Work's durable remote runtime reservation.
    saved_c54 is the pinned original result, never a replay in this function.
    """
    from backend.research.rebuild import kr3_c51_entry_context_study_v1 as shared
    if variant not in engine.VARIANTS:raise ValueError('UNKNOWN_CHART_VARIANT')
    shared.old.inherited.packet_check(period,packet)
    start,end=calendar['start_ms'],calendar['runoff_end_ms']
    expected=shared.read(shared.ROOT/shared.OUT/'SPEC.json')['periods'][period]
    if calendar!=expected:raise ValueError('ORIGINAL_CALENDAR_BINDING_CHANGED')
    bindings=volume_bindings or {}
    if variant in ('T1','F1','F0'):
        if set(bindings)!=set(packet['rows_by']):raise engine.UnverifiedVolume('ALL_SYMBOL_VOLUME_AUTHORITY_REQUIRED')
        for value in bindings.values():engine.validate_volume(value)
    raw_by={}
    with shared.p.native.sensitivity():
        for symbol,rows in sorted(packet['rows_by'].items()):
            if variant in ('T1','F1','F0'):
                bundle=shared.p.d.build_bundle(rows,shared.p.d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end)
                raw_by[symbol]=engine.replay_trend(rows,bundle,eval_start_ms=start,eval_end_ms=end,cost_model=packet['costs'][symbol],variant=variant,volume_binding=bindings[symbol])
            else:raw_by[symbol]=engine.replay_independent(rows,eval_start_ms=start,eval_end_ms=end,variant=variant)
    result=charge_and_mark(raw_by,variant,packet,calendar)
    if variant in ('T1','F1','F0'):
        if result['reference_states']!=saved_c54['reference_states']:raise RuntimeError('C54_REFERENCE_CHANGED')
        keys=lambda r:{(e['symbol'],e['signal_index'],e['signal_ts']) for e in r['events']}
        if keys(result)!=keys(saved_c54):raise RuntimeError('C54_SIGNAL_POOL_CHANGED')
        comparison=shared.a.compare(saved_c54,result);comparison['comparison_type']='C54_CHART_ENTRY_CONTEXT_FULL'
    else:
        comparison=dict(comparison_type='STANDALONE_NOT_C54_CHILD',common_calendar=True,comparable_equal_nominal=True,equal_risk_or_exposure=False,portfolio_combination_tested=False,
            terminal_net_delta_vs_c54=result['metrics']['terminal_net_bps']-saved_c54['metrics']['terminal_net_bps'])
    return raw_by,result,comparison
