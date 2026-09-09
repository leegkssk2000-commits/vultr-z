"""One new pre-release entry architecture; C63 is immutable comparison, not a filter parent.

No price/fee/network I/O. Entire observed squeeze pool, not selected future
C63 releases. Completed pullback confirmation -> next real open, not a
fabricated EMA-limit fill. Original native M1 exit function/holding clock.
"""
from copy import deepcopy
from backend.research.rebuild import chart_mechanism_execution_v1 as native
f=native.f
BAR=native.BAR
RULE_ID='SQUEEZE_PRE_RELEASE_FROZEN_EMA21_PULLBACK_V1'


def prepare_setups(bars,start,end):
    features=f.squeeze_features(bars)
    ema=f._average([b.close for b in bars],21,2/22)
    signals=[];log=[];active=None;episode=None
    for i,obs in enumerate(features):
        if obs is None:continue
        ts=bars[i].open_ts+BAR
        if obs['squeeze_on']:
            if episode is None:
                episode=dict(start=i,start_ts=bars[i].open_ts,consumed=False)
                active=None
            if ts<start:continue
            if ts>end:break
            log.append(dict(kind='SQUEEZE_OBSERVATION',index=i,ts=ts,episode_start=episode['start'],squeeze_count=i-episode['start']+1,close=bars[i].close,low=bars[i].low,ema21=ema[i],momentum=obs['momentum'],prepared=active is not None,consumed=episode['consumed']))
            if active is not None and not episode['consumed']:
                event=dict(kind='WAIT_PULLBACK',index=i,ts=ts,episode_start=episode['start'],prep_index=active['prep_index'],level=active['level'],floor=active['floor'],close=bars[i].close,low=bars[i].low,momentum=obs['momentum'])
                if bars[i].close<=active['floor']:
                    event['kind']='CANCEL_FLOOR_CLOSE';episode['consumed']=True
                elif bars[i].low<=active['level'] and bars[i].close>active['level'] and obs['momentum']>0:
                    event['kind']='PULLBACK_CONFIRMED';episode['consumed']=True
                    signals.append(dict(signal_index=i,signal_ts=ts,setup_id='M1:'+str(episode['start_ts']),episode_start=episode['start'],floor=active['floor'],target=None,expiry=None,max_hold_bars=20,feature=deepcopy(obs),setup_available_at=active['available_at'],entry_context=deepcopy(active)))
                log.append(event)
            if active is None and not episode['consumed'] and i-episode['start']+1>=3 and bars[i].close>ema[i] and obs['momentum']>0:
                floor=min(b.low for b in bars[episode['start']:i+1])
                if floor<ema[i]:
                    active=dict(prep_index=i,available_at=ts,level=ema[i],floor=floor,episode_start=episode['start'],squeeze_count=i-episode['start']+1,ema_period=21)
                    log.append(dict(kind='PREPARED',index=i,ts=ts,**deepcopy(active)))
        else:
            if episode is not None and ts>=start:
                log.append(dict(kind='EPISODE_ENDED',index=i,ts=ts,episode_start=episode['start'],prepared=active is not None,consumed=episode['consumed'],release=obs['release'],long_release=obs['long_release']))
            active=None;episode=None
    if active is not None and not episode['consumed']:
        log.append(dict(kind='PENDING_SETUP_AT_END',index=len(bars)-1,ts=end,episode_start=episode['start'],entry_context=deepcopy(active)))
    return signals,log,features


def replay(rows,*,eval_start_ms,eval_end_ms):
    bars=native.to_bars(rows,eval_start_ms,eval_end_ms)
    signals,log,features=prepare_setups(bars,eval_start_ms,eval_end_ms)
    out=dict(trades=[],open_positions=[],events=[],trace=[],setup_events=log,pending_entries=[])
    last_exit=-1;tail=False
    for signal in signals:
        i=signal['signal_index'];ei=i+1
        e=dict(deepcopy(signal),admission=False,status='EXCLUDED',exclusion_reason=None)
        if tail or signal['signal_ts']<=last_exit:e['exclusion_reason']='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
        elif ei>=len(bars) or bars[ei].open_ts>=eval_end_ms:
            e['exclusion_reason']='NO_NEXT_OPEN_IN_APPROVED_WINDOW';out['pending_entries'].append(deepcopy(e))
        elif bars[ei].open<=signal['floor']:e['exclusion_reason']='GAP_INVALIDATES_FIXED_SETUP'
        else:
            trade,opened,trace=native._position(bars,signal,'M1',features,eval_end_ms)
            record=trade if trade is not None else opened
            record.update(entry_preparation=deepcopy(signal['entry_context']),entry_architecture=RULE_ID,actual_exchange_fill=False)
            out['trace'].extend(trace);e.update(admission=True,status='COMPLETED' if trade else 'CENSORED')
            if trade:out['trades'].append(trade);last_exit=trade['exit_ts']
            else:out['open_positions'].append(opened);tail=True
        out['events'].append(e)
    if len(out['trades'])+len(out['open_positions'])+sum(not e['admission'] for e in out['events'])!=len(signals):raise RuntimeError('SIGNAL_ACCOUNTING')
    out['audit']=dict(rule=RULE_ID,comparison_mode='FULL_CHRONOLOGICAL_ENTRY_REPLACEMENT',source_setup_observations=len(log),raw_signals=len(signals),completed=len(out['trades']),open=len(out['open_positions']),excluded=sum(not e['admission'] for e in out['events']),fresh_flat_start=True,same_symbol_max_positions=1,new_exchange_orders=0,independent=False,formal_credit=0,original_trader_replication=False,native_exit_function_unchanged=True,initial_floor_known_at_preparation=True,limit_touch_fill_claimed=False)
    return out
