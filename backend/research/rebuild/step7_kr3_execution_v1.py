"""STEP7 native KR3 FULL execution producer. No network or self-granted authority.

Only --fixture supplies built-in artificial raw data. --request passes all actual
sealed IO to the independently provisioned authorization boundary. Pure functions
accept in-memory values for testing and the bounded source owner's isolated job.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import threading
from unittest.mock import patch
from backend.research.rebuild import keltner_kr3_v1 as kr3
from backend.research.rebuild import step7_candidate_contract_v1 as contracts
from backend.research.rebuild import step7_independent_validation_v1 as validation
from backend.research.rebuild.g5_forward_real_evidence_bridge_v1 import signed_funding_cost_bps
from backend.research.architecture_factory.g5a_development_probe_v1 import summarize

kr, m2, reservation, d = kr3.kr, kr3.m2, kr3.parent, kr3.d
BAR = d.BAR
SYMBOLS = ('1000PEPE-USDT','BCH-USDT','BTC-USDT','ETH-USDT','HYPE-USDT','LINK-USDT','SOL-USDT')
CENTER = (20, 50, 12)
NEIGHBORS = ((19,50,12),(21,50,12),(20,49,12),(20,51,12),(20,50,11),(20,50,13))
CONTROLS = ('direction_flip','time_shift_placebo','delayed_entry','regime_permutation')
ABLATIONS = ('without_trend_feature','without_reclaim_feature','without_directional_half','without_kr3_veto')
_LOCK = threading.RLock()
sha = contracts.sha


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


@contextmanager
def sensitivity(parameters=CENTER, ablation=None):
    """Scoped serial dependency propagation; disk owners and frozen base unchanged."""
    if tuple(parameters) not in (CENTER, *NEIGHBORS):
        raise ValueError('FINITE_NEIGHBOR_INVENTORY_ONLY')
    fast, slow, hold = parameters
    spec = deepcopy(d.PARENT_SPEC)
    spec['features'] = [{'name':'ema20','formula':f'ema(close,{fast})'},
                        {'name':'ema50','formula':f'ema(close,{slow})'}]
    spec['max_hold_bars'] = hold
    if ablation == 'without_trend_feature':
        spec['entry_rule'] = "lag('close',1) <= lag('ema20',1) and close > ema20"
    elif ablation == 'without_reclaim_feature':
        spec['entry_rule'] = 'ema20 > ema50'
    with _LOCK, ExitStack() as stack:
        for owner in (d, reservation, m2, kr, kr3):
            stack.enter_context(patch.object(owner, 'HOLD', hold))
        stack.enter_context(patch.object(d, 'PARENT_SPEC', spec))
        if ablation == 'without_directional_half':
            original = reservation.n.entry_observation
            def no_half(row):
                value = original(row)
                value[reservation.n.FEATURE] = True
                return value
            stack.enter_context(patch.object(reservation.n, 'entry_observation', no_half))
        yield spec


def _regimes(rows, bundle, rule):
    if rule.get('name') != 'EMA50_SLOPE_X_ATR20_RATIO' or not finite(rule.get('frozen_dev_atr_ratio_median')):
        raise ValueError('EXPLICIT_CAUSAL_REGIME_RULE_REQUIRED')
    values, atr = [], None
    trs = []
    for i, row in enumerate(rows):
        previous = rows[i-1]['close'] if i else row['close']
        tr = max(row['high']-row['low'], abs(row['high']-previous), abs(row['low']-previous))
        trs.append(tr)
        if i == 19:
            atr = sum(trs)/20
        elif i > 19:
            atr = (19*atr+tr)/20
        slope = 'UP' if i and bundle['ema50'][i]>bundle['ema50'][i-1] else 'DOWN_OR_FLAT'
        vol = 'HIGH' if atr is not None and atr/row['close']>rule['frozen_dev_atr_ratio_median'] else 'LOW'
        values.append(slope+':'+vol)
    return values


def native_replay(rows_by, specification, *, parameters=CENTER, control=None, ablation=None):
    start, stop, end = (specification[k] for k in ('start_ms','entry_stop_ms','runoff_end_ms'))
    if not start < stop <= end or any(x % BAR for x in (start,stop,end)):
        raise ValueError('NATIVE_CALENDAR')
    output = {k:[] for k in ('trades','open_positions','events','trace','reference_opportunities')}
    output['audit'] = {}
    with sensitivity(parameters, ablation) as policy:
        for symbol, rows in sorted(rows_by.items()):
            bundle = d.build_bundle(rows, policy, eval_start_ms=start, eval_end_ms=end)
            regimes = _regimes(rows, bundle, specification['regime'])
            original = deepcopy(bundle['signals'])
            signals = [s for s in original if s['signal_ts'] < stop]
            offset = 6 if control == 'time_shift_placebo' else 1 if control == 'delayed_entry' else 0
            # Control delays are forward-only. At the shifted completed close,
            # latch THAT bar's geometry and start its own reference/actual slot.
            # No later outcome or original parent's actual admitted list is used.
            if offset:
                signals = [{'signal_index':s['signal_index']+offset,
                            'signal_ts':rows[s['signal_index']+offset]['bar_close_ts']}
                           for s in signals if s['signal_index']+offset < len(rows)
                           and rows[s['signal_index']+offset]['bar_close_ts'] < stop]
            bundle['signals'] = signals
            owner = kr if ablation == 'without_kr3_veto' else kr3
            raw = owner.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end)
            references = {r['reference_signal_index']:r for r in raw['reference_opportunities']}
            for name in output:
                if name == 'audit':
                    continue
                for value in raw[name]:
                    row = deepcopy(value)
                    row['symbol'] = symbol
                    index = row.get('signal_index', row.get('reference_signal_index'))
                    if index is not None:
                        row['origin_id'] = f'{symbol}:{rows[index]["bar_close_ts"]}'
                        row['regime_id'] = regimes[index]
                    if name in ('trades','open_positions'):
                        row['signal_ts'] = rows[index]['bar_close_ts']
                        row['reference_end_ts'] = references.get(index,{}).get('release_ts')
                        row['side'] = 'short' if control == 'direction_flip' else 'long'
                        if row['side'] == 'short':
                            field = 'gross_bps' if name == 'trades' else 'gross_mark_bps'
                            row[field] = -row[field]
                            # Excursions are not re-used as short-side evidence.
                            row['mfe_bps'] = row['mae_bps'] = None
                        row['initial_protective_sl'] = row['tp'] = row['risk_R'] = None
                        if control == 'regime_permutation':
                            # Fixed causal bijection relabels the four regimes.
                            # KR3 has no regime entry filter: economics are
                            # necessarily invariant, making this a degenerate
                            # control, which the consumer reports, never PASSes.
                            labels = ['UP:HIGH','UP:LOW','DOWN_OR_FLAT:HIGH','DOWN_OR_FLAT:LOW']
                            row['regime_id'] = labels[(labels.index(row['regime_id'])+1)%4]
                    output[name].append(row)
            output['audit'][symbol] = {**raw['audit'], 'native_raw_signals':len(original),
                'parameters':list(parameters), 'decision_offset':parameters[2]-1,
                'extended_cap_offset':2*parameters[2], 'reference_hold':parameters[2],
                'fresh_flat_once_at_start':True, 'window_resets':0,
                'control':control, 'ablation':ablation,
                'regime_permutation_degenerate':control=='regime_permutation'}
    return output


def _cost_row(row, raw_source, cost, *, opened=False):
    value = deepcopy(row)
    end = row['mark_ts'] if opened else row['exit_ts']
    gross = row['gross_mark_bps'] if opened else row['gross_bps']
    unknown, parts = [], {}
    fee = cost.get('fee_bps_each_side')
    if not finite(fee) or fee < 0:
        unknown.append('FEE_EVIDENCE_MISSING')
    else:
        parts['fee_bps'] = 2*fee
    if cost.get('stress') != 'DOUBLE_ALL_SIGNED_COST_COMPONENTS':
        unknown.append('COST2_SIGNED_STRESS_UNAPPROVED_OR_UNDEFINED')
    quote_rows=raw_source.get('quotes', [])
    quotes = {q['ts']:q for q in quote_rows}
    if len(quotes)!=len(quote_rows): unknown.append('DUPLICATE_QUOTE_TIMESTAMP')
    qentry, qexit = quotes.get(row['entry_ts']), quotes.get(end)
    availability = {r['bar_close_ts']:r.get('available_ts') for r in raw_source['bars']}
    if type(availability.get(row['signal_ts'])) is not int or availability[row['signal_ts']] > row['entry_ts']:
        unknown.append('SIGNAL_AVAILABLE_AFTER_MODEL_ENTRY_NO_RETRO_FILL')
    if row.get('exit_trigger') and (type(availability.get(row['exit_trigger']['signal_ts'])) is not int or availability[row['exit_trigger']['signal_ts']] > end):
        unknown.append('EXIT_SIGNAL_AVAILABLE_AFTER_MODEL_EXIT_NO_RETRO_FILL')
    slip = 0.
    for phase, q, ts in (('ENTRY',qentry,row['entry_ts']),('EXIT_OR_MARK',qexit,end)):
        if q is None or not all(finite(q.get(k)) for k in ('bid','ask','impact_bps')) or q['bid']<=0 or q['ask']<q['bid'] or q['impact_bps']<0:
            unknown.append(phase+'_BBO_OR_IMPACT_MISSING')
            continue
        if type(q.get('available_ts')) is not int or type(q.get('event_ts')) is not int:
            unknown.append(phase+'_QUOTE_TIMESTAMP_EVIDENCE_MISSING')
        elif q['available_ts'] > ts or q['event_ts'] > ts:
            unknown.append(phase+'_QUOTE_NOT_AVAILABLE_AT_MODEL_TIME')
        elif type(cost.get('max_quote_age_ms')) is not int or cost['max_quote_age_ms']<0:
            unknown.append('QUOTE_MAX_AGE_POLICY_MISSING')
        elif ts-q['event_ts']>cost['max_quote_age_ms']:
            unknown.append(phase+'_QUOTE_STALE')
        mid = (q['bid']+q['ask'])/2
        slip += (q['ask']-q['bid'])/(2*mid)*10000 + q['impact_bps']
    parts['spread_impact_bps'] = slip if not any('BBO' in x for x in unknown) else None
    if cost.get('price_basis')!='MIDPOINT_RETURN_RECONCILIATION':
        unknown.append('MODEL_TO_QUOTE_PRICE_BASIS_UNBOUND')
    elif not any('BBO' in x for x in unknown):
        entry_mid=(qentry['bid']+qentry['ask'])/2
        exit_mid=(qexit['bid']+qexit['ask'])/2
        signed=1 if row['side']=='long' else -1
        parts['model_to_quote_mid_basis_bps']=gross-signed*(exit_mid/entry_mid-1)*10000
    funding = raw_source.get('funding')
    interval = cost.get('funding_interval_ms')
    if not isinstance(funding,list) or type(interval) is not int or interval<=0:
        unknown.append('FUNDING_SETTLEMENT_COVERAGE_UNKNOWN')
    else:
        expected = set(range((row['entry_ts']//interval+1)*interval, end+1, interval))
        selected = [f for f in funding if row['entry_ts']<f.get('ts',-1)<=end]
        actual = [f['ts'] for f in selected]
        if set(actual)!=expected or len(actual)!=len(set(actual)) or any(not finite(f.get('rate')) for f in selected):
            unknown.append('FUNDING_SETTLEMENT_GAP_DUPLICATE_OR_INVALID')
        else:
            parts['funding_bps'] = signed_funding_cost_bps(row['side'],selected)
    total = None if unknown else math.fsum(parts.values())
    value.update(cost_components=parts, cost_unknown_reasons=unknown,
                 cost_bps=total, net_bps=None if total is None else gross-total,
                 cost2x_net_bps=None if total is None else gross-2*total,
                 cost_sha=sha(cost), actual_fill=False,
                 timing_basis='UNCHANGED_NATIVE_ZERO_LATENCY_MODEL; LATE_AVAILABILITY_FAILS_REALISTIC_COST',
                 cost_basis='MODEL_TO_QUOTE_MID_RETURN_RECONCILIATION_PLUS_FEE_HALF_SPREAD_DEPTH_IMPACT_SIGNED_FUNDING; NO_SEPARATE_SLIPPAGE')
    if opened:
        value['hypothetical_net_mark_bps'] = value.pop('net_bps')
        value['hypothetical_cost2x_net_mark_bps'] = value.pop('cost2x_net_bps')
        value['terminal_liquidation'] = False
    return value


def cost_ledger(raw, source, cost):
    out = deepcopy(raw)
    out['trades'] = [_cost_row(r,source[r['symbol']],cost) for r in raw['trades']]
    out['open_positions'] = [_cost_row(r,source[r['symbol']],cost,opened=True) for r in raw['open_positions']]
    return out


def metrics(rows, spec, *, cost2=False):
    field = 'cost2x_net_bps' if cost2 else 'net_bps'
    if any(r.get(field) is None for r in rows):
        return {'completed_T':len(rows),'net_bps':None,'expectancy_bps_per_trade':None,'PF':None,
                'unknown_origin_ids':[r['origin_id'] for r in rows if r.get(field) is None],
                'status':'BLOCKED_UNKNOWN_COST_NO_ROWS_DROPPED'}
    return summarize(rows,start_ms=spec['start_ms'],end_ms=spec['runoff_end_ms'],symbol_count=len(SYMBOLS),cost2x=cost2)


def terminal(ledger):
    closed, opened = ledger['trades'],ledger['open_positions']
    def total(values):
        return None if any(v is None for v in values) else math.fsum(values)
    c = total([r['net_bps'] for r in closed]); o = total([r['hypothetical_net_mark_bps'] for r in opened])
    return {'closed_net_bps':c,'open_hypothetical_net_mark_bps':o,
            'terminal_net_bps':None if c is None or o is None else c+o,
            'terminal_cost2x_net_bps':total([r['cost2x_net_bps'] for r in closed]+[r['hypothetical_cost2x_net_mark_bps'] for r in opened]),
            'open_T':len(opened),'actual_terminal_liquidations':0}


def retention(parent,child):
    parent_unknown=[r['origin_id'] for r in parent['trades'] if r['net_bps'] is None]
    winners = [r for r in parent['trades'] if r['net_bps'] is not None and r['net_bps']>0]
    denominator = math.fsum(r['net_bps'] for r in winners)
    child_rows = {r['origin_id']:r for r in child['trades']+child['open_positions']}
    unknown = parent_unknown+[r['origin_id'] for r in winners if r['origin_id'] in child_rows and child_rows[r['origin_id']].get('net_bps') is None]
    numerator = math.fsum(min(r['net_bps'],max(0.,child_rows.get(r['origin_id'],{}).get('net_bps') or 0.)) for r in winners)
    return {'baseline':'KR1_FULL_OWN_ACTUAL_SLOT','parent_positive_closed_profit_bps':denominator,
            'retained_capped_profit_bps':None if unknown else numerator,
            'retention':None if unknown or not denominator else numerator/denominator,
            'unresolved_parent_winner_origins':unknown,'parent_unknown_cost_origins':parent_unknown,
            'missing_origin_credit':0,'missing_origin_is_not_a_zero_return_trade':True,
            'formal_retention_pass':False}


def validate_spec(spec):
    if tuple(tuple(v) for v in spec.get('neighbors',[])) != NEIGHBORS:
        raise ValueError('SIX_EXACT_NEIGHBORS_REQUIRED')
    if tuple(spec.get('controls',[])) != CONTROLS or tuple(spec.get('ablations',[])) != ABLATIONS:
        raise ValueError('FINITE_CONTROL_AND_ABLATION_SPECS_REQUIRED')
    windows = spec.get('windows',[])
    if len(windows)!=3 or windows[0]['start_ms']!=spec['start_ms'] or windows[-1]['end_ms']!=spec['entry_stop_ms']:
        raise ValueError('THREE_CONTIGUOUS_WINDOWS')
    for i,w in enumerate(windows):
        if w['start_ms']>=w['end_ms'] or (i and windows[i-1]['end_ms']!=w['start_ms']):
            raise ValueError('THREE_CONTIGUOUS_WINDOWS')
    if type(spec.get('embargo_ms')) is not int or spec['embargo_ms']<0:
        raise ValueError('EXPLICIT_EMBARGO_REQUIRED')
    if spec.get('control_semantics') != fixture_spec()['control_semantics']:
        raise ValueError('CONTROL_SEMANTICS_EXACT_INPUT_REQUIRED')


def _interval_end(row):
    end = row.get('exit_ts')
    reference = row.get('reference_end_ts')
    return float('inf') if end is None or reference is None else max(end,reference)


def produce_reports(source, spec, cost, *, evidence_kind):
    validate_spec(spec)
    if tuple(sorted(source)) != tuple(sorted(SYMBOLS)):
        raise ValueError('EXACT_SEVEN_SYMBOL_UNIVERSE')
    rows_by = {s:source[s]['bars'] for s in source}
    raw = native_replay(rows_by,spec)
    child = cost_ledger(raw,source,cost)
    parent = cost_ledger(native_replay(rows_by,spec,ablation='without_kr3_veto'),source,cost)
    identity = {'candidate_sha256':spec['candidate_sha256'],'data_sha':sha(source),'cost_sha':sha(cost)}
    base = metrics(child['trades'],spec)
    unknown = [{'origin_id':r['origin_id'],'reasons':r['cost_unknown_reasons']}
               for r in child['trades']+child['open_positions'] if r['cost_unknown_reasons']]
    windows, folds = [], []
    for w in spec['windows']:
        cohort = [r for r in child['trades']+child['open_positions'] if w['start_ms']<=r['signal_ts']<w['end_ms']]
        closed = [r for r in cohort if 'exit_ts' in r]
        training = [r for r in child['trades']+child['open_positions'] if r['signal_ts']<w['start_ms']]
        purged = [r['origin_id'] for r in training if _interval_end(r)+spec['embargo_ms']>=w['start_ms'] or
                  any(r['entry_ts']<=_interval_end(t) and t['entry_ts']<=_interval_end(r) for t in cohort)]
        windows.append({'window':w,'origin_ids':[r['origin_id'] for r in cohort],
                        'closed_metrics':metrics(closed,spec),'open_origin_ids':[r['origin_id'] for r in cohort if 'exit_ts' not in r],
                        'occupancy_reset':False,'cohort_attribution':'SIGNAL_CLOSE_WITH_FULL_ACTUAL_REFERENCE_RUNOFF'})
        folds.append({'window':w,'training_retained':[r['origin_id'] for r in training if r['origin_id'] not in purged],
                      'purged_origin_ids':purged,'oos_metrics':metrics(closed,spec),
                      'fixed_policy_no_training_fit':True,'independent':evidence_kind=='INDEPENDENT_ECONOMIC_EXECUTION'})
    neighbors,controls,ablations = [],[],[]
    for parameters in spec['neighbors']:
        ledger=cost_ledger(native_replay(rows_by,spec,parameters=tuple(parameters)),source,cost)
        neighbors.append({'parameters':parameters,'metrics':metrics(ledger['trades'],spec),
                          'terminal':terminal(ledger),'native_audit':ledger['audit'],'ledger_sha256':sha(ledger),
                          'actual_ledger':ledger})
    for name in spec['controls']:
        ledger=cost_ledger(native_replay(rows_by,spec,control=name),source,cost)
        controls.append({'control':name,'metrics':metrics(ledger['trades'],spec),'terminal':terminal(ledger),
                         'ledger_sha256':sha(ledger),'actual_ledger':ledger,
                         'comparison_valid':name!='regime_permutation',
                         'limitation':'NO_NATIVE_REGIME_ENTRY_FILTER: ECONOMIC_CONTROL_DEGENERATE' if name=='regime_permutation' else None})
    for name in spec['ablations']:
        ledger=parent if name=='without_kr3_veto' else cost_ledger(native_replay(rows_by,spec,ablation=name),source,cost)
        ablations.append({'ablation':name,'metrics':metrics(ledger['trades'],spec),'terminal':terminal(ledger),
                          'actual_ledger':ledger,'ledger_sha256':sha(ledger)})
    gross = math.fsum(r['gross_bps'] for r in child['trades'])
    payloads = {
      'base_replay':{'closed':child['trades'],'open':child['open_positions'],'events':child['events'],
        'trace':child['trace'],'reference_opportunities':child['reference_opportunities'],'native_audit':child['audit'],
        'net_expectancy_bps':base['expectancy_bps_per_trade'],'profit_factor':base['PF'],
        'metrics':base,'terminal':terminal(child),'KR1_FULL':parent,'retention':retention(parent,child)},
      'realistic_cost':{'components':[{'origin_id':r['origin_id'],'components':r['cost_components']} for r in child['trades']+child['open_positions']],
        'provenance':cost,'unknown_components':unknown,'metrics':base,'terminal':terminal(child)},
      'cost2x':{'gross_bps':gross,'all_cost_bps':None if unknown else math.fsum(r['cost_bps'] for r in child['trades']),
        'cost2x_net_bps':metrics(child['trades'],spec,cost2=True)['net_bps'],'open_marks':child['open_positions'],
        'terminal':terminal(child),'stress':cost.get('stress')},
      'purged_oos':{'folds':folds,'purged_origin_ids':sorted({v for f in folds for v in f['purged_origin_ids']}),
        'unresolved_intervals':[r['origin_id'] for r in child['trades']+child['open_positions'] if _interval_end(r)==float('inf')],
        'metrics':[f['oos_metrics'] for f in folds],'independence_claim':evidence_kind=='INDEPENDENT_ECONOMIC_EXECUTION'},
      'chronological_split':{'windows':windows,'open_marks':child['open_positions'],'metrics':[w['closed_metrics'] for w in windows]},
      'symbol_decomposition':{'symbols':list(SYMBOLS),'metrics':{s:metrics([r for r in child['trades'] if r['symbol']==s],spec) for s in SYMBOLS}},
      'regime_decomposition':{'label_method_sha256':sha(spec['regime']),'availability_audit':{'causal_only':True,'dev_threshold':spec['regime']['frozen_dev_atr_ratio_median']},
        'metrics':{g:metrics([r for r in child['trades'] if r['regime_id']==g],spec) for g in sorted({r['regime_id'] for r in child['trades']})}},
      'parameter_neighbor_stability':{'frozen_neighbors':spec['neighbors'],'all_results':neighbors,
        'exposure_log':[{'purpose':'FINITE_SENSITIVITY_NOT_SELECTION','parameters':v,'data_sha':identity['data_sha']} for v in spec['neighbors']]},
      'negative_controls':{'frozen_controls':spec['controls'],'all_results':controls,'required_feature_ablations':ablations,
        'exposure_log':[{'purpose':'FINITE_CONTROL_NOT_SELECTION','control':v,'data_sha':identity['data_sha']} for v in spec['controls']]}}
    reports={name:contracts.seal({'report':name,'input_identity':identity,'specification_sha256':sha(spec),
            'evidence_kind':evidence_kind,'payload':payloads[name],'formal_credit':0,'economic_pass':False}) for name in contracts.REPORTS}
    consumer=consume_reports(reports, identity, sha(spec))
    return {'schema':'zel.step7.kr3.execution.bundle.v1','reports':reports,'consumer':consumer,
            'evidence_kind':evidence_kind,'formal_credit':0,'economic_pass':False,
            'model_orders':0,'source_sha256':identity['data_sha'],'specification_sha256':sha(spec)}


def consume_reports(reports,identity,spec_sha):
    if set(reports)!=set(contracts.REPORTS):
        raise ValueError('NINE_ACTUAL_REPORTS_REQUIRED')
    for name,report in reports.items():
        if not contracts.check_seal(report) or report['report']!=name or report['input_identity']!=identity or report['specification_sha256']!=spec_sha:
            raise ValueError('REPORT_BYTES_IDENTITY_MISMATCH:'+name)
        if not contracts.PAYLOAD_FIELDS[name]<=set(report['payload']):
            raise ValueError('REPORT_PAYLOAD_MISSING:'+name)
    base=reports['base_replay']['payload']
    reasons=[]
    if reports['realistic_cost']['payload']['unknown_components']:
        reasons.append('UNKNOWN_COST_OR_AVAILABILITY')
    if base['open']:
        reasons.append('CENSORED_OPEN')
    if not base['closed']:
        reasons.append('NO_COMPLETED_NATIVE_TRADES')
    if any(not r['comparison_valid'] for r in reports['negative_controls']['payload']['all_results']):
        reasons.append('REGIME_CONTROL_HAS_NO_NATIVE_FILTER_TO_PERMUTE')
    return {'produced_reports':list(contracts.REPORTS),'produced_count':len(reports),'byte_binding':'VERIFIED',
            'consumer':'step7_kr3_execution_v1.consume_reports','economic_readiness_blockers':reasons,
            'formal_admission':False,'boundary_created':False,'formal_credit':0,
            'meaning':'FULL_PRODUCER_INTEGRATION_NOT_FORMAL_GATE_PASS'}


def native_source_probe(rows_by_symbol, available_ms, sequence_state=None):
    """Isolated source-owner metadata only: no historical actual model fills."""
    result={'symbols':{},'formal_credit':0,'actual_fills':0,'performance_exposed':False}
    for symbol,source_rows in sorted(rows_by_symbol.items()):
        rows=[r for r in source_rows if r['bar_close_ts']<=available_ms and r.get('available_ts',r['bar_close_ts'])<=available_ms]
        if len(rows)<240:
            result['symbols'][symbol]={'status':'INSUFFICIENT_SEED','rows':len(rows)}
            continue
        start,end=rows[239]['bar_open_ts'],rows[-1]['bar_close_ts']
        if start>=end:
            result['symbols'][symbol]={'status':'INSUFFICIENT_EVALUATION_SUFFIX','rows':len(rows)}
            continue
        bundle=d.build_bundle(rows,d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end)
        clock=reservation.causal_clock(rows,bundle,eval_start_ms=start,eval_end_ms=end)
        _,native_engine=d.old.dsl._features([dict(r,ts=r['bar_open_ts']) for r in rows],d.PARENT_SPEC)
        latest_raw_signal=bool(native_engine.eval(d.PARENT_SPEC['entry_rule'],len(rows)-1))
        middle=reservation.causal_clock(rows,bundle,eval_start_ms=start,eval_end_ms=end,stop_after_index=len(rows)//2)
        restored=reservation.causal_clock(rows,bundle,eval_start_ms=start,eval_end_ms=end,checkpoint=json.loads(json.dumps(middle)))
        if restored!=clock:
            raise ValueError('SOURCE_REFERENCE_RESTART_PARITY')
        result['symbols'][symbol]={'status':'CAUSAL_REFERENCE_PARITY','rows':len(rows),
            'seed_first_open_ms':rows[0]['bar_open_ts'],'completed_cursor_ms':end,
            'raw_signal_count':len(bundle['signals']),'reference_reservations':len(clock['reference_opportunities']),
            'reference_blocks':sum(e['status']=='EXCLUDED' for e in clock['opportunity_events']),
            'latest_completed_signal':latest_raw_signal,
            'latest_signal_next_open_unobserved':latest_raw_signal,
            'latest_signal_semantics':'RAW_NATIVE_COMPLETED_CLOSE_ONLY_NO_FILL_OR_ADMISSION',
            'reference_state_sha256':sha(clock),'restart_parity':True,
            'historical_actual_fills':0,'same_historical_DEV_origin_attested':False}
    state={'symbols':result['symbols'],'state_sha256':sha(result['symbols'])}
    prior=sequence_state or {}
    metadata={'status':'CAUSAL_REFERENCE_ONLY', 'signal_count':sum(v.get('raw_signal_count',0) for v in result['symbols'].values()),
      'new_signal_count':sum(max(0,v.get('raw_signal_count',0)-prior.get('symbols',{}).get(k,{}).get('raw_signal_count',0)) for k,v in result['symbols'].items()),
      'reference_event_count':sum(v.get('reference_reservations',0)+v.get('reference_blocks',0) for v in result['symbols'].values()),
      'decision_cursor':{k:v.get('completed_cursor_ms') for k,v in result['symbols'].items()},
      'seed':{k:{'first_open_ms':v.get('seed_first_open_ms'),'rows':v['rows']} for k,v in result['symbols'].items()},
      'restart_parity':all(v.get('restart_parity',False) for v in result['symbols'].values()),
      'state_sha256':state['state_sha256'],'formal_credit':0,'actual_fills':0,'performance_exposed':False,
      'historical_references_only':True,'historical_actual_fills':0,'symbols':result['symbols']}
    if not metadata['signal_count']: metadata['status']='NO_SIGNAL'
    return {'state':state,'metadata':metadata}


def fixture_spec():
    start=240*BAR; stop=360*BAR; end=390*BAR
    return {'candidate_sha256':'298ae6dfe19bed2503eae374c4540ae13beab0374033aa27842f3701d0c609cc',
       'start_ms':start,'entry_stop_ms':stop,'runoff_end_ms':end,'embargo_ms':4*BAR,
       'windows':[{'name':'W'+str(i+1),'start_ms':start+i*40*BAR,'end_ms':start+(i+1)*40*BAR} for i in range(3)],
       'neighbors':[list(v) for v in NEIGHBORS],'controls':list(CONTROLS),'ablations':list(ABLATIONS),
       'regime':{'name':'EMA50_SLOPE_X_ATR20_RATIO','frozen_dev_atr_ratio_median':0.02},
       'control_semantics':{'direction_flip':'SHORT_SAME_LONG_INFORMATION_CLOCK_AND_EXIT_TIMES_SIGNED_FUNDING',
         'time_shift_placebo':'PLUS_6_NATIVE_BARS_REVALIDATE_DIRECTIONAL_HALF_LATCH_SHIFTED_BAR_NEW_FULL_REFERENCE',
         'delayed_entry':'PLUS_1_NATIVE_BAR_REVALIDATE_DIRECTIONAL_HALF_LATCH_SHIFTED_BAR_NEW_FULL_REFERENCE',
         'regime_permutation':'FIXED_CAUSAL_FOUR_LABEL_ROTATION_NO_ENTRY_REGIME_FILTER_DEGENERATE'},
       'fixture_only':True,'formal_parameters_approved':False}


def fixture_input():
    source={}
    for si,symbol in enumerate(SYMBOLS):
        rows=[]
        for i in range(390):
            close=round(100+si*11+i*.08+2*math.sin(i*.43+si*.11),10)
            opened=round(close-.2*math.cos(i*.43+si*.11),10)
            rows.append({'bar_open_ts':i*BAR,'bar_close_ts':(i+1)*BAR,'open':opened,
              'high':max(opened,close)+.25,'low':min(opened,close)-.45,'close':close,'volume':1000.,
              'available_ts':(i+1)*BAR})
        quotes=[{'ts':r['bar_open_ts'],'event_ts':r['bar_open_ts'],'available_ts':r['bar_open_ts'],
                 'bid':r['open']*.9999,'ask':r['open']*1.0001,'impact_bps':.25} for r in rows]
        quotes.append({'ts':390*BAR,'event_ts':390*BAR,'available_ts':390*BAR,
                       'bid':rows[-1]['close']*.9999,'ask':rows[-1]['close']*1.0001,'impact_bps':.25})
        source[symbol]={'bars':rows,'quotes':quotes,'funding':[{'ts':i*2*BAR,'rate':-.00001 if i%2 else .00002} for i in range(196)]}
    return {'source':source,'specification':fixture_spec(),'cost':{'fee_bps_each_side':2.,
             'funding_interval_ms':2*BAR,'stress':'DOUBLE_ALL_SIGNED_COST_COMPONENTS',
             'max_quote_age_ms':0,'price_basis':'MIDPOINT_RETURN_RECONCILIATION','provenance':'EMBEDDED_SYNTHETIC_ONLY','formal_approved':False}}


def execute_sealed_bytes(data):
    """Invoked only by authorized_io.dispatch after durable reservation and IO."""
    obj=json.loads(data)
    if obj.get('specification',{}).get('fixture_only') is not False or obj.get('specification',{}).get('formal_parameters_approved') is not True:
        raise ValueError('FORMAL_SPECIFICATION_NOT_APPROVED')
    return produce_reports(obj['source'],obj['specification'],obj['cost'],evidence_kind='INDEPENDENT_ECONOMIC_EXECUTION')


def main():
    parser=argparse.ArgumentParser()
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--fixture',action='store_true')
    modes.add_argument('--request',type=Path)
    parser.add_argument('--out-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.fixture:
        data=fixture_input()
        output=produce_reports(data['source'],data['specification'],data['cost'],evidence_kind='SYNTHETIC_INTEGRATION_ONLY')
    else:
        from backend.research.rebuild.step7_authorized_io_v1 import dispatch
        output=dispatch(json.loads(args.request.read_text()),execute_sealed_bytes)
    args.out_dir.mkdir(parents=True,exist_ok=True)
    payload=canonical(output)
    target=args.out_dir/'BUNDLE.json'
    if target.exists() and target.read_bytes()!=payload:
        raise ValueError('IMMUTABLE_OUTPUT_ALREADY_EXISTS')
    target.write_bytes(payload)
    result=output.get('output',output)
    for name,report in result['reports'].items():
        (args.out_dir/(name+'.json')).write_bytes(canonical(report))
    print(json.dumps({'command_mode':'fixture' if args.fixture else 'authorized_sealed',
        'bundle_sha256':hashlib.sha256(payload).hexdigest(),'consumer':result['consumer'],
        'evidence_kind':result['evidence_kind'],'formal_credit':0},sort_keys=True))

if __name__=='__main__':
    main()
