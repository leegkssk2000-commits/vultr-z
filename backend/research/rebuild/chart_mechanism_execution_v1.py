"""Five source-chart mechanisms: full execution integration, no live authority.

No file/network I/O, candidate allocator or dispatcher. T1/F1/F0 retain C54;
M1/R1 are independent close-confirmed/next-real-open lifecycles. Prepared rules
are unchanged. Same-close exit/reentry conflicts use conservative occupancy.
"""
from __future__ import annotations
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import chart_mechanism_features_v1 as f
BAR,DAY=f.BAR_MS,f.DAY_MS
VARIANTS=('T1','M1','R1','F1','F0')
RULES={k:'SOURCE_CHART_'+k+'_AFTER_PR1228_V1' for k in VARIANTS}
class UnverifiedVolume(ValueError):
    """AVWAP lanes require verified base/fixed-contract-volume metadata."""

def validate_volume(binding):
    if (not isinstance(binding,dict) or binding.get('basis') not in ('BASE_VOLUME','FIXED_CONTRACT_VOLUME')
        or not isinstance(binding.get('source_ref'),str) or not binding['source_ref']
        or not isinstance(binding.get('source_sha256'),str) or len(binding['source_sha256'])!=64
        or any(x not in '0123456789abcdef' for x in binding['source_sha256'])):
        raise UnverifiedVolume('AVWAP_VOLUME_AUTHORITY_REQUIRED')

def to_bars(rows,start,end):
    if any(type(x) is not int or x%BAR for x in (start,end)) or end<=start:raise ValueError('INVALID_EVALUATION_CALENDAR')
    bars=[]
    for row in rows:
        if row.get('bar_close_ts')!=row.get('bar_open_ts',0)+BAR:raise ValueError('BAR_CLOSE_CLOCK')
        bars.append(f.Bar(row['bar_open_ts'],*(row[k] for k in ('open','high','low','close','volume'))))
    f.validate(bars)
    if not bars or bars[0].open_ts>start or bars[-1].open_ts+BAR!=end:raise ValueError('EXACT_PREFIX_AND_TERMINAL_REQUIRED')
    return bars

def trend_context(bars,obs,variant):
    i,q=obs['signal_index'],obs['trend_index']
    base=dict(variant=variant,available_at=bars[i].open_ts+BAR,eligible=False,reason='NO_CONFIRMED_ANCHORS',anchor=None)
    if q is None:return base
    anchor=f.known_upswing(bars,i,q)
    if anchor is None:return base
    a=anchor['low']['index'];current=f.anchored_bar_vwap(bars,a,i);prior=f.anchored_bar_vwap(bars,a,i-1)
    depth=f.retracement(anchor['low']['price'],anchor['high']['price'],min(x.low for x in bars[q+1:i]))
    available=current is not None and prior is not None
    above=available and bars[i].close>current;rising=available and current>prior
    zone=True if variant=='T1' else f.in_zone(depth,'FIB' if variant=='F1' else 'SHIFTED')
    return dict(base,anchor=anchor,avwap=current,previous_avwap=prior,retracement=depth,zone_pass=zone,above_avwap=above,
        rising_avwap=rising,eligible=bool(above and rising and zone),reason=('ZERO_ANCHORED_VOLUME' if not available else
        'AVWAP_CONTEXT_VETO' if not (above and rising) else 'RETRACEMENT_ZONE_VETO' if not zone else None),
        price_semantics='HLC3_BASE_OR_FIXED_CONTRACT_VOLUME_BAR_PROXY')

def replay_trend(rows,bundle,*,eval_start_ms,eval_end_ms,cost_model,variant='T1',volume_binding=None,enabled=True,reference_checkpoint=None):
    from backend.research.rebuild import kr3_c51_entry_context_v1 as c54
    if variant not in ('T1','F1','F0') or type(enabled) is not bool:raise ValueError('INVALID_TREND_VARIANT')
    kwargs=dict(eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost_model=cost_model,mode='B',reference_checkpoint=reference_checkpoint)
    if not enabled:return c54.replay(rows,bundle,**kwargs)
    validate_volume(volume_binding);bars=to_bars(rows,eval_start_ms,eval_end_ms)
    original_observations,original_allowed=c54.observations,c54.allowed
    def observations(r,b):
        out=original_observations(r,b)
        for i,obs in out.items():obs['chart_context']=trend_context(bars,obs,variant)
        return out
    def allowed(obs,mode):return original_allowed(obs,mode) and obs['chart_context']['eligible']
    with patch.object(c54,'observations',observations),patch.object(c54,'allowed',allowed):result=c54.replay(rows,bundle,**kwargs)
    for e in result['events']:
        if e['exclusion_reason']=='ENTRY_CONTEXT_B_VETO' and e['entry_context']['B']:e['exclusion_reason']=e['entry_context']['chart_context']['reason']
    result['audit'].update(rule=RULES[variant],direct_parent=c54.RULES['B'],C54_exit_unchanged=True,volume_binding=deepcopy(volume_binding))
    return result

def m1_setups(bars):
    features=f.squeeze_features(bars);signals,observations=[],[];episode=None
    for i,obs in enumerate(features):
        if obs is None:continue
        if obs['squeeze_on'] and episode is None:episode=i
        if obs['release']:
            if episode is None:raise RuntimeError('MISSING_SQUEEZE_EPISODE')
            event=dict(signal_index=i,signal_ts=obs['available_at'],setup_id='M1:'+str(bars[episode].open_ts),episode_start=episode,
                floor=min(b.low for b in bars[episode:i+1]),target=None,expiry=None,max_hold_bars=20,feature=deepcopy(obs),setup_available_at=obs['available_at'])
            observations.append(dict(event,long_signal=obs['long_release']))
            if obs['long_release']:signals.append(event)
            episode=None
    return signals,observations,features

def r1_setups(bars):
    first=next((j for j,b in enumerate(bars) if b.open_ts%DAY==0),len(bars))
    days=f.completed_utc_days(bars[first:],bars[-1].open_ts+BAR) if first<len(bars) else []
    index_by_open={b.open_ts:j for j,b in enumerate(bars)};signals,setups=[],[]
    for j in range(len(days)):
        setup=f.soup_plus_one_setup(days,j)
        if setup is None:continue
        record=dict(setup,status='NO_RECLAIM_BEFORE_EXPIRY',first_reclaim_index=None)
        d1=setup['available_at'];observed_lows=[setup['setup_low']]
        for stamp in range(d1,setup['order_expiry'],BAR):
            i=index_by_open.get(stamp)
            if i is None:record['status']='EVALUATION_END_BEFORE_SETUP_EXPIRY';break
            b=bars[i];observed_lows.append(b.low)
            if b.close<=setup['previous_low']:continue
            record.update(first_reclaim_index=i,status='RECLAIM_OBSERVED')
            signals.append(dict(signal_index=i,signal_ts=b.open_ts+BAR,setup_id='R1:'+str(setup['setup_day']),floor=min(observed_lows),
                target=setup['prior_range_mid'],expiry=setup['order_expiry'],max_hold_bars=12,setup_available_at=setup['available_at'],feature=deepcopy(setup)))
            break
        setups.append(record)
    return signals,setups,dict(leading_partial_bars=first,completed_days=len(days))

def exit_reason(variant,close,floor,target,momentum,held):
    if close<=floor:return 'FIXED_FLOOR_CLOSE'
    if variant=='M1' and momentum<=0:return 'MOMENTUM_NONPOSITIVE_CLOSE'
    if variant=='R1' and close>=target:return 'PRIOR_RANGE_MIDPOINT_CLOSE'
    if held>=(20 if variant=='M1' else 12):return 'FIXED_TIME_CLOSE'
    return None

def _position(bars,signal,variant,features,end):
    i,ei=signal['signal_index'],signal['signal_index']+1;entry=bars[ei]
    trace=[dict(kind='ENTRY_NEXT_OPEN',signal_index=i,index=ei,ts=entry.open_ts,price=entry.open,floor=signal['floor'],target=signal['target'])]
    pending=None;xi=None;last=ei-1;reason=None
    for j in range(ei,len(bars)):
        row=bars[j];last=j;mom=features[j]['momentum'] if variant=='M1' else None
        reason=exit_reason(variant,row.close,signal['floor'],signal['target'],mom,j-ei+1)
        trace.append(dict(kind='HELD_CLOSE_OBSERVATION',signal_index=i,index=j,ts=row.open_ts+BAR,close=row.close,
            floor=signal['floor'],target=signal['target'],momentum=mom,held_bars=j-ei+1,exit_reason=reason))
        if reason is None:continue
        pending=dict(signal_index=j,signal_ts=row.open_ts+BAR,observed_close=row.close,reason=reason)
        if j+1<len(bars) and bars[j+1].open_ts<end:xi=j+1
        break
    if last<ei:raise RuntimeError('POSITION_WITHOUT_HELD_BAR')
    price=bars[xi].open if xi is not None else bars[last].close
    stamp=bars[xi].open_ts if xi is not None else bars[last].open_ts+BAR
    held_bars=bars[ei:last+1];gross=(price/entry.open-1.)*10000
    mfe=max(0.,gross,max((b.high/entry.open-1.)*10000 for b in held_bars));mae=min(0.,gross,min((b.low/entry.open-1.)*10000 for b in held_bars))
    raw=dict(signal_index=i,signal_ts=signal['signal_ts'],entry_index=ei,entry_ts=entry.open_ts,entry_price=entry.open,side='long',
        hold_ms=stamp-entry.open_ts,mfe_bps=mfe,mae_bps=mae,exit_trigger=deepcopy(pending),setup_id=signal['setup_id'],
        fixed_floor=signal['floor'],fixed_target=signal['target'],original_protective_sl=None,exchange_resident_stop=False,
        excursion_semantics='HELD_COMPLETE_BARS_PLUS_EXIT_OPEN_ONLY')
    if xi is not None:
        raw.update(exit_index=xi,exit_ts=stamp,exit_price=price,gross_bps=gross,exit_reason=reason+'_NEXT_OPEN',exit_timestamp_semantics='OBSERVED_4H_OPEN')
        trace.append(dict(kind=raw['exit_reason'],signal_index=i,index=xi,ts=stamp,price=price));return raw,None,trace
    raw.update(mark_index=last,mark_ts=stamp,mark_price=price,gross_mark_bps=gross,status='CENSORED',terminal_liquidation=False,
        censor_reason='PENDING_EXIT_OUTSIDE_WINDOW' if pending else 'HOLD_UNFINISHED',pending_exit_signal_ts=pending['signal_ts'] if pending else None,pending_exit_trigger=deepcopy(pending))
    trace.append(dict(kind='TERMINAL_MARK',signal_index=i,index=last,ts=stamp,price=price));return None,raw,trace

def replay_independent(rows,*,eval_start_ms,eval_end_ms,variant):
    if variant not in ('M1','R1'):raise ValueError('INVALID_STANDALONE_VARIANT')
    bars=to_bars(rows,eval_start_ms,eval_end_ms)
    all_signals,setup_log,features=m1_setups(bars) if variant=='M1' else r1_setups(bars)
    signals=[s for s in all_signals if eval_start_ms<=s['signal_ts']<=eval_end_ms]
    result=dict(trades=[],open_positions=[],events=[],trace=[],setup_events=setup_log,pending_entries=[])
    last_exit,tail=-1,False
    for signal in signals:
        i=signal['signal_index'];ei=i+1;event=dict(deepcopy(signal),admission=False,status='EXCLUDED',exclusion_reason=None)
        if tail or signal['signal_ts']<=last_exit:event['exclusion_reason']='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
        elif signal['expiry'] is not None and signal['signal_ts']>=signal['expiry']:event['exclusion_reason']='SETUP_EXPIRED_BEFORE_ENTRY'
        elif ei>=len(bars) or bars[ei].open_ts>=eval_end_ms:
            event['exclusion_reason']='NO_NEXT_OPEN_IN_APPROVED_WINDOW';result['pending_entries'].append(deepcopy(event))
        elif bars[ei].open<=signal['floor'] or (signal['target'] is not None and bars[ei].open>=signal['target']):event['exclusion_reason']='GAP_INVALIDATES_FIXED_SETUP'
        else:
            trade,opened,trace=_position(bars,signal,variant,features,eval_end_ms)
            event.update(admission=True,status='COMPLETED' if trade else 'CENSORED');result['trace'].extend(trace)
            if trade:result['trades'].append(trade);last_exit=trade['exit_ts']
            else:result['open_positions'].append(opened);tail=True
        result['events'].append(event)
    excluded=sum(x['status']=='EXCLUDED' for x in result['events'])
    if len(result['trades'])+len(result['open_positions'])+excluded!=len(signals):raise RuntimeError('SIGNAL_ACCOUNTING_COVERAGE')
    result['audit']=dict(rule=RULES[variant],raw_signals=len(signals),completed=len(result['trades']),open=len(result['open_positions']),excluded=excluded,
        comparison_mode='FULL_CHRONOLOGICAL',same_symbol_max_positions=1,fresh_flat_start=True,new_exchange_orders=0,
        exit_model='COMPLETED_CLOSE_THEN_REAL_NEXT_OPEN',independent=False,formal_credit=0,source_setup_observations=len(setup_log))
    return result
