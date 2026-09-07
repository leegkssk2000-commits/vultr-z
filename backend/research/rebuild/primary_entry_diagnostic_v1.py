"""Feature-only TPC1 diagnostic. Stored outcomes are labels, never policy input.

No evaluator/path/replay is called. n.prepare regenerates exact native raw intents
with admission=False, so its owner computes no economic path. Diagnostic labels
read completed held-bar CLOSE only, strictly before the stored exit bar.
"""
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from backend.research.rebuild import top5_native_finite_runner_v1 as n
from backend.research.rebuild import top5_mechanism_b_v1 as b

ROOT = Path(__file__).resolve().parents[3]
PRIOR = 'research/development_evidence/TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1'
OUT = 'research/development_evidence/TOP5_AFTER_PR1206_WINRATE_FIRST_AI_V1/PRIMARY_DIAG'
NATIVE = 'research/development_evidence/TOP5_DEV_REPAIR_20260905_V1/native_1h'
EXPECTED = {
    NATIVE+'/BTC-USDT.json.gz': '2d24bcbaaaf63157f435970df17e0483eee84c92484cae49544bc862d2a15992',
    NATIVE+'/ETH-USDT.json.gz': '0acc743b8eb184c4e83ef95d1bec0d9e79805eacf6e4d68ee7af62e3b5da27af',
    NATIVE+'/manifest.json': '013668b5c5315f4521c4f150d9d3837fb16c14f4a6081a05fc283dd1e9b6b951',
    PRIOR+'/TPC1/DEV2025.json.gz': '360fdcc4ce3e3dae09010f0d1c57df46ee5e3fbb860e00afa8d0f9724cc5148a',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close_progress(rows, trade, cost_binding):
    """Never access exit-bar fields or full-trade MFE. Cost available at each close."""
    sign = 1 if trade['side'] == 'long' else -1
    entry = trade['entry_price']
    observations = []
    for j in range(trade['entry_index'], trade['exit_index']):
        row = rows[j]
        gross = sign * (row['close'] - entry) / entry * 10000
        cost = n.a.old.probe.cost_components(trade['entry_ts'], row['bar_close_ts'], cost_binding)
        observations.append((j, gross, max(20., cost['cost_bps'])))
    if not observations:
        category = 'NO_COMPLETED_PRE_EXIT_BAR_UNKNOWN_INTRABAR'
    elif max(x[1] for x in observations) <= 0:
        category = 'NO_POSITIVE_COMPLETED_CLOSE'
    elif not any(x[1] > x[2] for x in observations):
        category = 'POSITIVE_CLOSE_NEVER_ABOVE_MODELED_COST'
    else:
        category = 'ABOVE_COST_COMPLETED_CLOSE'
    first_above = next((j for j, gross, cost in observations if gross > cost), None)
    return {
        'category': category,
        'completed_pre_exit_bars': len(observations),
        'first_close_gross_bps': observations[0][1] if observations else None,
        'max_pre_exit_close_gross_bps': max((x[1] for x in observations), default=None),
        'first_above_cost_completed_index': first_above,
        'above_cost_then_adverse_close': first_above is not None and any(j > first_above and gross <= 0 for j, gross, _ in observations),
        'late_recovery': trade['net_bps'] > 0 and bool(observations) and observations[0][1] <= 0 and first_above is not None,
    }


def state_at(rows, cache, event, episode_start, previous_trade=None):
    """All fields available no later than signal close; no current outcome input."""
    i = event['signal_index']; sign = 1 if event['side'] == 'long' else -1
    row = rows[i]; prev = rows[i-1]; line, direction = cache.st[i]
    if previous_trade is not None and previous_trade['exit_ts'] > event['signal_ts']:
        raise RuntimeError('PRIOR_OUTCOME_NOT_YET_AVAILABLE')
    body = sign*(row['close']-row['open'])
    change = sign*(row['close']-prev['close'])
    prior_same = previous_trade is not None and previous_trade['side'] == event['side'] and previous_trade['signal_index'] >= episode_start
    return {
        'available_at': event['signal_ts'],
        'signed_signal_body': body,
        'signal_body_state': 'ADVERSE' if body < 0 else 'ALIGNED_OR_FLAT',
        'signed_signal_close_change': change,
        'signal_close_change_state': 'ADVERSE' if change < 0 else 'ALIGNED_OR_FLAT',
        'native_direction': direction,
        'native_maintained': n.maintained(rows, cache, i, event['side']),
        'signed_ema_distance_atr': sign*(row['close']-cache.ema[i])/cache.atr[i],
        'signed_ema_slope_atr': sign*(cache.ema[i]-cache.ema[i-1])/cache.atr[i],
        'native_st_distance_atr': abs(row['close']-line)/cache.atr[i],
        'signal_location_in_range': (row['close']-row['low'])/(row['high']-row['low']) if row['high']>row['low'] else None,
        'previous_candle_aligned': sign*(prev['close']-prev['open']) >= 0,
        'st_episode_start_index': episode_start,
        'st_episode_age_bars': i-episode_start,
        'prior_attempt_state': ('REATTEMPT_AFTER_SL' if previous_trade['exit_reason']=='SL' else 'REATTEMPT_AFTER_OTHER') if prior_same else 'FIRST_ACTUAL_ATTEMPT_IN_EPISODE',
        'previous_completed_origin': previous_trade['origin_key'] if previous_trade else None,
    }


def summarize(records):
    counts = Counter()
    for r in records:
        counts['T'] += 1
        counts[r['outcome']] += 1
        counts['SL'] += r['exit_reason'] == 'SL'
        counts['late_recovery'] += r['close_progress']['late_recovery']
    return dict(counts)


def run():
    out = ROOT/OUT
    freeze = json.loads((out/'DIAGNOSTIC_FREEZE.json').read_text())
    if not freeze['diagnostic_definitions']['no_sweeps']:
        raise RuntimeError('DIAGNOSTIC_FREEZE_REQUIRED')
    inputs = {p: sha(ROOT/p) for p in EXPECTED}
    if inputs != EXPECTED:
        raise RuntimeError('USER_INPUT_SHA_MISMATCH')
    spec = json.loads((ROOT/PRIOR/'SPEC.json').read_text())
    doc = json.loads(gzip.decompress((ROOT/PRIOR/'TPC1/DEV2025.json.gz').read_bytes()))
    # Costs are the identical approved source binding; native bytes already verified above.
    costdoc = n.a.old.read(n.a.old.probe.STAGE)
    dev = b.a.account.source.inputs.require_development(costdoc, ROOT)
    if dev['receipt_sha256'] != spec['cost_sha256']:
        raise RuntimeError('COST_BINDING_SHA_MISMATCH')
    costs = {s: dev['cost_by_symbol'][s] for s in spec['symbols']}
    full = doc['views']['FULL']; trades = full['trades']
    positives = sorted([t for t in trades if t['net_bps'] > 0], key=lambda t: (-t['net_bps'],t['origin_key']))
    large = {t['origin_key'] for t in positives[:math.ceil(len(positives)*.1)]}
    records = []; unknowns = []; parity = {}; bundles = {}
    for symbol in spec['symbols']:
        raw = json.loads(gzip.decompress((ROOT/NATIVE/(symbol+'.json.gz')).read_bytes()))
        rows = [dict(r,bar_open_ts=r['ts_ms'],bar_close_ts=r['ts_ms']+n.HOUR) for r in raw]
        cache, tape, cfg = n.prepare(rows,symbol,'TPR1',*spec['calendar'],spec['native_policy_sha256']['TPR1'])
        stored = [e for e in full['events'] if e['symbol']==symbol]
        if [{k:e[k] for k in n.FIELDS} for e in stored] != [{k:e[k] for k in n.FIELDS} for e in tape]:
            raise RuntimeError('RAW_SIGNAL_DRIFT:'+symbol)
        parity[symbol] = {'raw_intents':len(tape),'stored_raw_tape_parity':'PASS','config_sha':cfg.sha}
        episodes = []; beginning = 0
        for j, (_,direction) in enumerate(cache.st):
            if j and cache.st[j-1][1] != direction: beginning = j
            episodes.append(beginning)
        tt = {t['signal_index']:t for t in trades if t['symbol']==symbol}
        closed = sorted(tt.values(),key=lambda t:t['exit_ts']); cursor = 0; previous = None
        for event in stored:
            while cursor < len(closed) and closed[cursor]['exit_ts'] <= event['signal_ts']:
                previous = closed[cursor]; cursor += 1
            f = state_at(rows,cache,event,episodes[event['signal_index']],previous)
            t = tt.get(event['signal_index'])
            if t is None:
                unknowns.append({'symbol':symbol,'signal_index':event['signal_index'],'signal_ts':event['signal_ts'],'status':event['status'],'outcome':'UNKNOWN','entry_features':f})
                continue
            outcome = ('LARGE_WINNER' if t['origin_key'] in large else 'ORDINARY_WINNER') if t['net_bps']>0 else ('LOSS' if t['net_bps']<0 else 'BREAKEVEN')
            records.append({'symbol':symbol,'origin_key':t['origin_key'],'signal_index':t['signal_index'],'entry_index':t['entry_index'],'exit_index':t['exit_index'],'signal_ts':t['signal_ts'],'side':t['side'],'outcome':outcome,'exit_reason':t['exit_reason'],'entry_features':f,'close_progress':close_progress(rows,t,costs[symbol])})
        bundles[symbol] = (rows,cache,tape,cfg)
        print('FEATURE_ONLY_COMPLETE',symbol,len(tt),len(tape),flush=True)
    sl = [r for r in records if r['exit_reason']=='SL']
    crosses = {}
    for feature in ('signal_body_state','signal_close_change_state','prior_attempt_state','native_maintained'):
        groups = defaultdict(list)
        for r in records: groups[str(r['entry_features'][feature])].append(r)
        crosses[feature] = {k:summarize(v) for k,v in groups.items()}
    path_groups = defaultdict(list)
    for r in records: path_groups[r['close_progress']['category']].append(r)
    cases = {}
    for outcome in ('LOSS','ORDINARY_WINNER','LARGE_WINNER'):
        candidates = [r for r in records if r['outcome']==outcome and r['entry_features']['signal_body_state']=='ADVERSE']
        cases[outcome] = candidates[:3]
    stored_comparison = {k: {m:v[m] for m in ('closed_T','win_rate','closed_net_bps','closed_cost2x_net_bps')} for k,v in doc['values'].items() if k in ('P','TPR1_FULL','TPP1_FULL','FULL')}
    summary = {
        'scope_key':freeze['scope_key'],'status':'FEATURE_DIAGNOSTIC_COMPLETE','input_sha256':inputs,
        'diagnostic_freeze_sha256':sha(out/'DIAGNOSTIC_FREEZE.json'),'native_policy_sha256':spec['native_policy_sha256']['TPR1'],'cost_binding_sha256':spec['cost_sha256'],
        'calendar_ms':spec['calendar'],'population':'TPC1 FULL Primary BTC/ETH native1h reused DEV; no independent OOS',
        'already_audited_facts_reused':{'completed':406,'net_winners':110,'net_losses':296,'initial_SL':288,'other_price_loss':6,'cost_sign_flip':2,'gross_positive':112},
        'exact_native_intent_parity':parity,'stored_comparisons_only':stored_comparison,
        'SL_completed_close_categories':dict(Counter(r['close_progress']['category'] for r in sl)),
        'all_outcome_close_categories':{k:summarize(v) for k,v in path_groups.items()},
        'entry_state_counterparts':crosses,'blocked_raw_signals_outcome_UNKNOWN':len(unknowns),
        'all_raw_signal_body_states':dict(Counter(r['entry_features']['signal_body_state'] for r in records+unknowns)),
        'late_recovery_winners':summarize([r for r in records if r['close_progress']['late_recovery']]),
        'counterexamples_adverse_signal_candle':cases,
        'interpretation_limits':['No completed-close gain does not prove no intrabar favorable move; stopped-bar HLC and final MFE excluded.','Same-bar SL paths have no completed held close and are UNKNOWN intrabar, not immediate-adverse proof.','Post-entry paths/outcomes label diagnosis only; no SL expansion or new time cutoff follows.','Parent exclusion outcomes stay UNKNOWN. Entry-state proportions do not estimate unexecuted raw-signal win rate.'],
        'Broad_lane':{'status':'COMMON_PATH_DIAGNOSTIC_REUSED','separate_new_path_runs':0,'claim':'Shared native SL mechanism only; no Primary win-rate pooling into Broad'},
        'economic_replays':0,'candidate_economic_executions':0,'paid_AI_calls':0,'parameter_sweeps':0,
        'candidate_hypothesis':'Adverse signal-candle veto at signed(signal close-open)<0; hypothesis frozen before scan, recommendation subject to semantic failure review and winner counterexamples; root selects.'
    }
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    (out/'FEATURE_ROWS.json.gz').write_bytes(gzip.compress(json.dumps({'completed':records,'blocked_unknown':unknowns},sort_keys=True,separators=(',',':')).encode(),mtime=0))
    return summary


if __name__ == '__main__':
    print(json.dumps(run(),indent=2,sort_keys=True))
