"""Native1h timeout-only extension, exact raw intent owners and causal fills.

The raw intent tape is regenerated through native_replay with admission=False:
no parent market path is computed by that call. Its existing cache and entry
policies are reused verbatim. Replay then owns actual positions and cooldown.
"""
from copy import deepcopy
from contextlib import contextmanager
from unittest.mock import patch
from backend.research.rebuild import top5_development_native_v1 as native
from backend.research.rebuild import top5_mechanism_a_v1 as a

HOUR=native.HOUR
LANES={'TPR1':'trend_rider_primary_wr8125','TBR1':'trend_rider_broad_wr7000'}
RULES={k:k+'_NATIVE_TIMEOUT_ONLY_EXTENSION_DEV_V1' for k in LANES}
FIELDS=('symbol','signal_index','signal_ts','side','sl','tp','timeout','risk_size','exposure')


def prepare(rows,symbol,kind,start,end,policy_sha):
    native.validate_native(rows,start,end)
    cfg=native.primary.TrendRiderWR80USChaseCoolingConfig() if kind=='TPR1' else native.native.TrendPolicyConfig()
    cache=native.NativeFeatureCache(rows,cfg); ownership={}
    def capture(i,feature,intent):
        ownership[i]=native.owner.ev.execution_ownership_policy(intent)
        return False
    trades,events=native.native_replay(rows,symbol,'primary' if kind=='TPR1' else 'broad',start,end,capture,policy_sha)
    if trades:raise RuntimeError('INTENT_ONLY_PASS_MUST_NOT_COMPUTE_TRADES')
    tape=[]
    for e in events:
        t={k:deepcopy(e[k]) for k in FIELDS}
        t['owns_position'],t['cooldown_bars']=ownership[t['signal_index']]
        t['lane_id']=LANES[kind];tape.append(t)
    return cache,tape,cfg


def maintained(rows,cache,j,side):
    line,direction=cache.st[j];close=rows[j]['close'];ema=cache.ema[j]
    if j<1:return False
    if side=='long':return direction==1 and close>line and close>ema and ema>cache.ema[j-1]
    if side=='short':return direction==-1 and close<line and close<ema and ema<cache.ema[j-1]
    raise RuntimeError('NATIVE_SIDE')


def path(rows,event,cache,*,enabled=True,checkpoint=None):
    i=event['signal_index'];ei=i+1;side=event['side'];sign=1 if side=='long' else -1
    h=event['timeout']['bars'];native_exit=ei+h;entry=float(rows[ei]['open'])
    if h!=48:raise RuntimeError('NATIVE_H48_DRIFT')
    state=deepcopy(checkpoint) if checkpoint else {'cursor':ei-1,'final':native_exit,
        'extension':{'decided':False,'allowed':False},'pending':None,'trace':[]}
    def prefix_hash(cursor):
        return a.old.digest({'event':event,'enabled':enabled,'rows':rows[ei:cursor+1],
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
        if sl is not None and ((side=='long' and row['low']<=sl) or (side=='short' and row['high']>=sl)):
            fill=(j,float(sl),row['bar_close_ts'],'SL',False);break
        if tp is not None and ((side=='long' and row['high']>=tp) or (side=='short' and row['low']<=tp)):
            fill=(j,float(tp),row['bar_close_ts'],'TP',False);break
        if j==state['final']:
            candidate=(j,float(row['close']),row['bar_close_ts'],'TIMEOUT',False)
            if j==len(rows)-1:state['boundary_timeout']=candidate
            else:fill=candidate
            break
        if enabled and j==native_exit-1:
            trend=maintained(rows,cache,j,side)
            allowed=sign*(row['close']-entry)>0 and trend
            line,direction=cache.st[j]
            state['extension']={'decided':True,'allowed':allowed,'index':j,'ts':row['bar_close_ts'],
                'close':row['close'],'entry_price':entry,'direction':direction,'line':line,
                'ema50':cache.ema[j],'previous_ema50':cache.ema[j-1]}
            state['trace'].append({'kind':'NATIVE_RUNNER_DECISION',**state['extension']})
            if allowed:state['final']=native_exit+h
        if enabled and state['extension']['allowed'] and j>=native_exit and not maintained(rows,cache,j,side):
            state['pending']={'index':j,'signal_ts':row['bar_close_ts']}
            state['trace'].append({'kind':'NATIVE_RUNNER_TREND_LOSS_CLOSE',**state['pending']})
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
         'runner_extension':deepcopy(state['extension']),
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


def replay(rows,tape,cache,*,enabled=True,fixed_indices=None):
    if type(enabled) is not bool:raise RuntimeError('NATIVE_ENABLED_BOOL')
    fixed=fixed_indices is not None;wanted=set(fixed_indices or [])
    if fixed and (len(wanted)!=len(fixed_indices) or not wanted<={e['signal_index'] for e in tape}):
        raise RuntimeError('NATIVE_FIXED_ORIGINS')
    out={k:[] for k in ('trades','open_positions','events','trace')}
    blocked=-1;tail=False
    for source in tape:
        e=deepcopy(source);i=e['signal_index']
        if fixed and i not in wanted:continue
        e.update(admission=True,status='PENDING',exclusion_reason=None)
        if not fixed and (tail or (e['owns_position'] and native.owner.ev.ownership_blocked(rows[i+1]['bar_open_ts'],blocked))):
            e.update(status='EXCLUDED',exclusion_reason='NATIVE_ACTUAL_OWNERSHIP_COOLDOWN')
        else:
            t,o,trace,_=path(rows,e,cache,enabled=enabled)
            out['trace'].extend(dict(x,signal_index=i) for x in trace)
            if t:
                out['trades'].append(t);e['status']='COMPLETED'
                if e['owns_position']:
                    blocked=max(blocked,native.owner.ev.reserve_position_ownership(exit_ts=t['native_exit_bar_open_ts'],
                        open_horizon_ts=None,cooldown_bars=e['cooldown_bars'],timeframe_ms=HOUR))
            else:
                out['open_positions'].append(o);e['status']='CENSORED';tail=True
        out['events'].append(e)
    out['audit']={'comparison_mode':'FIXED_INDEPENDENT_DIAGNOSTIC' if fixed else 'FULL_NATIVE_ACTUAL_SLOT',
        'raw_signals':len(out['events']),'completed':len(out['trades']),'open':len(out['open_positions']),
        'excluded':sum(e['status']=='EXCLUDED' for e in out['events']),
        'extension_allowed_T':sum(x['kind']=='NATIVE_RUNNER_DECISION' and x['allowed'] for x in out['trace']),
        'native_SL_first':True,'priority_scope':'SL_BEFORE_TP_TIMEOUT_DECISION; PRIOR_PENDING_OPEN_ORDER_BEFORE_NEW_INTRABAR_PATH','native_TP_preserved':True,'trailing_implemented':False,
        'native_entry_bar_inclusive_count':49,'maximum_entry_bar_inclusive_count':97 if enabled else 49,
        'cooldown_clock':'EXIT_BAR_OPEN_PLUS_NATIVE_COOLDOWN; NOT COST_TIMESTAMP',
        'tail_owner_restored':True,'execution_authority':'NONE'}
    return out


def boundary(item,ts,prices,costs,start,end):
    status,t=item;final=a.metrics.bridge._values(item)
    terminal=t['exit_ts'] if status=='C' else t['mark_ts']
    if t['side'] not in ('long','short') or not start<=t['entry_ts']<=terminal<=end:
        raise RuntimeError('NATIVE_REPORT_CALENDAR_SIDE')
    if ts==start or t['entry_ts']>ts:return dict.fromkeys(a.metrics.exits.VALUE_FIELDS,0.)
    if (status=='C' and terminal<=ts) or (status=='O' and ts==end):return final
    px=prices[t['symbol']][ts];sign=1 if t['side']=='long' else -1
    gross=sign*(px-t['entry_price'])/t['entry_price']*10000
    parts=a.old.probe.cost_components(t['entry_ts'],ts,costs[t['symbol']])
    parts['frozen_floor_reserve_bps']=max(0.,20.-parts['cost_bps']);cost=max(20.,parts['cost_bps'])
    return {'gross_bps':gross,'net_bps':gross-cost,'cost2x_net_bps':gross-2*cost,
            'cost_bps':cost,**{k:parts[k] for k in a.metrics.exits.shared.COST_FIELDS}}


@contextmanager
def reporting():
    with patch.object(a.metrics.exits,'BAR',HOUR),patch.object(a.metrics.exits,'_boundary',boundary):
        yield
