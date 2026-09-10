"""Campaign accounting and saved-only verification; no economic dispatcher."""
from collections import Counter
from copy import deepcopy
from math import ceil, fsum, isclose
from pathlib import Path
from unittest.mock import patch
import gzip
import hashlib
import json
from backend.research.rebuild import c63_initial_failure_f_study_v1 as inherited
from backend.research.rebuild import parallel_exit_metrics_v1 as marks
from backend.research.rebuild import c63_c70_trader_management_v1 as tm

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'research/development_evidence'/tm.SCOPE
INPUTS = ROOT/inherited.INPUTS
C63 = ROOT/'research/development_evidence/M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'
C70 = ROOT/'research/development_evidence/C70_PRICE_CONFIRMATION_SUCCESSOR_V1'
PERIODS = ('DEV2025', 'SEEN2026')
p, a, bridge = inherited.p, inherited.a, inherited.a.owner
canon = lambda x: json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
h = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
gz = lambda path: json.loads(gzip.decompress(Path(path).read_bytes()))
read = lambda path: json.loads(Path(path).read_text())
key = lambda t: (t['symbol'], t['signal_index'], t['signal_ts'])


def put(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as target:
        target.write(gzip.compress(canon(obj), mtime=0) if path.suffix=='.gz' else canon(obj)+b'\n')


def parents(per, packet, cal):
    c63 = gz(C63/per/'RESULT.json.gz'); c70 = deepcopy(c63)
    meta = read(C70/'LOCAL_C70_IMPORT.json')['periods'][per]
    wanted = {tuple(x) for x in meta['admitted']}
    for name in ('trades', 'open_observations'):
        c70[name] = [t for t in c70[name] if key(t) in wanted]
    projection = gz(C70/'C70_LOCAL_EVENT_DECISIONS.json.gz')
    c70['events'] = [dict(zip(projection['fields'], row)) for row in projection['periods'][per]['rows']]
    c70['candidate'] = tm.C70_RULE
    c70['metrics'] = p.old.metrics(c70['trades'], c70['open_observations'], cal, packet['rows_by'], packet['costs'])
    snap = a.snapshot(c70)
    for name in ('closed','open','win_rate','average_win_bps','average_loss_bps','realized_payoff','PF',
                 'terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps'):
        assert isclose(snap[name], meta['snapshot'][name], rel_tol=1e-11, abs_tol=1e-7), name
    return {'C63':c63, 'C70_LOCAL':c70}


def unit(raw, leg):
    row = {k: deepcopy(v) for k,v in raw.items() if k not in (
        'tm_legs','exit_index','exit_ts','exit_price','gross_bps','exit_reason',
        'mark_index','mark_ts','mark_price','gross_mark_bps','status')}
    row['hold_ms'] = leg['ts']-row['entry_ts']
    gross = (leg['price']/row['entry_price']-1)*10000
    if leg['status']=='C':
        row.update(exit_index=leg['index'], exit_ts=leg['ts'], exit_price=leg['price'],
                   gross_bps=gross, exit_reason=leg['reason'], exit_timestamp_semantics='OBSERVED_4H_OPEN')
    else:
        row.update(mark_index=leg['index'], mark_ts=leg['ts'], mark_price=leg['price'],
                   gross_mark_bps=gross, status='CENSORED', terminal_liquidation=False)
    return row


def campaign(raw, symbol, label, packet):
    charged = []
    for leg in raw['tm_legs']:
        status = leg['status']; row = unit(raw, leg)
        rr = dict(trades=[row] if status=='C' else [], open_positions=[row] if status=='O' else [],
                  events=[], trace=[], audit={})
        result = p.account.charge_result(rr, symbol, 'source_squeeze_momentum_long', tm.RULES[label],
                                        packet['policy'], packet['costs'], packet['rows_by'][symbol])
        charged.append(dict(status=status, row=result['trades' if status=='C' else 'open_observations'][0],
                            numerator=leg['qty'], denominator=1., qty=leg['qty']))
    assert isclose(fsum(l['qty'] for l in charged), 1., abs_tol=1e-12)
    status = charged[-1]['status']; row = deepcopy(charged[-1]['row'])
    row.pop('trade_sha256', None); row.pop('observation_sha256', None)
    weighted = {field: fsum(bridge._values((l['status'],l['row']))[field]*l['qty'] for l in charged)
                for field in bridge.VALUE_FIELDS}
    row.update(weighted_legs=charged, assembled_qty=1., remaining_qty=raw['remaining_qty'],
               partial_count=raw['partial_count'], runner_activated=raw['runner_activated'],
               evidence_type='SOURCE_GROUNDED_PROFIT_MANAGEMENT_COMPONENT_BENCHMARK',
               original_trader_replication=False, return_semantics='EQUAL_INITIAL_NOTIONAL_WEIGHTED_LEGS',
               hold_ms=raw['hold_ms'])
    if status=='C':
        row.update(weighted)
    else:
        row.update(gross_mark_bps=weighted['gross_bps'],
                   hypothetical_liquidation_net_mark_bps=weighted['net_bps'],
                   hypothetical_liquidation_cost2x_net_mark_bps=weighted['cost2x_net_bps'],
                   hypothetical_liquidation_cost_bps=weighted['cost_bps'],
                   hypothetical_cost_components_bps={k:weighted[k] for k in bridge.COST_FIELDS})
    row['trade_sha256' if status=='C' else 'observation_sha256'] = p.sha(row)
    return status, row


def metrics(result, packet, cal):
    original = marks._boundary
    def boundary(item, ts, prices, costs, start, end):
        legs = item[1].get('weighted_legs')
        if not legs:
            return original(item, ts, prices, costs, start, end)
        values = [(l, original((l['status'], l['row']), ts, prices, costs, start, end)) for l in legs]
        return {k:fsum(l['qty']*v[k] for l,v in values) for k in bridge.VALUE_FIELDS}
    with patch.object(marks, '_boundary', boundary):
        result = p.old.metrics(result['trades'], result['open_observations'], cal, packet['rows_by'], packet['costs'])
    return result


def charge(raw_by, label, packet, cal):
    result = dict(trades=[], open_observations=[], events=[], trace=[], audit={}, candidate=tm.RULES[label],
                  independent=False, formal_credit=0, operating_adoption=False)
    for symbol, raw in sorted(raw_by.items()):
        for value in raw['trades']+raw['open_positions']:
            status,row = campaign(value, symbol, label, packet)
            result['trades' if status=='C' else 'open_observations'].append(row)
        for name in ('events','trace'):
            result[name].extend(dict(x, symbol=symbol) for x in raw[name])
        result['audit'][symbol] = raw['audit']
    result['metrics'] = metrics(result, packet, cal)
    return result


def snapshot(result, parent=None):
    s = a.snapshot(result); items = bridge._index(result['trades'], result['open_observations'])
    values = [bridge._values(v)['net_bps'] for v in items.values()]
    profits = fsum(max(0.,v) for v in values)
    closed = sorted(result['trades'], key=lambda t:(t['exit_ts'], key(t)))
    streak = longest = 0
    for row in closed:
        streak = streak+1 if row['net_bps']<0 else 0; longest=max(longest,streak)
    losses = sorted(t['net_bps'] for t in closed if t['net_bps']<0)
    positions = [t for _,t in items.values()]
    s.update(partial_count=sum(t.get('partial_count',0) for t in positions),
             runner_count=sum(t.get('runner_activated',False) for t in positions),
             runner_sma10_exit_count=sum(t.get('exit_reason')=='RUNNER_SMA10_CLOSE_NEXT_OPEN' for t in positions),
             max_losing_streak=longest,
             loss_tail_worst_bps=min(losses, default=None),
             loss_tail_worst_decile_mean_bps=fsum(losses[:ceil(len(losses)*.1)])/ceil(len(losses)*.1) if losses else None,
             top1_positive_contribution_share=max([0.]+values)/profits if profits else None,
             top1_signed_terminal_share=max([0.]+values)/fsum(values) if fsum(values) else None,
             quantity_exposure_symbol_days=fsum(
                 fsum(l['row']['hold_ms']*l['qty'] for l in t['weighted_legs']) if t.get('weighted_legs') else t['hold_ms']
                 for t in positions)/tm.DAY)
    s['mean_quantity_exposure_positions'] = s['quantity_exposure_symbol_days']/(
        (result['metrics']['daily'][-1]['mark_ts']-result['metrics']['daily'][0]['interval_start_ms'])/tm.DAY)
    if parent is not None:
        old=bridge._index(parent['trades'],parent['open_observations'])
        winners=sorted([k for k,(status,t) in old.items() if status=='C' and t['net_bps']>0],
                       key=lambda k:(-old[k][1]['net_bps'],k))
        cut=ceil(len(winners)*.1)
        for name,cohort in [('ordinary',winners[cut:]),('top_decile',winners[:cut])]:
            den=fsum(old[k][1]['net_bps'] for k in cohort)
            kept=fsum(min(old[k][1]['net_bps'],max(0.,items[k][1]['net_bps']))
                      for k in cohort if k in items and items[k][0]=='C')
            s[name+'_winner_retention']=kept/den if den else None
        s.update(excluded_parent_positions=len(old.keys()-items.keys()),new_positions=len(items.keys()-old.keys()),
                 closed_open_transitions=dict(Counter(old[k][0]+items[k][0] for k in old.keys()&items.keys())),
                 occupancy_exclusion_delta=s['exclusions'].get('ACTUAL_POSITION_OCCUPIED_AT_DECISION',0)-
                 a.snapshot(parent)['exclusions'].get('ACTUAL_POSITION_OCCUPIED_AT_DECISION',0))
    return s


def decomposition(parent, child):
    old = bridge._index(parent['trades'], parent['open_observations'])
    new = bridge._index(child['trades'], child['open_observations'])
    loss_reduction=winner_extension=winner_cut=loss_extension=extra_cost=occupancy=0.
    detail=[]
    for k in sorted(old.keys()|new.keys()):
        pv=bridge._values(old.get(k));cv=bridge._values(new.get(k))
        dg=cv['gross_bps']-pv['gross_bps'];dn=cv['net_bps']-pv['net_bps']
        if k not in old or k not in new:
            occupancy+=dn;group='OCCUPANCY_NEW_OR_EXCLUDED_NET'
        else:
            extra_cost+=cv['cost_bps']-pv['cost_bps']
            if pv['net_bps']<=0:
                if dg>=0:loss_reduction+=dg;group='REDUCED_EXISTING_LOSS'
                else:loss_extension-=dg;group='ADDED_EXISTING_LOSS'
            elif dg>=0:winner_extension+=dg;group='EXTENDED_EXISTING_WIN'
            else:winner_cut-=dg;group='CUT_EXISTING_WIN'
        detail.append(dict(origin=k,group=group,delta_gross_bps=dg,delta_net_bps=dn,
                           delta_cost_bps=cv['cost_bps']-pv['cost_bps']))
    delta=fsum(bridge._values(v)['net_bps'] for v in new.values())-fsum(bridge._values(v)['net_bps'] for v in old.values())
    total=loss_reduction+winner_extension-winner_cut-loss_extension-extra_cost+occupancy
    assert isclose(total,delta,rel_tol=1e-11,abs_tol=1e-7)
    return dict(reduced_existing_loss_gross_bps=loss_reduction,extended_existing_win_gross_bps=winner_extension,
                cut_existing_win_gross_bps=winner_cut,added_existing_loss_gross_bps=loss_extension,
                additional_common_cost_funding_bps=extra_cost,occupancy_new_excluded_net_bps=occupancy,
                terminal_delta_bps=delta,residual_bps=total-delta,identity='PASS',
                note='Common gross components minus common cost delta; absent/new are net. Added losses explicitly included, never hidden.',
                details=detail)


def verify_parent_binding():
    """Evaluate entry observations only; use sealed parent fills, never replay exits."""
    import importlib.util
    import sys
    # Existing independent verifier binds reg71 projection to the original archive.
    path=C70/'verify_saved.py'
    spec=importlib.util.spec_from_file_location('verify_saved',path)
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
    saved=sys.modules.get('verify_saved');sys.modules['verify_saved']=verifier
    try:
        spec2=importlib.util.spec_from_file_location('reg71_corrected',C70/'verify_corrected.py')
        corrected=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(corrected)
        independent=corrected.verify(INPUTS)
    finally:
        if saved is None:sys.modules.pop('verify_saved',None)
        else:sys.modules['verify_saved']=saved
    checked=0;financial={}
    for per in PERIODS:
        packet=gz(INPUTS/(per+'.json.gz'));cal=read(C63/'SPEC.json')['periods'][per]
        ctrl=parents(per,packet,cal);financial[per]={n:a.snapshot(r) for n,r in ctrl.items()}
        raw=gz(C63/per/'RAW.json.gz')
        for symbol,rr in raw.items():
            bars=tm.native.to_bars(packet['rows_by'][symbol],cal['start_ms'],cal['runoff_end_ms'])
            for event in rr['events']:
                current=tm.c63.context(bars,event,tm.c63.er.context)
                assert current==event['er_context'],'EXACT_C63_CONTEXT_DRIFT'
                obs=tm.daily.observation(bars,event['signal_index'])
                actual=tm.c70_context(current,obs)
                expected=verifier.expected_context(packet['rows_by'][symbol],event)
                eligible=bool(expected['original'] and expected['ema'] is not None and (
                    expected['dailygood'] or expected['sma'] is not None and expected['previous_sma'] is not None and
                    bars[event['signal_index']].close>expected['sma'] and expected['sma']>=expected['previous_sma'] and expected['escape']))
                assert actual['eligible']==eligible,'REG71_ENTRY_PREDICATE_DRIFT'
                checked+=1
    return dict(status='PASS',entry_observations_checked=checked,independent_import_verification=independent,
                parent_strategy_replays=0,parent_financial_reconstruction=financial,
                OFF_parity='EXACT_SYNTHETIC_DELEGATION_PLUS_SEALED_ALL_EVENT_AND_FILL_BINDING_NO_HISTORICAL_EXIT_REPLAY')
