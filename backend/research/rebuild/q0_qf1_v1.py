"""QF1 admits original Q0 UP confirmations with positive close progress only.

The original preparation generator is called before filtering: a rejected UP
never restarts an attempt. DOWN, stops, gaps and execution remain Q0 A.
"""
from copy import deepcopy
from backend.research.rebuild import break_channel_structure_v1 as q0

RULE_ID = 'Q0_QF1_CONFIRMATION_PROGRESS_DEV_V1'
VETO = 'QF1_CONFIRMATION_NOT_ABOVE_FIRST_BREAKOUT_CLOSE'


def build_bundle(rows, start, end):
    daily = q0.aggregate_daily(rows, split_end_ms=end)['daily']
    return daily, q0.generate_signals(daily, eval_start_ms=start,
        eval_end_ms=end, require_preparation=True)


def admission(signal, daily):
    if signal['direction'] != 'UP':
        return None
    anchor = daily[signal['anchor_daily_index']]
    confirm = daily[signal['daily_index']]
    if (anchor['bar_close_ts'] != signal['anchor_ts']
            or anchor['source_last_index'] != signal['anchor_signal_index']
            or confirm['bar_close_ts'] != signal['signal_ts']
            or confirm['close'] != signal['confirmation_close']
            or anchor['bar_close_ts'] >= confirm['bar_close_ts']):
        raise RuntimeError('QF1_ORIGINAL_CONFIRMATION_LINEAGE')
    a, b = float(anchor['close']), float(confirm['close'])
    return {'first_breakout_close': a, 'confirmation_close': b,
            'feature_available_ts': signal['signal_ts'], 'allowed': b > a,
            'confirmation_advance_bps': (b / a - 1) * 10000}


def replay(rows, daily, bundle, *, eval_start_ms, eval_end_ms,
           enabled=True, fixed_signal_indices=None):
    if type(enabled) is not bool:
        raise RuntimeError('QF1_BOOL_REQUIRED')
    if not enabled:
        if fixed_signal_indices is not None:
            raise RuntimeError('QF1_DISABLED_FIXED_UNSUPPORTED')
        return q0.replay(rows, bundle, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
    wanted = None if fixed_signal_indices is None else set(fixed_signal_indices)
    up = {s['signal_index'] for s in bundle['signals'] if s['direction']=='UP'}
    if wanted is not None and not wanted <= up:
        raise RuntimeError('QF1_FIXED_NOT_ORIGINAL_UP')
    allowed, rejected, observations = [], [], {}
    for signal in bundle['signals']:
        obs = admission(signal, daily)
        if obs is None:
            allowed.append(signal)
            continue
        observations[signal['signal_index']] = obs
        reason = VETO if not obs['allowed'] else (
            'FIXED_VIEW_NOT_ORIGINAL_Q0_ENTRY' if wanted is not None and signal['signal_index'] not in wanted else None)
        if reason:
            rejected.append(dict(signal, admission=False, status='EXCLUDED',
                exclusion_reason=reason, qf1_observation=deepcopy(obs)))
        else:
            allowed.append(signal)
    result = q0.replay(rows, dict(bundle, signals=allowed),
        eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
    for event in result['events']:
        event['qf1_observation'] = deepcopy(observations[event['signal_index']])
    result['events'] = sorted(result['events']+rejected, key=lambda e:e['signal_index'])
    result['audit'].update(rule=RULE_ID, comparison_type='ENTRY_FILTER',
        raw_up_signals=len(up), qf1_rejected_T=sum(e['exclusion_reason']==VETO for e in rejected),
        admitted_up_confirmed=sum(s['direction']=='UP' for s in allowed),
        up_confirmed=len(up), excluded=sum(e['status']=='EXCLUDED' for e in result['events']),
        original_up_denominator_preserved=len(result['events'])==len(up),
        original_generator_unchanged=True, preparation=True, sizing='Q0_A_UNIT',
        comparison_mode='FULL_CHRONOLOGICAL' if wanted is None else 'FIXED_ORIGINAL_Q0_OPPORTUNITIES',
        forced_terminal_liquidations=0, execution_authority='NONE')
    assert len(result['events']) == len(up)
    assert len(result['trades'])+len(result['open_positions'])+sum(e['status']=='EXCLUDED' for e in result['events']) == len(up)
    return result
