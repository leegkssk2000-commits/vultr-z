"""One frozen Squeeze failure-exit child; old parent economics are reused.

No signal search, old-model replay, exchange API, or live/promotion authority.
The sole new rule is observed native 30m momentum <=0 at an existing management
observation. The unchanged receipt-clocked simulator owns execution/occupancy.
"""
from __future__ import annotations
import copy
import json
import lzma
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ops import scalp7_clocked_execution_v1 as clock
from ops.kp_committed_cursor_snapshot_v1 import load, require, sha, SYMBOLS
from ops.kp_connected_research_validation_v1 import build_frames, encoded, write_once, START, END, PRICE_SHA

ROOT = Path(__file__).resolve().parents[1]
PARENT = clock.PARENT
CHILD = 'scalp7_squeeze_panic_cost4_momentum_nonpositive_utc30m_v1'
IDENTITIES = (CHILD,)
BATCH = 'SCALP7_SQUEEZE_NONPOSITIVE_EXIT_20261005_V1'
MODE = clock.MODE
RULE = 'SQUEEZE_OBSERVED_NONPOSITIVE_MOMENTUM_NEXT_OPEN'
OLD = 'research/campaigns/scalp7_20261004/clocked_lanes_v1'
BUNDLE_SHA = 'd8e64b248d25a66ccdd44e403da82284ec7f5f49fcf9ebd5be68e9876c1d6ed1'
PARENT_SHA = 'a390f985245f32d52681fea688617d01fb6eb597b1269f10a62466075a9edbc9'
TOL = 1e-7  # Arithmetic comparison only, not an economic admission gate.


def key(row):
    return row['symbol'], row['side'], row['signal_ts_ms']


def saved_parent():
    raw = (ROOT/OLD/'RESULT_BUNDLE.json.xz').read_bytes()
    require(sha(raw) == BUNDLE_SHA, 'PARENT_BUNDLE_CHANGED')
    decoder = lzma.LZMADecompressor(memlimit=256*1024*1024)
    body = decoder.decompress(raw, max_length=32*1024*1024+1)
    require(decoder.eof and not decoder.unused_data and len(body) <= 32*1024*1024, 'BUNDLE_SIZE')
    files = load(body)
    original = files[PARENT+'/RESULT.json'].encode()
    require(sha(original) == PARENT_SHA, 'PARENT_RESULT_CHANGED')
    result = load(original)
    require(result['identity'] == PARENT and not result['unresolved'], 'BASELINE_PROFILE')
    require(len(result['signals']) == 15 and len(result['trades']) == 9, 'BASELINE_COUNTS')
    require(len(set(map(key, result['signals']))) == len(result['signals']), 'DUPLICATE_BASELINE_SIGNAL')
    return result


def as_child(signal):
    require(signal['identity'] == PARENT and signal['side'] == 1, 'PARENT_LONG_ONLY')
    require(signal['meta']['be_arm_r'] is None and not signal.get('legs')
            and not signal.get('partial_take_profit_r') and signal.get('take_profit_r') is None,
            'NO_BE_PARTIAL_OR_TARGET_ADDITION')
    out = copy.deepcopy(signal)
    out['identity'] = CHILD
    out['research_parent_identity'] = PARENT
    return out


def native_signal(signal):
    require(signal['identity'] == CHILD and signal.get('research_parent_identity') == PARENT,
            'CHILD_IDENTITY_REQUIRED')
    out = copy.deepcopy(signal)
    out['identity'] = PARENT
    out.pop('research_parent_identity')
    return out


def admission(signal, price):
    from backend.research.rebuild import scalp7_positive_lanes_v2 as rules
    return rules.entry_update(native_signal(signal), price)


def management(position, bar, history):
    from backend.research.rebuild import scalp7_positive_lanes_v2 as rules
    native = copy.deepcopy(position)
    native['signal'] = native_signal(position['signal'])
    update = rules.exit_update(native, bar, history)
    # Native validation and existing exits keep priority. No new evaluation clock.
    if update.get('exit_next_open'):
        return update
    require(len(history) >= 41, 'MOMENTUM_HISTORY_REQUIRED')
    momenta = rules._last_momenta(history)
    require(all(math.isfinite(float(v)) for v in momenta), 'NONFINITE_MOMENTUM')
    if float(momenta[-1]) <= 0:
        return {'exit_next_open': True, 'reason': RULE,
                'observed_momentum': float(momenta[-1])}
    return update


def replay_child(signals, frames, minutes, ready, costs, simulate=clock.simulate):
    """Full opportunity/occupancy replay. Never substitute a saved exit price."""
    trades, unresolved, events = [], [], []
    rejects, owned = Counter(), {}
    ordered = sorted(signals, key=lambda s: (ready[int(s['signal_open_ts_ms'])], s['symbol']))
    for s in ordered:
        available = max(ready[int(s['signal_open_ts_ms'])], int(s['signal_ts_ms']))
        if clock.next_minute(available) <= owned.get(s['symbol'], -1):
            rejects['POSITION_OR_ACK_OCCUPIED'] += 1
            continue
        row, open_pos, release, why, trace = simulate(
            s, frames[s['symbol']], minutes[s['symbol']], ready, float(costs[s['symbol']]),
            admission, management)
        events.extend({'signal_key': f"{CHILD}|{s['symbol']}|{s['signal_ts_ms']}", **e} for e in trace)
        if why:
            rejects[why] += 1
            continue
        owned[s['symbol']] = release
        if row is not None:
            trades.append(row)
        if open_pos is not None:
            unresolved.append(open_pos)
    require(len(signals) == len(trades)+len(unresolved)+sum(rejects.values()), 'SIGNAL_ACCOUNTING')
    return {'identity': CHILD, 'signals': signals, 'trades': trades, 'unresolved': unresolved,
            'rejections': dict(rejects), 'events': events}


def paired(parent, child):
    # Match scored completed trades; unresolved exposure is disclosed separately.
    def selected(rows):
        return {key(r): r for r in rows if START <= r['signal_ts_ms'] < END
                and r['outcome_available_ts_ms'] < END}
    p, c = selected(parent['trades']), selected(child['trades'])
    report = {}
    for mult in (1, 2):
        net = lambda r: r['gross_bps']-mult*r['cost_bps']
        common = sorted(p.keys() & c.keys())
        rows = [{'key': list(k), 'parent_net_bps': net(p[k]), 'child_net_bps': net(c[k]),
                 'delta_bps': net(c[k])-net(p[k]), 'parent_exit': p[k]['reason'],
                 'child_exit': c[k]['reason']} for k in common]
        delta = math.fsum(r['delta_bps'] for r in rows)
        added = math.fsum(net(c[k]) for k in c.keys()-p.keys())
        removed = -math.fsum(net(p[k]) for k in p.keys()-c.keys())
        total = math.fsum(map(net, c.values()))-math.fsum(map(net, p.values()))
        require(abs(total-delta-added-removed) <= TOL, 'PAIR_RECONCILIATION')
        report[str(mult)+'x'] = {
            'common_T': len(common), 'child_only_T': len(c.keys()-p.keys()), 'parent_only_T': len(p.keys()-c.keys()),
            'improved_T': sum(r['delta_bps'] > TOL for r in rows),
            'harmed_T': sum(r['delta_bps'] < -TOL for r in rows),
            'parent_winners_harmed_T': sum(r['parent_net_bps'] > 0 and r['delta_bps'] < -TOL for r in rows),
            'parent_loss_change_bps': math.fsum(r['delta_bps'] for r in rows if r['parent_net_bps'] < 0),
            'parent_winner_change_bps': math.fsum(r['delta_bps'] for r in rows if r['parent_net_bps'] > 0),
            'common_delta_bps': delta, 'new_opportunities_net_bps': added,
            'missing_opportunities_contribution_bps': removed, 'total_net_delta_bps': total, 'rows': rows}
    return report


def run_lanes(data, contract, out):
    from backend.research.rebuild import scalp7_metrics_v2 as metrics
    parent = saved_parent()
    require(sha(encoded(parent['signals'])) == contract['parent_signals_sha256'], 'SIGNAL_LIST_CHANGED')
    frames, clocks, manifest = build_frames(data)
    ready = clock.prefix_clocks(clocks)
    for s in SYMBOLS:
        clock.verify_minute_rows(data['minutes'][s])
    costs = contract['reference_costs_bps']
    require(costs == data['contracts']['cost_snapshot']['content']['costs_bps'], 'COST_CHANGED')
    timed = {}
    for s, f in frames.items():
        f = f.copy()
        f['available_ts_ms'] = [ready.get(int(r.open_ts_ms), int(r.available_ts_ms)) for r in f.itertuples()]
        timed[s] = f
    signals = [as_child(s) for s in parent['signals']]
    lane = out/CHILD
    lane.mkdir(exist_ok=False)
    write_once(lane, 'STARTED.json', {'identity': CHILD, 'executions': 1,
                                   'utc': datetime.now(timezone.utc).isoformat()})
    result = replay_child(signals, timed, data['minutes'], ready, costs)
    for mult in (1, 2):
        result['reference'+str(mult)+'x'] = metrics.summarize(result['trades'], START, END, cost_multiplier=mult)
    result['paired'] = paired(parent, result)
    write_once(lane, 'RESULT.json', result)
    write_once(lane, 'COMPLETED.json', {'identity': CHILD, 'executions': 1,
                                     'result_sha256': sha((lane/'RESULT.json').read_bytes())})
    summary = {'schema': 'scalp7.squeeze_nonpositive.result.v1', 'batch_id': BATCH, 'identity': CHILD,
               'native_parent': PARENT, 'rule': RULE, 'mode': MODE, 'input_sha256': PRICE_SHA,
               'parent_result_sha256': PARENT_SHA, 'original_signals_reused': len(signals),
               'new_signal_generation_calls': 0, 'shared_frame_builds': 1,
               'economic_lane_executions': 1, 'parent_replays': 0, 'keltner_replays': 0,
               'complete_T': len(result['trades']), 'unresolved_T': len(result['unresolved']),
               'rejections': result['rejections'],
               'parent_reference1x': parent['reference1x'], 'parent_reference2x': parent['reference2x'],
               'child_reference1x': result['reference1x'], 'child_reference2x': result['reference2x'],
               'paired': result['paired'], 'frame_manifest': manifest,
               'unused_oos_certified': False, 'realtime_fill_certified': False,
               'g5_promotion': False, 'orders': 0, 'account_nav': None, 'account_dd': None,
               'limitations': ['Consumed DEV history; discovery was post-outcome.',
                   'Seed/config readiness, minute-open fills/stops/ACK remain prior model assumptions.',
                   'No account funding, margin, liquidation or running-consumer deployment.',
                   'A saved-parent comparison is not an independent-market replication.']}
    write_once(out, 'SUMMARY.json', summary)
    return summary
