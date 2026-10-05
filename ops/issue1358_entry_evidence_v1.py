"""Pinned, saved-entry diagnostics. No signal generation, fitting or replay.

Prices available by the decision clock are features. A subsequent modeled fill
is an outcome diagnostic, never a decision-time quote or admissible feature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = 'scalp7_squeeze_panic_cost4_parent_utc30m_v2'
PRICE_SHA = '3da2f940e532be2c04ea25386782ef5732b12eb99d6f8203473ee3d57433d0b3'
BUNDLE_SHA = 'd8e64b248d25a66ccdd44e403da82284ec7f5f49fcf9ebd5be68e9876c1d6ed1'
RESULT_SHA = 'a390f985245f32d52681fea688617d01fb6eb597b1269f10a62466075a9edbc9'
CONTRACT_SHA = '0717e695a33abed5ec3c362bc4e266b3ff9475766e8eab3186a30544ed61e088'
TF = 1_800_000
MINUTE = 60_000


def require(ok, why):
    if not ok:
        raise ValueError(why)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def latest_known_minute(rows, as_of):
    """Select the latest closed market minute actually received by as_of."""
    require(type(as_of) is int and as_of >= 0, 'INTEGER_AS_OF')
    selected = None
    for r in rows:
        require(type(r[0]) is int and type(r[6]) is int, 'INTEGER_SOURCE_CLOCK')
        require(r[0] % MINUTE == 0 and r[6] >= r[0] + MINUTE, 'SOURCE_CLOCK')
        if r[0] + MINUTE <= as_of and r[6] <= as_of:
            if selected is None or r[0] > selected[0]:
                selected = r
    require(selected is not None, 'NO_KNOWN_MINUTE')
    require(math.isfinite(float(selected[4])) and float(selected[4]) > 0, 'SOURCE_PRICE')
    return selected


def split_evidence(signal_low, known_close, fill_price):
    require(all(math.isfinite(float(v)) and float(v) > 0
                for v in (signal_low, known_close, fill_price)), 'FINITE_POSITIVE_PRICE')
    return {
        'known_close_below_signal_low': float(known_close) < float(signal_low),
        'later_fill_below_signal_low': float(fill_price) < float(signal_low),
        'later_fill_is_decision_feature': False,
    }


def reconstruct(price_path, parent_path, source_contract):
    # No model is imported until the same pre-existing source pins are checked.
    contract_bytes = source_contract.read_bytes()
    require(digest(contract_bytes) == CONTRACT_SHA, 'SOURCE_CONTRACT_PIN')
    pins = json.loads(contract_bytes)['source_pins']
    for name, expected in pins.items():
        path = (ROOT / name).resolve(strict=True)
        require(path.is_relative_to(ROOT) and digest(path.read_bytes()) == expected,
                'SOURCE_PIN:' + name)
    from ops.kp_connected_research_validation_v1 import bounded_gunzip
    raw = bounded_gunzip(price_path.read_bytes(), 64 * 1024 * 1024)
    require(len(raw) <= 64 * 1024 * 1024 and digest(raw) == PRICE_SHA, 'PRICE_PIN')
    packed = parent_path.read_bytes()
    require(digest(packed) == BUNDLE_SHA, 'PARENT_BUNDLE_PIN')
    files = json.loads(lzma.decompress(packed))
    original = files[PARENT + '/RESULT.json'].encode()
    require(digest(original) == RESULT_SHA, 'PARENT_RESULT_PIN')
    data, parent = json.loads(raw), json.loads(original)
    from ops.kp_connected_research_validation_v1 import build_frames
    from ops.scalp7_clocked_execution_v1 import prefix_clocks, next_minute
    from backend.research.rebuild import scalp7_positive_lanes_v2 as rules
    frames, clocks, frame_manifest = build_frames(data)
    ready = prefix_clocks(clocks)
    trades = {(r['symbol'], r['signal_ts_ms']): r for r in parent['trades']}
    require(len(trades) == len(parent['trades']), 'DUPLICATE_TRADE')
    rows = []
    for signal in parent['signals']:
        symbol, stamp = signal['symbol'], signal['signal_open_ts_ms']
        frame = frames[symbol]
        matches = frame.index[frame.open_ts_ms == stamp].tolist()
        require(len(matches) == 1, 'SIGNAL_BAR')
        prefix = frame.iloc[:matches[0] + 1]
        enriched = rules.enriched_segments(prefix)
        require(len(enriched) == 1, 'SOURCE_SEGMENT')
        x = enriched[0]
        current, previous = x.iloc[-1], x.iloc[-2]
        positive_acceleration = bool(current.momentum > 0 and current.momentum > previous.momentum)
        require(positive_acceleration and bool(previous.squeeze_on) and not bool(current.squeeze_on),
                'NATIVE_RELEASE_MOMENTUM_NOT_RECONSTRUCTED')
        require(current.g8 > current.g21 > current.g34 and current.close > current.g34,
                'NATIVE_MA_NOT_RECONSTRUCTED')
        require(math.isclose(float(current.atr20), signal['meta']['atr_price'], rel_tol=1e-12),
                'NATIVE_ATR_MISMATCH')
        decision = max(ready[stamp], signal['signal_ts_ms'])
        entry = next_minute(decision)
        require(stamp + TF <= decision < entry < stamp + 2 * TF, 'ENTRY_CLOCK')
        minute_rows = data['minutes'][symbol]
        known = latest_known_minute(minute_rows, decision)
        observed = [t for t, received in clocks[symbol].items() if t <= stamp and received <= decision]
        require(observed and max(observed) == stamp, 'LATEST_RECEIVED_DECISION_BAR')
        index = (entry - minute_rows[0][0]) // MINUTE
        require(0 <= index < len(minute_rows) and minute_rows[index][0] == entry, 'FILL_INDEX')
        later_fill = float(minute_rows[index][1])
        trade = trades.get((symbol, signal['signal_ts_ms']))
        if trade:
            require(trade['entry_ts_ms'] == entry and trade['signal_available_ms'] == decision,
                    'SAVED_ENTRY_CLOCK')
            require(trade['entry_prices'][symbol] == later_fill, 'SAVED_ENTRY_PRICE')
        rows.append({
            'symbol': symbol, 'signal_open_ms': stamp, 'signal_close_ms': stamp + TF,
            'signal_key': f"{PARENT}|{symbol}|{signal['signal_ts_ms']}",
            'decision_input_ready_ms': decision, 'modeled_entry_ms': entry,
            'decision_lag_seconds': (decision - stamp - TF) / 1000,
            'entry_lag_seconds': (entry - stamp - TF) / 1000,
            'features': {
                'native_momentum_positive_and_accelerating': positive_acceleration,
                'signal_close': float(current.close), 'signal_low': float(current.low),
                'previous_bar_high': float(previous.high),
                'known_minute_open_ms': known[0], 'known_minute_received_ms': known[6],
                'known_minute_close': float(known[4]),
                'signal_close_above_previous_high': bool(current.close > previous.high),
            },
            'outcome_diagnostics': {
                'completed_parent_trade': trade is not None,
                'saved_net_bps': None if trade is None else trade['net_bps'],
                'modeled_entry_price_not_decision_quote': later_fill,
                'fill_move_from_signal_close_bps': (later_fill / float(current.close) - 1) * 10000,
                **split_evidence(current.low, known[4], later_fill),
            },
        })
    completed = [r for r in rows if r['outcome_diagnostics']['completed_parent_trade']]
    winners = [r for r in completed if r['outcome_diagnostics']['saved_net_bps'] > 0]
    summary = {
        'signals_reviewed': len(rows), 'completed_trades_reviewed': len(completed),
        'uncompleted_signal_outcomes_not_invented': len(rows) - len(completed),
        'winners_reviewed': len(winners), 'losers_reviewed': len(completed) - len(winners),
        'positive_native_momentum_already_required': sum(r['features']['native_momentum_positive_and_accelerating'] for r in rows),
        'later_fills_below_signal_low_completed': sum(r['outcome_diagnostics']['later_fill_below_signal_low'] for r in completed),
        'known_closes_below_signal_low_completed': sum(r['outcome_diagnostics']['known_close_below_signal_low'] for r in completed),
        'winners_not_closing_above_previous_high': sum(not r['features']['signal_close_above_previous_high'] for r in winners),
        'losers_closing_above_previous_high': sum(r['features']['signal_close_above_previous_high'] and r['outcome_diagnostics']['saved_net_bps'] < 0 for r in completed),
    }
    return {'schema': 'zel.issue1358.saved_entry_evidence.v1',
            'scope': 'POINT_IN_TIME_ENTRY_DIAGNOSIS_NOT_A_STRATEGY_BACKTEST',
            'source_input_sha256': PRICE_SHA, 'parent_bundle_sha256': BUNDLE_SHA,
            'parent_result_sha256': RESULT_SHA, 'source_pins': pins,
            'summary': summary, 'rows': rows, 'frame_manifest': frame_manifest,
            'new_model_executions': 0, 'new_signal_generation': 0,
            'parameter_search': False, 'entry_candidate_selected': False,
            'unused_oos_certified': False, 'profitability_improvement_measured': False,
            'decision': 'NO_JUSTIFIED_ENTRY_ALPHA_FROM_THIS_SMALL_INSPECTED_PACKET',
            'next': 'Select a distinct executable entry mechanism from broader existing source/attempt evidence; do not convert these nine outcomes into a classifier, add a redundant momentum gate, or use a later fill as an ex-ante quote. Freeze at most one justified candidate before any new model execution.',
            'limitations': ['Recorded receipt timestamps are not authenticated quote/fill/ACK evidence.',
                           'Seed and configuration readiness retain previous modeling assumptions.',
                           'Observed groups are post-outcome diagnostics, not a causal filter effectiveness test.',
                           'Rejected/occupied opportunities have no newly calculated counterfactual outcome.',
                           'No evidence of autonomous scheduled progression is implied.']}


def compact_projection(d):
    columns = ['symbol', 'signal_open_ms', 'decision_input_ready_ms', 'modeled_entry_ms',
               'signal_low', 'signal_close', 'previous_bar_high', 'known_minute_open_ms',
               'known_minute_received_ms', 'known_minute_close', 'later_modeled_fill',
               'saved_parent_net_bps']
    rows = []
    for r in d['rows']:
        f, o = r['features'], r['outcome_diagnostics']
        rows.append([r['symbol'], r['signal_open_ms'], r['decision_input_ready_ms'],
                     r['modeled_entry_ms'], f['signal_low'], f['signal_close'],
                     f['previous_bar_high'], f['known_minute_open_ms'],
                     f['known_minute_received_ms'], f['known_minute_close'],
                     o['modeled_entry_price_not_decision_quote'], o['saved_net_bps']])
    return {'schema': 'zel.issue1358.entry_evidence.compact.v1',
            'full_diagnostic_sha256': digest(encoded(d)),
            'source_input_sha256': d['source_input_sha256'],
            'parent_result_sha256': d['parent_result_sha256'],
            'summary': d['summary'], 'columns': columns, 'rows': rows,
            'all_native_release_momentum_ma_atr_checks_passed': True,
            'later_modeled_fill_is_decision_feature': False,
            'new_model_executions': 0, 'new_signal_generation': 0,
            'entry_candidate_selected': False, 'profitability_improvement_measured': False,
            'unused_oos_certified': False, 'decision': d['decision']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--price', type=Path, required=True)
    p.add_argument('--parent-bundle', type=Path, required=True)
    p.add_argument('--source-contract', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--compact-output', type=Path)
    a = p.parse_args()
    result = reconstruct(a.price, a.parent_bundle, a.source_contract)
    with a.output.open('xb') as stream:
        stream.write(encoded(result))
    if a.compact_output:
        with a.compact_output.open('xb') as stream:
            stream.write(encoded(compact_projection(result)))
    print(json.dumps(result['summary'], sort_keys=True))


if __name__ == '__main__':
    main()
