"""One allocated DEV entry-notional study over the immutable Q0 ledger.

This is an accounting adapter, not an account-sizing or order implementation.
The causal weight path never receives outcomes, risk windows or control k.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

from backend.research.rebuild import break_channel_q2_diagnosis_v1 as previous
from backend.research.rebuild import q0_risk_entry_weights_v1 as weights
from backend.research.rebuild import q0_risk_entry_metrics_v1 as accounting

prior = previous.prior
old = previous.old
ROOT = old.ROOT
OUTPUT = 'research/development_evidence/Q0_RISK_ENTRY_V1'
CONTRACT = OUTPUT + '/SPEC.json'
DESIGN = OUTPUT + '/DESIGN_AND_SOURCES.md'
Q2_SHA = '5e9d22df713ecce3afff95ff33d185ad0a32ecce466b05e0f7ec7e17c264e7a2'
Q2_SEAL = '2d3ab121867b7ecdb7c66427f2affbad4396a34c29cc9caceb6024411dcad7ae'
CODE = ['backend/research/rebuild/' + p for p in (
    'q0_risk_entry_v1.py', 'q0_risk_entry_weights_v1.py', 'q0_risk_entry_metrics_v1.py',
    'test_q0_risk_entry_v1.py', 'test_q0_risk_entry_weights_v1.py', 'test_q0_risk_entry_metrics_v1.py')]
BUDGET = {'previous_applications': 25, 'allocated_new_trials': 1,
    'candidate': 'Q0_RISK_ENTRY_V1', 'candidate_slots': 1,
    'allocation_source': 'EXPLICIT_USER_REALLOCATION_OF_PR1192_UNUSED_CONDITIONAL_SLOT',
    'Q2_prior_status': 'NOT_RUN_NO_SUPPORTED_INTERVENTION',
    'fixed_control_new_strategy_trials': 0, 'reproduction_new_trials': 0,
    'cumulative_after_measurement': 26, 'automatic_extension': False,
    'paid_external_AI_calls': 0}
RULE = {
    'kind': 'DEV_ENTRY_NOTIONAL_ALLOCATION_ONLY',
    'fixed': 'All Q0 signals, admissions, fills, entry/exit timestamps, initial SL, ownership, costs and calendar are immutable; no skipped/new trades or rebalancing.',
    'daily': 'Existing aggregate_daily: six contiguous completed UTC 4h bars. Same fixed seven-symbol basket; missing/partial internal days or symbols fail, no interpolation.',
    'basket': 'Arithmetic mean of seven simple close-to-close daily returns, fixed equal weights; return available_at is ending daily bar_close_ts.',
    'reference': 'Sample standard deviation ddof=1 of every valid basket return whose available_at is strictly before Q0 evaluation start. Entire approved warmup, no return selection.',
    'current': 'Sample standard deviation ddof=1 of exactly latest30 contiguous basket daily returns with available_at<=original Q0 signal_ts. Decision after completed close before next-open fill at same timestamp.',
    'weight': 'm=min(1,sigma_ref/sigma_t), strictly positive, fixed at entry through exit/terminal. Zero/nonfinite sigma or insufficient history fails, no epsilon.',
    'control': 'C fixed k=sum(B m*holding_ms)/sum(A holding_ms), including open time. EX_POST_ANALYTIC_NORMALIZATION_ONLY; no k input to B/ref, no strategy or trial.',
    'cost': 'Preserve unit bps fee/spread/impact/slippage/funding and max20bps floor; multiply amount only under frozen price-taker research model. No fee splitting, nonlinear/minimum-order claim or signed funding lineage.',
    'valuation': 'Reuse original per-position daily valuation, full hypothetical roundtrip costs on open marks; multiply each fixed entry amount. No forced close. Original conservative4h stop timing retained.',
    'units': 'Unit trade-bps separate from weighted base-notional amount-bps. Neither account return nor bound account MDD; unweighted signal win rate and expectancy unchanged.',
    'windows': 'Original PR1192 all losing/winning daily envelopes and its distinct marked-DD interval frozen before outcomes. May overlap; do not sum as disjoint. Full monthly/symbol contributions retained.',
    'uncertainty': 'Existing paired noncircular30day moving-block bootstrap1000 seed1178 of daily marked deltas B-C, fixed ex-post k. Descriptive repeatedDEV, dependence may exceed blocks; no independentOOS.',
}
GOAL = {
    'primary': 'B versus identical average exposure C, not merely smaller than unscaled Q0.',
    'positive_terminal_net': True, 'positive_cost2_terminal_net': True,
    'B_terminal_net_at_least_C': True, 'B_marked_DD_at_most_C': True,
    'B_max_grouped_loss_amount_at_most_C': True, 'one_strict_improvement_required': True,
    'numerical_equality_abs_tolerance_bps': 1e-7,
    'decision': 'All economic conditions met: DEV_PROMISING_NO_CREDIT only if B-C daily increment95% lower>0, otherwise DEV_INCONCLUSIVE. Mixed relative advantages: DEV_INCONCLUSIVE_TRADEOFF. Nonpositive terminal/cost2 or no relative advantage: DEV_REJECT. No automatic operating/research-parent replacement.',
    'official_SSOT_changed': False,
}


def read(path):
    return json.loads((ROOT / path).read_text())


def authorize():
    q0, q1, parent_spec, protected = previous.authorize()
    q2 = read(previous.OUTPUT + '/analysis.json')
    old.probe.verify_seal(q2, 'Q2_DIAGNOSIS')
    if old.file_sha(ROOT / previous.OUTPUT / 'analysis.json') != Q2_SHA or q2['receipt_sha256'] != Q2_SEAL:
        raise RuntimeError('RISK_Q2_ORIGINAL_IDENTITY')
    if q2['budget']['cumulative_after'] != 25 or q2['budget']['conditional_allocation_unconsumed'] != 1 or q2['decision']['economic_decision'] != 'NOT_RUN':
        raise RuntimeError('RISK_UNUSED_ALLOCATION_OR_PRIOR_STATUS')
    c = read(CONTRACT); old.probe.verify_seal(c, 'RISK_SPEC')
    if c['authorization'] != 'EXPLICIT_USER_Q0_ENTRY_RISK_ONE_AFTER_PR1192' or c['budget'] != BUDGET or c['rule'] != RULE or c['goal'] != GOAL or c['outcomes_seen_at_freeze'] is not False:
        raise RuntimeError('RISK_FROZEN_RULE_OR_BUDGET')
    for k, v in old.probe.DEV_AUTH.items():
        if c.get(k) != v: raise RuntimeError('RISK_AUTHORITY:' + k)
    for k in ('validation_access','OOS_access','G5B_changed','G6_authorized','G7_formal_authorized','G11_formal_authorized','actual_account_sizing','operating_changed'):
        if c.get(k) is not False: raise RuntimeError('RISK_PROTECTED_BOUNDARY:' + k)
    for k in ('symbols','evaluation_interval_ms','data_sha256','cost_sha256'):
        if c[k] != parent_spec[k]: raise RuntimeError('RISK_PARENT_SCOPE:' + k)
    if c['Q0_receipt_sha256'] != q0['receipt_sha256'] or c['Q1_receipt_sha256'] != q1['receipt_sha256'] or c['Q2_analysis_sha256'] != Q2_SEAL:
        raise RuntimeError('RISK_PARENT_SEAL')
    if set(c['code_files_sha256']) != set(CODE): raise RuntimeError('RISK_CODE_COVERAGE')
    expected={**protected,**q2['code_files_sha256'],
        **{a['path']:a['file_sha256'] for a in q2['artifacts'].values()},
        previous.SOURCE:q2['source_note_sha256'],previous.OUTPUT+'/analysis.json':Q2_SHA}
    for path,sha in expected.items():
        if c['preserved_files_sha256'].get(path)!=sha: raise RuntimeError('RISK_PRESERVATION_COVERAGE:'+path)
    for path, sha in {**c['code_files_sha256'], **c['preserved_files_sha256']}.items():
        if old.file_sha(ROOT/path) != sha: raise RuntimeError('RISK_FROZEN_BYTES:' + path)
    if old.file_sha(ROOT/DESIGN) != c['design_sha256']: raise RuntimeError('RISK_DESIGN_BYTES')
    return c, q0, q1, q2


def load_parent(q0):
    ans = {}
    for name in ('trades','open_observations','events','daily_bars','daily_valuation'):
        a = q0['artifacts'][name]
        if old.file_sha(ROOT/a['path']) != a['file_sha256']: raise RuntimeError('RISK_PARENT_LEDGER:' + name)
        rows = previous.read_lines(a['path'])
        ans[name] = rows if name == 'daily_bars' else [r for r in rows if r['comparison_stage'] == 'Q']
    return ans


def check_unit_parity(parent, four, costs, policy, symbols, start, end, q0):
    ts, opened = parent['trades'], parent['open_observations']
    # Re-price the same sealed fills and elapsed costs, without replaying a rule.
    for t in ts:
        parts = old.probe.cost_components(t['entry_ts'],t['exit_ts'],costs[t['symbol']])
        parts['frozen_floor_reserve_bps'] = max(0.,20.-parts['cost_bps'])
        checks = {**{k:parts[k] for k in prior.accounting.COST_FIELDS},
            'cost_bps':max(20.,parts['cost_bps']),
            'gross_bps':(t['exit_price']/t['entry_price']-1)*10000}
        checks['net_bps']=checks['gross_bps']-checks['cost_bps']
        checks['cost2x_net_bps']=checks['gross_bps']-2*checks['cost_bps']
        for k,v in checks.items():
            if not math.isclose(v,t[k],rel_tol=1e-12,abs_tol=1e-7): raise RuntimeError('RISK_UNIT_COST_PRICE_PARITY:'+k)
    metrics = prior.accounting.summarize(ts,opened,parent['events'],policy,symbols)
    for k,v in metrics.items():
        if v != q0['metrics']['Q'][k]: raise RuntimeError('RISK_UNIT_METRIC_PARITY:'+k)
    daily = prior.daily_valuation(ts,opened,four,costs,start,end)
    original = [{k:v for k,v in r.items() if k!='comparison_stage'} for r in parent['daily_valuation']]
    if daily != original: raise RuntimeError('RISK_UNIT_DAILY_PARITY')
    if prior.accounting.diagnostics(ts,start,end)!=q0['diagnostics']['Q'] or prior.accounting.daily_mark_diagnostics(daily)!=q0['marked_diagnostics']['Q']:
        raise RuntimeError('RISK_UNIT_RISK_PARITY')
    return {'prices_costs_metrics_daily_risk':'PASS','rule_replayed':False,'original_ledger_rewritten':False}


def study_decision(terminal_B, cost2_B, terminal_C, dd_B, dd_C, loss_B, loss_C, interval):
    eps=GOAL['numerical_equality_abs_tolerance_bps']
    checks={'positive_terminal_net':terminal_B>0,'positive_cost2_terminal_net':cost2_B>0,
        'net_not_worse_than_C':terminal_B>=terminal_C-eps,
        'DD_not_worse_than_C':dd_B<=dd_C+eps,'loss_run_not_worse_than_C':loss_B<=loss_C+eps}
    advantages={'terminal_net':terminal_B>terminal_C+eps,'marked_DD':dd_B<dd_C-eps,'loss_run':loss_B<loss_C-eps}
    checks['at_least_one_improvement']=any(advantages.values())
    met=all(checks.values()); strong=interval[0] is not None and interval[0]>0
    positive=checks['positive_terminal_net'] and checks['positive_cost2_terminal_net']
    status=('DEV_PROMISING_NO_CREDIT' if strong else 'DEV_INCONCLUSIVE') if met else ('DEV_INCONCLUSIVE_TRADEOFF' if positive and any(advantages.values()) else 'DEV_REJECT')
    return {'decision':status,'economic_status':'MEASURED','comparison_type':'ENTRY_NOTIONAL_ALLOCATION',
        'study_goal_met':met,'checks':checks,'relative_advantages':advantages,
        'failed_checks':[k for k,v in checks.items() if not v],
        'B_minus_C_increment_lower95_positive':strong,'research_reference':'Q0',
        'signal_prediction_improvement_claimed':False,'formal_pass':False,'operating_adoption':False,
        'code_test_PASS_is_economic_PASS':False,'automatic_next_candidate':False}


def write_artifact(name, value, verify_only):
    path=ROOT/OUTPUT/name; raw=old.probe.canonical(value)
    payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
    if gzip.decompress(payload)!=raw: raise RuntimeError('RISK_REPRODUCTION_DRIFT:'+name)
    old.probe.write_immutable(path,payload,verify_only=verify_only)
    return {'path':str(path.relative_to(ROOT)),'file_sha256':old.file_sha(path)}


def run(data_dir, verify_only=False):
    c,q0,q1,q2=authorize(); out=ROOT/OUTPUT
    if (out/'receipt.json').exists() and not verify_only: raise RuntimeError('ALLOCATION_CONSUMED_USE_VERIFY_ONLY')
    policy,dev,four,_,access=prior.inputs.load_inputs(data_dir)
    if policy['combined_data_sha256']!=c['data_sha256'] or policy['cost_binding_sha256']!=c['cost_sha256'] or sorted(four)!=c['symbols']:
        raise RuntimeError('RISK_DATA_COST_UNIVERSE_BINDING')
    start,end=c['evaluation_interval_ms']
    policy={**policy,'development_interval_ms':[start,end]}
    parent=load_parent(q0)
    with old.probe.io_boundary([],out):
        parity=check_unit_parity(parent,four,dev['cost_by_symbol'],policy,c['symbols'],start,end,q0)
        market=weights.market_state(four,c['symbols'],start,end)
        if not math.isclose(market['sigma_ref'],c['reference']['sigma_ref'],rel_tol=1e-12,abs_tol=1e-15): raise RuntimeError('RISK_REFERENCE_PARITY')
        # Only these pre-entry fields reach the weight calculator.
        fields=('lane_id','symbol','signal_ts','entry_ts','side')
        causal=lambda rows:[{k:t[k] for k in fields} for t in rows]
        entry=weights.entry_weights(market,causal(parent['trades']),causal(parent['open_observations']))
        measured=accounting.build(parent['trades'],parent['open_observations'],parent['events'],four,dev['cost_by_symbol'],policy,c['symbols'],start,end,entry,
            pinned_windows=c['pinned_windows'])
    # Final extraction/report is defined alongside the frozen accounting schema.
    result=assemble_result(c,q0,q1,q2,parity,market,entry,measured,access,verify_only)
    return result


def assemble_result(c,q0,q1,q2,parity,market,entry,measured,access,verify_only):
    stages=measured['stages']; b=stages['B_RISK']; control=stages['C_FIXED']
    loss=lambda s:s['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps']
    decision=study_decision(b['metrics']['terminal_net_amount_bps'],b['metrics']['terminal_cost2x_net_amount_bps'],
        control['metrics']['terminal_net_amount_bps'],b['marked_diagnostics']['marked_DD_trade_sum_bps'],
        control['marked_diagnostics']['marked_DD_trade_sum_bps'],loss(b),loss(control),
        measured['uncertainty']['child_minus_parent_95pct_interval_bps_per_day'])
    artifacts={
        'market_and_entry_weights':write_artifact('market_and_entry_weights.json.gz',{'market':market,'entry_weights':entry},verify_only),
        'weighted_accounting':write_artifact('weighted_accounting.json.gz',measured,verify_only)}
    summaries={s:{k:v for k,v in stage.items() if k not in ('daily','ledger')} for s,stage in stages.items()}
    for summary in summaries.values():
        summary['exposure']={k:v for k,v in summary['exposure'].items() if k!='holding_intervals'}
    windows=[]
    for w in measured['windows']:
        data={k:v for k,v in w.items() if k!='stages'};data['stages']={}
        for name,value in w['stages'].items():
            contributions=value['position_contributions']
            cohorts={}
            for label,predicate in (
                ('entered_before_window',lambda t:t['unit_contribution']['entry_ts']<w['start_ms']),
                ('entered_at_or_after_window_start',lambda t:t['unit_contribution']['entry_ts']>=w['start_ms'])):
                selected=[t for t in contributions if predicate(t) and any(abs(v)>1e-12 for v in t['delta'].values())]
                cohorts[label]={'contributing_T':len(selected),
                    'net_mark_delta_bps':sum(t['delta']['net_bps'] for t in selected),
                    'minimum_entry_weight':min((t['entry_weight'] for t in selected),default=None),
                    'maximum_entry_weight':max((t['entry_weight'] for t in selected),default=None),
                    'weights_fixed_at_original_entry':True}
            data['stages'][name]={'totals':value['totals'],'entry_timing_cohorts':cohorts}
        windows.append(data)
    ws=[v['weight'] for v in entry.values()]
    r=old.seal({'batch_id':'Q0_RISK_ENTRY_V1','contract_sha256':c['receipt_sha256'],
        'Q0_receipt_sha256':q0['receipt_sha256'],'Q1_receipt_sha256':q1['receipt_sha256'],'Q2_analysis_sha256':q2['receipt_sha256'],
        'parent_states':{'Q0':'DEV_INCONCLUSIVE','Q1':'DEV_REJECT','Q2':'NOT_RUN_NO_SUPPORTED_INTERVENTION'},
        'decision':decision,'budget':{**BUDGET,'new_trials_consumed':1,'cumulative_after':26,'remaining_allocated_trials':0},
        'reference':{**market['reference'],'sigma_ref':market['sigma_ref']},
        'weight_summary':{'T':len(ws),'minimum':min(ws),'maximum':max(ws),'mean_per_entry':sum(ws)/len(ws),'reduced_entries':sum(w<1 for w in ws)},
        'unit_metrics':q0['metrics']['Q'],'preserved_P_metrics':q0['metrics']['P'],
        'unit_parity':parity,'invariants':measured['invariants'],'control':measured['control'],'stages':summaries,
        'same_calendar_windows':windows,'attribution':measured['attribution'],'uncertainty':measured['uncertainty'],
        'artifacts':artifacts,'source_access':access,'data_sha256':c['data_sha256'],'cost_sha256':c['cost_sha256'],
        'symbols':c['symbols'],'evaluation_interval_ms':c['evaluation_interval_ms'],
        'data_reuse_history':c['data_reuse_history'],
        'unused_validation_readiness':c['unused_validation_readiness'],
        'validation_rows_decoded':0,'OOS_rows_decoded':0,'paid_external_AI_calls':0,'Gemini_actual_video':'NOT_RUN',
        'G5B_changed':False,'operating_changed':False,'G6_authorized':False,'G7_formal_authorized':False,'G11_formal_authorized':False,'actual_account_sizing':False,
        **old.probe.DEV_AUTH})
    out=ROOT/OUTPUT
    old.probe.write_immutable(out/'receipt.json',old.probe.canonical(r),verify_only=verify_only)
    old.probe.write_immutable(out/'RESULTS.md',report(r),verify_only=verify_only)
    paths=[CONTRACT,DESIGN,OUTPUT+'/receipt.json',OUTPUT+'/RESULTS.md']+[v['path'] for v in artifacts.values()]
    durable=old.seal({'result_receipt_sha256':r['receipt_sha256'],
        'files_sha256':{p:old.file_sha(ROOT/p) for p in paths},'code_files_sha256':c['code_files_sha256'],
        'preserved_files_sha256':c['preserved_files_sha256'],**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'durable_receipt.json',old.probe.canonical(durable),verify_only=verify_only)
    return r


def report(r):
    f=lambda v:'NA' if v is None else f'{v:,.4f}'
    ss=r['stages']; names=('A_Q0','C_FIXED','B_RISK')
    lines=['# Q0 entry-notional risk study — measured DEV result','',
        'Same signals/fills/SL/holding/ownership; only entry notional changes. Unit trade returns remain Q0. Weighted amounts below use one fixed reference notional, expressed in bps units; these are not account returns or account MDD.', '',
        '| Metric | Q0 A | Fixed same-exposure C | Entry-risk B |','|---|---:|---:|---:|']
    rows=[('Signals',lambda s:ss[s]['metrics']['raw_signals']),
        ('Closed / open',lambda s:str(ss[s]['metrics']['base_cost']['completed_T'])+' / '+str(ss[s]['metrics']['open_observations']['T'])),
        ('Unweighted unit net expectancy',lambda s:f(r['unit_metrics']['base_cost']['expectancy_bps_per_trade'])),
        ('Unweighted win rate %',lambda s:f(100*r['unit_metrics']['base_cost']['win_rate'])),
        ('Weighted gross amount / closed T',lambda s:f(ss[s]['metrics']['base_cost']['gross_expectancy_bps'])),
        ('Weighted net amount / closed T',lambda s:f(ss[s]['metrics']['base_cost']['expectancy_bps_per_trade'])),
        ('Amount PF',lambda s:f(ss[s]['metrics']['base_cost']['PF'])),
        ('Mean winning / losing amount',lambda s:f(ss[s]['metrics']['base_cost']['average_win_bps'])+' / '+f(ss[s]['metrics']['base_cost']['average_loss_bps'])),
        ('Amount realized payoff',lambda s:f(ss[s]['metrics']['base_cost']['realized_payoff'])),
        ('Cost2 weighted net / closed T',lambda s:f(ss[s]['metrics']['cost2x']['expectancy_bps_per_trade'])),
        ('Closed net amount',lambda s:f(ss[s]['metrics']['base_cost']['net_bps'])),
        ('Open hypothetical net mark',lambda s:f(ss[s]['metrics']['open_observations']['hypothetical_liquidation_net_mark_bps'])),
        ('Terminal net amount',lambda s:f(ss[s]['metrics']['terminal_net_amount_bps'])),
        ('Terminal cost2 net amount',lambda s:f(ss[s]['metrics']['terminal_cost2x_net_amount_bps'])),
        ('Daily marked DD amount',lambda s:f(ss[s]['marked_diagnostics']['marked_DD_trade_sum_bps'])),
        ('Max grouped losing-run amount',lambda s:f(ss[s]['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'])),
        ('Nominal-weighted position-days',lambda s:f(ss[s]['exposure']['nominal_weighted_position_days'])),
        ('Max simultaneous weighted slots',lambda s:f(ss[s]['exposure']['max_simultaneous_nominal_weighted_open_slots'])),
        ('Original winner money retained',lambda s:f(ss[s]['original_profit_retention']['all_winners']['preserved_amount_bps'])),
        ('Original top-decile money retained / %',lambda s:f(ss[s]['original_profit_retention']['original_top_decile_winners']['preserved_amount_bps'])+' / '+f(100*ss[s]['original_profit_retention']['original_top_decile_winners']['amount_retention'])),
        ('Fees / funding / all closed costs',lambda s:' / '.join(f(ss[s]['metrics']['closed_cost_totals_bps'][k]) for k in ('fee_bps','funding_bps','cost_bps'))),
        ('Net / weighted exposure-day',lambda s:f(ss[s]['descriptive_ratios']['terminal_net_per_nominal_weighted_day'])),
        ('Terminal net / marked DD',lambda s:f(ss[s]['descriptive_ratios']['terminal_net_to_marked_DD'])),
        ('Top-symbol / top-decile profit share',lambda s:' / '.join(f(ss[s]['metrics']['concentration'][k]) for k in ('top_one_symbol_profit_share','top_decile_winners_share'))),
        ('Mixed-sign close-group sign changes',lambda s:ss[s]['group_sign_changes_from_Q0']['changed_simultaneous_group_sign_T'])]
    for label,fn in rows:lines.append('| '+label+' | '+' | '.join(str(fn(s)) for s in names)+' |')
    lines += ['',f"Reference daily sigma: {r['reference']['sigma_ref']:.12f}; pre-evaluation returns {r['reference']['N']}. Entry weights: {r['weight_summary']}. C k={r['control']['k']:.12f}, **ex-post analytical normalization only**, not a trading rule or an input to B. No weight above1, no zero/drop, no intraholding changes.", '',
        '**Research decision: '+r['decision']['decision']+'**; study goal met='+str(r['decision']['study_goal_met'])+'. Failed checks: '+', '.join(r['decision']['failed_checks'])+'. Q0 remains the research reference. Code/CI PASS does not imply economic or formal adoption.', '',
        '| Contribution | B minus Q0 | B minus C |','|---|---:|---:|']
    a=r['attribution']
    for label,fn in [('Closed net change',lambda x:x['closed_delta']['net_bps']),('Terminal net change',lambda x:x['terminal_delta']['net_bps']),('Original loss amount saved, signed',lambda x:x['loss_amount_reduction_bps_signed']),('Original winner amount foregone, signed',lambda x:x['foregone_winner_amount_bps_signed']),('Cost saving, already included in net',lambda x:x['closed_cost_amount_saving_bps_signed']),('Gross change',lambda x:x['terminal_delta']['gross_bps'])]:
        lines.append('| '+label+' | '+' | '.join(f(fn(a[s])) for s in ('B_minus_A','B_minus_C'))+' |')
    lines += ['',f"All {r['invariants']['closed_T']} closed and {r['invariants']['open_T']} open positions are common. New/removed trades and their PnL are0. Loss/winner net contributions already include cost savings; do not add costs a second time.", '',
        '## Original pinned calendar intervals','',
        'Original Q0 labels are analysis-only; windows can overlap. Mark all positions on identical boundaries. Different worst-window maxima are not causal attribution. Full per-position starting/ending marks are in weighted_accounting.json.gz.', '',
        '| Original interval | UTC milliseconds | Q0 net mark change | C net mark change | B net mark change |','|---|---|---:|---:|---:|']
    for w in r['same_calendar_windows']:
        lines.append('| '+w['label']+f" | {w['start_ms']} to {w['end_ms']} | "+' | '.join(f(w['stages'][s]['totals']['delta']['net_bps']) for s in names)+' |')
    lines += ['', 'Entry-timing cohorts in receipt.json split positions entered before each window from later entries. Their recorded available_at and weight were fixed at each original entry; subsequent volatility cannot resize already held positions. These are retrospective calendar cohorts, not proof of pre-loss prediction. Positive individual multipliers preserve wins/losses; weighted simultaneous mixed-sign groups may nevertheless change aggregate run labels.', '',
        '## Monthly marked net contributions','', '| Month | Q0 | C | B |','|---|---:|---:|---:|']
    for month in sorted(ss['A_Q0']['by_mark_month']):
        lines.append('| '+month+' | '+' | '.join(f(ss[s]['by_mark_month'][month]['net_bps']) for s in names)+' |')
    lines += ['', '## Symbol terminal net contributions','', '| Symbol | Q0 | C | B |','|---|---:|---:|---:|']
    for symbol in r['symbols']:
        lines.append('| '+symbol+' | '+' | '.join(f(ss[s]['by_symbol_marked'].get(symbol,{}).get('terminal_net_bps',0)) for s in names)+' |')
    u=r['uncertainty']
    lines += ['', '## Uncertainty and boundaries','',
        f"B-C mean daily marked increment: {f(u['child_minus_parent_mean_daily_bps'])};95% interval {u['child_minus_parent_95pct_interval_bps_per_day']}; calendar-sum interval {u['child_minus_parent_95pct_interval_calendar_sum_bps']}. Existing paired noncircular30day1000draw seed1178 method. Fixed realized C k is conditioned on, not re-estimated as a tradable parameter. Dependence can exceed30days; repeated DEV and model selection are uncorrected. This is not independent OOS or account Sharpe.", '',
        'Original unit prices/costs/metrics/daily risk parity PASS. All legacy files are verified by frozen SHA; original Q0/Q1/Q2 states and25-trial history remain unchanged. One measured new entry-risk candidate consumes the reallocated slot: cumulative26, remaining0. Exact reproductions are not new hypotheses. No automatic window/ref retuning.', '',
        'Unused validation: the old Break validation was already consumed/rejected. Metadata identifies a purged-OOS pool, but Q0-specific authorization, candidate freeze, warmup/purge/ownership and open-end specification are absent. Original26bar embargo is a STAPC20+6 design, not automatic Q0 eligibility. Actual fill/depth/signed-funding and formal terminal lineage are unbound. These future gaps did not block this authorized DEV calculation.', '',
        'See DESIGN_AND_SOURCES.md for directly read source locations and limitations. Moreira/Muir monthly inverse-variance and other rebalanced literature are not replications of this entry-only30day capped ZEL design. No paper performance is transferred to Q0.', '',
        'validation/OOS decoded0; paid external AI0; Gemini actual videoNOT_RUN. G5B/operating/actual-account-sizing/G7/G11 unchanged; executionNONE/orderBLOCKED/liveBLOCKED. No deploy required.', '']
    return '\n'.join(lines).encode()


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true')
    args=ap.parse_args();r=run(args.data_dir.resolve(),args.verify_only)
    print(json.dumps({'receipt':r['receipt_sha256'],'decision':r['decision'],'budget':r['budget']},indent=2))
