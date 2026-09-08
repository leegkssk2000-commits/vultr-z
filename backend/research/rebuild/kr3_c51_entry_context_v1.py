"""C51 entry eligibility A/B/AB; frozen C51 path and reference clock unchanged.

Research only. Features use completed bars; no I/O or outcome-selected gates.
A: direction/strength immediately BEFORE the contiguous EMA20 pullback.
B: recovery-close extension at most one PREVIOUS-bar ATR14 above EMA20.
"""
from copy import deepcopy
from functools import partial
from unittest.mock import patch
import math
from backend.research.rebuild import kr3_profit_zone_exit_v1 as parent
from backend.research.rebuild import top5_external_features_v1 as f
BAR=parent.BAR
MODES=('A','B','AB')
RULES={m:'KR3_C51_ENTRY_CONTEXT_'+m+'_V1' for m in MODES}
CONSTANTS={'dmi_length':14,'adx_min':25.,'atr_length':14,'max_extension_atr':1.}


def observations(rows,bundle):
    """All signals retained. Prior trend checkpoint is not a hindsight peak."""
    dmi=f.directional_movement(rows,14)
    # Conventional Wilder ATR: row0 has no previous close; seed TR1..TR14.
    atr=[None]+f.rma(f.kernel.true_ranges(rows)[1:],14)
    e20,e50=bundle['ema20'],bundle['ema50']
    signals={s['signal_index'] for s in bundle['signals']}
    last_above=None;out={}
    for i,row in enumerate(rows):
        if i in signals:
            q=last_above
            pullback=i>0 and rows[i-1]['close']<=e20[i-1] and q is not None and q<i-1
            available=pullback and q>0 and dmi['adx'][q] is not None and dmi['adx'][q-1] is not None
            a=bool(available and e20[q]>e50[q] and dmi['plus_di'][q]>dmi['minus_di'][q]
                   and dmi['adx'][q]>=CONSTANTS['adx_min'] and dmi['adx'][q]>dmi['adx'][q-1])
            prior_atr=atr[i-1] if i>0 else None
            distance=float(row['close'])-e20[i]
            ext=distance/prior_atr if prior_atr is not None and prior_atr>0 else None
            b=ext is not None and 0.<ext<=CONSTANTS['max_extension_atr']
            out[i]={'signal_index':i,'available_at':row['bar_close_ts'],'A':a,'B':bool(b),
                    'trend_index':q if pullback else None,
                    'trend_available_at':rows[q]['bar_close_ts'] if pullback else None,
                    'pullback_bars':i-q-1 if pullback else None,
                    'adx':dmi['adx'][q] if available else None,'adx_previous':dmi['adx'][q-1] if available else None,
                    'plus_di':dmi['plus_di'][q] if available else None,'minus_di':dmi['minus_di'][q] if available else None,
                    'atr_previous':prior_atr,'extension_atr':ext,
                    'atr_available_at':rows[i-1]['bar_close_ts'] if i else None}
        if row['close']>e20[i]:last_above=i
    return out


def allowed(obs,mode):
    if mode not in MODES:raise ValueError('ENTRY_CONTEXT_MODE')
    return (mode=='A' and obs['A']) or (mode=='B' and obs['B']) or (mode=='AB' and obs['A'] and obs['B'])


def replay(rows,bundle,*,eval_start_ms,eval_end_ms,cost_model,mode='AB',enabled=True,reference_checkpoint=None):
    if type(enabled) is not bool:raise ValueError('ENTRY_CONTEXT_BOOL')
    if not enabled:
        return parent.replay(rows,bundle,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,
                             cost_model=cost_model,reference_checkpoint=reference_checkpoint)
    if mode not in MODES:raise ValueError('ENTRY_CONTEXT_MODE')
    kr=parent.parent.kr;d=kr.d
    # Exact original reference state, independent of feature veto and real exits.
    clock=kr.parent.causal_clock(rows,bundle,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,checkpoint=reference_checkpoint)
    obs=observations(rows,bundle);selected=set(clock['admitted_signal_indices'])
    parent.decision_cost(eval_start_ms,eval_start_ms,cost_model)
    with patch.object(d,'_path',partial(parent.path,cost_model=deepcopy(cost_model))):
        result=d.replay(rows,bundle,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,fixed_signal_indices=[])
        decisions={};last_exit=-1;tail=False
        for signal in bundle['signals']:
            i=signal['signal_index']
            if i not in selected:continue
            if not allowed(obs[i],mode):
                decisions[i]=dict(signal,admission=False,status='EXCLUDED',exclusion_reason='ENTRY_CONTEXT_'+mode+'_VETO')
                continue
            if tail or signal['signal_ts']<=last_exit:
                decisions[i]=dict(signal,admission=False,status='EXCLUDED',exclusion_reason='RUNNER_OCCUPIED')
                continue
            one=d.replay(rows,bundle,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,fixed_signal_indices=[i])
            for key in ('trades','open_positions','trace'):result[key].extend(one[key])
            decisions.update({e['signal_index']:e for e in one['events']})
            if one['trades']:last_exit=one['trades'][0]['exit_ts']
            tail=bool(one['open_positions'])
    result['events']=deepcopy(clock['opportunity_events'])
    for event in result['events']:
        i=event['signal_index']
        if i in decisions:event.update(decisions[i])
        event['entry_context']=obs[i]
    excluded=sum(e['status']=='EXCLUDED' for e in result['events'])
    if len(result['trades'])+len(result['open_positions'])+excluded!=len(result['events']):raise RuntimeError('ENTRY_CONTEXT_EVENT_COVERAGE')
    result.update(reference_events=deepcopy(clock['reference_events']),reference_opportunities=deepcopy(clock['reference_opportunities']),reference_checkpoint=clock)
    result['audit'].update(rule=RULES[mode],comparison_type='ENTRY_ELIGIBILITY_ONLY',comparison_mode='FULL_ACTUAL_SLOT_AND_D_REFERENCE',
        raw_signals=len(result['events']),completed=len(result['trades']),open=len(result['open_positions']),excluded=excluded,
        entry_context_veto_T=sum(e['exclusion_reason']=='ENTRY_CONTEXT_'+mode+'_VETO' for e in result['events']),
        original_C51_exit_unchanged=True,original_reference_unchanged=True,
        same_symbol_max_positions=1,reference_released_by_actual_exit=False,execution_authority='NONE')
    return result
