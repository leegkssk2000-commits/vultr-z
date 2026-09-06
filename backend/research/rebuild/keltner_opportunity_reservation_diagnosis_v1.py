#!/usr/bin/env python3
"""Read-only PR1197 ledger diagnosis. Never reads prices or executes any strategy.

Historical origin IDs, timestamps and exit indices below are OFFLINE truth only.
They must not be imported into M's admission/reference-clock implementation.
"""
import collections
import datetime
import math

COST_FIELDS = ('gross_bps', 'cost_bps', 'fee_bps', 'spread_bps', 'impact_bps',
               'slippage_bps', 'funding_bps', 'frozen_floor_reserve_bps',
               'net_bps', 'cost2x_net_bps')

def stamp(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat()

def key(t):
    return t['origin_key']

def event_key(t):
    return t['symbol'], t['signal_index']

def totals(trades):
    return {'T': len(trades), **{k: math.fsum(t[k] for t in trades) for k in COST_FIELDS}}

def trade(t):
    fields = ('origin_key', 'symbol', 'signal_index', 'signal_ts', 'entry_index',
              'entry_ts', 'exit_index', 'exit_ts', 'entry_price', 'exit_price',
              'gross_bps', 'cost_bps', 'net_bps', 'cost2x_net_bps')
    out = {k: t[k] for k in fields}
    out['signal_utc'] = stamp(t['signal_ts'])
    out['entry_utc'] = stamp(t['entry_ts'])
    out['exit_utc'] = stamp(t['exit_ts'])
    out['diagnostic_ownership'] = 'signal_index < later_signal_index <= exit_index'
    out['execution_input_allowed'] = False
    return out

def identity_map(view, field='trades'):
    result = {key(t): t for t in view[field]}
    assert len(result) == len(view[field])
    return result

def blocker(pool, later):
    candidates = [t for t in pool.values() if t['symbol'] == later['symbol']
                  and t['signal_index'] < later['signal_index'] <= t['exit_index']]
    assert len(candidates) == 1, (event_key(later), [event_key(t) for t in candidates])
    return candidates[0]

def close(a, b):
    assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8), (a, b)

def analyze_period(payload):
    views = payload['views']; record = payload['record']
    d, n, c, p = (identity_map(views[k]) for k in ('D', 'N', 'N_COMMON_D', 'P'))
    de = {event_key(e): e for e in views['D']['events']}
    ne = {event_key(e): e for e in views['N']['events']}
    direct = {k: t for k, t in d.items() if ne[event_key(t)]['exclusion_reason'] == 'SIGNAL_CLOSE_BELOW_DIRECTIONAL_HALF'}
    displaced = {k: d[k] for k in c.keys() - n.keys()}
    new = {k: n[k] for k in n.keys() - d.keys()}
    assert d.keys() - n.keys() == direct.keys() | displaced.keys()
    assert not direct.keys() & displaced.keys()
    edges = []
    for k, t in new.items():
        b = blocker(d, t)
        assert de[event_key(t)]['exclusion_reason'] == 'SIGNAL_DURING_OPEN'
        assert key(b) in direct or key(b) in displaced
        assert ne[event_key(t)]['status'] == 'COMPLETED'
        edges.append({'from': key(b), 'to': k,
                      'kind': 'D_REFERENCE_INTERVAL_CONTAINS_N_ONLY_ORIGINAL_SIGNAL',
                      'from_class': 'DIRECT_HALF_VETO' if key(b) in direct else 'DISPLACED_D_ENTRY',
                      'observed_D_block_reason': de[event_key(t)]['exclusion_reason']})
    for k, t in displaced.items():
        b = blocker(n, t)
        assert key(b) in new
        assert ne[event_key(t)]['entry_observation']['close_on_directional_half']
        assert ne[event_key(t)]['exclusion_reason'] == 'SIGNAL_DURING_OPEN'
        edges.append({'from': key(b), 'to': k, 'kind': 'N_ONLY_INTERVAL_DISPLACES_UPPER_HALF_D_SIGNAL',
                      'from_class': 'N_ONLY_TRADE', 'observed_N_block_reason': ne[event_key(t)]['exclusion_reason']})
    adjacency = collections.defaultdict(list)
    for e in edges: adjacency[e['from']].append(e['to'])
    def descendants(origin):
        seen, pending = set(), list(adjacency[origin])
        while pending:
            child = pending.pop()
            assert child != origin
            if child not in seen:
                seen.add(child); pending.extend(adjacency[child])
        return sorted(seen)
    assert set().union(*(set(descendants(k)) for k in direct)) == set(new) | set(displaced)
    ordered = lambda values: sorted(values, key=lambda t: (t['symbol'], t['signal_index']))
    roots = []
    for t in ordered(direct.values()):
        x = trade(t)
        x['original_N_observation'] = ne[event_key(t)]['entry_observation']
        x['downstream_origins'] = descendants(key(t))
        roots.append(x)
    common_keys = d.keys() & n.keys()
    for k in common_keys:
        for field in ('entry_ts','exit_ts','entry_price','exit_price','gross_bps','net_bps','cost_bps','cost2x_net_bps'):
            close(d[k][field], n[k][field])
    common_open = identity_map(views['D'], 'open_observations')
    nopen = identity_map(views['N'], 'open_observations')
    assert set(common_open) == set(nopen)
    for k in common_open:
        for field in ('entry_ts','mark_ts','gross_mark_bps','hypothetical_liquidation_net_mark_bps','hypothetical_liquidation_cost2x_net_mark_bps'):
            close(common_open[k][field], nopen[k][field])
    bridge = {'D_closed_net_bps': totals(list(d.values()))['net_bps'],
              'direct_D_veto_net_bps': totals(list(direct.values()))['net_bps'],
              'additional_displaced_D_net_bps': totals(list(displaced.values()))['net_bps'],
              'new_N_not_D_net_bps': totals(list(new.values()))['net_bps'],
              'N_closed_net_bps': totals(list(n.values()))['net_bps'],
              'stored_COMMON_D_closed_net_bps': totals(list(c.values()))['net_bps']}
    bridge['N_minus_D_bps'] = bridge['N_closed_net_bps'] - bridge['D_closed_net_bps']
    bridge['COMMON_D_minus_N_bps_known_diagnostic_only'] = bridge['stored_COMMON_D_closed_net_bps'] - bridge['N_closed_net_bps']
    close(bridge['N_minus_D_bps'], -bridge['direct_D_veto_net_bps'] - bridge['additional_displaced_D_net_bps'] + bridge['new_N_not_D_net_bps'])
    close(bridge['COMMON_D_minus_N_bps_known_diagnostic_only'], bridge['additional_displaced_D_net_bps'] - bridge['new_N_not_D_net_bps'])
    comparison_windows = record.get('comparisons', {}).get('D_to_N', {}).get('same_calendar_windows', [])
    result = {'counts': {'D_closed':len(d), 'D_open':len(common_open), 'N_closed':len(n),
                        'N_open':len(nopen), 'N_common_D_closed':len(common_keys),
                        'direct_D_half_veto':len(direct), 'additional_displaced_D':len(displaced),
                        'N_new_not_D':len(new), 'direct_root_linked_new':sum(e['from_class']=='DIRECT_HALF_VETO' for e in edges),
                        'displaced_linked_new':sum(e['from_class']=='DISPLACED_D_ENTRY' for e in edges)},
              'D_direct_half_veto_roots':roots,
              'N_new_not_D':list(map(trade,ordered(new.values()))),
              'D_additional_displaced':list(map(trade,ordered(displaced.values()))),
              'offline_dependency_edges': sorted(edges,key=lambda e:(e['from'],e['to'])),
              'bridge':bridge,
              'same_calendar_windows_from_stored_receipt':comparison_windows,
              'daily_rows_seen': {k:len(record.get('stages', {}).get(k, {}).get('daily', [])) for k in ('P','D','N')},
              'daily_terminal_parity':{},
              'M_economic_result': 'NOT_MEASURED_BY_THIS_SCRIPT'}
    for label in ('P','D','N'):
        view=views[label];daily=record.get('stages', {}).get(label, {}).get('daily', []); expected=math.fsum(t['net_bps'] for t in view['trades'])+math.fsum(t['hypothetical_liquidation_net_mark_bps'] for t in view['open_observations'])
        if daily: close(daily[-1]['cumulative_net_mark_bps'],expected)
        result['daily_terminal_parity'][label]=expected
    return result

def residue(payload, strategy_label='N'):
    v=payload['views'];p=identity_map(v['P']);n=identity_map(v['N']);d=identity_map(v['D'])
    groups=collections.defaultdict(list)
    for k,t in n.items():
        parent=p.get(k)
        changed=parent is not None and any(t[f] != parent[f] for f in ('exit_index','exit_ts','exit_price'))
        if parent is None:label='new_to_P'
        elif changed:label='changed_exit_helpful' if t['net_bps']>=parent['net_bps'] else 'changed_exit_harmful'
        elif t['net_bps']<0:label='unchanged_exit_loss'
        else:label='unchanged_exit_nonloss'
        groups[label].append(t)
    closed_groups={label: {'totals':totals(ts),'origins':[key(t) for t in ts]} for label,ts in sorted(groups.items())}
    for label in ('changed_exit_helpful','changed_exit_harmful'):
        ts=groups[label]; q=closed_groups[label];q['original_P_same_origin_totals']=totals([p[key(t)] for t in ts]);q['N_minus_P_same_origin_bps']={f:q['totals'][f]-q['original_P_same_origin_totals'][f] for f in COST_FIELDS}
    no_exit_losses=groups['unchanged_exit_loss'];cost_only=[t for t in no_exit_losses if t['gross_bps']>=0]
    closed_total=totals(list(n.values()));assert sum(g['totals']['T'] for g in closed_groups.values())==len(n)
    for f in COST_FIELDS:close(math.fsum(g['totals'][f] for g in closed_groups.values()),closed_total[f])
    opens=[]
    for t in v['N']['open_observations']:
        x={f:t[f] for f in ('origin_key','symbol','signal_index','entry_index','entry_ts','mark_index','mark_ts','gross_mark_bps','hypothetical_liquidation_cost_bps','hypothetical_liquidation_net_mark_bps','hypothetical_liquidation_cost2x_net_mark_bps','modeled_funding_accrued_bps','hypothetical_cost_components_bps','status','actual_exit','terminal_liquidation')}; opens.append(x)
    open_totals={'T':len(opens),'gross_mark_bps':math.fsum(x['gross_mark_bps'] for x in opens),'hypothetical_cost_bps':math.fsum(x['hypothetical_liquidation_cost_bps'] for x in opens),'net_mark_bps':math.fsum(x['hypothetical_liquidation_net_mark_bps'] for x in opens),'cost2x_net_mark_bps':math.fsum(x['hypothetical_liquidation_cost2x_net_mark_bps'] for x in opens),'funding_accrued_bps':math.fsum(x['modeled_funding_accrued_bps'] for x in opens)}
    # Additive decomposition uses gross groups, subtracts costs exactly once, then adds separate open marks.
    additive=[{'category':label,'trade_T':g['totals']['T'],'gross_bps':g['totals']['gross_bps']} for label,g in closed_groups.items()]
    additive.extend([{'category':'ALL_CLOSED_MODEL_COST_ONCE','contribution_bps':-closed_total['cost_bps']},{'category':'OPEN_MARKS_GROSS','contribution_bps':open_totals['gross_mark_bps']},{'category':'OPEN_HYPOTHETICAL_COST_ONCE','contribution_bps':-open_totals['hypothetical_cost_bps']}])
    terminal=closed_total['net_bps']+open_totals['net_mark_bps']
    close(math.fsum(x.get('gross_bps',x.get('contribution_bps',0)) for x in additive),terminal)
    for t in groups['new_to_P']:
        assert key(t) in d
        for f in ('signal_ts','entry_ts','exit_ts','entry_price','exit_price','net_bps'):close(t[f],d[key(t)][f])
    return {'basis':'EXHAUSTIVE_MUTUALLY_EXCLUSIVE_CLOSED_COHORTS; GROSS_MINUS_COST_ONCE; OPEN_MARKS_SEPARATE', 'strategy_label':strategy_label,
            'closed_groups':closed_groups,'closed_total':closed_total,'open_marks':opens,'open_totals':open_totals,
            'terminal_net_bps_hypothetical':terminal,'terminal_cost2x_bps_hypothetical':closed_total['cost2x_net_bps']+open_totals['cost2x_net_mark_bps'],
            'no_doublecount_additive_gross_bridge':additive,
            'unchanged_loss_secondary_partition':{'gross_adverse_T':len(no_exit_losses)-len(cost_only),'gross_adverse_totals':totals([t for t in no_exit_losses if t['gross_bps']<0]),'cost_only_T':len(cost_only),'cost_only':list(map(trade,cost_only))},
            'new_to_P_but_shared_D':list(map(trade,groups['new_to_P'])),
            'one_next_cause_diagnosis':{'focus':'ADVERSE_PRICE_PATHS_WITHOUT_EXIT_CHANGE', 'unchanged_exit_loss_T':len(no_exit_losses), 'negative_gross_T':len(no_exit_losses)-len(cost_only), 'gross_loss_cohort_is_post_outcome_label':True, 'execution_time_separating_evidence':'NOT_TESTED; no new predictor or next candidate authorized', 'reservation_changes_common_exit_path':False},
            'hypothesis_or_execution_feature_created':False}


def _view_economic_parity(a, b):
    """Comparison only; historical lists never become a candidate allowlist."""
    for field in ('trades', 'open_observations'):
        aa, bb = identity_map(a, field), identity_map(b, field)
        assert set(aa) == set(bb), ('historical_view_origin_mismatch', field)
        features = ('entry_index','entry_ts','exit_index','exit_ts','entry_price','exit_price','gross_bps','cost_bps','funding_bps','net_bps','cost2x_net_bps') if field == 'trades' else ('entry_index','entry_ts','mark_index','mark_ts','gross_mark_bps','hypothetical_liquidation_cost_bps','hypothetical_liquidation_net_mark_bps','hypothetical_liquidation_cost2x_net_mark_bps')
        for origin in aa:
            for feature in features: close(aa[origin][feature],bb[origin][feature])
    return True


def diagnose(stored1197_by_period, stored1196_by_period):
    """Read-only stored-ledger provenance, causal opportunity DAG and residue.

    Calls no strategy, feature, market-input or file reader. Reference intervals
    are retrospective evidence only and are prohibited runtime clock inputs.
    """
    assert set(stored1197_by_period) == set(stored1196_by_period)
    periods={}
    for period,doc in sorted(stored1197_by_period.items()):
        old=stored1196_by_period[period]
        _view_economic_parity(doc['views']['P'],old['views']['P'])
        _view_economic_parity(doc['views']['D'],old['views']['FULL'])
        result=analyze_period(doc)
        original_p=old['views']['P']['trades']; fixed=old['views']['FIXED']['trades']
        assert {key(t) for t in original_p}=={key(t) for t in fixed}
        result['PR1196_fixed_D_minus_P_net_bps']=totals(fixed)['net_bps']-totals(original_p)['net_bps']
        result['PR1196_fixed_D_closed_totals']=totals(fixed)
        result['historical_P_D_parity']=True
        periods[period]=result
    return {'schema':'keltner.reservation.offline.diagnosis.v1',
            'raw_prices_read':False,'strategy_replay_performed':False,'new_candidate_evaluations':0,
            'independent':False,'reference_clock_runtime_data':'NOT_PROVIDED_BY_THIS_OFFLINE_DIAGNOSIS',
            'execution_input_prohibition':'Do not import origin IDs, historical exit indices/times, cohort labels, final PnL or this DAG into M. Compute the clock causally from original signals and then-observable completed EMA values; stored paths are regression truth only.',
            'periods':periods,'SEEN2026_residue':residue(stored1197_by_period['SEEN2026']) if 'SEEN2026' in stored1197_by_period else None}


def after_M_audit(prior1197document, Mview, period):
    """Audit already-produced M ledger; never returns gate or allowlist inputs."""
    views=prior1197document['views']
    d,n,c,p=(identity_map(views[label]) for label in ('D','N','N_COMMON_D','P'))
    m=identity_map(Mview)
    old_new=n.keys()-d.keys(); displaced=c.keys()-n.keys()
    economic=('entry_index','entry_ts','exit_index','exit_ts','entry_price','exit_price',*COST_FIELDS)
    def unchanged(a,b):
        return all(math.isclose(a[f],b[f],rel_tol=1e-12,abs_tol=1e-8) for f in economic)
    blocked_details=[]
    for origin in sorted(old_new):
        old=n[origin]; actual=m.get(origin)
        blocked_details.append({'origin_key':origin,'symbol':old['symbol'],'signal_index':old['signal_index'],
                                'N_net_bps':old['net_bps'],'M_status':'BLOCKED_NO_TRADE' if actual is None else 'RETAINED',
                                'M_net_bps':None if actual is None else actual['net_bps'],
                                'removal_effect_bps':-old['net_bps'] if actual is None else 0.0})
    restored_details=[]
    for origin in sorted(displaced):
        old=d[origin]; actual=m.get(origin)
        restored_details.append({'origin_key':origin,'symbol':old['symbol'],'signal_index':old['signal_index'],
                                 'D_net_bps':old['net_bps'],'M_status':'NOT_RESTORED' if actual is None else 'RESTORED',
                                 'M_net_bps':None if actual is None else actual['net_bps'],
                                 'same_D_economics':False if actual is None else unchanged(old,actual)})
    common=n.keys() & m.keys(); removed=n.keys()-m.keys(); new=m.keys()-n.keys()
    bridge={'common_effect_bps':math.fsum(m[k]['net_bps']-n[k]['net_bps'] for k in common),
            'removed_effect_bps':-math.fsum(n[k]['net_bps'] for k in removed),
            'new_effect_bps':math.fsum(m[k]['net_bps'] for k in new),
            'N_closed_net_bps':totals(list(n.values()))['net_bps'],
            'M_closed_net_bps':totals(list(m.values()))['net_bps']}
    bridge['M_minus_N_bps']=bridge['M_closed_net_bps']-bridge['N_closed_net_bps']
    close(bridge['M_minus_N_bps'],bridge['common_effect_bps']+bridge['removed_effect_bps']+bridge['new_effect_bps'])
    mismatch={'M_missing_COMMON_D':sorted(c.keys()-m.keys()),'M_extra_to_COMMON_D':sorted(m.keys()-c.keys()),
              'common_changed_economics':[k for k in sorted(c.keys() & m.keys()) if not unchanged(c[k],m[k])]}
    co=identity_map(views['N_COMMON_D'],'open_observations');mo=identity_map(Mview,'open_observations')
    mismatch['M_open_missing_COMMON_D']=sorted(co.keys()-mo.keys());mismatch['M_open_extra_to_COMMON_D']=sorted(mo.keys()-co.keys())
    open_fields=('entry_index','entry_ts','mark_index','mark_ts','gross_mark_bps','hypothetical_liquidation_cost_bps','hypothetical_liquidation_net_mark_bps','hypothetical_liquidation_cost2x_net_mark_bps')
    mismatch['common_open_changed_economics']=[k for k in sorted(co.keys() & mo.keys()) if any(not math.isclose(co[k][f],mo[k][f],rel_tol=1e-12,abs_tol=1e-8) for f in open_fields)]
    sol=[]
    for origin in sorted(n.keys()-p.keys()):
        old=n[origin];actual=m.get(origin)
        sol.append({'origin_key':origin,'symbol':old['symbol'],'signal_index':old['signal_index'],
                    'N_net_bps':old['net_bps'],'also_in_D':origin in d,'preserved_in_M':actual is not None,
                    'M_net_bps':None if actual is None else actual['net_bps'],
                    'same_D_N_economics':actual is not None and origin in d and unchanged(actual,d[origin]) and unchanged(actual,old),
                    'added_as_constant_bonus':False})
    Mdoc={'views':{**views,'N':Mview},'record':prior1197document['record']}
    return {'schema':'keltner.reservation.after.M.offline.audit.v1','period':period,
            'not_execution_input':True,'new_strategy_execution_performed_here':False,
            'known_COMMON_D_is_prior_seen_diagnostic':True,
            'new_N_trades_audit':blocked_details,'displaced_D_trades_audit':restored_details,
            'N_new_blocked_T':sum(t['M_status']=='BLOCKED_NO_TRADE' for t in blocked_details),
            'N_new_retained_T':sum(t['M_status']=='RETAINED' for t in blocked_details),
            'displaced_D_restored_T':sum(t['M_status']=='RESTORED' for t in restored_details),
            'M_minus_N_closed_bridge':bridge,'COMMON_D_regression_mismatches':mismatch,
            'COMMON_D_regression_equal':not any(mismatch.values()),
            'new_to_P_origin_preservation':sol,
            'SEEN2026_residue':residue(Mdoc,'M') if period=='SEEN2026' else None,
            'mismatch_policy':'Report timing/ownership/boundary differences; never delete trades or adjust rules to match stored COMMON_D.'}
