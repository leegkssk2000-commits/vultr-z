"""Prepared causal chart features. No orders, network, market loaders or PnL.
Numerical priors are from the user-approved chart WORK_SPEC, not tuned values.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import fsum,isfinite,sqrt
from typing import Literal,Sequence
BAR_MS=14_400_000
DAY_MS=86_400_000
@dataclass(frozen=True)
class Bar:
    open_ts:int
    open:float
    high:float
    low:float
    close:float
    volume:float

def validate(bars:Sequence[Bar],step_ms:int=BAR_MS)->None:
    if not isinstance(step_ms,int) or isinstance(step_ms,bool) or step_ms<=0:raise ValueError('INVALID_STEP')
    previous=None
    for b in bars:
        if type(b.open_ts) is not int or b.open_ts%step_ms:raise ValueError('MISALIGNED_TIMESTAMP')
        vals=(b.open,b.high,b.low,b.close,b.volume)
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not isfinite(x) for x in vals):raise ValueError('NONFINITE_OHLCV')
        if min(b.open,b.high,b.low,b.close)<=0 or b.volume<0:raise ValueError('INVALID_PRICE_OR_VOLUME')
        if not b.low<=min(b.open,b.close)<=max(b.open,b.close)<=b.high:raise ValueError('INCONSISTENT_OHLC')
        if previous is not None and b.open_ts-previous!=step_ms:raise ValueError('GAP_OR_DUPLICATE')
        previous=b.open_ts

def confirmed_pivots(bars:Sequence[Bar],asof_index:int,radius:int=2)->list[dict]:
    if type(radius) is not int or radius<1:raise ValueError('INVALID_RADIUS')
    if not 0<=asof_index<len(bars):raise ValueError('INVALID_ASOF')
    prefix=bars[:asof_index+1];validate(prefix);found=[]
    for j in range(radius,len(prefix)-radius):
        others=list(prefix[j-radius:j])+list(prefix[j+1:j+radius+1])
        for kind,qualifies,price in [('LOW',all(prefix[j].low<x.low for x in others),prefix[j].low),('HIGH',all(prefix[j].high>x.high for x in others),prefix[j].high)]:
            if qualifies:found.append(dict(kind=kind,index=j,price=price,known_index=j+radius,available_at=prefix[j+radius].open_ts+BAR_MS))
    return found

def known_upswing(bars:Sequence[Bar],decision_index:int,pre_pullback_index:int)->dict|None:
    if decision_index<1 or not 0<=pre_pullback_index<decision_index:raise ValueError('INVALID_EPISODE')
    pivots=confirmed_pivots(bars,decision_index-1)
    highs=[p for p in pivots if p['kind']=='HIGH' and p['index']<=pre_pullback_index]
    if not highs:return None
    high=max(highs,key=lambda x:x['index'])
    lows=[p for p in pivots if p['kind']=='LOW' and p['index']<high['index']]
    if not lows:return None
    low=max(lows,key=lambda x:x['index'])
    if high['price']<=low['price']:return None
    return dict(low=low,high=high,known_at=max(low['available_at'],high['available_at']))

def anchored_bar_vwap(bars:Sequence[Bar],anchor:int,end:int)->float|None:
    if not 0<=anchor<=end<len(bars):raise ValueError('INVALID_ANCHOR')
    segment=bars[anchor:end+1];validate(segment);den=fsum(x.volume for x in segment)
    if den==0:return None
    return fsum(((x.high+x.low+x.close)/3)*x.volume for x in segment)/den

def retracement(low:float,high:float,pullback_low:float)->float:
    if not all(isfinite(x) and x>0 for x in (low,high,pullback_low)) or high<=low:raise ValueError('INVALID_IMPULSE')
    return (high-pullback_low)/(high-low)

def in_zone(depth:float,zone:Literal['FIB','SHIFTED'])->bool:
    limits={'FIB':(.382,.618),'SHIFTED':(.350,.586)}
    if zone not in limits or not isfinite(depth):raise ValueError('INVALID_ZONE')
    lo,hi=limits[zone];return lo<=depth<=hi

def _average(values:list[float],n:int,alpha:float)->list[float|None]:
    if n<1:raise ValueError('INVALID_PERIOD')
    out=[None]*len(values)
    if len(values)>=n:
        out[n-1]=fsum(values[:n])/n
        for i in range(n,len(values)):out[i]=alpha*values[i]+(1-alpha)*out[i-1]
    return out

def squeeze_features(bars:Sequence[Bar])->list[dict|None]:
    validate(bars);close=[b.close for b in bars];center=_average(close,20,2/21)
    tr=[max(b.high-b.low,abs(b.high-bars[i-1].close),abs(b.low-bars[i-1].close)) for i,b in enumerate(bars) if i]
    atr=[None]+_average(tr,20,1/20) if bars else [];out=[]
    for i,b in enumerate(bars):
        if i<20:out.append(None);continue
        window=close[i-19:i+1];avg=fsum(window)/20;sd=sqrt(fsum((v-avg)**2 for v in window)/20)
        upper,lower=avg+2*sd,avg-2*sd;ku,kl=center[i]+1.5*atr[i],center[i]-1.5*atr[i]
        on=lower>kl and upper<ku;previous_on=out[-1] is not None and out[-1]['squeeze_on']
        # A touch is neither strict containment nor a release outside KC.
        # It breaks the squeeze episode, but cannot create a buy signal.
        outside=lower<kl or upper>ku
        momentum=close[i]-close[i-14];release=bool(previous_on and outside)
        out.append(dict(available_at=b.open_ts+BAR_MS,squeeze_on=on,release=release,bb_upper=upper,bb_lower=lower,kc_upper=ku,kc_lower=kl,momentum=momentum,long_release=release and momentum>0 and b.close>upper))
    return out

def completed_utc_days(bars:Sequence[Bar],asof_ms:int)->list[Bar]:
    prefix=[b for b in bars if b.open_ts+BAR_MS<=asof_ms];validate(prefix)
    if prefix and prefix[0].open_ts%DAY_MS:raise ValueError('PREFIX_START_NOT_MIDNIGHT')
    days=[]
    for j in range(0,len(prefix),6):
        group=prefix[j:j+6]
        if len(group)<6:break
        days.append(Bar(group[0].open_ts,group[0].open,max(b.high for b in group),min(b.low for b in group),group[-1].close,fsum(b.volume for b in group)))
    validate(days,DAY_MS);return days

def soup_plus_one_setup(days:Sequence[Bar],index:int)->dict|None:
    if not 0<=index<len(days):raise ValueError('INVALID_DAY_INDEX')
    prefix=days[:index+1];validate(prefix,DAY_MS)
    if index<20:return None
    old=prefix[index-20:index];level=min(b.low for b in old)
    low_index=max(j for j in range(index-20,index) if prefix[j].low==level);setup=prefix[index]
    if index-low_index<3 or not (setup.low<level and setup.close<=level):return None
    return dict(previous_low=level,prior_low_index=low_index,setup_low=setup.low,setup_day=setup.open_ts,available_at=setup.open_ts+DAY_MS,order_expiry=setup.open_ts+2*DAY_MS,prior_range_mid=(max(b.high for b in old)+level)/2)

def next_open_time(signal_bar:Bar,evaluation_end:int)->int|None:
    stamp=signal_bar.open_ts+BAR_MS;return stamp if stamp<evaluation_end else None
