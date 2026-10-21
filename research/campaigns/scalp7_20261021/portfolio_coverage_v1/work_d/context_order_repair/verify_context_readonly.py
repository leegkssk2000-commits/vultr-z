"""Read existing cache and compute context hashes only; never import an economic runner."""
from pathlib import Path
import argparse
import ast
import base64
import hashlib
import io
import json
import sys
import types

ENGINE_REF = '6f7a42171dab54ff1be544304f44ee06fdd8f056'
SOURCE_SHA = '7cf2507ad4a23827644d7f58a33512ea6c83590305c5630cce6ff1063ae506e5'
CONTEXT_SHA = '672934c9df51d2fd30c43e5099342d7bda1c5b0661dec1670165ad9fd7a6ceaf'
LOADER_SHA = 'dd54d017df362f51e587fa5feaa215bb1bf711430f4e5b7e8cd3bd6fe3efdd57'
EXPECTED = '168044bf3bfd2bc4299c55fca84bc45c2e3ce56a79310e4583b02277c296b86c'
FAILED = '7f56091f7671215dc96ebf5c02f5f815dcfe18e54f0b5d262d1821b9d17769c3'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify(loader_text, stage, baseline, repo):
    sys.dont_write_bytecode = True
    stage, baseline, repo = map(Path, (stage, baseline, repo))
    assert sha(loader_text.encode()) == LOADER_SHA, 'PATCHED_LOADER_CHANGED'
    for relative, expected in [
        ('backend/research/rebuild/scalp7_source_data_v2.py', SOURCE_SHA),
        ('backend/research/rebuild/scalp7_rolling_context_v2.py', CONTEXT_SHA),
    ]:
        assert sha((repo / relative).read_bytes()) == expected, relative
    cache_path = stage / 'INPUT_CACHE.json'
    windows_path = repo / 'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json'
    baseline_path = baseline / 'CHRONO_SOURCE_BINDING.json'
    cache = json.loads(cache_path.read_text())
    # Detect source and execution evidence mutations across this read-only operation.
    watched = [cache_path, baseline_path, windows_path]
    watched += [stage / name for name in ('guarded_once.py', 'STARTED.json', 'EXECUTION.log', 'GUARD_STATUS.json') if (stage / name).is_file()]
    watched += [stage / row['path'] for row in cache['symbols'].values()]
    before = {str(p): sha(p.read_bytes()) for p in watched}
    sys.path.insert(0, str(repo))
    from backend.research.rebuild import scalp7_source_data_v2 as source
    from backend.research.rebuild import scalp7_rolling_context_v2 as context
    functions = [n for n in ast.parse(loader_text).body if isinstance(n, ast.FunctionDef) and n.name == 'run_cached']
    assert len(functions) == 1, 'RUN_CACHED_NOT_UNIQUE'
    captured = {}
    runner = types.ModuleType('run_handoff')
    runner.BASE = baseline
    runner.previous = types.SimpleNamespace()
    # This stub cannot replay a control, candidate, strategy or order.
    runner.run = lambda: captured.update(frames=runner.previous.full_frames())
    previous_module = sys.modules.get('run_handoff')
    sys.modules['run_handoff'] = runner
    try:
        namespace = {'S': stage, 'json': json, 'io': io, 'sha': sha}
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<patched-loader-only>', 'exec'), namespace)
        namespace['run_cached']()
    finally:
        if previous_module is None:
            sys.modules.pop('run_handoff', None)
        else:
            sys.modules['run_handoff'] = previous_module
    frames = captured['frames']
    assert tuple(frames) == tuple(source.SYMBOLS), 'ORDER_NOT_RESTORED'
    windows = json.loads(windows_path.read_text())['windows']

    def fits_for(ordered):
        features = context.cross_features(ordered)
        fits = [context.fit_context(features, window) for window in windows]
        return fits, sha(json.dumps(fits, sort_keys=True, separators=(',', ':')).encode())

    restored_fits, restored_hash = fits_for(frames)
    cached_fits, cached_hash = fits_for({s: frames[s] for s in cache['symbols']})
    assert restored_hash == EXPECTED, 'RESTORED_CONTEXT_FIT_CHANGED'
    assert cached_hash == FAILED, 'NEGATIVE_CONTROL_DIFFERENT_FROM_PINNED_DIAGNOSIS'
    after = {str(p): sha(p.read_bytes()) for p in watched}
    assert before == after, 'OBSERVED_INPUT_OR_EXECUTION_EVIDENCE_CHANGED'
    return {
        'schema': 'zel.work_d.context_order_readonly_parity.v1',
        'classification': 'REAL_CACHED_CSV_CONTEXT_ONLY_NO_CONTROL_OR_CANDIDATE_REPLAY',
        'engine_ref': ENGINE_REF, 'patched_loader_sha256': LOADER_SHA,
        'source_module_sha256': SOURCE_SHA, 'context_module_sha256': CONTEXT_SHA,
        'cache_order': list(cache['symbols']), 'restored_order': list(frames),
        'rows_by_symbol': {s: len(f) for s, f in frames.items()},
        'all_gzip_csv_and_original_binding_checks_passed': True,
        'fit_windows': len(windows),
        'changed_fit_windows_between_orders': sum(a != b for a, b in zip(cached_fits, restored_fits)),
        'expected_context_fit_sha256': EXPECTED,
        'cached_order_context_fit_sha256': cached_hash,
        'restored_context_fit_sha256': restored_hash,
        'restored_exact_match': restored_hash == EXPECTED,
        'watched_file_sha256_before_and_after': before,
        'watched_files_unchanged': True,
        'runner_is_capture_stub': True,
        'remote_patch_installed': False,
        'control126_replays': 0, 'candidate_replays': 0, 'guards_started': 0,
        'workflow_dispatches': 0, 'orders': 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--loader')
    group.add_argument('--loader-base64')
    for name in ('stage', 'baseline', 'repo'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    text = Path(args.loader).read_text() if args.loader else base64.b64decode(args.loader_base64, validate=True).decode()
    print(json.dumps(verify(text, args.stage, args.baseline, args.repo), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
