"""One conditionally authorized JC successor; unchanged execution lifecycle."""
from copy import deepcopy
from math import isfinite
from backend.research.rebuild import jc_lifecycle_v1 as parent
from backend.research.rebuild import jc_boundary_context_v1 as context
f=parent.f;DAY=parent.DAY;BAR=parent.BAR
RULE_ID='JC_REPAIRED_BOUNDARY_CONDITIONAL_WAIT_V1';LANE=parent.LANE
average=parent.average


def setup_at(days,index,features,tick,*,remove_extra_wait):
    if not remove_extra_wait:return parent.setup_at(days,index,features,tick)
    if type(tick) not in (int,float) or not isfinite(tick) or tick<=0:raise ValueError('NATIVE_INCREMENT_REQUIRED')
    normalized,sq,e8,e21,atr=features
    if index<364:return None
    high_events=[j for j in range(max(364,index-19),index+1) if days[j].high>=max(b.high for b in days[j-364:j+1])]
    if not high_events or not all(sq[j] and sq[j]['squeeze_on'] for j in range(index-2,index+1)):return None
    if e21[index] is None or days[index].close<=e21[index] or atr[index] is None or atr[index]<=0:return None
    pivots=f.confirmed_pivots(normalized,index,2);alternating=[]
    dual={p['index'] for p in pivots if sum(q['index']==p['index'] for q in pivots)>1}
    for p in pivots:
        if p['index'] in dual:continue
        if alternating and alternating[-1]['kind']==p['kind']:alternating[-1]=p
        else:alternating.append(p)
    if len(alternating)<4:return None
    abcd=alternating[-4:]
    if [p['kind'] for p in abcd]!=['HIGH','LOW','HIGH','LOW']:return None
    a,b,c,d=[p['price'] for p in abcd]
    if not(b<a and .9*a<=c<=1.1*a and b<d<c):return None
    # The sole authorized timing difference. Radius2 confirmation stays intact.
    if abcd[-1]['known_index']>index:return None
    targets=[c-tick,d+1.272*(c-d),d+1.618*(c-d)]
    if not(0<d<targets[0]<targets[1]<targets[2]) or days[index].close>=targets[0]:return None
    return dict(setup_ts=days[index].open_ts+DAY,setup_day_index=index,handle_ts=days[abcd[-1]['index']].open_ts,
        H=c,L=d,ema8=e8[index],ema21=e21[index],atr=atr[index],tick=tick,breakout=d+.618*(c-d),targets=targets,
        pivots=abcd,high_event_indices=high_events,source='JC_OPTIONS_SPECIFIC_V1',implementation='A01_A12',setup_close=days[index].close)


def prepare(days,tick,start,end,*,remove_extra_wait):
    setups={}
    for piece in context.segments(days):
        features=parent.daily_features(piece)
        for i,b in enumerate(piece):
            if not start<=b.open_ts+DAY<=end:continue
            s=setup_at(piece,i,features,tick,remove_extra_wait=remove_extra_wait)
            if s is not None:
                # Preserve normalized pivot metadata but add true UTC availability.
                s['pivot_availability_utc']=[dict(index=p['index'],known_index=p['known_index'],available_at=piece[p['known_index']].open_ts+DAY) for p in s['pivots']]
                setups[s['setup_ts']]=s
    return setups


def replay(rows,*,eval_start_ms,eval_end_ms,warmup_days,boundary_day,tick,cost_model,remove_extra_wait):
    original=deepcopy(rows);bars=context.rows_to_bars(rows,eval_end_ms);f.validate(bars)
    if not bars or bars[-1].open_ts+BAR!=eval_end_ms:raise ValueError('BOUND_PREFIX_END')
    days=context.timeline(rows,warmup_days,boundary_day,eval_end_ms,start=eval_start_ms)
    setups=prepare(days,tick,eval_start_ms,eval_end_ms,remove_extra_wait=remove_extra_wait)
    c=None;last_handle=None;campaigns=[];pending=[];events=[]
    for i,b in enumerate(bars):
        if b.open_ts<eval_start_ms:continue
        setup=setups.get(b.open_ts)
        if setup and (last_handle is None or setup['handle_ts']>last_handle):
            if c is None:
                c=parent.new_campaign(setup,i-1);last_handle=setup['handle_ts'];events.append(dict(kind='SETUP',ts=b.open_ts,handle_ts=last_handle))
            else:events.append(dict(kind='OCCUPIED_SETUP',ts=b.open_ts,handle_ts=setup['handle_ts']))
        if c is None:continue
        c=parent.execute_bar(c,b,i,cost_model)
        completed=[d for d in days if d.open_ts+DAY<=b.open_ts+BAR]
        # Trailing must use the contiguous as-of segment, never bridge a missing day.
        pieces=context.segments(completed);known=pieces[-1] if pieces else []
        parent.manage_close(c,b,known,cost_model)
        if not c['closed'] and c['first_fill_ts'] is None and (b.open_ts+BAR)%DAY==0:
            if b.close<c['setup']['L'] or b.open_ts+BAR>=c['setup']['setup_ts']+20*DAY:
                c['closed']=True;c['trace'].append(dict(kind='UNFILLED_CANCEL',ts=b.open_ts+BAR))
        if c['closed']:
            if c['first_fill_ts'] is not None:campaigns.append(c)
            else:pending.append(c)
            c=None
    if c is not None:
        if c['first_fill_ts'] is not None:
            c['mark_price']=bars[-1].close;c['mark_ts']=eval_end_ms;c['mark_index']=len(bars)-1;campaigns.append(c)
        else:pending.append(c)
    if eval_end_ms in setups:pending.append(dict(status='SETUP_AT_END_NO_NEXT_OPEN',setup=setups[eval_end_ms]))
    if rows!=original:raise RuntimeError('INPUT_MUTATED')
    return dict(campaigns=campaigns,pending=pending,events=events,audit=dict(rule=RULE_ID,setups=len(setups),
        remove_extra_wait=remove_extra_wait,boundary_context_only=boundary_day is not None,
        boundary_first_available_at=None if boundary_day is None else boundary_day.open_ts+DAY,
        coverage=context.coverage(days,eval_start_ms,eval_end_ms),daily_rows=len(days),
        daily_before_start=sum(d.open_ts+DAY<=eval_start_ms for d in days),native_C63_exit=False,
        source_implementation='CRYPTO_ADAPTATION_NOT_EXACT_OPTIONS',ambiguity_model='UNCHANGED_PR1251_WORST_OF_TWO_FEASIBLE_OHLC_PATHS'))
