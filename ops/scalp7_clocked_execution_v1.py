"""Receipt-clocked research execution shared by frozen Squeeze parent/BE1R.

No trading API, server writes, live promotion, model fitting, or parameter search.
Uses the existing verified input and strategy functions, not the spent KP runner.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter
from datetime import datetime, timezone
import math
import os
import stat
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops.kp_committed_cursor_snapshot_v1 import load, require, sha, SYMBOLS
from ops.kp_connected_research_validation_v1 import (
    build_frames, bounded_gunzip, encoded, write_once, START, END, SOURCE_START,
    PRICE_SHA, CONFIG_SHA, INPUT_FIELDS,
)

MINUTE = 60_000
TF = 30 * MINUTE
PARENT = 'scalp7_squeeze_panic_cost4_parent_utc30m_v2'
CHILD = 'scalp7_squeeze_panic_cost4_be1r_utc30m_v2'
IDENTITIES = (PARENT, CHILD)
MODE = 'RECORDED_RECEIPT_CLOCK_NEXT_MINUTE_SQUEEZE_RESEARCH_V1'
BATCH = 'SCALP7_SQUEEZE_CLOCKED_PARENT_BE1R_20261004_V1'
CLAIM_ROOT = Path('/mnt/data/scalp7_economic_claims')


def owner_fingerprint():
    # An execution-owner binding, not a trading credential; never exported raw.
    return sha(Path('/proc/sys/kernel/random/boot_id').read_bytes()
               + b'|' + Path('/etc/hostname').read_bytes())


def acquire_reservation(contract, activation, output):
    """Atomic, persistent, single-owner claim independent of caller output.

    The reviewed batch is executable only on its predeclared host. Different
    checkouts/outputs on that host share this fixed namespace. Claim is never
    released on failure or completion. Cross-host continuation is NOT supported.
    """
    require(contract['batch_id'] == BATCH and activation['batch_id'] == BATCH,
            'RESERVATION_BATCH_MISMATCH')
    require(contract['execution_owner_sha256'] == owner_fingerprint(),
            'WRONG_EXECUTION_OWNER_NO_CROSS_HOST_REPLAY')
    CLAIM_ROOT.mkdir(mode=0o700, parents=False, exist_ok=True)
    fd = os.open(CLAIM_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(info.st_uid == os.geteuid() and stat.S_ISDIR(info.st_mode),
                'UNOWNED_RESERVATION_DIRECTORY')
        name = BATCH + '.json'
        handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=fd)
        receipt = {'batch_id': BATCH, 'contract_sha256': activation['contract_sha256'],
                   'activation_sha256': sha(encoded(activation)), 'output': str(output.resolve()),
                   'state': 'CLAIMED_NONRETRYABLE', 'max_lane_executions': 2,
                   'claimed_utc': datetime.now(timezone.utc).isoformat(),
                   'owner_sha256': contract['execution_owner_sha256']}
        with os.fdopen(handle, 'wb') as stream:
            stream.write(encoded(receipt)); stream.flush(); os.fsync(stream.fileno())
        os.fsync(fd)
        return receipt
    finally:
        os.close(fd)



def next_minute(stamp: int) -> int:
    require(type(stamp) is int and stamp >= 0, 'INTEGER_CLOCK_REQUIRED')
    return (stamp // MINUTE + 1) * MINUTE


def prefix_clocks(clocks):
    """All six causal price prefixes, O(symbols*bars), not per-signal rescans."""
    require(set(clocks) == set(SYMBOLS), 'SIX_CLOCKS_REQUIRED')
    stamps = sorted(clocks[SYMBOLS[0]])
    require(all(sorted(clocks[s]) == stamps for s in SYMBOLS), 'CLOCK_GRID_MISMATCH')
    latest = {s: 0 for s in SYMBOLS}
    out = {}
    for stamp in stamps:
        for s in SYMBOLS:
            t = clocks[s][stamp]
            require(type(t) is int and t >= stamp + TF, 'INVALID_RECEIPT_CLOCK')
            latest[s] = max(latest[s], t)
        out[stamp] = max(latest.values())
    return out


def verify_minute_rows(rows):
    previous = None
    for r in rows:
        require(len(r) == len(INPUT_FIELDS), 'MINUTE_SCHEMA')
        stamp, received = r[0], r[6]
        require(type(stamp) is int and stamp % MINUTE == 0 and type(received) is int
                and received >= stamp + MINUTE, 'MINUTE_CLOCK')
        require(previous is None or stamp == previous + MINUTE, 'MINUTE_GAP')
        values = [float(v) for v in r[1:6]]
        require(all(math.isfinite(v) for v in values), 'NONFINITE_MINUTE')
        o,h,l,c,v = values
        require(0 < l <= min(o,c) <= max(o,c) <= h and v >= 0, 'MINUTE_GEOMETRY')
        previous = stamp


def simulate(signal, frame, minute_rows, ready, cost, admission, callback):
    """A single position; callback orders activate AFTER observed 30m data.

    Initial incomplete decision bar is excluded from lifecycle evaluations.
    Resting protection is active immediately. Only full post-entry 30m bars
    feed the frozen management callback. No partial/pair policy is supported
    in this adapter version; such signals reject instead of silently degrading.
    """
    require(signal['timeframe_min'] == 30 and signal['side'] in (-1,1), 'SIGNAL_PROFILE')
    require(not signal.get('legs') and not signal.get('partial_take_profit_r')
            and signal.get('take_profit_r') is None, 'UNSUPPORTED_ORDER_PROFILE')
    source_stamp = int(signal['signal_open_ts_ms'])
    require(source_stamp in ready, 'SIGNAL_CLOCK_MISSING')
    available = max(ready[source_stamp], int(signal['signal_ts_ms']))
    entered = next_minute(available)
    # A predeclared execution TTL, not a tuned strategy parameter.
    if entered >= source_stamp + 2*TF:
        return None, None, -1, 'STALE_SIGNAL_ONE_DECISION_BAR', []
    first = minute_rows[0][0]
    offset = (entered-first)//MINUTE
    if not 0 <= offset < len(minute_rows):
        return None, None, -1, 'NO_POST_AVAILABILITY_MINUTE', []
    require(minute_rows[offset][0] == entered, 'ENTRY_MINUTE_MISSING')
    entry = float(minute_rows[offset][1]); side = int(signal['side'])
    gate = admission(signal, entry)
    if gate.get('reject'):
        return None, None, -1, str(gate.get('reason','ENTRY_REJECT')), []
    stop = float(gate.get('stop_price', signal['stop_price']))
    risk = side*(entry-stop)
    require(math.isfinite(stop) and stop > 0 and risk > 0, 'ADVERSE_INITIAL_STOP_REQUIRED')
    require(math.isfinite(cost) and cost > 0, 'POSITIVE_COST_REQUIRED')
    p = {'signal':copy.deepcopy(signal),'side':side,'entry_price':entry,
         'entry_prices':{signal['symbol']:entry},'entry_ts_ms':entered,
         'stop_price':stop,'initial_stop':stop,'initial_risk':risk,'hold_bars':0,
         'mfe_R':0.0,'mae_R':0.0,'cost_bps':cost,'remaining':1.0,'realized_parts_bps':0.0}
    events=[]; last_eval=-1
    records=frame.to_dict('records')
    # Native exit_update requires the whole evaluated bar to follow entry.
    decisions=[(next_minute(ready[int(r['open_ts_ms'])]), i) for i,r in enumerate(records)
               if int(r['open_ts_ms']) >= entered and int(r['open_ts_ms']) in ready]
    require(all(decisions[i][0] <= decisions[i+1][0] for i in range(len(decisions)-1)), 'NONCAUSAL_EVALUATION_QUEUE')
    di=0
    def finish(px, stamp, witness, reason):
        gross=side*(px/entry-1)*10000
        row={**{k:signal[k] for k in ('identity','lane','symbol','timeframe_min','signal_open_ts_ms','signal_ts_ms')},
             'side':side,'entry_ts_ms':entered,'exit_ts_ms':stamp,
             'outcome_available_ts_ms':witness,'entry_prices':{signal['symbol']:entry},
             'exit_prices':{signal['symbol']:px},'gross_bps':gross,'cost_bps':cost,
             'net_bps':gross-cost,'reason':reason,'hold_bars':p['hold_bars'],
             'hold_minutes':(stamp-entered)/MINUTE,'mfe_R':p['mfe_R'],'mae_R':p['mae_R'],
             'regime':signal['meta'].get('regime','UNCLASSIFIED'),'signal':signal,
             'signal_available_ms':available,'execution_profile':MODE,
             'order_authority':'BLOCKED','fill_is_model_not_exchange':True,
             'mfe_mae_semantics':'RECEIVED_POSTENTRY_PREFIX_AT_LAST_MANAGEMENT_NOT_FULL_PATH'}
        return row,None,witness,None,events
    for mi in range(offset,len(minute_rows)):
        m=minute_rows[mi]; t=m[0]
        o,h,l,c=map(float,m[1:5])
        # Orders based on received prefix can execute at this later minute open.
        while di<len(decisions) and decisions[di][0]<=t:
            effective,fi=decisions[di];di+=1
            bar=records[fi]; bar_open=int(bar['open_ts_ms']); bar_close=int(bar['close_ts_ms'])
            if fi <= last_eval: continue
            last_eval=fi
            require(ready[bar_open] < effective <= t and bar_close <= ready[bar_open], 'CALLBACK_BEFORE_AVAILABILITY')
            known_end=(bar_close-first)//MINUTE
            known=minute_rows[offset:known_end]
            require(bool(known) and max(x[6] for x in known) < effective, 'POSITION_PREFIX_NOT_YET_RECEIVED')
            highs=max(float(x[2]) for x in known); lows=min(float(x[3]) for x in known)
            p['mfe_R']=max(0.0,(highs-entry)/risk if side==1 else (entry-lows)/risk)
            p['mae_R']=max(0.0,(entry-lows)/risk if side==1 else (highs-entry)/risk)
            p['hold_bars']+=1
            before=copy.deepcopy(p)
            update=callback(p,bar,frame.iloc[:fi+1])
            require(p==before, 'CALLBACK_MUTATED_POSITION')
            require(not update.get('partial_fraction'), 'UNSUPPORTED_PARTIAL_CALLBACK')
            e={'bar_open_ms':bar_open,'input_ready_ms':ready[bar_open],'order_effective_ms':effective,
               'mfe_R':p['mfe_R'],'stop_before':p['stop_price'],'update':update}
            events.append(e)
            if update.get('exit_next_open') or p['hold_bars']>=signal['max_hold_bars']:
                return finish(o,t,t,str(update.get('reason')) if update.get('exit_next_open') else 'MAX_HOLD_CLOCKED_OPEN')
            if update.get('next_stop') is not None:
                new=float(update['next_stop']);require(math.isfinite(new) and new>0,'STOP_UPDATE_INVALID')
                p['stop_price']=max(p['stop_price'],new) if side==1 else min(p['stop_price'],new)
        stop=p['stop_price']
        if (l<=stop if side==1 else h>=stop):
            gap=side*(o-stop)<0
            return finish(o if gap else stop,t if gap else t+MINUTE,max(t+MINUTE,m[6]),
                          'CLOCKED_OPEN_GAP_STOP' if gap else 'CLOCKED_MINUTE_STOP_FIRST')
    return None,{'signal':signal,'position':p,'reason':'UNRESOLVED_END_NO_FORCE_CLOSE'},2**63-1,None,events


def run_lanes(data, contract, out):
    from backend.research.rebuild import scalp7_positive_lanes_v2 as rules
    from backend.research.rebuild import scalp7_metrics_v2 as metrics
    frames,clocks,manifest=build_frames(data)
    ready=prefix_clocks(clocks)
    for s in SYMBOLS: verify_minute_rows(data['minutes'][s])
    costs=contract['reference_costs_bps']
    require(costs==data['contracts']['cost_snapshot']['content']['costs_bps'],'COST_CHANGED')
    generated=rules.generate_signals(frames,costs=costs,identities=IDENTITIES)
    signals=[s for s in generated if START<=s['signal_open_ts_ms'] and s['signal_ts_ms']<END]
    # Feature histories are fixed values; ready stamps preserve late past inputs.
    timed={}
    for s,f in frames.items():
        f=f.copy()
        f['available_ts_ms']=[ready.get(int(x.open_ts_ms),int(x.available_ts_ms)) for x in f.itertuples()]
        timed[s]=f
    results={}
    for identity in IDENTITIES:
        lane=out/identity;lane.mkdir(exist_ok=False)
        write_once(lane,'STARTED.json',{'identity':identity,'started_utc':datetime.now(timezone.utc).isoformat(),'maximum_executions':1})
        selected=[s for s in signals if s['identity']==identity]
        ordered=sorted(selected,key=lambda s:(ready[int(s['signal_open_ts_ms'])],s['symbol']))
        trades=[];unresolved=[];rejects=Counter();events=[];owned={}
        for s in ordered:
            ready_at=max(ready[int(s['signal_open_ts_ms'])],int(s['signal_ts_ms']))
            if next_minute(ready_at)<=owned.get(s['symbol'],-1):rejects['POSITION_OR_ACK_OCCUPIED']+=1;continue
            row,open_pos,release,why,trace=simulate(s,timed[s['symbol']],data['minutes'][s['symbol']],ready,
                                                  float(costs[s['symbol']]),rules.entry_update,rules.exit_update)
            events.extend({'signal_key':f"{identity}|{s['symbol']}|{s['signal_ts_ms']}",**e} for e in trace)
            if why:rejects[why]+=1;continue
            owned[s['symbol']]=release
            if row:trades.append(row)
            if open_pos:unresolved.append(open_pos)
        require(len(selected)==len(trades)+len(unresolved)+sum(rejects.values()),'SIGNAL_ACCOUNTING')
        result={'identity':identity,'signals':selected,'trades':trades,'unresolved':unresolved,'rejections':dict(rejects),
                'events':events,'reference1x':metrics.summarize(trades,START,END,cost_multiplier=1),
                'reference2x':metrics.summarize(trades,START,END,cost_multiplier=2)}
        write_once(lane,'RESULT.json',result)
        write_once(lane,'COMPLETED.json',{'identity':identity,'result_sha256':sha((lane/'RESULT.json').read_bytes()),'executions':1})
        results[identity]={k:v for k,v in result.items() if k not in ('trades','signals','events','unresolved')}
        results[identity].update(signal_count=len(selected),unresolved_count=len(unresolved),event_count=len(events))
    summary={'schema':'scalp7.clocked_lanes.result.v1','mode':MODE,'lanes':results,'input_sha256':PRICE_SHA,
             'shared_frame_builds':1,'economic_lane_executions':2,'keltner_replays':0,'new_strategy_rules':0,
             'unused_oos_certified':False,'realtime_fill_certified':False,'seed_clock_assumed':True,
             'g5_promotion':False,'account_nav':None,'account_dd':None,'live_orders':0,
             'notes':['Existing historical input is consumed research, not a new validation window.',
                      'Minute OHLC market-open fills, stops and acknowledgments remain model assumptions.',
                      'Seed/config fit assumed ready before window; real observation, funding and margin are uncertified.',
                      'No service or persistent consumer is changed; frozen rules reused without tuning.']}
    write_once(out,'SUMMARY.json',summary)
    return summary


def main():
    require(not (ROOT/'research/campaigns/scalp7_20261004/clocked_lanes_v1/COMPLETION.json').exists(), 'COMPLETED_BATCH_NO_REPLAY')
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('input','contract','activation','output'):parser.add_argument('--'+name,type=Path,required=True)
    a=parser.parse_args(); raw_contract=a.contract.read_bytes(); contract=load(raw_contract); activation=load(a.activation.read_bytes())
    require(activation['contract_sha256']==sha(raw_contract),'CONTRACT_PIN')
    require(contract['mode']==MODE and tuple(contract['identities'])==IDENTITIES and contract['max_lane_executions']==2,'SCOPE_CHANGED')
    require(contract['window']=={'start_ms':START,'end_exclusive_ms':END} and contract['unused_oos_certified'] is False,'WINDOW_OR_CREDIT_CHANGED')
    require(contract['script_sha256']==sha(Path(__file__).read_bytes()),'RUNNER_CHANGED')
    for path,expected in contract['source_pins'].items():
        full=(ROOT/path).resolve(strict=True);require(full.is_relative_to(ROOT) and sha(full.read_bytes())==expected,'SOURCE_PIN:'+path)
    raw=bounded_gunzip(a.input.read_bytes(),64*1024*1024);require(sha(raw)==PRICE_SHA==contract['input_sha256'],'PRICE_PIN')
    d=load(raw)
    require(d['configured_sources_verified'] is True and d['price_bodies_verified'] is True,'INPUT_UNVERIFIED')
    require(d['config_source']['sha256']==CONFIG_SHA and d['fields']==INPUT_FIELDS and set(d['minutes'])==set(SYMBOLS),'INPUT_SCHEMA')
    require(d['config_projection']['regime_fit']==contract['frozen_regime_fit'],'FIT_CHANGED')
    claim=acquire_reservation(contract,activation,a.output)
    a.output.mkdir(parents=True,exist_ok=False)
    write_once(a.output,'RESERVATION.json',claim)
    write_once(a.output,'STARTED.json',{'contract_sha256':sha(raw_contract),'maximum_lane_executions':2,'utc':datetime.now(timezone.utc).isoformat()})
    start=time.monotonic()
    try:r=run_lanes(d,contract,a.output)
    except BaseException as exc:
        write_once(a.output,'FAILED.json',{'error':str(exc),'automatic_retry':False,'started_budget_not_reset':True});raise
    write_once(a.output,'COMPLETED.json',{'summary_sha256':sha((a.output/'SUMMARY.json').read_bytes()),'lane_executions':2,'elapsed_s':time.monotonic()-start})
    print(encoded(r).decode())

if __name__=='__main__':main()
