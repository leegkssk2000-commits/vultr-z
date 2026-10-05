"""Frozen internal hypothesis; modeled development orders, never exchange fills.

Real-price feature generation is economic execution and requires the permanent
reservation exported by the independently approved GitHub owner driver.
"""
from __future__ import annotations
import copy
import math
from collections import Counter
from pathlib import Path

from ops import scalp7_clocked_execution_v1 as clock
from ops import squeeze_nonpositive_exit_v1 as baseline
from ops.kp_committed_cursor_snapshot_v1 import require, sha, SYMBOLS
from ops.kp_connected_research_validation_v1 import build_frames, encoded, write_once, START, END, PRICE_SHA

ROOT = Path(__file__).resolve().parents[1]
PARENT = clock.PARENT
CHILD = 'scalp7_squeeze_release_ema21_limit_utc30m_v1'
IDENTITIES = (CHILD,)
BATCH = 'ISSUE1358_SQUEEZE_EMA21_LIMIT_20261005_V1'
MODE = 'MODELED_DEVELOPMENT_EMA21_LIMIT_RECEIPT_CLOCK_V1'
CLAIM_REF = 'refs/heads/research-execution-claims/issue1358-ema21-limit-20261005-v1'
MINUTE, TF = clock.MINUTE, clock.TF
saved_parent = baseline.saved_parent


class LimitOrder:
    """Restartable one-episode order. Terminal states never produce another fill.

    Touch is a modeled full-size fill at the limit, including a lower opening
    gap: the limit is an adverse entry price bound, not an observed transaction.
    No maker credit. Last processed minute is part of the serialized state.
    """
    def __init__(self, key, created, effective, expires, limit):
        require(created < effective < expires, 'ORDER_CLOCK_PROFILE')
        require(math.isfinite(limit) and limit > 0, 'LIMIT_PRICE')
        self.state = dict(key=key, created=created, effective=effective,
                          expires=expires, limit=limit, status='PENDING',
                          last_minute=-1, fill=None)

    @classmethod
    def restore(cls, snapshot):
        obj = cls.__new__(cls)
        obj.state = copy.deepcopy(snapshot)
        return obj

    def snapshot(self):
        return copy.deepcopy(self.state)

    def cancel(self, at):
        require(at >= self.state['created'], 'CANCEL_BEFORE_CREATE')
        if self.state['status'] == 'PENDING':
            self.state.update(status='CANCELLED', cancelled=at)

    def tick(self, minute):
        s = self.state
        t = int(minute[0])
        if s['status'] != 'PENDING' or t <= s['last_minute']:
            return None
        s['last_minute'] = t
        if t >= s['expires']:
            s['status'] = 'EXPIRED_UNFILLED'
            return None
        if t < s['effective']:
            return None
        if float(minute[3]) <= s['limit']:
            fill = dict(minute_open_ms=t, witness_ms=max(t+MINUTE, int(minute[6])),
                        price=s['limit'], gap_open=float(minute[1]) < s['limit'],
                        price_semantics='ADVERSE_LIMIT_BOUND_NOT_OBSERVED_TRANSACTION',
                        intraminute_time_unknown=True, evidence='MODELED_DEVELOPMENT_EVENTS')
            s.update(status='FILLED', fill=fill)
            return fill
        return None


def simulate(signal, frame, minutes, ready, cost, admission, callback):
    require(signal['identity'] == PARENT and signal['side'] == 1
            and signal['timeframe_min'] == 30, 'NATIVE_PARENT_LONG_ONLY')
    require(not signal.get('legs') and not signal.get('partial_take_profit_r')
            and signal.get('take_profit_r') is None, 'UNSUPPORTED_ORDER_PROFILE')
    opened = int(signal['signal_open_ts_ms'])
    require(opened in ready, 'SIGNAL_CLOCK_MISSING')
    require(ready[opened] >= opened+TF and int(signal['signal_ts_ms']) >= opened+TF,
            'INCOMPLETE_SIGNAL_BAR')
    available = max(ready[opened], int(signal['signal_ts_ms']))
    effective, expires = clock.next_minute(available), opened+2*TF
    key = f"{CHILD}|{signal['symbol']}|{signal['signal_ts_ms']}"
    census = dict(key=key, symbol=signal['symbol'], signal_ts_ms=signal['signal_ts_ms'],
                  signal_open_ts_ms=opened, available_ms=available, effective_ms=effective,
                  expires_ms=expires, evidence='MODELED_DEVELOPMENT_EVENTS')
    if effective >= expires:
        return None, None, -1, {**census, 'status':'REJECTED_STALE'}, []
    anchor = float(signal['stop_price'])+2*float(signal['meta']['atr_price'])
    gate = admission(signal, anchor)
    if gate.get('reject'):
        return None, None, -1, {**census, 'status':'REJECTED_GATE', 'reason':gate.get('reason')}, []
    stop = float(gate.get('stop_price', signal['stop_price']))
    risk = anchor-stop
    require(math.isfinite(stop) and stop > 0 and risk > 0
            and math.isfinite(cost) and cost > 0, 'RISK_AND_COST')
    order = LimitOrder(key, available, effective, expires, anchor)
    events = [dict(kind='ORDER_CREATED', at_ms=available, effective_ms=effective,
                   expires_ms=expires, limit=anchor)]
    fill, offset = None, None
    for mi, minute in enumerate(minutes):
        fill = order.tick(minute)
        if fill:
            offset = mi
            break
        if order.state['status'] != 'PENDING':
            break
    census.update(order=order.snapshot())
    if fill is None:
        expired = order.state['status'] == 'EXPIRED_UNFILLED' or (minutes and minutes[-1][0]+MINUTE >= expires)
        if expired:
            order.state['status'] = 'EXPIRED_UNFILLED'
            census['order'] = order.snapshot()
        status = 'EXPIRED_UNFILLED' if expired else 'PENDING_END'
        if expired:
            events.append(dict(kind='ORDER_EXPIRED', at_ms=expires))
        # Timer expiry is known at the start of its minute; no invented ack.
        return None, None, expires-1 if expired else 2**63-1, {**census, 'status':status}, events
    entered = fill['minute_open_ms']
    events.append(dict(kind='MODELED_FILL', **fill))
    p = dict(signal=copy.deepcopy(signal), side=1, entry_price=anchor,
             entry_prices={signal['symbol']:anchor}, entry_ts_ms=entered,
             stop_price=stop, initial_stop=stop, initial_risk=risk, hold_bars=0,
             mfe_R=0.0, mae_R=0.0, cost_bps=cost, remaining=1.0, realized_parts_bps=0.0)
    records = frame.to_dict('records')
    # Touch time within the entry minute is unknown. Exclude the entire entry
    # minute/bar from subsequent management features and excursion estimates.
    decisions = [(clock.next_minute(ready[int(r['open_ts_ms'])]), i)
                 for i,r in enumerate(records)
                 if int(r['open_ts_ms']) >= entered+MINUTE and int(r['open_ts_ms']) in ready]
    require(all(decisions[i][0] <= decisions[i+1][0] for i in range(len(decisions)-1)), 'NONCAUSAL_QUEUE')
    di, last_eval = 0, -1
    first = minutes[0][0]

    def finish(px, stamp, witness, reason):
        gross = (px/anchor-1)*10000
        row = {**{k:signal[k] for k in ('lane','symbol','timeframe_min','signal_open_ts_ms','signal_ts_ms')},
               'identity':CHILD, 'side':1, 'entry_ts_ms':entered, 'exit_ts_ms':stamp,
               'outcome_available_ts_ms':max(witness, fill['witness_ms']),
               'entry_prices':{signal['symbol']:anchor}, 'exit_prices':{signal['symbol']:px},
               'gross_bps':gross, 'cost_bps':cost, 'net_bps':gross-cost, 'reason':reason,
               'hold_bars':p['hold_bars'], 'hold_minutes':(stamp-entered)/MINUTE,
               'mfe_R':p['mfe_R'], 'mae_R':p['mae_R'], 'regime':signal['meta'].get('regime','UNCLASSIFIED'),
               'signal':signal, 'signal_available_ms':available, 'execution_profile':MODE,
               'order_authority':'BLOCKED', 'fill_is_model_not_exchange':True, 'entry_model':fill,
               'mfe_mae_semantics':'RECEIVED_POST_FILL_MINUTE_PREFIX_AT_MANAGEMENT'}
        events.append(dict(kind='EXIT', at_ms=stamp, witness_ms=row['outcome_available_ts_ms'], reason=reason))
        return row, None, row['outcome_available_ts_ms'], {**census, 'status':'FILLED_COMPLETED'}, events

    for mi in range(offset, len(minutes)):
        m = minutes[mi]
        t = m[0]
        o,h,l,c = map(float,m[1:5])
        while di < len(decisions) and decisions[di][0] <= t:
            activation, fi = decisions[di]
            di += 1
            if fi <= last_eval:
                continue
            last_eval = fi
            bar = records[fi]
            bar_open, bar_close = int(bar['open_ts_ms']), int(bar['close_ts_ms'])
            require(ready[bar_open] < activation <= t and bar_close <= ready[bar_open], 'UNRECEIVED_CALLBACK')
            whole = minutes[offset+1:(bar_close-first)//MINUTE]
            require(bool(whole) and max(x[6] for x in whole) < activation, 'UNRECEIVED_POSITION_PREFIX')
            known = [x for x in minutes[offset+1:mi] if x[6] < activation]
            require(bool(known), 'NO_POST_FILL_RECEIVED_PREFIX')
            p['mfe_R'] = max(0.0,(max(float(x[2]) for x in known)-anchor)/risk)
            p['mae_R'] = max(0.0,(anchor-min(float(x[3]) for x in known))/risk)
            p['hold_bars'] += 1
            before = copy.deepcopy(p)
            update = callback(p, bar, frame.iloc[:fi+1])
            require(p == before and not update.get('partial_fraction'), 'UNSUPPORTED_CALLBACK_MUTATION')
            events.append(dict(kind='MANAGEMENT', bar_open_ms=bar_open,
                               input_ready_ms=ready[bar_open], order_effective_ms=activation, update=update))
            if update.get('exit_next_open') or p['hold_bars'] >= signal['max_hold_bars']:
                return finish(o,t,t, str(update['reason']) if update.get('exit_next_open') else 'MAX_HOLD_CLOCKED_OPEN')
            if update.get('next_stop') is not None:
                new = float(update['next_stop'])
                require(math.isfinite(new) and new > 0, 'STOP_UPDATE_INVALID')
                p['stop_price'] = max(p['stop_price'],new)
        if l <= p['stop_price']:
            gap = o < p['stop_price']
            # In the fill minute choose the adverse entry-before-stop path.
            return finish(o if gap else p['stop_price'], t if gap else t+MINUTE,
                          max(t+MINUTE,m[6]), 'ADVERSE_OPEN_GAP_STOP' if gap else 'MINUTE_ENTRY_STOP_FIRST')
    unresolved = dict(signal=signal,position=p,reason='UNRESOLVED_END_NO_FORCE_CLOSE')
    return None, unresolved, 2**63-1, {**census, 'status':'FILLED_UNRESOLVED'}, events


def replay(signals, frames, minutes, ready, costs, admission, callback):
    trades, unresolved, census, events, owned = [], [], [], [], {}
    seen = set()
    ordered = sorted(signals,key=lambda s:(max(ready[int(s['signal_open_ts_ms'])],int(s['signal_ts_ms'])),s['symbol']))
    for signal in ordered:
        key = f"{CHILD}|{signal['symbol']}|{signal['signal_ts_ms']}"
        require(key not in seen, 'DUPLICATE_EPISODE')
        seen.add(key)
        available = max(ready[int(signal['signal_open_ts_ms'])],int(signal['signal_ts_ms']))
        if clock.next_minute(available) <= owned.get(signal['symbol'],-1):
            census.append(dict(key=key,symbol=signal['symbol'],signal_ts_ms=signal['signal_ts_ms'],
                               available_ms=available,status='REJECTED_OCCUPIED', evidence='MODELED_DEVELOPMENT_EVENTS'))
            continue
        row, position, release, opportunity, trace = simulate(signal,frames[signal['symbol']],
            minutes[signal['symbol']],ready,float(costs[signal['symbol']]),admission,callback)
        census.append(opportunity)
        events.extend({'key':key,'event_id':f'{key}|{i}','evidence':'MODELED_DEVELOPMENT_EVENTS',**e} for i,e in enumerate(trace))
        owned[signal['symbol']] = release
        if row:
            trades.append(row)
        if position:
            unresolved.append(position)
    require(len(census) == len(signals) and len({c['key'] for c in census}) == len(signals),'CENSUS_BALANCE')
    return dict(identity=CHILD,signals=signals,trades=trades,unresolved=unresolved,census=census,events=events,
                status_counts=dict(Counter(c['status'] for c in census)))


def run_lanes(data, contract, out):
    from backend.research.rebuild import scalp7_positive_lanes_v2 as rules
    from backend.research.rebuild import scalp7_metrics_v2 as metrics
    from ops.kp_committed_cursor_snapshot_v1 import load
    receipt = load((out/'RESERVATION.json').read_bytes())
    require(receipt['batch_id'] == BATCH and receipt['claim_ref'] == CLAIM_REF
            and receipt['claim_commit_sha'] and receipt['independent_approval_commit_sha']
            and receipt['contract_sha256'] == sha(encoded(contract)), 'CLAIM_BEFORE_REAL_SIGNALS')
    parent = saved_parent()  # Immutable baseline, not another parent FULL.
    frames, clocks, manifest = build_frames(data)
    ready = clock.prefix_clocks(clocks)
    for symbol in SYMBOLS:
        clock.verify_minute_rows(data['minutes'][symbol])
    costs = contract['reference_costs_bps']
    require(costs == data['contracts']['cost_snapshot']['content']['costs_bps'],'COST_CHANGED')
    signals = [s for s in rules.generate_signals(frames,costs=costs,identities=(PARENT,))
               if START <= s['signal_open_ts_ms'] and s['signal_ts_ms'] < END]
    require(sha(encoded(signals)) == contract['parent_signals_sha256'],'CONTROL_SETUP_STREAM_CHANGED_NO_AUTO_REPLAY')
    timed = {}
    for symbol,f in frames.items():
        f = f.copy()
        f['available_ts_ms'] = [ready.get(int(r.open_ts_ms),int(r.available_ts_ms)) for r in f.itertuples()]
        timed[symbol] = f
    result = replay(signals,timed,data['minutes'],ready,costs,rules.entry_update,rules.exit_update)
    for mult in (1,2):
        result['reference'+str(mult)+'x'] = metrics.summarize(result['trades'],START,END,cost_multiplier=mult)
    result['paired'] = baseline.paired(parent,result)
    lane = out/CHILD
    lane.mkdir(exist_ok=False)
    write_once(lane,'RESULT.json',result)
    summary = dict(schema='issue1358.ema21_limit.result.v1',batch_id=BATCH,identity=CHILD,mode=MODE,
                   input_sha256=PRICE_SHA,economic_lane_executions=1,parent_replays=0,
                   candidate_count=1,status_counts=result['status_counts'],signal_count=len(signals),
                   trade_count=len(result['trades']),unresolved_count=len(result['unresolved']),
                   reference1x=result['reference1x'],reference2x=result['reference2x'],paired=result['paired'],
                   baseline_reference1x=parent['reference1x'],baseline_reference2x=parent['reference2x'],
                   event_evidence='MODELED_DEVELOPMENT_EVENTS',order_authority='BLOCKED',
                   unused_oos_certified=False,realtime_fill_certified=False,
                   account_nav=None,account_dd=None,g5_promotion=False,live_orders=0)
    write_once(out,'SUMMARY.json',summary)
    return summary
