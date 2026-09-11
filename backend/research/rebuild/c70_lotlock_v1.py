"""Independent per-entry post-partial risk; frozen CAPREUSE admission.

Only this lot's actual fills and completed closes feed its bank/peak. Unit
cash is scaled by its constant exact allocation in accounting; the trigger
inequality is homogeneous, so allocation never changes a lot's exit path.
No group state, dispatcher, network, orders, or production authority.
"""
from copy import deepcopy
from fractions import Fraction
from math import fsum
from backend.research.rebuild import c70_tm_capreuse_v1 as cap

tm=cap.tm
SCOPE='C70_LOT_LEVEL_RISK_AFTER_PR1264_V1'
RULE='C70_CAPREUSE_LOTLOCK_V1'
EXIT='LOT_LEVEL_POST_PARTIAL_RISK_ENVELOPE'
OCCUPIED=cap.OCCUPIED
allocation=cap.allocation
remaining=cap.remaining
capacity=cap.capacity


def assert_authorized(scope,status):
    if scope!=SCOPE or status!='FROZEN_AUTHORIZED_FIRST_FULL':
        raise ValueError('SCOPE_REPORT_ONLY_OR_NOT_AUTHORIZED')


def lot_value(raw,stamp,price,cost):
    """One unit lot, close before equal-timestamp open fills. No other cash."""
    bank=realized=0.;filled=0.;first=None
    for leg in raw['tm_legs']:
        if leg['status']!='C' or leg['ts']>=stamp:continue
        net=leg['qty']*((leg['price']/raw['entry_price']-1)*10000-tm.cost_at(cost,raw['entry_ts'],leg['ts']))
        realized+=net;filled+=leg['qty']
        if leg['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN':
            first=leg['ts'] if first is None else min(first,leg['ts'])
            bank+=max(0.,net)
    left=1-filled
    marked=left*((price/raw['entry_price']-1)*10000-tm.cost_at(cost,raw['entry_ts'],stamp))
    return dict(first_partial_fill_ts=first,lot_realized_bank_net=bank,
                lot_realized_net=realized,lot_remaining_mark_net=marked,
                lot_marked_net=realized+marked,remaining_qty=left)


def cut_at_open(raw,trace,bars,j,decision):
    """Preserve source fills due at this open, then close residual once."""
    stamp=bars[j].open_ts
    if cap.remaining(raw,stamp,include_equal=True)==0:return False
    kept=[deepcopy(l) for l in raw['tm_legs'] if l['status']=='C' and l['ts']<=stamp]
    qty=1-fsum(l['qty'] for l in kept)
    kept.append(dict(status='C',qty=qty,index=j,ts=stamp,price=bars[j].open,reason=EXIT+'_NEXT_OPEN'))
    trace[:]=[t for t in trace if t['index']<j or t['index']==j and t['kind']=='PARTIAL_FILL']
    trace.append(dict(kind='FINAL_FILL',ts=stamp,index=j,price=bars[j].open,remaining_qty=0.,
                      decision=deepcopy(decision),slot_released=True,signal_index=raw['signal_index'],
                      lot_lock_exit=True))
    for name in ('mark_index','mark_ts','mark_price','gross_mark_bps','status','terminal_liquidation','censor_reason','pending_exit_trigger'):
        raw.pop(name,None)
    ei=raw['entry_index'];entry=raw['entry_price'];held=bars[ei:j]
    raw.update(tm_legs=kept,remaining_qty=0.,partial_count=sum(l['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' for l in kept),
               runner_activated=any(l['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' for l in kept),
               exit_index=j,exit_ts=stamp,exit_price=bars[j].open,exit_reason=EXIT+'_NEXT_OPEN',
               gross_bps=fsum(l['qty']*(l['price']/entry-1)*10000 for l in kept),hold_ms=stamp-raw['entry_ts'],
               exit_timestamp_semantics='OBSERVED_4H_OPEN',exit_trigger=deepcopy(decision),lot_lock_exit=True,
               mfe_bps=max([0.,(bars[j].open/entry-1)*10000]+[(b.high/entry-1)*10000 for b in held]),
               mae_bps=min([0.,(bars[j].open/entry-1)*10000]+[(b.low/entry-1)*10000 for b in held]))
    return True


def manage(raw,trace,bars,cost,end):
    """Apply one lot's first causal breach; source full exits have priority."""
    raw['lot_lock_exit']=False
    observations=[];peak=None
    for j in range(raw['entry_index'],len(bars)):
        clock=bars[j].open_ts+tm.BAR
        if clock>end:break
        value=lot_value(raw,clock,bars[j].close,cost)
        if value['remaining_qty']<=0:break
        if value['first_partial_fill_ts'] is not None:
            peak=value['lot_marked_net'] if peak is None else max(peak,value['lot_marked_net'])
        trigger=bool(peak is not None and value['lot_realized_bank_net']>0 and
                     value['lot_marked_net']<=peak-value['lot_realized_bank_net'])
        observations.append(dict(kind='LOT_CLOSE_OBSERVATION',signal_index=raw['signal_index'],
            index=j,ts=clock,price=bars[j].close,**value,lot_peak_marked_net=peak,trigger=trigger))
        if trigger:
            decision=dict(action='FINAL',reason=EXIT,signal_index=j,signal_ts=clock,
                          lot_signal_index=raw['signal_index'])
            if j+1<len(bars) and bars[j+1].open_ts<end:
                cut_at_open(raw,trace,bars,j+1,decision)
            else:
                raw.update(pending_lot_envelope=decision,censor_reason='PENDING_LOT_ENVELOPE_OUTSIDE_WINDOW')
            break
    return observations


def replay(rows, *, eval_start_ms, eval_end_ms, cost, enabled=True):
    if type(enabled) is not bool:
        raise ValueError('LOTLOCK_ENABLED_BOOL')
    if not enabled:
        return cap.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost=cost)
    bars=tm.native.to_bars(rows,eval_start_ms,eval_end_ms)
    original,setup_log,features=tm.native.m1_setups(bars)
    signals=[s for s in original if eval_start_ms<=s['signal_ts']<=eval_end_ms]
    if [s['signal_ts'] for s in signals] != sorted(set(s['signal_ts'] for s in signals)):
        raise ValueError('ORIGINAL_SIGNAL_CLOCK_NOT_STRICTLY_ORDERED')
    result=dict(trades=[],open_positions=[],events=[],trace=[],setup_events=setup_log,pending_entries=[],source_references={},lot_trace=[])
    campaigns=[]
    for signal in signals:
        i=signal['signal_index']; ei=i+1; stamp=signal['signal_ts']
        obs=tm.c70_context(tm.c63.context(bars,signal,tm.c63.er.context),tm.daily.observation(bars,i))
        active,available=capacity(campaigns,stamp)
        event=dict(deepcopy(signal),admission=False,status='EXCLUDED',exclusion_reason=None,er_context=obs,
                   active_normalized_qty=float(active),available_capacity=float(available),
                   available_fraction=[available.numerator,available.denominator],
                   decision_phase='CLOSE_BEFORE_EQUAL_TIMESTAMP_OPEN_FILLS',
                   capacity_reuse_entry=False,entry_normalized_qty=0.)
        # Legacy normalized simulator has no exchange lot/min-notional floor.
        # Its executable minimum is strictly positive; rational arithmetic keeps
        # that rule exact without a fitted epsilon or overlay-count cutoff.
        if available <= 0:
            reason=OCCUPIED
        elif signal['expiry'] is not None and stamp>=signal['expiry']:
            reason='SETUP_EXPIRED_BEFORE_ENTRY'
        elif not obs['eligible']:
            reason=obs['reason']
        elif ei>=len(bars) or bars[ei].open_ts>=eval_end_ms:
            reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
        elif bars[ei].open<=signal['floor'] or signal['target'] is not None and bars[ei].open>=signal['target']:
            reason='GAP_INVALIDATES_FIXED_SETUP'
        else:
            reason=None
        event['exclusion_reason']=reason
        if reason is None:
            qty=min(Fraction(1),available)  # reserved at close; no equal-open upsizing
            before_open,_=capacity(campaigns,stamp,include_equal=True)
            assert before_open+qty<=1, 'ENTRY_EXCEEDS_ACTUAL_AVAILABLE_CAPACITY'
            trade,opened,trace=tm.position(bars,signal,'M1',features,eval_end_ms,cost)
            raw=trade if trade is not None else opened
            result['source_references'][str(i)]=dict(raw=deepcopy(raw),trace=deepcopy(trace))
            observations=manage(raw,trace,bars,cost,eval_end_ms)
            for t in observations:
                t.update(allocation_numerator=qty.numerator,allocation_denominator=qty.denominator,
                         cash_semantics='UNIT_REFERENCE; NORMALIZED_FIELDS_ARE_ACTUAL_ALLOCATED_LOT')
                for name in ('lot_realized_bank_net','lot_realized_net','lot_remaining_mark_net',
                             'lot_marked_net','lot_peak_marked_net','remaining_qty'):
                    t['normalized_'+name]=None if t[name] is None else float(qty)*t[name]
            result['lot_trace'].extend(observations)
            trade=raw if 'exit_ts' in raw else None
            raw.update(allocation_numerator=qty.numerator,allocation_denominator=qty.denominator,
                       allocated_normalized_qty=float(qty),capacity_reuse_entry=active>0)
            for t in trace:
                t['allocation_numerator']=qty.numerator;t['allocation_denominator']=qty.denominator
                if 'qty' in t:t['normalized_fill_qty']=float(qty)*t['qty']
                if 'remaining_qty' in t:t['remaining_normalized_qty']=float(qty)*t['remaining_qty']
            result['trades' if trade is not None else 'open_positions'].append(raw)
            result['trace'].extend(trace);campaigns.append(raw)
            event.update(admission=True,status='COMPLETED' if trade is not None else 'CENSORED',
                         entry_normalized_qty=float(qty),capacity_reuse_entry=active>0,
                         active_after_entry=float(before_open+qty))
        elif reason=='NO_NEXT_OPEN_IN_APPROVED_WINDOW':
            result['pending_entries'].append(deepcopy(event))
        result['events'].append(event)
    # All fill instants, including overlaps with no intervening entry signals.
    stamps=sorted({r['entry_ts'] for r in campaigns} |
                  {l['ts'] for r in campaigns for l in r['tm_legs'] if l['status']=='C'})
    result['capacity_timeline']=[dict(ts=t,active_after_open=float(capacity(campaigns,t,include_equal=True)[0])) for t in stamps]
    excluded=sum(not e['admission'] for e in result['events'])
    assert len(campaigns)+excluded==len(signals),'SIGNAL_ACCOUNTING'
    result['audit']=dict(rule=RULE,scope=SCOPE,change_axis='ZEL_LOT_LEVEL_POST_PARTIAL_RISK_ENVELOPE',
        lot_lock_triggers=sum(t['trigger'] for t in result['lot_trace']),
        lot_lock_exited_campaigns=sum(r['lot_lock_exit'] for r in campaigns),
        source_manager=tm.RULES['C70_TM'],entry_rule=tm.C70_RULE,raw_signals=len(signals),
        completed=len(result['trades']),open=len(result['open_positions']),excluded=excluded,
        capacity_reuse_entries=sum(r['capacity_reuse_entry'] for r in campaigns),
        same_symbol_max_normalized_qty=1.,minimum_normalized_quantity='STRICTLY_POSITIVE_EXACT_RATIONAL',
        comparison_mode='FULL_CHRONOLOGICAL',fresh_flat_start=True,new_exchange_orders=0,
        independent=False,formal_credit=0,production_compatibility=False)
    return result
