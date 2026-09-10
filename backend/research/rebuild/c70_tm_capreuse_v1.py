"""ZEL occupancy repair; frozen PR1260 manager, original reg71 entry rules.

Independent unit lifecycle paths are merged using only fills STRICTLY earlier
than each signal-close decision. Future path/PnL never selects or sizes entries.
At an equal timestamp: close decision, old open fills, reserved new entry.
Pure research function: no dispatcher, order, network or production authority.
"""
from copy import deepcopy
from fractions import Fraction
from backend.research.rebuild import c63_c70_trader_management_v1 as tm

SCOPE = 'C70_TM_PARTIAL_CAPACITY_REUSE_AFTER_PR1260_V1'
RULE = 'C70_TM_CAPREUSE_V1'
OCCUPIED = 'ACTUAL_POSITION_OCCUPIED_AT_DECISION'


def allocation(raw):
    return Fraction(raw.get('allocation_numerator', 1), raw.get('allocation_denominator', 1))


def remaining(raw, stamp, *, include_equal=False):
    """Reference quantity from actual observable fills, never exit decisions."""
    if raw['entry_ts'] > stamp:
        return Fraction(0)
    released = sum((Fraction(l['qty']).limit_denominator(3) for l in raw['tm_legs']
                    if l['status']=='C' and (l['ts'] < stamp or include_equal and l['ts']==stamp)), Fraction(0))
    return allocation(raw) * (1-released)


def capacity(campaigns, stamp, *, include_equal=False):
    active = sum((remaining(r, stamp, include_equal=include_equal) for r in campaigns), Fraction(0))
    if not 0 <= active <= 1:
        raise AssertionError('SAME_SYMBOL_CAPACITY_OVERBOOKED')
    return active, 1-active


def assert_authorized(scope, status):
    if scope != SCOPE or status != 'FROZEN_AUTHORIZED_FIRST_FULL':
        raise ValueError('SCOPE_REPORT_ONLY_OR_NOT_AUTHORIZED')


def replay(rows, *, eval_start_ms, eval_end_ms, cost, enabled=True):
    if type(enabled) is not bool:
        raise ValueError('CAPREUSE_ENABLED_BOOL')
    if not enabled:
        return tm.replay(rows, parent='C70_LOCAL', eval_start_ms=eval_start_ms,
                         eval_end_ms=eval_end_ms, cost=cost)
    bars=tm.native.to_bars(rows,eval_start_ms,eval_end_ms)
    original,setup_log,features=tm.native.m1_setups(bars)
    signals=[s for s in original if eval_start_ms<=s['signal_ts']<=eval_end_ms]
    if [s['signal_ts'] for s in signals] != sorted(set(s['signal_ts'] for s in signals)):
        raise ValueError('ORIGINAL_SIGNAL_CLOCK_NOT_STRICTLY_ORDERED')
    result=dict(trades=[],open_positions=[],events=[],trace=[],setup_events=setup_log,pending_entries=[])
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
    result['audit']=dict(rule=RULE,scope=SCOPE,change_axis='ZEL_OCCUPANCY_REPAIR',
        source_manager=tm.RULES['C70_TM'],entry_rule=tm.C70_RULE,raw_signals=len(signals),
        completed=len(result['trades']),open=len(result['open_positions']),excluded=excluded,
        capacity_reuse_entries=sum(r['capacity_reuse_entry'] for r in campaigns),
        same_symbol_max_normalized_qty=1.,minimum_normalized_quantity='STRICTLY_POSITIVE_EXACT_RATIONAL',
        comparison_mode='FULL_CHRONOLOGICAL',fresh_flat_start=True,new_exchange_orders=0,
        independent=False,formal_credit=0,production_compatibility=False)
    return result
