"""One causal post-partial group envelope over frozen TM/CAPREUSE semantics.

Unit source paths are immutable references, materialized once per admitted
signal. Only completed fills and observations enter group state. No I/O/CLI.
"""
from copy import deepcopy
from fractions import Fraction
from math import fsum
from backend.research.rebuild import c70_tm_capreuse_v1 as cap

tm=cap.tm
SCOPE='C70_CUMULATIVE_PROFITLOCK_AFTER_PR1262_V1'
RULE='C70_CUMULATIVE_PROFITLOCK_V1'
EXIT='ZEL_POST_PARTIAL_RISK_ENVELOPE'


def assert_authorized(scope,status):
    if scope!=SCOPE or status!='FROZEN_AUTHORIZED_FIRST_FULL':
        raise ValueError('SCOPE_REPORT_ONLY_OR_NOT_AUTHORIZED')


def group_value(lots,stamp,price,cost):
    """Completed close BEFORE equal-time next-open fills; self-financing group.

Realized cash of all group members remains until the group is flat. Only the
remaining active quantity is marked. Removing closed-member cash would create
an artificial giveback; it is not an economic loss under inherited accounting.
"""
    bank=realized=marked=gross=cost_total=0.;first=None;active=[]
    for raw in lots:
        q=float(cap.allocation(raw));filled=0.
        for leg in raw['tm_legs']:
            if leg['status']!='C' or leg['ts']>=stamp:continue
            w=q*leg['qty'];g=w*(leg['price']/raw['entry_price']-1)*10000
            paid=w*tm.cost_at(cost,raw['entry_ts'],leg['ts']);net=g-paid
            realized+=net;gross+=g;cost_total+=paid;filled+=leg['qty']
            if leg['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN':
                first=leg['ts'] if first is None else min(first,leg['ts']);bank+=max(0.,net)
        remaining=q*(1-filled)
        if remaining>0:
            g=remaining*(price/raw['entry_price']-1)*10000
            paid=remaining*tm.cost_at(cost,raw['entry_ts'],stamp)
            marked+=g-paid;gross+=g;cost_total+=paid
            active.append(dict(signal_index=raw['signal_index'],qty=remaining))
    return dict(realized_bank_net=bank,realized_net=realized,remaining_mark_net=marked,
                group_marked_net=realized+marked,gross_bps=gross,cost_bps=cost_total,
                first_partial_fill_ts=first,active_lots=active)


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
                      risk_envelope_exit=True))
    for name in ('mark_index','mark_ts','mark_price','gross_mark_bps','status','terminal_liquidation','censor_reason','pending_exit_trigger'):
        raw.pop(name,None)
    ei=raw['entry_index'];entry=raw['entry_price'];held=bars[ei:j]
    raw.update(tm_legs=kept,remaining_qty=0.,partial_count=sum(l['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' for l in kept),
               runner_activated=any(l['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' for l in kept),
               exit_index=j,exit_ts=stamp,exit_price=bars[j].open,exit_reason=EXIT+'_NEXT_OPEN',
               gross_bps=fsum(l['qty']*(l['price']/entry-1)*10000 for l in kept),hold_ms=stamp-raw['entry_ts'],
               exit_timestamp_semantics='OBSERVED_4H_OPEN',exit_trigger=deepcopy(decision),risk_envelope_exit=True,
               mfe_bps=max([0.,(bars[j].open/entry-1)*10000]+[(b.high/entry-1)*10000 for b in held]),
               mae_bps=min([0.,(bars[j].open/entry-1)*10000]+[(b.low/entry-1)*10000 for b in held]))
    return True


def replay(rows,*,eval_start_ms,eval_end_ms,cost,enabled=True):
    if type(enabled) is not bool:raise ValueError('PROFITLOCK_ENABLED_BOOL')
    if not enabled:return cap.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost=cost)
    bars=tm.native.to_bars(rows,eval_start_ms,eval_end_ms)
    original,setup_log,features=tm.native.m1_setups(bars)
    signals={s['signal_index']:s for s in original if eval_start_ms<=s['signal_ts']<=eval_end_ms}
    if len(signals)!=sum(eval_start_ms<=s['signal_ts']<=eval_end_ms for s in original):raise ValueError('DUPLICATE_SIGNAL')
    campaigns=[];traces={};references={};events=[];group_trace=[];groups={}
    group=None;peak=None;pending_entry=None;pending_lock=None;triggers=0
    for j,b in enumerate(bars):
        stamp=b.open_ts
        # Old source fills and risk fills precede a reserved new entry. An entry
        # reserved at the prior close is never upsized by these same-open exits.
        if pending_lock is not None and stamp<eval_end_ms:
            exited=[]
            for raw in groups[pending_lock['group_id']]:
                if cap.remaining(raw,stamp)>0:
                    changed=cut_at_open(raw,traces[raw['signal_index']],bars,j,pending_lock['decision'])
                    exited.append(dict(signal_index=raw['signal_index'],risk_exit=changed,exit_reason=raw.get('exit_reason')))
            group_trace.append(dict(kind='GROUP_EXIT_FILL',ts=stamp,index=j,group_id=pending_lock['group_id'],
                                    decision=deepcopy(pending_lock['decision']),lots=exited))
            pending_lock=None
        if group is not None and not any(cap.remaining(r,stamp,include_equal=True)>0 for r in groups[group]):
            group_trace.append(dict(kind='GROUP_FLAT_RESET',ts=stamp,index=j,group_id=group))
            group=None;peak=None
        if pending_entry is not None:
            signal,event,q=pending_entry;pending_entry=None
            if b.open<=signal['floor'] or signal['target'] is not None and b.open>=signal['target']:
                event['exclusion_reason']='GAP_INVALIDATES_FIXED_SETUP'
            else:
                before,available=cap.capacity(campaigns,stamp,include_equal=True);assert q<=available
                if group is None:
                    group='ROOT:'+str(signal['signal_index']);groups[group]=[];peak=None
                    group_trace.append(dict(kind='GROUP_ROOT_ENTRY',ts=stamp,index=j,group_id=group))
                closed,opened,trace=tm.position(bars,signal,'M1',features,eval_end_ms,cost)
                raw=closed if closed is not None else opened
                references[str(signal['signal_index'])]=dict(raw=deepcopy(raw),trace=deepcopy(trace))
                raw.update(allocation_numerator=q.numerator,allocation_denominator=q.denominator,
                           allocated_normalized_qty=float(q),capacity_reuse_entry=event['active_normalized_qty']>0,
                           group_id=group,risk_envelope_exit=False)
                campaigns.append(raw);groups[group].append(raw);traces[signal['signal_index']]=trace
                event.update(admission=True,exclusion_reason=None,entry_normalized_qty=float(q),
                             capacity_reuse_entry=raw['capacity_reuse_entry'],group_id=group,
                             active_after_entry=float(before+q))
        close_ts=stamp+tm.BAR
        if group is not None:
            value=group_value(groups[group],close_ts,b.close,cost)
            armed=value['first_partial_fill_ts'] is not None
            if armed:peak=value['group_marked_net'] if peak is None else max(peak,value['group_marked_net'])
            trigger=bool(armed and value['realized_bank_net']>0 and value['group_marked_net']<=peak-value['realized_bank_net'])
            obs=dict(kind='GROUP_CLOSE_OBSERVATION',ts=close_ts,index=j,group_id=group,price=b.close,
                     **value,peak_group_marked_net=peak,trigger=trigger)
            group_trace.append(obs)
            if trigger:
                triggers+=1
                decision=dict(action='FINAL',reason=EXIT,signal_index=j,signal_ts=close_ts,group_id=group)
                pending_lock=dict(group_id=group,decision=decision)
                if j+1>=len(bars) or bars[j+1].open_ts>=eval_end_ms:
                    for raw in groups[group]:
                        if cap.remaining(raw,close_ts)>0:
                            raw.update(pending_risk_envelope=deepcopy(decision),censor_reason='PENDING_RISK_ENVELOPE_OUTSIDE_WINDOW')
        if j not in signals:continue
        signal=signals[j];active,available=cap.capacity(campaigns,close_ts)
        obs=tm.c70_context(tm.c63.context(bars,signal,tm.c63.er.context),tm.daily.observation(bars,j))
        event=dict(deepcopy(signal),admission=False,status='EXCLUDED',exclusion_reason=None,er_context=obs,
                   active_normalized_qty=float(active),available_capacity=float(available),
                   available_fraction=[available.numerator,available.denominator],entry_normalized_qty=0.,
                   decision_phase='CLOSE_BEFORE_EQUAL_TIMESTAMP_OPEN_FILLS',capacity_reuse_entry=False)
        if available<=0:reason=cap.OCCUPIED
        elif signal['expiry'] is not None and close_ts>=signal['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
        elif not obs['eligible']:reason=obs['reason']
        elif j+1>=len(bars) or bars[j+1].open_ts>=eval_end_ms:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
        else:reason=None
        event['exclusion_reason']=reason;events.append(event)
        if reason is None:pending_entry=(signal,event,min(Fraction(1),available))
    by={r['signal_index']:r for r in campaigns}
    for event in events:
        if event['admission']:event['status']='COMPLETED' if 'exit_ts' in by[event['signal_index']] else 'CENSORED'
    trace=[]
    for raw in campaigns:
        q=float(cap.allocation(raw))
        for t in traces[raw['signal_index']]:
            t.update(allocation_numerator=raw['allocation_numerator'],allocation_denominator=raw['allocation_denominator'])
            if 'qty' in t:t['normalized_fill_qty']=q*t['qty']
            if 'remaining_qty' in t:t['remaining_normalized_qty']=q*t['remaining_qty']
            trace.append(t)
    times=sorted({r['entry_ts'] for r in campaigns}|{l['ts'] for r in campaigns for l in r['tm_legs'] if l['status']=='C'})
    timeline=[dict(ts=t,active_after_open=float(cap.capacity(campaigns,t,include_equal=True)[0])) for t in times]
    return dict(trades=[r for r in campaigns if 'exit_ts' in r],open_positions=[r for r in campaigns if 'exit_ts' not in r],
                events=events,trace=trace,setup_events=setup_log,pending_entries=[e for e in events if e['exclusion_reason']=='NO_NEXT_OPEN_IN_APPROVED_WINDOW'],
                group_trace=group_trace,source_references=references,capacity_timeline=timeline,
                audit=dict(rule=RULE,scope=SCOPE,source_manager=tm.RULES['C70_TM'],entry_rule=tm.C70_RULE,
                           change_axis=EXIT,raw_signals=len(events),completed=sum('exit_ts' in r for r in campaigns),
                           open=sum('exit_ts' not in r for r in campaigns),excluded=sum(not e['admission'] for e in events),
                           capacity_reuse_entries=sum(r['capacity_reuse_entry'] for r in campaigns),
                           profitlock_triggers=triggers,profitlock_exited_campaigns=sum(r['risk_envelope_exit'] for r in campaigns),
                           same_symbol_max_normalized_qty=1.,new_exchange_orders=0,independent=False,formal_credit=0,
                           production_compatibility=False))
