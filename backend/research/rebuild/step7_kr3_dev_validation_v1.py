"""Finite, previously used DEV-only KR3 validation. No base replay or promotion.

Execution uses the preserved native producer and original proxy cost owner.
A manifest is frozen before the first actual variant. Every attempt is reserved
persistently before native replay; a failed/exposed attempt is never retried.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

from backend.research.rebuild import step7_kr3_execution_v1 as native
from backend.research.rebuild import parallel_exit_dev_v1 as account
from backend.research.rebuild import parallel_exit_metrics_v1 as marks
from backend.research.rebuild import break_channel_metrics_v1 as risk
from backend.research.rebuild import top5_external_metrics_v1 as streaks
from backend.research.rebuild import step7_kr3_dev_evidence_v1 as evidence

ROOT = Path(__file__).resolve().parents[3]
CANDIDATE = '298ae6dfe19bed2503eae374c4540ae13beab0374033aa27842f3701d0c609cc'
CONTROLS = ('direction_flip', 'time_shift_placebo', 'delayed_entry')
ABLATIONS = ('without_trend_feature', 'without_reclaim_feature', 'without_directional_half')
COST_SEMANTICS = 'ORIGINAL_DEV_PROXY_FEE_SPREAD_IMPACT_ABSOLUTE_FUNDING_DEBIT_20BPS_FLOOR; ALL_COST2_DOUBLES_ALL; OPEN_FULL_ROUNDTRIP_HYPOTHETICAL'
canonical = native.canonical
sha = native.sha


def variants():
    return ([{'id': name, 'kind': 'control', 'control': name, 'parameters': list(native.CENTER)} for name in CONTROLS]
            + [{'id': name, 'kind': 'ablation', 'ablation': name, 'parameters': list(native.CENTER)} for name in ABLATIONS]
            + [{'id': 'neighbor_'+'_'.join(map(str, p)), 'kind': 'neighbor', 'parameters': list(p)} for p in native.NEIGHBORS])


def code_dependencies():
    # Bind actual native and charge/report owners. Loading source is not data IO.
    modules = (sys.modules[__name__], evidence, evidence.admission, native, native.contracts, native.kr3, native.kr,
               native.m2, native.reservation, native.reservation.n, native.d,
               native.d.old, native.d.old.dsl, native.d.old.common,
               account, account.old, account.old.probe, account.source.prior,
               account.old.probe.parent, account.old.probe.evaluator,
               marks, risk, streaks, marks.bridge, marks.shared, risk.censored,
               risk.censored.previous, risk.censored.previous.prep)
    return {str(Path(m.__file__).resolve().relative_to(ROOT)): hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in modules}


def regime_rule(rows_by):
    """Descriptive DEV-only cutoff frozen before outcomes; not an entry feature."""
    ratios = []
    for rows in rows_by.values():
        atr = None
        trs = []
        for i, row in enumerate(rows):
            previous = rows[i-1]['close'] if i else row['close']
            tr = max(row['high']-row['low'], abs(row['high']-previous), abs(row['low']-previous))
            trs.append(tr)
            if i == 19:
                atr = sum(trs)/20
            elif i > 19:
                atr = (19*atr+tr)/20
            if i >= 239 and atr is not None:
                ratios.append(atr/row['close'])
    if not ratios:
        raise ValueError('DEV_CAUSAL_REGIME_OBSERVATIONS_MISSING')
    return {'name': 'EMA50_SLOPE_X_ATR20_RATIO', 'frozen_dev_atr_ratio_median': statistics.median(ratios),
            'cutoff_population': 'ALL_ORIGINAL_SYMBOL_DEV_ROWS_INDEX_GE239; NO_OUTCOME_SELECTION',
            'classification': 'DESCRIPTIVE_USED_DEV_ONLY; FULL_DEV_MEDIAN_IS_NOT_A_PROSPECTIVE_THRESHOLD',
            'native_entry_uses_regime': False}


def propose_spec(rows_by, policy, costs, input_receipt):
    start, end = policy['development_interval_ms']
    if tuple(sorted(rows_by)) != tuple(sorted(native.SYMBOLS)):
        raise ValueError('EXACT_ORIGINAL_SEVEN_SYMBOLS')
    if any(not rows or rows[-1]['bar_close_ts'] > end for rows in rows_by.values()):
        raise ValueError('DEV_END_ONLY')
    return native.contracts.seal({
        'schema': 'zel.step7.kr3.dev.validation.spec.v1', 'candidate_sha256': CANDIDATE,
        'candidate_variant': 'KR3_FULL', 'direct_parent': 'KR1_FULL', 'start_ms': start,
        'entry_stop_ms': end, 'runoff_end_ms': end, 'data_sha256': sha(rows_by),
        'data_input_receipt': input_receipt, 'cost_sha256': sha(costs),
        'policy_sha256': sha(policy), 'cost_semantics': COST_SEMANTICS,
        'variants': variants(), 'seed': 'NO_RANDOM', 'regime': regime_rule(rows_by),
        'code_files_sha256': code_dependencies(), 'runtime': {'python': sys.version, 'implementation': sys.implementation.name},
        'control_semantics': {
            'direction_flip': 'NEGATED_LONG_RETURN_ON_UNCHANGED_LONG_INFORMATION_EXIT_CLOCK; CONSERVATIVE_UNSIGNED_DEV_FUNDING_DEBIT; NOT_NATIVE_SHORT_POLICY',
            'time_shift_placebo': 'PLUS6_OBSERVED_BARS_NOT_GUARANTEED_24H; RELATCH_SHIFTED_BAR_GEOMETRY_AND_REBUILD_REFERENCE_ACTUAL_OCCUPANCY',
            'delayed_entry': 'PLUS1_OBSERVED_BAR; RELATCH_SHIFTED_BAR_GEOMETRY_AND_REBUILD_REFERENCE_ACTUAL_OCCUPANCY'},
        'ablations': 'SINGLE_FEATURE_REMOVAL_FULL_NATIVE_SIGNAL_REFERENCE_ACTUAL_REPLAY; NO_FIXED_PARENT_ADMISSION_LIST',
        'neighbors': 'SIX_PREEXISTING_ONE_COORDINATE_NEIGHBORS; HOLD_PROPAGATED_TO_REFERENCE_DECISION_AND_EXTENSION_CAP',
        'center': 'REUSE_STORED_KR3_DEV2025_FULL; NO_BASE_REPLAY',
        'excluded_replays': ['base', 'without_kr3_veto', 'regime_permutation'],
        'evaluation': 'DESCRIPTIVE_SAME_DATA_COST_METRICS_AND_CENTRE_DELTAS; NO_BEST_VARIANT_SELECTION_OR_NEW_FORMAL_GATE',
        'evidence_kind': 'ACTUAL_REUSED_DEV_VALIDATION', 'independent': False,
        'formal_credit': 0, 'new_candidate_selection': False, 'orders': 0})


def validate_spec(spec, rows_by, costs, policy):
    if not native.contracts.check_seal(spec) or spec['candidate_sha256'] != CANDIDATE:
        raise ValueError('DEV_SPEC_IDENTITY_OR_SEAL')
    if spec['variants'] != variants() or spec['seed'] != 'NO_RANDOM' or spec['cost_semantics'] != COST_SEMANTICS:
        raise ValueError('EXACT_FINITE_VARIANTS_AND_COST_REQUIRED')
    if spec['code_files_sha256'] != code_dependencies():
        raise ValueError('FROZEN_EXECUTION_DEPENDENCIES_CHANGED')
    if spec['runtime'] != {'python': sys.version, 'implementation': sys.implementation.name}:
        raise ValueError('FROZEN_RUNTIME_CHANGED')
    if (sha(rows_by), sha(costs), sha(policy)) != (spec['data_sha256'], spec['cost_sha256'], spec['policy_sha256']):
        raise ValueError('FROZEN_DEV_BYTES_OR_COST_CHANGED')
    if policy['development_interval_ms'] != [spec['start_ms'], spec['runoff_end_ms']]:
        raise ValueError('DEV_CALENDAR_MISMATCH')


def _terminal(closed, opened, cost2=False):
    field = 'cost2x_net_bps' if cost2 else 'net_bps'
    mark = 'hypothetical_liquidation_cost2x_net_mark_bps' if cost2 else 'hypothetical_liquidation_net_mark_bps'
    return sum(r[field] for r in closed)+sum(r[mark] for r in opened)


def _daily(closed, opened, rows_by, costs, start, end):
    if all(t['side'] == 'long' for t in closed+opened):
        return marks.daily_valuation(closed, opened, rows_by, costs, start, end)
    # The direction reflection retains the long exit clock. Its valuation must
    # reflect gross marks too; cost debits stay unchanged, never funding credits.
    prices = marks._prices(rows_by, start, end)
    daily, previous, left = [], 0., start
    for ts in marks._calendar(start, end):
        values = []
        for t in closed+opened:
            if t['entry_ts'] > ts:
                continue
            if 'exit_ts' in t and t['exit_ts'] <= ts:
                values.append(t['net_bps'])
                continue
            gross = (-1 if t['side'] == 'short' else 1)*(prices[t['symbol']][ts]/t['entry_price']-1)*10000
            parts = account.old.probe.cost_components(t['entry_ts'], ts, costs[t['symbol']])
            values.append(gross-max(20., parts['cost_bps']))
        total = sum(values)
        daily.append({'mark_ts': ts, 'interval_start_ms': left, 'interval_hours': (ts-left)/3600000,
                      'value': total-previous, 'cumulative_net_mark_bps': total,
                      'basis': 'UTC_NATIVE_MARKS_SIGNED_RETURN_REFLECTION_SAME_UNSIGNED_PROXY_COST'})
        previous, left = total, ts
    # Same float expressions and ordering, not a newly introduced tolerance.
    if daily[-1]['cumulative_net_mark_bps'] != _terminal(closed, opened):
        raise ValueError('DIRECTION_REFLECTION_TERMINAL_PARITY')
    return daily


def metrics(closed, opened, spec, rows_by=None, costs=None):
    kw = {'start_ms': spec['start_ms'], 'end_ms': spec['runoff_end_ms'], 'symbol_count': len(native.SYMBOLS)}
    base = account.old.probe.summarize(closed, **kw)
    cost2 = account.old.probe.summarize(closed, cost2x=True, **kw)
    exposure = risk.exposure_summary(closed, opened, start_ms=kw['start_ms'], end_ms=kw['end_ms'])
    groups = streaks.streaks(streaks.grouped(closed))[0]
    result = {'base_cost': base, 'cost2x': cost2, 'closed_T': len(closed), 'open_T': len(opened),
              'terminal_net_bps': _terminal(closed, opened), 'terminal_cost2x_net_bps': _terminal(closed, opened, True),
              'open_hypothetical_net_mark_bps': sum(t['hypothetical_liquidation_net_mark_bps'] for t in opened),
              'exposure': exposure, 'closed_loss_groups': groups,
              'all_closed_cost_bps': sum(t['cost_bps'] for t in closed),
              'all_open_hypothetical_cost_bps': sum(t['hypothetical_liquidation_cost_bps'] for t in opened),
              'initial_protective_sl': None, 'tp': None, 'actual_liquidation_T': 0,
              'units': 'EQUAL_NOTIONAL_TRADE_BPS; NOT_ACCOUNT_RETURN', 'formal_pass': False}
    if rows_by is not None:
        daily = _daily(closed, opened, rows_by, costs, kw['start_ms'], kw['end_ms'])
        equity = peak = dd = 0.
        for row in daily:
            equity += row['value']; peak = max(peak, equity); dd = max(dd, peak-equity)
        result.update(marked_DD_trade_sum_bps=dd, daily=daily)
    return result


def run_variant(variant, rows_by, costs, policy, spec):
    validate_spec(spec, rows_by, costs, policy)
    if variant not in spec['variants']:
        raise ValueError('UNFROZEN_VARIANT')
    raw = native.native_replay(rows_by, spec, parameters=tuple(variant['parameters']),
                               control=variant.get('control'), ablation=variant.get('ablation'))
    out = {name: [] for name in ('trades', 'open_observations', 'events', 'trace', 'reference_opportunities')}
    out['audit'] = raw['audit']
    for symbol, rows in sorted(rows_by.items()):
        selected = {key: [t for t in raw[key] if t['symbol'] == symbol]
                    for key in ('trades', 'open_positions', 'events', 'trace')}
        selected['audit'] = raw['audit'][symbol]
        charged = account.charge_result(selected, symbol, 'keltner_trend_main', variant['id'], policy, costs, rows)
        for key in ('trades', 'open_observations', 'events', 'trace'):
            out[key].extend(charged[key])
    out['reference_opportunities'] = raw['reference_opportunities']
    out.update(variant=variant, specification_sha256=spec['receipt_sha256'], data_sha256=spec['data_sha256'],
               cost_sha256=spec['cost_sha256'], candidate_sha256=CANDIDATE,
               evidence_kind='ACTUAL_REUSED_DEV_VALIDATION', independent=False, formal_credit=0,
               limitation=spec['control_semantics'].get(variant.get('control')), new_candidate_selected=False)
    out['metrics'] = metrics(out['trades'], out['open_observations'], spec, rows_by, costs)
    out['economic_digest'] = sha({k: out[k] for k in ('trades', 'open_observations', 'events', 'trace', 'reference_opportunities', 'audit')})
    return out


def regime_decomposition(center, rows_by, spec):
    """Annotate existing admitted trade origins; no native replay or new entries."""
    labels = {}
    for symbol, rows in rows_by.items():
        bundle = native.d.build_bundle(rows, native.d.PARENT_SPEC, eval_start_ms=spec['start_ms'], eval_end_ms=spec['runoff_end_ms'])
        labels[symbol] = native._regimes(rows, bundle, spec['regime'])
    closed = deepcopy(center['trades'])
    opened = deepcopy(center.get('open_observations', center.get('open_positions', [])))
    for t in closed+opened:
        i = t['signal_index']
        if t['signal_ts'] != rows_by[t['symbol']][i]['bar_close_ts']:
            raise ValueError('STORED_CENTER_SIGNAL_INDEX_ORIGIN_MISMATCH')
        t['regime_id'] = labels[t['symbol']][i]
    groups = ('UP:HIGH', 'UP:LOW', 'DOWN_OR_FLAT:HIGH', 'DOWN_OR_FLAT:LOW')
    return {'evidence_kind': 'ACTUAL_EXISTING_DEV_LEDGER_DECOMPOSITION', 'replay_count': 0,
            'regime_rule': spec['regime'], 'center_ledger_sha256': sha(center),
            'by_regime': {g: metrics([t for t in closed if t['regime_id'] == g],
                                    [t for t in opened if t['regime_id'] == g], spec) for g in groups},
            'annotated_closed': closed, 'annotated_open': opened, 'formal_credit': 0,
            'regime_permutation': {'applicable': False, 'reason': 'NO_REGIME_VARIABLE_IN_NATIVE_ENTRY_POLICY'}}


def _write_new(path, value):
    data = canonical(value)
    with path.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def validate_actual_dev_entry(spec, rows_by, policy):
    """Reject synthetic/expanded inputs before allocating any actual attempt."""
    calendar = [evidence.DEV_START, evidence.DEV_END]
    if (policy.get('data_ref') != evidence.DATA_REF
            or policy.get('development_interval_ms') != calendar
            or [spec.get('start_ms'), spec.get('entry_stop_ms')] != calendar
            or spec.get('runoff_end_ms') != evidence.DEV_END
            or set(rows_by) != set(native.SYMBOLS)):
        raise ValueError('ACTUAL_DEV_EXACT_SCOPE_REQUIRED')
    lineage = spec.get('data_input_receipt', {})
    if (not isinstance(lineage, dict)
            or lineage.get('receipt_sha256') != evidence.alpha.sha(
                {k: v for k, v in lineage.items() if k != 'receipt_sha256'})
            or lineage.get('calendar_ms') != calendar
            or lineage.get('data_ref') != evidence.DATA_REF
            or lineage.get('candidate_sha256') != CANDIDATE
            or lineage.get('cost_sha256') != policy.get('cost_binding_sha256')
            or any(type(lineage.get(k)) is not int or lineage[k] != 0
                   for k in ('decoded_OOS_rows', 'decoded_validation_rows', 'new_collection_calls'))
            or lineage.get('immutable_history_verified') is not True):
        raise ValueError('ACTUAL_DEV_LINEAGE_REQUIRED')
    access = lineage.get('decoded_prefix_by_symbol', {})
    if set(access) != set(native.SYMBOLS):
        raise ValueError('ACTUAL_DEV_PREFIX_UNIVERSE')
    prefix_hashes = {}
    for symbol, rows in rows_by.items():
        if (len(rows) != evidence.COUNT
                or any(r.get('bar_open_ts') != evidence.DEV_START+i*evidence.BAR
                       or r.get('bar_close_ts') != evidence.DEV_START+(i+1)*evidence.BAR
                       for i, r in enumerate(rows))):
            raise ValueError('ACTUAL_DEV_EXACT_PREFIX_REQUIRED:'+symbol)
        prefix_hashes[symbol] = evidence.alpha.sha(rows)
        expected = {'decoded_partition': 'development', 'decoded_rows': evidence.COUNT,
                    'development_rows_sha256': prefix_hashes[symbol],
                    'first_open_ms': evidence.DEV_START, 'last_close_ms': evidence.DEV_END,
                    'decoded_OOS_rows': 0, 'decoded_validation_rows': 0,
                    'opaque_complete_file_checksum_only': True}
        if access[symbol] != expected:
            raise ValueError('ACTUAL_DEV_PREFIX_RECEIPT_MISMATCH:'+symbol)
    # Pinned after the sole authorized source decode, before variant outcomes.
    prefix = evidence.alpha.sha(prefix_hashes)
    if (prefix != 'c53b9ad73cbc167e35e147b127bf875a99de90067caa685e0c551e576e3588cd'
            or lineage.get('actual_prefix_map_sha256') != prefix):
        raise ValueError('ACTUAL_DEV_CANONICAL_PREFIX_BYTES_REQUIRED')
    probe_policy = json.loads((ROOT/evidence.PROBE_POLICY).read_bytes())
    if (lineage.get('manifest_receipt_sha256') != probe_policy['manifest_sha256']
            or set(lineage.get('opaque_source_files_sha256', {})) !=
               {'ohlcv/'+s+'.json' for s in native.SYMBOLS}
            or set(lineage.get('cost_file_sha256', {})) != set(native.SYMBOLS)):
        raise ValueError('ACTUAL_DEV_SOURCE_MANIFEST_REQUIRED')


def run_manifest(spec, rows_by, costs, policy, out_dir):
    """Single actual runner; completed artifacts reused, every failure consumed."""
    validate_spec(spec, rows_by, costs, policy)
    validate_actual_dev_entry(spec, rows_by, policy)
    out_dir = Path(out_dir)
    expected = ROOT/evidence.CAMPAIGN/'DEV_VALIDATION/VARIANTS'
    budget_path = ROOT/evidence.CAMPAIGN/'BUDGET.json'
    budget = json.loads(budget_path.read_bytes())
    allocation = budget.get('kr3_dev_validation_allocation', {})
    if (out_dir.resolve() != expected.resolve()
            or allocation.get('specification_sha256') != spec['receipt_sha256']
            or allocation.get('variant_ids') != [v['id'] for v in spec['variants']]
            or allocation.get('max_actual_variants') != 12):
        raise ValueError('CANONICAL_SHARED_ALLOCATION_REQUIRED_NO_PATH_RESET')
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for ordinal, variant in enumerate(spec['variants'], 1):
        folder = out_dir/variant['id']; folder.mkdir(exist_ok=True)
        attempt, receipt, payload = folder/'ATTEMPT.json', folder/'RECEIPT.json', folder/'RESULT.json.gz'
        if receipt.exists():
            value = json.loads(receipt.read_bytes())
            if (value['specification_sha256'] != spec['receipt_sha256'] or value['status'] != 'COMPLETED'
                    or hashlib.sha256(payload.read_bytes()).hexdigest() != value['artifact_sha256']):
                raise ValueError('CONSUMED_OR_DIFFERENT_VARIANT_NO_RETRY:'+variant['id'])
            index.append(value); continue
        reservation = {'variant': variant, 'ordinal_within_manifest': ordinal,
                       'actual_experiment_ordinal': 44+ordinal,
                       'specification_sha256': spec['receipt_sha256'], 'data_sha256': spec['data_sha256'],
                       'pid': os.getpid(), 'started_at': datetime.now(timezone.utc).isoformat(),
                       'status': 'RESERVED_BEFORE_NATIVE_REPLAY', 'retry_allowed': False}
        _write_new(attempt, reservation)
        # Root is the sole execution/ledger writer. An attempt file consumed
        # before this write also blocks a retry after a process interruption.
        budget = json.loads(budget_path.read_bytes())
        budget['trials'].append(reservation)
        budget['kr3_dev_validation_allocation']['used'] += 1
        budget['cumulative_actual_evaluations'] = 44+budget['kr3_dev_validation_allocation']['used']
        pending_budget = budget_path.with_suffix('.pending')
        with pending_budget.open('x') as stream:
            json.dump(budget, stream, sort_keys=True, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(pending_budget, budget_path)
        started = time.perf_counter()
        try:
            result = run_variant(variant, rows_by, costs, policy, spec)
            data = gzip.compress(canonical(result), mtime=0)
            with payload.open('xb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            value = {**reservation, 'status': 'COMPLETED', 'seconds': time.perf_counter()-started,
                     'finished_at': datetime.now(timezone.utc).isoformat(),
                     'artifact_sha256': hashlib.sha256(data).hexdigest(), 'economic_digest': result['economic_digest'],
                     'metrics': {k: v for k, v in result['metrics'].items() if k != 'daily'}}
            _write_new(receipt, value); index.append(value)
            print(json.dumps({'variant': variant['id'], 'status': 'COMPLETED', 'closed_T': result['metrics']['closed_T'],
                              'open_T': result['metrics']['open_T'], 'seconds': value['seconds']}), flush=True)
        except BaseException as exc:
            if not receipt.exists():
                _write_new(receipt, {**reservation, 'status': 'FAILED_CONSUMED', 'error_type': type(exc).__name__,
                                    'error': str(exc), 'seconds': time.perf_counter()-started,
                                    'finished_at': datetime.now(timezone.utc).isoformat()})
            raise
    return {'specification_sha256': spec['receipt_sha256'], 'results': index,
            'actual_variants': len(index), 'new_adoption': False, 'formal_credit': 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--run', action='store_true', required=True)
    args = parser.parse_args()
    # This loader has no observer/SEEN2026/OOS decode route.
    from backend.research.rebuild.step7_kr3_dev_evidence_v1 import load_dev_slice
    rows_by, policy, costs, _ = load_dev_slice(args.data_dir)
    result = run_manifest(json.loads(args.spec.read_bytes()), rows_by, costs, policy, args.out_dir)
    path = args.out_dir/'INDEX.json'
    if path.exists():
        if json.loads(path.read_bytes()) != result:
            raise ValueError('EXISTING_INDEX_DIFFERENT')
    else:
        _write_new(path, result)


if __name__ == '__main__':
    main()
