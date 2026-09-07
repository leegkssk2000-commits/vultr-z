"""TPP1: completed native line profit protection; exact native entry/SL/H48.

The fee/absolute funding inputs are frozen DEV scenario parameters, not claims
of historical executable quotes or signed settlement observations. At close j
only boundaries through j enter the activation cost; future funding is absent.
Native SL and TP retain precedence over a same-bar intrabar protection touch.
An already active gap order fills at the observed open before unavailable HLC.
"""
from copy import deepcopy
from functools import partial
from unittest.mock import patch
from backend.research.rebuild import top5_native_finite_runner_v1 as n
from backend.research.rebuild import top5_mechanism_a_v1 as a
HOUR=n.HOUR
RULE='Native Primary parent; initial SL/TP/entry/H48 inclusive49/cooldown unchanged. After surviving native exits and before original timeout, close j activates/raises long (lowers short) protection only if native direction agrees, close is strictly beyond line and signed line gain bps strictly exceeds max(20, frozen full roundtrip fee+spread+impact plus modeled accrued absolute funding through j). Frozen costs are ex-ante DEV scenario parameters, not historical observable quotes; no future funding count/rate. Monotonic level effective j+1 only; gap through active level fills actual open before new HLC; otherwise native SL first, TP second, protection touch third, original timeout close fourth. No extension, TP cap, new filter, stop widening, partial sizing or future outcome feature. Final-boundary censor accounting and actual exit-bar-open+native cooldown ownership preserved.'

def path(rows,event,cache,*,cost_binding,enabled=True,checkpoint=None):
    i=event['signal_index'];ei=i+1;side=event['side'];sign=1 if side=='long' else -1
    h=event['timeout']['bars'];native_exit=ei+h;entry=float(rows[ei]['open'])
    if h!=48:raise RuntimeError('NATIVE_H48_DRIFT')
    state=deepcopy(checkpoint) if checkpoint else {'cursor':ei-1,'final':native_exit,
        'extension':{'decided':False,'allowed':False},'protection':None,'pending':None,'trace':[]}
    def prefix_hash(cursor):
        return a.old.digest({'event':event,'enabled':enabled,'cost_binding':cost_binding,'rows':rows[ei:cursor+1],
            'st':cache.st[max(0,ei-1):cursor+1],'ema':cache.ema[max(0,ei-1):cursor+1]})
    if checkpoint and (checkpoint.get('origin')!=i or checkpoint['cursor']>=len(rows)
                       or checkpoint.get('prefix_hash')!=prefix_hash(checkpoint['cursor'])):
        raise RuntimeError('NATIVE_RESTART_ORIGIN_OR_PREFIX')
    state['origin']=i
    sl,tp=event['sl'],event['tp'];fill=state.get('fill')
    if state.get('boundary_timeout') and state['boundary_timeout'][2]<rows[-1]['bar_close_ts']:
        fill=state.pop('boundary_timeout')
    for j in ([] if fill else range(state['cursor']+1,min(ei+h,len(rows)-1)+1)):
        row=rows[j];state['cursor']=j
        # Only the previously completed bar can set a protection level.
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
            if j==len(rows)-1:state['boundary_timeout']=candidate
            else:fill=candidate
            break
        if enabled:
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


def replay(rows,tape,cache,cost_binding,*,fixed_indices=None):
    with patch.object(n,'path',partial(path,cost_binding=cost_binding)):
        out=n.replay(rows,tape,cache,enabled=True,fixed_indices=fixed_indices)
    out['audit'].update(trailing_implemented=True,extension_allowed_T=0,maximum_entry_bar_inclusive_count=49,
        protection_activated_T=sum(t['kind']=='PROTECTION_ACTIVATE' for t in out['trace']),
        priority_scope='ACTIVE_GAP_OPEN; NATIVE_SL; NATIVE_TP; PROTECTION_TOUCH; NATIVE_TIMEOUT; COMPLETED_BAR_UPDATE')
    return out
