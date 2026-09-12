"""Issue #1294: immutable CAPREUSE core + exact C54 native donor sleeve.

Uses saved exact parent/donor campaign streams on the same USED_DEV packets.
Core campaigns have absolute priority. Donor admission/preemption is processed
chronologically per symbol; no future overlap screen is used at donor entry.
"""
from copy import deepcopy
from math import isfinite

RULE_ID='SQUEEZE_KR3_CAPREUSE_CORE_PLUS_C54_NATIVE_SLEEVE_V1'
PREEMPT='CAPREUSE_CORE_PRIORITY_PREEMPT'


def key(row):
    return (row['symbol'], int(row['signal_ts']), row.get('side','long'))


def end_ts(row):
    return int(row['exit_ts'] if 'exit_ts' in row else row['mark_ts'])


def raw_key(symbol,row):
    return (symbol,int(row['signal_ts']),row.get('side','long'))


def raw_index(raw_by):
    out={}
    for symbol,result in raw_by.items():
        for row in result.get('trades',[])+result.get('open_positions',[]):
            k=raw_key(symbol,row)
            if k in out: raise RuntimeError('DUPLICATE_DONOR_RAW_KEY')
            out[k]=row
    return out


def _gross(side,entry,exit_price):
    if side=='long': return (exit_price/entry-1)*10000
    if side=='short': return (entry/exit_price-1)*10000
    raise RuntimeError('UNKNOWN_SIDE')


def _excursions(side,entry,bars,entry_index,exit_index,exit_price):
    held=bars[entry_index:exit_index]
    if side=='long':
        fav=[(b['high']/entry-1)*10000 for b in held]
        adv=[(b['low']/entry-1)*10000 for b in held]
    elif side=='short':
        fav=[(entry/b['low']-1)*10000 for b in held]
        adv=[(entry/b['high']-1)*10000 for b in held]
    else: raise RuntimeError('UNKNOWN_SIDE')
    g=_gross(side,entry,exit_price)
    return max([0.,g]+fav),min([0.,g]+adv)


def preempt_raw(raw,rows,ts):
    """Create a causal next-open donor exit at a known core entry open."""
    out=deepcopy(raw)
    opens={int(r['bar_open_ts']):i for i,r in enumerate(rows)}
    if int(ts) not in opens: raise RuntimeError('PREEMPT_OPEN_NOT_IN_PACKET')
    j=opens[int(ts)]
    if int(ts)<=int(out['entry_ts']): raise RuntimeError('PREEMPT_NOT_AFTER_DONOR_ENTRY')
    if j<=int(out['entry_index']): raise RuntimeError('PREEMPT_INDEX_NOT_AFTER_ENTRY')
    px=float(rows[j]['open']); entry=float(out['entry_price']); side=out.get('side','long')
    if not all(isfinite(v) and v>0 for v in (px,entry)): raise RuntimeError('INVALID_PREEMPT_PRICE')
    for name in ('exit_index','exit_ts','exit_price','gross_bps','exit_reason','mark_index','mark_ts','mark_price',
                 'gross_mark_bps','status','terminal_liquidation','censor_reason','pending_exit_trigger',
                 'profit_zone_state','exit_trigger','runner_extension','low_exit_state'):
        out.pop(name,None)
    mfe,mae=_excursions(side,entry,rows,int(out['entry_index']),j,px)
    out.update(exit_index=j,exit_ts=int(ts),exit_price=px,gross_bps=_gross(side,entry,px),
               exit_reason=PREEMPT,exit_timestamp_semantics='OBSERVED_4H_OPEN',
               hold_ms=int(ts)-int(out['entry_ts']),mfe_bps=mfe,mae_bps=mae,
               core_priority_preempted=True)
    return out


def chronological_plan(core_rows,donor_rows):
    """Pure timestamp arbitration plan; donor PnL is not inspected."""
    core_keys={key(r) for r in core_rows}
    events=[]
    for r in core_rows:
        k=key(r);events.append((int(r['entry_ts']),2,'CORE_ENTRY',k,r));events.append((end_ts(r),1,'CORE_END',k,r))
    for r in donor_rows:
        k=key(r);events.append((int(r['entry_ts']),3,'DONOR_ENTRY',k,r));events.append((end_ts(r),0,'DONOR_END',k,r))
    events.sort(key=lambda x:(x[0],x[1],x[2],x[3]))
    active_core={};active_donor={};accepted=[];excluded=[];preempt=[]
    for ts,_,kind,k,row in events:
        symbol=k[0]
        cores=active_core.setdefault(symbol,set())
        donor=active_donor.get(symbol)
        if kind=='DONOR_END':
            if donor is not None and donor['key']==k:
                accepted.append(dict(key=k,row=donor['row'],mode='NATURAL',end_ts=ts))
                active_donor.pop(symbol,None)
        elif kind=='CORE_END':
            cores.discard(k)
        elif kind=='CORE_ENTRY':
            if donor is not None:
                preempt.append(dict(key=donor['key'],row=donor['row'],preempt_ts=ts,core_key=k))
                active_donor.pop(symbol,None)
            cores.add(k)
        elif kind=='DONOR_ENTRY':
            if k in core_keys:
                excluded.append(dict(key=k,reason='DUPLICATE_CORE_IDENTITY',ts=ts))
            elif cores:
                excluded.append(dict(key=k,reason='CORE_ACTIVE_AT_DONOR_ENTRY',ts=ts))
            elif donor is not None:
                excluded.append(dict(key=k,reason='DONOR_ACTIVE_AT_DONOR_ENTRY',ts=ts))
            else:
                active_donor[symbol]=dict(key=k,row=row)
        else: raise RuntimeError('UNKNOWN_EVENT')
    if active_donor: raise RuntimeError('DONOR_EVENT_STREAM_UNCLOSED')
    return dict(accepted_natural=accepted,accepted_preempt=preempt,excluded=excluded,
                core_keys=sorted(core_keys),event_count=len(events))
