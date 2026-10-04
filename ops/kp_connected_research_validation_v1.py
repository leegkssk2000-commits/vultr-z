"""One-shot frozen-parent historical-model replay on verified recorded prices.

NOT a late-observation fill engine: actual receipt times remain separate from
explicit model bar-boundary availability. Existing live/fresh guards are not
changed. No collection, server state, order, tuning or promotion interface.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import re
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops.kp_committed_cursor_snapshot_v1 import load, require, sha, SYMBOLS
from ops.kp_price_input_export_v1 import bounded_gunzip, CONFIG_SHA

CANDIDATE = 'scalp7_keltner_hg_parent_utc30m_v2'
START = 1789502400000
END = 1791075300000
SOURCE_START = 1789430400000
TF = 1800000
PRICE_SHA = '3da2f940e532be2c04ea25386782ef5732b12eb99d6f8203473ee3d57433d0b3'
INPUT_FIELDS = ['timestamp_ms', 'open', 'high', 'low', 'close', 'volume',
                'source_received_at_ms', 'snapshot_receipt_index', 'source_namespace']


def plain(obj: Any) -> Any:
    if isinstance(obj, np.generic):
        return obj.item()
    raise TypeError('UNSUPPORTED_JSON_VALUE:' + type(obj).__name__)


def encoded(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, default=plain, allow_nan=False) + '\n').encode()


def write_once(out: Path, name: str, value: Any) -> None:
    with (out/name).open('xb') as handle:
        handle.write(encoded(value))


def verify_contract(raw: bytes, activation: dict[str, Any]) -> dict[str, Any]:
    require(sha(raw) == activation['contract_sha256'], 'CONTRACT_HASH')
    c = load(raw)
    require(c['candidate'] == CANDIDATE and c['window'] == {'start_ms': START, 'end_exclusive_ms': END}, 'FROZEN_CANDIDATE_WINDOW')
    require(c['input_payload_sha256'] == PRICE_SHA, 'PRICE_PIN')
    require(c['max_model_replays'] == activation['max_model_replays'] == 1, 'ONE_REPLAY_ONLY')
    require(c['semantics'] == 'RECORDED_PRICE_HISTORICAL_BAR_BOUNDARY_MODEL', 'EXECUTION_MODE')
    require(c['official_fresh_credit'] is False and activation['official_fresh_credit'] is False
            and c['unused_oos_certified'] is False and c['live_authority'] == 'BLOCKED', 'AUTHORITY_NOT_GRANTED')
    require(c['initial_position'] == 'FLAT_INDEPENDENT_RESEARCH_RUN'
            and c['force_close_at_end'] is False and c['cost_multipliers'] == [1, 2], 'BOUNDARY_POLICY')
    require(activation['run_id'] == c['run_id'] and re.fullmatch(r'KP30_[A-Z0-9_]+', c['run_id']), 'RUN_ID')
    require(c['source_start_ms'] == SOURCE_START and c['strategy_rules_changed'] is False, 'SOURCE_START_OR_RULE_CHANGE')
    return c


def verify_input(raw: bytes, c: dict[str, Any]) -> dict[str, Any]:
    require(sha(raw) == c['input_payload_sha256'], 'INPUT_HASH')
    d = load(raw)
    require(d['configured_sources_verified'] is True and d['price_bodies_verified'] is True, 'BODY_INPUT_UNVERIFIED')
    require(d['source_start_ms'] == SOURCE_START and d['common_end_exclusive_ms'] == END, 'INPUT_WINDOW')
    require(d['fields'] == INPUT_FIELDS and set(d['minutes']) == set(SYMBOLS), 'EXACT_INPUT_SCHEMA')
    require(d['market_runs'] == 0 and d['shared_state_modified'] is False, 'INPUT_PROVENANCE')
    require(d['config_source']['sha256'] == c['forward_config_sha256'] == CONFIG_SHA, 'FORWARD_CONFIG_PIN')
    require(d['deployed_code_hashes'] == c['source_code_hashes'], 'INPUT_CODE_PINS')
    for path, expected in c['source_code_hashes'].items():
        require(path.startswith('backend/research/rebuild/') and Path(path).suffix == '.py', 'SOURCE_PATH')
        full = (ROOT/path).resolve(strict=True)
        require(full.is_relative_to(ROOT) and sha(full.read_bytes()) == expected, 'FROZEN_CODE_CHANGED:' + path)
    for path, expected in c['adapter_code_hashes'].items():
        full = (ROOT/path).resolve(strict=True)
        require(full.is_relative_to(ROOT) and sha(full.read_bytes()) == expected, 'ADAPTER_CODE_CHANGED:' + path)
    require(d['config_projection']['fresh_start_ms'] == START, 'ORIGINAL_START_CHANGED')
    fit = d['config_projection']['regime_fit']
    require(fit == c['frozen_regime_fit'] and fit['train_end_ms'] <= SOURCE_START
            and fit['last_fit_observation_ms'] < SOURCE_START, 'FIT_LEAKAGE_OR_CHANGED')
    require(d['contracts']['cost_snapshot']['sha256'] == c['cost_snapshot_sha256'], 'COST_SOURCE_PIN')
    return d


def read_seed(raw: bytes) -> pd.DataFrame:
    """Match the pinned runtime CSV parser; the completed old result is unchanged."""
    return pd.read_csv(io.BytesIO(bounded_gunzip(raw, 4*1024*1024)), float_precision="round_trip")


def causal_clock_witness(signal: dict[str, Any], clocks: dict[str, dict[int, int]]) -> dict[str, Any]:
    """Conservative six-symbol prefix bound, not proof of complete live availability.

    The seed/config observation clocks are not certified. Even an on-time
    price prefix therefore cannot produce a True realtime-fill claim.
    """
    require(set(clocks) == set(SYMBOLS), 'CLOCK_EXACT_SIX_SYMBOLS')
    stamp = int(signal['signal_open_ts_ms'])
    own = clocks[signal['symbol']][stamp]
    bounds = {}
    for symbol in SYMBOLS:
        require(stamp in clocks[symbol], 'CLOCK_MISSING_CURRENT_SYMBOL')
        prior = [available for opening, available in clocks[symbol].items() if opening <= stamp]
        require(prior and all(type(t) is int for t in prior), 'CLOCK_PREFIX_INCOMPLETE')
        bounds[symbol] = max(prior)
    available = max(bounds.values())
    close = stamp + TF
    return {'signal_key': key(signal), 'decision_close_ms': close,
            'recorded_constituent_available_ms': own,
            'recorded_causal_prefix_available_ms': available,
            'prefix_available_by_symbol_ms': bounds,
            'eligibility_basis': 'CONSERVATIVE_ALL_SIX_SYMBOL_PRICE_PREFIX',
            'seed_and_config_live_observation_certified': False,
            'historical_next_open_available_in_realtime': False if available > close else None,
            'actual_strategy_observation_reconstructed': False}


def build_frames(data: dict[str, Any]):
    # Imported only after exact source/adapter hashes and recorded input checks.
    from backend.research.rebuild.scalp7_source_data_v2 import aggregate_minutes
    from backend.research.rebuild.scalp7_fresh_forward_v2 import combine_context, bind_frozen_context
    frames, original_clocks, summary = {}, {}, {}
    for symbol in SYMBOLS:
        rows = data['minutes'][symbol]
        require([r[0] for r in rows] == list(range(SOURCE_START, END, 60000)), 'INPUT_MINUTE_GAP')
        require(all(len(r) == len(INPUT_FIELDS) and type(r[6]) is int and r[6] >= r[0]+60000 for r in rows), 'INPUT_RECEIPT_CLOCK')
        minute = pd.DataFrame(rows, columns=INPUT_FIELDS)
        minute = minute.rename(columns={'source_received_at_ms': 'received_at_ms'})
        # Two projections, explicitly different. No raw receipt is overwritten.
        observed = aggregate_minutes(minute, 30, observed=True)
        modeled = aggregate_minutes(minute, 30, observed=False)
        require(modeled.open_ts_ms.tolist() == observed.open_ts_ms.tolist(), 'PROJECTION_BAR_ID')
        original_clocks[symbol] = {int(r.open_ts_ms): int(r.available_ts_ms) for r in observed.itertuples()}
        seed = data['context'][symbol]
        raw = base64.b64decode(seed['gzip_base64'], validate=True)
        require(sha(raw) == seed['sha256'] == data['config_projection']['historical_context']['30'][symbol]['sha256'], 'SEED_HASH')
        history = read_seed(raw)
        require(int(history.close_ts_ms.max()) == SOURCE_START, 'SEED_SEAM')
        frame = combine_context(history, modeled, 30)
        require(frame.segment_id.nunique() == 1 and frame.close_ts_ms.max() <= END, 'COMBINED_GAP_OR_FUTURE')
        # The helper's flag names its input origin, not this run's certification.
        frame['fresh_observed'] = False
        frames[symbol] = frame
        summary[symbol] = {'minute_rows': len(rows), 'seed_bars': len(history), 'new_complete_30m_bars': len(modeled),
                           'combined_bars': len(frame), 'incomplete_edge_minutes': len(rows)-len(modeled)*30,
                           'recorded_late_30m_bars': int((observed.available_ts_ms > observed.close_ts_ms).sum()),
                           'frame_values_sha256': sha(frame.to_csv(index=False).encode())}
    return bind_frozen_context({30: frames}, data['config_projection']['regime_fit'])[30], original_clocks, summary


def key(signal: dict[str, Any]) -> str:
    return f"{signal['identity']}|{signal['symbol']}|{int(signal['signal_ts_ms'])}"


def arithmetic_audit(trades: list[dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, Any]:
    parts = defaultdict(list)
    for t in traces:
        if t['partial_fraction']:
            parts[t['signal_key']].append(t)
    residuals, checks = [], []
    for row in trades:
        sid = key(row['signal']); partial = parts[sid]
        require(len(partial) <= 1, 'REPEATED_PARTIAL')
        entry = float(row['entry_prices'][row['symbol']]); side = row['side']
        fraction = sum(t['partial_fraction'] for t in partial)
        part = math.fsum(t['partial_fraction']*side*(t['partial_price']/entry-1)*10000 for t in partial)
        terminal = (1-fraction)*side*(float(row['exit_prices'][row['symbol']])/entry-1)*10000
        delta = part+terminal-float(row['gross_bps'])
        require(abs(delta) <= 1e-7 and abs(row['gross_bps']-row['cost_bps']-row['net_bps']) <= 1e-7, 'NEW_TRADE_ARITHMETIC')
        residuals.append(abs(delta))
        checks.append({'signal_key': sid, 'partial_gross_bps': part, 'terminal_gross_bps': terminal,
                       'gross_residual_bps': delta, 'partial_decision_rows': len(partial)})
    return {'status': 'PASS', 'complete_trades_checked': len(trades), 'partial_trades_checked': len([x for x in checks if x['partial_decision_rows']]),
            'max_abs_residual_bps': max(residuals, default=0), 'checks': checks,
            'event_time_precision': 'MODEL_BAR_CLOSE_NOT_EXCHANGE_EXECUTION', 'actual_fills_recovered': 0}


def execute(data: dict[str, Any], contract: dict[str, Any], out: Path) -> dict[str, Any]:
    from backend.research.rebuild import scalp7_positive_lanes_v2 as parent
    from backend.research.rebuild import scalp7_execution_v2 as engine
    from backend.research.rebuild import scalp7_metrics_v2 as metrics
    frames, clocks, input_summary = build_frames(data)
    costs = data['contracts']['cost_snapshot']['content']['costs_bps']
    require(costs == contract['reference_costs_bps'], 'FROZEN_COST_CHANGED')
    generated = parent.generate_signals(frames, costs=costs, identities=(CANDIDATE,))
    selected = [s for s in generated if s['signal_open_ts_ms'] >= START and s['signal_ts_ms'] < END]
    write_once(out, 'SIGNALS.json', selected)
    write_once(out, 'FRAME_MANIFEST.json', input_summary)
    observed_eligibility = [causal_clock_witness(s, clocks) for s in selected]
    traces = []
    def observer(position, bar, history):
        before = copy.deepcopy(position)
        update = parent.exit_update(position, bar, history)
        require(position == before, 'TRACE_WRAPPER_PARENT_MUTATION')
        traces.append({'signal_key': key(position['signal']), 'bar_open_ms': int(bar['open_ts_ms']),
                       'modeled_decision_ms': int(bar['close_ts_ms']), 'entry_ts_ms': int(position['entry_ts_ms']),
                       'entry_price': float(position['entry_price']), 'initial_risk': float(position['initial_risk']),
                       'remaining_before': float(position['remaining']), 'mfe_R': float(position['mfe_R']),
                       'stop_before': float(position['stop_price']), 'next_stop': update.get('next_stop'),
                       'partial_fraction': float(update.get('partial_fraction', 0)), 'partial_price': update.get('partial_price'),
                       'exit_next_open': bool(update.get('exit_next_open', False)), 'reason': update.get('reason')})
        return update
    result = engine.replay(selected, frames, costs, identity=CANDIDATE, exit_update=observer, entry_update=parent.entry_update)
    write_once(out, 'EXECUTION.json', result)
    write_once(out, 'LIFECYCLE_TRACE.json', traces)
    audit = arithmetic_audit(result['trades'], traces)
    write_once(out, 'INDEPENDENT_AMOUNT_AUDIT.json', audit)
    one = metrics.summarize(result['trades'], START, END, cost_multiplier=1)
    two = metrics.summarize(result['trades'], START, END, cost_multiplier=2)
    require(one['T'] == two['T'], 'COST_SCENARIO_CHANGED_TRADES')
    report = {'schema': 'kp30.connected_recorded_price_result.v1', 'run_id': contract['run_id'],
              'candidate': CANDIDATE, 'input_sha256': PRICE_SHA, 'window': contract['window'],
              'execution_status': 'COMPLETED', 'economic_replay_count': 1, 'reparameterizations': 0,
              'signals_generated_before_window_filter': len(generated), 'potential_signals_in_window': len(selected),
              'reference_cost_1x': one, 'reference_cost_2x': two,
              'rejections': result['rejections'], 'unresolved_count': len(result['unresolved']),
              'lifecycle_trace_rows': len(traces), 'amount_audit': {k:v for k,v in audit.items() if k!='checks'},
              'input_rows': sum(x['minute_rows'] for x in input_summary.values()),
              'receipt_clock_witness': observed_eligibility,
              'prior_candidate_observation': data['prefix_before']['fresh_forward']['candidate_evaluation'],
              'evidence_class': contract['semantics'], 'unused_oos_certified': False, 'genuine_fresh_trades': 0,
              'g5a_shortlist': False, 'g5b_terminal': False, 'g6': False, 'live': False,
              'account_dd': None, 'account_return': None, 'leverage': None, 'historical_funding_settled': False,
              'deployed_runtime_repaired': False, 'shared_state_writes': 0, 'actual_exchange_orders': 0,
              'versions': {'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__},
              'limits': ['Recorded prices are real; fills, bar-boundary availability and lifecycle events are historical model assumptions.',
                         'Reference cost reserve is not observed historical funding or an account margin model.',
                         'Prior observer inspected part of the interval; whole-window usage is not certified unused.',
                         'Unresolved holdings are preserved, not forcibly closed; metrics select complete outcomes only.',
                         'This run now consumes the entire interval as research history; no future retune may call it untouched OOS.',
                         'No old 119-trade ledger or strategy is overwritten; actual running consumers are not activated.']}
    write_once(out, 'RESULT.json', report)
    return report


def main():
    # This run has been consumed. Keep the callable pieces for generated tests
    # and review, but require a separately versioned/authorized future runner.
    raise SystemExit('COMPLETED_RUN_ENTRYPOINT_DISABLED_NO_AUTOMATIC_REPLAY')


def _archived_main_not_an_entrypoint():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input','contract','activation','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    a=parser.parse_args(); a.output.mkdir(parents=True, exist_ok=False)
    activation=load(a.activation.read_bytes())
    c=verify_contract(a.contract.read_bytes(),activation)
    d=verify_input(bounded_gunzip(a.input.read_bytes(),64*1024*1024),c)
    write_once(a.output,'STARTED.json',{'run_id':c['run_id'],'started_at_utc':datetime.now(timezone.utc).isoformat(),
               'scope':'ONE_RESEARCH_REPLAY_NO_RETRY','input_sha256':PRICE_SHA,'contract_sha256':sha(a.contract.read_bytes())})
    try:
        result=execute(d,c,a.output)
    except BaseException as exc:
        write_once(a.output,'FAILED.json',{'run_id':c['run_id'],'exception_type':type(exc).__name__,'reason':str(exc)[:1000],
                                          'started_attempt_consumed':True,'automatic_retry':False})
        raise
    write_once(a.output,'COMPLETED.json',{'run_id':c['run_id'],'finished_at_utc':datetime.now(timezone.utc).isoformat(),
                                        'result_sha256':sha((a.output/'RESULT.json').read_bytes()),'economic_replays':1})
    print(json.dumps({k:result[k] for k in ('run_id','execution_status','potential_signals_in_window','unresolved_count','reference_cost_1x','reference_cost_2x')},default=plain,allow_nan=False))

if __name__ == '__main__':main()
