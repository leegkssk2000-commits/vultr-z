"""A-only, run-once passive K117 instrumentation. D runs synthetic tests only.

No policy, carry-reference replay, guard, Actions, owner-marker or source writes.
The existing owner arranges the existing global-heavy slot before this command.
An acknowledgement neither acquires that slot nor grants execution authority.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OWNER = "CLOUD_WORK_COORDINATOR_ISSUE1358_V1"
COMMIT = "8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8"
K117 = Path('/home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1')
STRUCTURE = Path('/home/z/z/runtime/k126_pullback_structure_failure_20261021_v1')
C_EXACT = Path('/home/z/z/runtime/k126_c_veto_consume_20261022_v1/work_c_exact')
CACHE = Path('/home/z/z/runtime/k_winner_handoff_20261021T1230Z')
PINS = {
    'SUMMARY.json': 'c2dfcdbec704fb7ab020c2d4d53293fd03dab5820672e0ac6fb4f9aa6094e5ae',
    'EXECUTION_FREEZE.json': '918d00133ddb1b498bd93353a48f6e8a75f2da83b4062e3430db52b99b57ef0a',
}
ROWS_SHA = '7cba96a0627dbec42459f344a6e8e7dd70d97f87d71dfb573e10975153d7d0a7'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def checked(path, pin):
    raw = Path(path).read_bytes()
    if sha(raw) != pin:
        raise ValueError('PIN_CHANGED:' + str(path))
    return raw


def load_saved(directory):
    values = {name: json.loads(checked(directory / name, pin)) for name, pin in PINS.items()}
    plain = gzip.decompress((directory / 'ROWS.json.gz').read_bytes())
    if sha(plain) != ROWS_SHA:
        raise ValueError('K117_ROWS_CHANGED')
    saved = json.loads(plain)
    summary = values['SUMMARY.json']
    if (len(saved['trades']) != 117 or len(saved['raw_trades']) != 117
            or summary['candidate'] != 'scalp7_k126_veto_objective_completed_fresh_touch_v1'
            or summary['rows_sha256'] != ROWS_SHA):
        raise ValueError('K117_IDENTITY_CHANGED')
    return saved, summary


def key(row):
    return str(row['symbol']), int(row['side']), int(row['signal_ts_ms'])


def verify_parity(result, saved):
    """All ordered raw rows, unresolved and boundary collections must be equal."""
    for new, old in [('trades', 'raw_trades'), ('unresolved', 'unresolved'),
                     ('boundary_excluded', 'boundary_excluded')]:
        rolling = [r for r in result[new] if r['partition'] == 'rolling']
        if rolling != saved[old]:
            raise ValueError('K117_OBSERVER_PARITY_FAILED:' + new)
    if len(saved['raw_trades']) != 117 or len({key(r) for r in saved['raw_trades']}) != 117:
        raise ValueError('K117_ALL117_REQUIRED')


@contextmanager
def existing_lock(path):
    # Read-only existing file; never create, truncate or replace a runtime lock.
    with path.open('rb') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def memory_only_single(module, instrumented):
    original = module._single
    module._single = instrumented
    try:
        yield
    finally:
        module._single = original


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save_new(directory, name, value, compressed=False):
    raw = encoded(value)
    if compressed:
        raw = gzip.compress(raw, mtime=0)
    with (directory / name).open('xb') as handle:
        handle.write(raw)
    return {'sha256': sha(raw), 'bytes': len(raw)}


def bind_frames(source, context, pd, dependency, repo, base):
    expected = dependency['source_symbols_order']
    if list(source.SYMBOLS) != expected:
        raise ValueError('FROZEN_SYMBOL_ORDER_CHANGED')
    cache = json.loads(checked(CACHE / 'INPUT_CACHE.json', dependency['cache_manifest_sha256']))
    binding = json.loads(checked(base / 'CHRONO_SOURCE_BINDING.json', dependency['binding_sha256']))
    if set(cache['symbols']) != set(expected) or set(binding) != set(expected):
        raise ValueError('SOURCE_SYMBOL_SET_CHANGED')
    frames, data_pins = {}, {}
    for symbol in source.SYMBOLS:
        rec = cache['symbols'][symbol]
        path = (CACHE / rec['path']).resolve()
        if not path.is_relative_to(CACHE.resolve()):
            raise ValueError('CACHE_PATH_ESCAPE')
        raw = checked(path, rec['sha256'])
        frame = pd.read_csv(io.BytesIO(raw), compression='gzip', float_precision='round_trip')
        digest = sha(frame.to_csv(index=False).encode())
        if len(frame) != 17519 or digest != rec['csv_sha256'] or digest != binding[symbol]['full_csv_sha256']:
            raise ValueError('ORIGINAL_FULL_FRAME_CHANGED:' + symbol)
        frames[symbol] = frame
        data_pins[symbol] = {'compressed_sha256': sha(raw), 'full_csv_sha256': digest, 'rows': len(frame)}
    windows = json.loads((repo / 'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json').read_bytes())['windows']
    costs = json.loads((repo / 'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json').read_bytes())['costs_bps']
    # Fit once on the entire original365-day frames, before native window slicing.
    bound, fits = context.bind_context(frames, context.cross_features(frames), windows)
    fit_sha = sha(json.dumps(fits, sort_keys=True, separators=(',', ':')).encode())
    if fit_sha != dependency['context_fit_sha256']:
        raise ValueError('CONTEXT_FIT_CHANGED')
    return bound, costs, windows, data_pins, fit_sha


def run(args):
    if not args.run_once or args.owner_ack != OWNER:
        raise ValueError('A_ONLY_EXPLICIT_OBSERVER_REQUIRED')
    saved, summary = load_saved(args.baseline_dir)
    dependency = json.loads((HERE / 'REPLAY_DEPENDENCY_PINS.json').read_bytes())
    repo = Path(dependency['repo_root'])
    # Verify the whole inherited chain before importing any native strategy code.
    for path, pin in dependency['runtime_sha256'].items():
        checked(path, pin)
    for path, pin in dependency['repo_sha256'].items():
        checked(repo / path, pin)
    out = args.output_dir.resolve()
    protected = [Path('/home/z/z/runtime'), repo.resolve(), args.baseline_dir.resolve(), HERE]
    if any(out == p or out.is_relative_to(p) for p in protected):
        raise ValueError('OUTPUT_MUST_BE_NEW_OWNER_SCRATCH_OUTSIDE_RUNTIME_REPO_INPUT')
    # Fail closed if used before; this is also the run-once reservation.
    out.mkdir(parents=False, exist_ok=False)
    started = False
    try:
        sys.path[:0] = [str(STRUCTURE), str(C_EXACT), str(K117), str(repo)]
        structure = module_at('_d_frozen_k117_structure', STRUCTURE / 'structural_failure.py')
        objective = module_at('_d_frozen_k117_objective', K117 / 'objective_lifetime.py')
        h = structure.h
        if h.REPO.resolve() != repo.resolve():
            raise ValueError('NATIVE_REPO_ROOT_CHANGED')
        h.timeout.verify_dependencies()
        from backend.research.rebuild import scalp7_source_data_v2 as source
        from backend.research.rebuild import scalp7_rolling_context_v2 as context
        import pandas as pd
        sys.path.insert(0, str(HERE))
        from be_observer import BEObserver, instrument_single
        with existing_lock(h.BASE / 'paired.lock'):
            bound, costs, windows, data_pins, fit_sha = bind_frames(source, context, pd, dependency, repo, h.BASE)
            incumbent = structure.ExitComparison(True).build()
            source_text = inspect.getsource(h.k._fresh_touch_successor)
            if objective.build(incumbent, source_text=source_text, enabled=False) is not incumbent:
                raise ValueError('K117_DISABLED_BUILD_CHANGED')
            baseline = objective.build(incumbent, source_text=source_text, enabled=True)
            recorder = BEObserver()
            engine_text = Path(h.execution.__file__).read_text()
            instrumented = instrument_single(h.execution._single, source_text=engine_text,
                                             observer=recorder, enabled=True)
            save_new(out, 'OBSERVER_INVOCATION.json', {
                'at_utc': datetime.now(timezone.utc).isoformat(), 'owner': OWNER,
                'control_commit': COMMIT, 'kind': 'PASSIVE_K117_NATIVE_INSTRUMENTATION_ONLY',
                'new_policy_comparisons': 0, 'baseline_rows_sha256': ROWS_SHA,
                'no_blind_retry': True, 'source_inputs': data_pins})
            started = True
            with memory_only_single(h.execution, instrumented):
                result = baseline(bound, costs, windows)
            verify_parity(result, saved)
            if baseline.events != saved['objective_expiry_events']:
                raise ValueError('K117_OBJECTIVE_EVENTS_CHANGED')
            if result.get('traces', []) != saved['native_traces']:
                raise ValueError('K117_NATIVE_ENTRY_TRACES_CHANGED')
            joined = join_all117(recorder.records, saved, h.k._relabel)
            files = {
                'BE_NATIVE_CALLS.json.gz': save_new(out, 'BE_NATIVE_CALLS.json.gz', recorder.records, True),
                'BE_ALL117.json.gz': save_new(out, 'BE_ALL117.json.gz', joined, True),
            }
            receipt = {'classification': 'PASSIVE_EXACT_K117_TRACE_NOT_NEW_PERFORMANCE',
                       'control_commit': COMMIT, 'raw117_exact': True, 'all117_joined': len(joined),
                       'unresolved_exact': True, 'boundary_exact': True,
                       'objective_events_exact': True, 'entry_traces_exact': True,
                       'context_fit_sha256': fit_sha, 'saved_cost1x': summary['child']['cost1x']['Net_bps'],
                       'saved_cost2x': summary['child']['cost2x']['Net_bps'],
                       'costs_recomputed_or_changed': False, 'new_policy_comparisons': 0,
                       'source_policy_changed': False, 'orders': 0, 'files': files}
            save_new(out, 'OBSERVER_RECEIPT.json', receipt)
            print(json.dumps(receipt, sort_keys=True))
    except Exception as exc:
        save_new(out, 'OBSERVER_FAILURE.json', {'error_type': type(exc).__name__,
                 'error': str(exc), 'native_instrumentation_started': started, 'no_blind_retry': True})
        raise


def join_all117(records, saved, relabel):
    """Implemented against observer's return schema; never selects by final PnL."""
    wanted = {key(row): row for row in saved['raw_trades']}
    found = {}
    for rec in records:
        native = rec.get('trade')
        if native is None or key(native) not in wanted:
            continue
        k = key(native)
        expected = wanted[k]
        actual = relabel(deepcopy(native))
        actual.update(window_label=expected['window_label'], partition=expected['partition'])
        if actual != expected:
            # A duplicated development-window call cannot masquerade as the rolling trade.
            continue
        if k in found:
            if rec['events'] != found[k]['events']:
                raise ValueError('AMBIGUOUS_K117_TRACE')
            found[k]['identical_native_call_count'] += 1
        else:
            found[k] = {'key': list(k), 'events': deepcopy(rec['events']),
                        'identical_native_call_count': 1, 'raw_trade_exact': True}
    if set(found) != set(wanted) or len(wanted) != 117:
        raise ValueError('K117_TRACE_JOIN_INCOMPLETE')
    economic = {key(row): row for row in saved['trades']}
    joined = []
    for raw in saved['raw_trades']:
        k = key(raw)
        item = found[k]
        item.update(reference_cost_bps=raw['signal']['meta']['frozen_cost_bps'],
                    native_cost_bps=raw['cost_bps'], booked_cost_bps=economic[k]['cost_bps'],
                    extra_carry_scenario_bps=economic[k]['cost_bps']-raw['cost_bps'],
                    stress2x_is_posthoc_only=True, decision_inputs_include_outcomes=False)
        joined.append(item)
    return joined


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-ack', required=True)
    parser.add_argument('--run-once', action='store_true')
    parser.add_argument('--baseline-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path,
                        help='new directory under existing A scratch parent, outside runtime/repo/inputs')
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()
