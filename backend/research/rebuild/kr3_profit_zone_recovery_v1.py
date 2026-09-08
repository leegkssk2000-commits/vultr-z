"""One bounded C51 child: one-close recovery check only at a nonpositive mark.
C51 arming, monotone line, original exits and reference reservations are retained.
No I/O, outcome labels, guaranteed fill or initial protective SL.
"""
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import kr3_profit_zone_exit_v1 as parent
RULE_ID='KR3_PROFIT_ZONE_ONCE_LOSS_RECOVERY_V1'
RULE=('Keep C51 arming and ratcheted line, entries, reference reservations and all original exits. '
      'On its first eligible support breach only, if completed-close gross bps minus decision-time '
      'common cost is nonpositive, defer this extra exit until exactly the next completed close. '
      'Recovery to or above the previously known line cancels that intent; otherwise exit at next open. '
      'Original exits may preempt. One grace per position, never reset or lower the line. '
      'Positive-mark breaches exit normally. No future prices/costs or guaranteed fills.')
ORIGINAL_OBSERVATION=parent.guard_observation

def observation(state,**kw):
    pending=state.get('recovery_pending_index');used=state.get('recovery_used',False)
    if type(used) is not bool or (pending is not None and (not used or pending!=state['last_index'])):
        raise ValueError('RECOVERY_INVALID_STATE')
    if pending is not None and kw['index']!=pending+1:
        raise ValueError('RECOVERY_NOT_NEXT_COMPLETED_BAR')
    current,hit=ORIGINAL_OBSERVATION(state,**kw)
    current.setdefault('recovery_used',False)
    current.setdefault('recovery_pending_index',None)
    current.setdefault('recovery_events',[])
    if state['exit_requested']:return current,False
    mark=(float(kw['row']['close'])/kw['entry_price']-1.)*10000.-kw['cost']['cost_bps']
    event=None
    if pending is not None:
        current['recovery_pending_index']=None
        event='CONFIRM_AFTER_ONE_CLOSE' if hit else 'RECOVERED_GRACE_CONSUMED'
    elif hit and not used and mark<=0.:
        current.update(exit_requested=False,recovery_used=True,recovery_pending_index=kw['index'])
        hit=False;event='DEFER_FIRST_NONPOSITIVE_BREACH'
    if event is not None:
        current['recovery_events']=deepcopy(state.get('recovery_events',[]))+[dict(
            kind=event,index=kw['index'],ts=kw['row']['bar_close_ts'],
            prior_line=state['protected_line'],close=float(kw['row']['close']),
            completed_close_net_mark_bps=mark,decision_cost=deepcopy(kw['cost']))]
    return current,hit

def replay(rows,bundle,*,eval_start_ms,eval_end_ms,cost_model=None,
           enabled=True,reference_checkpoint=None,fixed_signal_indices=None):
    if type(enabled) is not bool:raise ValueError('RECOVERY_BOOL_REQUIRED')
    kwargs=dict(eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost_model=cost_model,
                enabled=True,reference_checkpoint=reference_checkpoint,fixed_signal_indices=fixed_signal_indices)
    if not enabled:return parent.replay(rows,bundle,**kwargs)
    with patch.object(parent,'guard_observation',observation):
        out=parent.replay(rows,bundle,**kwargs)
    out['audit'].update(rule=RULE_ID,direct_parent=parent.RULE_ID,
        mutation='ONE_NONPOSITIVE_PROFIT_BREACH_CONFIRMATION',
        recovery_deferrals=sum(t.get('profit_zone_state',{}).get('recovery_used',False)
                              for t in out['trades']+out['open_positions']))
    return out
