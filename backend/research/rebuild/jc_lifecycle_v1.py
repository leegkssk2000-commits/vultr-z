"""Carter Options-inspired fixed crypto lifecycle, never an options track record.

No I/O or general backtester. Daily preparation reuses canonical squeeze and
confirmed-pivot primitives through a clock-only adapter. Conditional fills use
Q0's observed-open gap / touched-level convention. Two feasible OHLC paths are
compared conservatively within each bar, not separate economic experiments.
"""
from copy import deepcopy
from math import fsum,isfinite
from dataclasses import replace
from backend.research.rebuild import chart_mechanism_features_v1 as f
from backend.research.rebuild.kr3_profit_zone_exit_v1 import decision_cost
BAR,DAY=f.BAR_MS,f.DAY_MS
RULE_ID='JC_LIFECYCLE_CRYPTO_V1'
LANE='john_carter_options_crypto_lifecycle_long'


def daily_features(days):
    f.validate(days,DAY)
    # Only the clock changes. Values, order and canonical predicate are identical.
    normalized=[replace(b,open_ts=i*BAR) for i,b in enumerate(days)]
    sq=f.squeeze_features(normalized)
    closes=[b.close for b in days]
    e8=f._average(closes,8,2/9);e21=f._average(closes,21,2/22)
    tr=[max(b.high-b.low,abs(b.high-days[i-1].close),abs(b.low-days[i-1].close)) for i,b in enumerate(days) if i]
    atr=[None]+f._average(tr,21,1/21) if days else []
    return normalized,sq,e8,e21,atr


def setup_at(days,index,features,tick):
    if type(tick) not in (int,float) or not isfinite(tick) or tick<=0:raise ValueError('NATIVE_INCREMENT_REQUIRED')
    normalized,sq,e8,e21,atr=features
    if index<364:return None
    high_events=[j for j in range(max(364,index-19),index+1)
                 if days[j].high>=max(b.high for b in days[j-364:j+1])]
    if not high_events or not all(sq[j] and sq[j]['squeeze_on'] for j in range(index-2,index+1)):return None
    if e21[index] is None or days[index].close<=e21[index] or atr[index] is None or atr[index]<=0:return None
    pivots=f.confirmed_pivots(normalized,index,2);alternating=[]
    # Outside pivots with both kinds have unknown daily sequence: reject that pivot.
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
    # All three squeeze observations are after the handle becomes confirmed.
    if abcd[-1]['known_index']>index-2:return None
    targets=[c-tick,d+1.272*(c-d),d+1.618*(c-d)]
    if not(0<d<targets[0]<targets[1]<targets[2]) or days[index].close>=targets[0]:return None
    return dict(setup_ts=days[index].open_ts+DAY,setup_day_index=index,handle_ts=days[abcd[-1]['index']].open_ts,
                H=c,L=d,ema8=e8[index],ema21=e21[index],atr=atr[index],tick=tick,
                breakout=d+.618*(c-d),targets=targets,pivots=abcd,high_event_indices=high_events,
                source='JC_OPTIONS_SPECIFIC_V1',implementation='A01_A12',setup_close=days[index].close)


def prepare(days,tick,start,end):
    features=daily_features(days)
    return {s['setup_ts']:s for i,b in enumerate(days) if start<=b.open_ts+DAY<=end
            for s in [setup_at(days,i,features,tick)] if s is not None}


def new_campaign(setup,signal_index):
    return dict(setup=deepcopy(setup),signal_index=signal_index,lots=[],legs=[],fills=[],invested=0.,
                limits_done=[],adds=True,first_fill_ts=None,first_fill_index=None,stop=None,next_stop=None,
                stage=0,snapshot_qty=None,checked72=False,pending_exit=False,closed=False,
                ambiguity=[],trace=[],initial_stop=None)


def remaining(c):return fsum(l['qty'] for l in c['lots'])
def average(c):return fsum(l['allocation'] for l in c['lots'])/fsum(l['original_qty'] for l in c['lots'])


def add(c,allocation,price,ts,index,kind):
    if allocation<=1e-14 or not c['adds']:return
    if c['invested']+allocation>1+1e-12:raise ValueError('INVALID_ENTRY_BUDGET')
    if not 0<price-2*c['setup']['atr']:
        c['adds']=False
        if c['first_fill_ts'] is None:c['closed']=True
        c['trace'].append(dict(kind='INVALID_ENTRY_RISK_CANCEL',ts=ts,price=price));return
    q=allocation/price
    c['lots'].append(dict(price=price,ts=ts,index=index,qty=q,original_qty=q,allocation=allocation))
    c['invested']+=allocation
    if c['first_fill_ts'] is None:c['first_fill_ts']=ts;c['first_fill_index']=index
    stop=average(c)-2*c['setup']['atr'];c['stop']=max(c['stop'] or stop,stop)
    if c['initial_stop'] is None:c['initial_stop']=c['stop']
    c['fills'].append(dict(kind=kind,price=price,ts=ts,index=index,allocation=allocation,qty=q,stop=c['stop']))


def sell(c,qty,price,ts,index,kind):
    current=remaining(c)
    if not 0<qty<=current+1e-12:raise ValueError('OVERSELL')
    ratio=min(1.,qty/current)
    for l in c['lots']:
        sold=l['qty']*ratio
        if sold<=0:continue
        c['legs'].append(dict(entry_price=l['price'],entry_ts=l['ts'],entry_index=l['index'],exit_price=price,
                             exit_ts=ts,exit_index=index,qty=sold,weight=sold*l['price'],reason=kind))
        l['qty']-=sold
    c['fills'].append(dict(kind=kind,price=price,ts=ts,index=index,qty=qty))
    if remaining(c)<=1e-14:c['closed']=True;c['adds']=False


def liquidation_value(c,price,stamp,cost):
    total=0.
    for l in c['legs']:
        total+=l['weight']*((l['exit_price']/l['entry_price']-1)*10000-decision_cost(l['entry_ts'],l['exit_ts'],cost)['cost_bps'])
    for l in c['lots']:
        total+=l['qty']*l['price']*((price/l['price']-1)*10000-decision_cost(l['ts'],stamp,cost)['cost_bps'])
    return total


def target(c,price,ts,index):
    if c['stage']==0:c['snapshot_qty']=remaining(c);c['adds']=False
    amount=remaining(c) if c['stage']==2 else c['snapshot_qty']/3
    sell(c,amount,price,ts,index,'PROFIT_'+str(c['stage']+1));c['stage']+=1
    if c['stage']<3:
        proposed=average(c)-(c['setup']['atr'] if c['stage']==1 else 0.)
        c['next_stop']=max(c['next_stop'] or c['stop'],c['stop'],proposed)


def open_point(c,price,ts,index):
    if c['closed']:return
    if c['first_fill_ts'] is None and price>=c['setup']['targets'][0]:c['closed']=True;c['adds']=False;c['trace'].append(dict(kind='NO_CHASE_GAP',ts=ts));return
    if remaining(c)>0:
        if price<=c['stop']:sell(c,remaining(c),price,ts,index,'STOP_GAP');return
        if c['pending_exit']:sell(c,remaining(c),price,ts,index,'FAILED_PROGRESS_NEXT_OPEN');return
    # At a gap breakout, remaining budget takes precedence over unfilled limits.
    if c['adds'] and price>=c['setup']['breakout']:
        add(c,1-c['invested'],price,ts,index,'BREAKOUT_GAP');c['adds']=False
    elif c['adds']:
        for name,a in [('ema8',.3),('ema21',.4)]:
            if name not in c['limits_done'] and price<=c['setup'][name]:
                add(c,a,price,ts,index,name+'_GAP');c['limits_done'].append(name)
    while remaining(c)>0 and c['stage']<3 and price>=c['setup']['targets'][c['stage']]:target(c,price,ts,index)


def segment(c,left,right,ts,index):
    """Touch levels in feasible path order; a newly created stop can act later."""
    if c['closed'] or left==right:return
    up=right>left;cursor=left
    for _ in range(12):
        if c['closed']:break
        orders=[]
        if remaining(c)>0:
            if not up and right<=c['stop']<cursor:orders.append((c['stop'],'STOP'))
            if up and c['stage']<3 and cursor<c['setup']['targets'][c['stage']]<=right:orders.append((c['setup']['targets'][c['stage']],'TARGET'))
        if c['adds']:
            if up and cursor<c['setup']['breakout']<=right:orders.append((c['setup']['breakout'],'BREAKOUT'))
            if not up:
                orders.extend((c['setup'][name],name) for name in ('ema8','ema21') if name not in c['limits_done'] and right<=c['setup'][name]<cursor)
        if not orders:break
        # Stop wins exact-price ties, before additional exposure.
        level,kind=sorted(orders,key=lambda x:((x[0] if up else -x[0]),0 if x[1]=='STOP' else 1))[0]
        if kind=='STOP':sell(c,remaining(c),level,ts,index,'STOP_TOUCH')
        elif kind=='TARGET':target(c,level,ts,index)
        elif kind=='BREAKOUT':add(c,1-c['invested'],level,ts,index,kind);c['adds']=False
        else:
            for name in ('ema8','ema21'):
                if name not in c['limits_done'] and c['setup'][name]==level:
                    add(c,.3 if name=='ema8' else .4,level,ts,index,name);c['limits_done'].append(name)
        cursor=level


def execute_bar(c,b,index,cost):
    base=deepcopy(c)
    if base['next_stop'] is not None:base['stop']=max(base['stop'],base['next_stop']);base['next_stop']=None
    open_point(base,b.open,b.open_ts,index)
    paths=[]
    for name,points in [('OLHC',[b.open,b.low,b.high,b.close]),('OHLC',[b.open,b.high,b.low,b.close])]:
        trial=deepcopy(base)
        for left,right in zip(points,points[1:]):segment(trial,left,right,b.open_ts+BAR,index)
        paths.append((liquidation_value(trial,b.close,b.open_ts+BAR,cost),name,trial))
    chosen=min(paths,key=lambda x:(x[0],x[1]));out=chosen[2]
    if paths[0][2]['fills']!=paths[1][2]['fills']:
        out['ambiguity'].append(dict(index=index,ts=b.open_ts+BAR,chosen_path=chosen[1],
            conservative_mark_net=chosen[0],alternative_mark_net=max(x[0] for x in paths),
            difference_bps=max(x[0] for x in paths)-chosen[0],reference_allocation=out['invested']))
    return out


def manage_close(c,b,days,cost):
    if c['closed'] or c['first_fill_ts'] is None:return
    stamp=b.open_ts+BAR
    if not c['checked72'] and stamp>=c['first_fill_ts']+3*DAY:
        net=liquidation_value(c,b.close,stamp,cost);c['checked72']=True
        c['trace'].append(dict(kind='CHECK72',ts=stamp,net_bps=net))
        if net<=0:c['pending_exit']=True;c['adds']=False
    if c['stage']==2 and len(days)>=3:
        value=min(d.low for d in days[-3:])-c['setup']['tick']
        c['next_stop']=max(c['stop'],c['next_stop'] or c['stop'],value)


def replay(rows,*,eval_start_ms,eval_end_ms,warmup_days,tick,cost_model):
    original=deepcopy(rows)
    bars=[f.Bar(r['bar_open_ts'],*[float(r[k]) for k in ('open','high','low','close','volume')]) for r in rows]
    f.validate(bars)
    if not bars or bars[-1].open_ts+BAR!=eval_end_ms:raise ValueError('BOUND_PREFIX_END')
    warm=deepcopy(warmup_days)
    f.validate(warm,DAY)
    if any(x.open_ts+DAY>eval_start_ms for x in warm):raise ValueError('WARMUP_BOUNDARY')
    full_bars=[b for b in bars if b.open_ts>=((bars[0].open_ts+DAY-1)//DAY)*DAY]
    observed=f.completed_utc_days(full_bars,eval_end_ms)
    # Missing initial midnight bars cannot be supplied by a daily candle crossing
    # the evaluation boundary. Retain only the latest continuous daily segment;
    # A02 makes earlier insufficient-history dates ineligible, never interpolated.
    combined=warm+observed
    last_gap=max((i for i in range(1,len(combined)) if combined[i].open_ts-combined[i-1].open_ts!=DAY),default=0)
    days=combined[last_gap:];f.validate(days,DAY)
    setups=prepare(days,tick,eval_start_ms,eval_end_ms)
    c=None;last_handle=None;campaigns=[];pending=[];events=[]
    for i,b in enumerate(bars):
        if b.open_ts<eval_start_ms:continue
        # A completed prior daily bar may create a new order at this actual open.
        setup=setups.get(b.open_ts)
        if setup and (last_handle is None or setup['handle_ts']>last_handle):
            if c is None:
                c=new_campaign(setup,i-1);last_handle=setup['handle_ts'];events.append(dict(kind='SETUP',ts=b.open_ts,handle_ts=last_handle))
            else:events.append(dict(kind='OCCUPIED_SETUP',ts=b.open_ts,handle_ts=setup['handle_ts']))
        if c is None:continue
        c=execute_bar(c,b,i,cost_model)
        completed=[d for d in days if d.open_ts+DAY<=b.open_ts+BAR]
        manage_close(c,b,completed,cost_model)
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
    return dict(campaigns=campaigns,pending=pending,events=events,audit=dict(rule=RULE_ID,
        source_implementation='CRYPTO_ADAPTATION_A01_A12_NOT_EXACT_OPTIONS',setups=len(setups),
        daily_rows=len(days),daily_before_start=sum(d.open_ts+DAY<=eval_start_ms for d in days),
        ineligible_365_days_at_start=sum(d.open_ts+DAY<=eval_start_ms for d in days)<365,
        native_C63_exit=False,listing_origin_verified=False,ambiguity_model='WORST_OF_TWO_FEASIBLE_OHLC_PATHS',
        intrabar_timestamp='BAR_CLOSE_UPPER_BOUND_NOT_ACTUAL_TIME'))
