"""TPC1: the frozen TPR1 extension plus the frozen TPP1 completed-bar protection.

Single-feature ablations delegate to the unchanged parents, including trace and
checkpoint byte contracts. Only the both-on mode runs the combined state machine.
Replay reuses native actual occupancy/cooldown. Cost charging stays with its
existing owner and must use each returned actual exit/mark timestamp.
"""
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import top5_native_finite_runner_v1 as n
from backend.research.rebuild import trend_primary_protection_v1 as p
from backend.research.rebuild import top5_mechanism_a_v1 as a

HOUR=n.HOUR
RULE=(
    'TPC1 G5_DEV_NO_CREDIT; comparison parent TPR1_FULL, with P and TPP1 preserved. '
    'Exact native Primary BTC/ETH native1h entry, initial SL, existing TP, risk/exposure, '
    'actual slot and exit-bar-open plus native cooldown. Native H48 inclusive49; '
    'at native_exit-1 only a surviving position with signed close profit and exact '
    'top5_native_finite_runner_v1.maintained permits one additional H48, maximum inclusive97. '
    'During extension, failed native maintained at completed close schedules the next observed open. '
    'Add exact TPP1 protection: after surviving exits/cap, completed close j activates or '
    'raises long (lowers short) line only with matching native direction, close strictly '
    'beyond line, and signed line gain strictly beyond max(20, frozen full roundtrip '
    'fee+spread+impact plus modeled accrued absolute funding through j). Preserve the '
    'TPP1 price-space strict comparison; frozen ex-ante DEV costs are not historical '
    'quotes/signed settlement evidence. Effective j+1 only; monotonic level persists '
    'and updates through extension without resetting entry/cost/funding state. '
    'Priority: prior completed-bar pending next-open exit; active protection gap at '
    'actual open; native SL; existing TP; active protection touch; current cap close; '
    'survivor completed-bar extension/trend-loss/protection updates. Pending plus '
    'protection gap produces one fill and one cost charge; pending keeps original '
    'TPR1 stop-gap reason. Protection exit before extension decision ends the position. '
    'Unknown same-bar high/low order is unresolved; native conservative priority remains. '
    'No same-bar new-line touch, stopped-bar HLC state update, future funding, final '
    'MFE, final outcome, new entry filter, SL widening, TP cap or partial sizing. '
    'Strict-end censor/checkpoint/prefix semantics preserved; actual changed exit/mark '
    'timestamps determine all costs and unfinished accounting, never copied H48 costs. '
    'FIXED uses explicitly supplied reference origins; FULL native actual ownership. '
    'No formal G6/G9 approval, independent OOS claim or execution authority.'
)
PRIORITY='PENDING_NEXT_OPEN; ACTIVE_PROTECTION_GAP_OPEN; NATIVE_SL; NATIVE_TP; PROTECTION_TOUCH; CURRENT_CAP_CLOSE; COMPLETED_BAR_UPDATE'


def _validate_flags(extension_enabled,protection_enabled):
    if type(extension_enabled) is not bool or type(protection_enabled) is not bool:
        raise RuntimeError('TPC1_ENABLED_BOOL')


def path(rows,event,cache,*,cost_binding,extension_enabled=True,protection_enabled=True,checkpoint=None):
    """Return (closed, censored, trace, checkpoint), with exact parent ablations."""
    _validate_flags(extension_enabled,protection_enabled)
    if not protection_enabled:
        return n.path(rows,event,cache,enabled=extension_enabled,checkpoint=checkpoint)
    if not extension_enabled:
        return p.path(rows,event,cache,cost_binding=cost_binding,enabled=True,checkpoint=checkpoint)
    i=event['signal_index'];ei=i+1;side=event['side'];sign=1 if side=='long' else -1
    h=event['timeout']['bars'];native_exit=ei+h;entry=float(rows[ei]['open'])
    if h!=48:raise RuntimeError('NATIVE_H48_DRIFT')
    state=deepcopy(checkpoint) if checkpoint else {'cursor':ei-1,'final':native_exit,
        'extension':{'decided':False,'allowed':False},'protection':None,'pending':None,'trace':[]}
    def prefix_hash(cursor):
        return a.old.digest({'event':event,'mode':'TPC1_V1','extension_enabled':extension_enabled,
            'protection_enabled':protection_enabled,'cost_binding':cost_binding,'rows':rows[ei:cursor+1],
            'st':cache.st[max(0,ei-1):cursor+1],'ema':cache.ema[max(0,ei-1):cursor+1]})
    if checkpoint and (checkpoint.get('origin')!=i or checkpoint['cursor']>=len(rows)
                       or checkpoint.get('prefix_hash')!=prefix_hash(checkpoint['cursor'])):
        raise RuntimeError('NATIVE_RESTART_ORIGIN_OR_PREFIX')
    state['origin']=i
    sl,tp=event['sl'],event['tp'];fill=state.get('fill')
    if state.get('boundary_timeout') and state['boundary_timeout'][2]<rows[-1]['bar_close_ts']:
        fill=state.pop('boundary_timeout')
    for j in ([] if fill else range(state['cursor']+1,min(ei+2*h,len(rows)-1)+1)):
        row=rows[j];state['cursor']=j
        # Previous completed-bar order precedes this bar's unavailable HLC.
        # Same observed-open/gap semantics as the frozen native exit overlay.
        if state['pending'] is not None:
            reason='PENDING_EXIT_GAP_THROUGH_STOP' if sl is not None and sign*(row['open']-sl)<=0 else 'NATIVE_RUNNER_NEXT_OPEN'
            fill=(j,float(row['open']),row['bar_open_ts'],reason,True);state['pending']=None;break
        # The previous completed bar's level applies before this bar's HLC.
        active=state['protection']
        if active is not None and sign*(row['open']-active)<=0:
            fill=(j,float(row['open']),row['bar_open_ts'],'PROTECTION_GAP_OPEN',True);break
        if sl is not None and ((side=='long' and row['low']<=sl) or (side=='short' and row['high']>=sl)):
            fill=(j,float(sl),row['bar_close_ts'],'SL',False);break
        if tp is not None and ((side=='long' and row['high']>=tp) or (side=='short' and row['low']<=tp)):
            fill=(j,float(tp),row['bar_close_ts'],'TP',False);break
        if active is not None and ((side=='long' and row['low']<=active) or (side=='short' and row['high']>=active)):
            fill=(j,float(active),row['bar_close_ts'],'PROTECTION_TOUCH',False);break
        if j==state['final']:
            candidate=(j,float(row['close']),row['bar_close_ts'],'TIMEOUT',False)
            if j==len(rows)-1:state['boundary_timeout']=list(candidate)
            else:fill=candidate
            break
        if j==native_exit-1:
            trend=n.maintained(rows,cache,j,side)
            allowed=sign*(row['close']-entry)>0 and trend
            line,direction=cache.st[j]
            state['extension']={'decided':True,'allowed':allowed,'index':j,'ts':row['bar_close_ts'],
                'close':row['close'],'entry_price':entry,'direction':direction,'line':line,
                'ema50':cache.ema[j],'previous_ema50':cache.ema[j-1]}
            state['trace'].append({'kind':'NATIVE_RUNNER_DECISION',**state['extension']})
            if allowed:state['final']=native_exit+h
        if state['extension']['allowed'] and j>=native_exit and not n.maintained(rows,cache,j,side):
            state['pending']={'index':j,'signal_ts':row['bar_close_ts']}
            state['trace'].append({'kind':'NATIVE_RUNNER_TREND_LOSS_CLOSE',**state['pending']})
        line,direction=cache.st[j]
        # Frozen research cost scenario: no future settlement count/rate.
        cost=a.old.probe.cost_components(rows[ei]['bar_open_ts'],row['bar_close_ts'],cost_binding)
        hurdle=max(20.,cost['cost_bps'])
        qualified=(direction==sign and sign*(row['close']-line)>0 and sign*(line-(entry*(1+sign*hurdle/10000)))>0)
        if qualified:
            new=float(line) if active is None else (max(active,line) if sign>0 else min(active,line))
            if active is None or new!=active:
                state['protection']=new
                state['trace'].append({'kind':'PROTECTION_ACTIVATE' if active is None else 'PROTECTION_UPDATE',
                    'index':j,'available_at':row['bar_close_ts'],'effective_from_index':j+1,
                    'level':new,'native_line':line,'cost_hurdle_bps':hurdle,
                    'cost_available_at':row['bar_close_ts'],'funding_boundaries_observed':cost['funding_settlements_crossed']})
    state['fill']=list(fill) if fill else None
    state['prefix_hash']=prefix_hash(state['cursor'])
    end=rows[-1]['bar_close_ts']
    j,price,stamp,reason,at_open=fill if fill else (len(rows)-1,float(rows[-1]['close']),end,None,False)
    held=rows[ei:j] if at_open else rows[ei:j+1]
    hi=max([price]+[r['high'] for r in held]);lo=min([price]+[r['low'] for r in held])
    gross=sign*(price-entry)/entry*10000
    raw={'signal_index':i,'signal_ts':event['signal_ts'],'entry_index':ei,
         'entry_ts':rows[ei]['bar_open_ts'],'entry_price':entry,'side':side,
         'hold_ms':stamp-rows[ei]['bar_open_ts'],'mfe_bps':max(0.,(hi/entry-1)*10000 if sign>0 else (1-lo/entry)*10000),
         'mae_bps':min(0.,(lo/entry-1)*10000 if sign>0 else (1-hi/entry)*10000),
         'native_risk_preserved':True,'native_interval_ms':HOUR,
         'native_sl':sl,'native_tp':tp,'native_timeout_bars':h,
         'native_intent_risk_size':deepcopy(event['risk_size']),
         'native_intent_exposure':deepcopy(event['exposure']),
         'runner_extension':deepcopy(state['extension']),'protection_level':state['protection'],
         'excursion_semantics':'HELD_COMPLETE_BARS_PLUS_EXIT_OPEN_ONLY' if at_open else 'FULL_EXIT_BAR_BOUND_INCLUDES_UNKNOWN_POST_STOP_PATH; DIAGNOSTIC_ONLY'}
    trace=deepcopy(state['trace'])
    if fill and stamp<end:
        raw.update(exit_index=j,exit_ts=stamp,exit_price=price,gross_bps=gross,exit_reason=reason,
            native_exit_bar_open_ts=rows[j]['bar_open_ts'],
            exit_timestamp_semantics='EXACT_NEXT_BAR_OPEN_MODELLED' if at_open else 'CLOSED_EXIT_BAR_UPPER_BOUND; NATIVE_INTRABAR_FILL_TIME_UNKNOWN')
        trace.append({'kind':reason,'index':j,'ts':stamp,'price':price})
        return raw,None,trace,state
    # Preserve strict-end closed exclusion, but never erase boundary SL/TP loss.
    # Known boundary native fill is a censored completion-time observation at
    # its original proxy fill price, not a claim of a still-live position.
    raw.update(mark_index=j,mark_ts=end,mark_price=price,gross_mark_bps=gross,
        status='CENSORED',terminal_liquidation=False,
        censor_reason='NATIVE_EXIT_TIMESTAMP_UPPER_BOUND_AT_END' if fill else 'NATIVE_HOLD_UNFINISHED',
        boundary_native_fill_reason=reason if fill else None,
        pending_exit_signal_ts=state['pending']['signal_ts'] if state['pending'] else None,
        native_planned_exit_index=state['final'],restart_checkpoint=state)
    trace.append({'kind':'TERMINAL_CENSORED_OBSERVATION','ts':end,'price':price,'reason':raw['censor_reason']})
    return None,raw,trace,state


def replay(rows,tape,cache,cost_binding,*,extension_enabled=True,protection_enabled=True,fixed_indices=None):
    """Reuse native serial ownership; FIXED is an independent origin diagnostic.

    The temporary native path binding follows the frozen TPP1 adapter. Callers
    must serialize replay (the authorized root runner is the single owner).
    """
    _validate_flags(extension_enabled,protection_enabled)
    if not protection_enabled:
        return n.replay(rows,tape,cache,enabled=extension_enabled,fixed_indices=fixed_indices)
    if not extension_enabled:
        return p.replay(rows,tape,cache,cost_binding,fixed_indices=fixed_indices)
    def combined_path(rows,event,cache,*,enabled=True,checkpoint=None):
        if enabled is not True:raise RuntimeError('TPC1_COMBINED_REPLAY_MODE')
        return path(rows,event,cache,cost_binding=cost_binding,checkpoint=checkpoint)
    with patch.object(n,'path',combined_path):
        out=n.replay(rows,tape,cache,enabled=True,fixed_indices=fixed_indices)
    out['audit'].update(trailing_implemented=True,
        protection_activated_T=sum(t['kind']=='PROTECTION_ACTIVATE' for t in out['trace']),
        priority_scope=PRIORITY,combined_rule='TPC1',same_bar_high_low_order='UNKNOWN')
    return out
