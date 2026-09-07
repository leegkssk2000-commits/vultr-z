"""Release only a completed BR1 extension-cap slot for its close's new signal.

Native unextended and early-exit bar reservations remain unchanged. No live
position is displaced, no old cap is reset, and no synthetic capital is opened.
FIXED retains BR1 paths exactly; only FULL's subsequent admission can change.
"""
from copy import deepcopy
from backend.research.rebuild import top5_finite_runner_4h_v1 as br

RULE_ID='BREAK_BR2_COMPLETED_EXTENSION_CAP_RELEASE_DEV_V1'


def release_after_cap(previous, signal):
    return bool(previous and previous.get('runner_extension',{}).get('allowed')
        and previous['exit_index']==previous['signal_index']+12
        and signal['signal_index']==previous['exit_index']
        and signal['signal_ts']==previous['exit_ts']
        and previous.get('exit_reason')!=br.EXIT)


def replay(rows,bundle,*,eval_start_ms,eval_end_ms,enabled=True,fixed_signal_indices=None):
    if type(enabled) is not bool: raise RuntimeError('BR2_BOOL_REQUIRED')
    kw=dict(kind='BR1',eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    if not enabled or fixed_signal_indices is not None:
        return br.replay(rows,bundle,fixed_signal_indices=fixed_signal_indices,**kw)
    # Empty fixed path validates the complete signal tape and features; no
    # market path or old exit is computed to decide an earlier admission.
    out=br.replay(rows,bundle,fixed_signal_indices=[],**kw)
    previous=None;tail_open=False;released=0
    for signal in bundle['signals']:
        i=signal['signal_index'];event=dict(signal,admission=True,status='PENDING',exclusion_reason=None)
        exception=release_after_cap(previous,signal)
        if tail_open or (previous and i<=previous['exit_index'] and not exception):
            event.update(status='EXCLUDED',exclusion_reason='SIGNAL_DURING_OPEN')
            out['events'].append(event);continue
        one=br.replay(rows,bundle,fixed_signal_indices=[i],**kw)
        for key in ('trades','open_positions','events','trace'):out[key].extend(one[key])
        if one['trades']:
            previous=one['trades'][0]
        tail_open=bool(one['open_positions'])
        if exception and (one['trades'] or one['open_positions']):
            released+=1
            out['events'][-1]['admission_transition']='PRIOR_EXTENSION_CAP_FILLED_THEN_NEXT_OPEN'
    out['audit'].update(rule=RULE_ID,comparison_mode='FULL_CHRONOLOGICAL',
        same_symbol_max_positions=1,fixed_origins_independent_diagnostic_positions=False,
        raw_signals=len(bundle['signals']),completed=len(out['trades']),open=len(out['open_positions']),
        excluded=sum(e['status']=='EXCLUDED' for e in out['events']),
        completed_extension_cap_releases_T=released,
        original_signal_exit_bar_ownership_preserved=False,
        ownership_exception='ONLY_ACTUALLY_FILLED_EXTENSION_FINAL_CAP_CLOSE',
        live_position_displacements=0,old_position_hold_cap_resets=0,
        extension_decisions=sum(t['kind']==br.DECISION for t in out['trace']),
        extension_allowed_T=sum(t['kind']==br.DECISION and t['allowed'] for t in out['trace']),
        strict_boundary_timeout_marks=sum(o['censor_reason']=='ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY' for o in out['open_positions']),
        pending_exit_at_end=sum(o['pending_exit_signal_ts'] is not None for o in out['open_positions']))
    assert len(out['events'])==len(bundle['signals'])
    assert len(out['trades'])+len(out['open_positions'])+out['audit']['excluded']==len(out['events'])
    return out
