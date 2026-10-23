#!/usr/bin/env python3
"""Run only isolated Work D offline verification into a NEW output directory."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    base = Path(__file__).resolve().parent
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(base))
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    input_hashes = {str(p.relative_to(base)): sha(p) for p in sorted(base.rglob('*'))
                    if p.is_file() and '__pycache__' not in p.parts and 'results' not in p.relative_to(base).parts}
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(base), pattern='test_*.py', top_level_dir=str(base))
    start = time.monotonic()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    (out / 'TEST_LOG.txt').write_text(stream.getvalue())
    commands = [[sys.executable, '-B', str(base / 'receipt_guard.py'), '--inputs-root', str(base), '--out', str(out / 'RESULT.json')]]
    for command in commands:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        (out / 'CLI_LOG.txt').write_text(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError('OFFLINE_CLI_FAILED:' + str(completed.returncode))
    from test_guard import observer_mixing_counterexample
    (out / 'OBSERVER_MIXING_COUNTEREXAMPLE.json').write_text(json.dumps(observer_mixing_counterexample(), indent=2, sort_keys=True) + '\n')
    # A published top-ten reference is a saved result excerpt, never an old replay.
    from historical_winner_reference import compare_reference
    from receipt_guard import load_pinned_bundle
    reference = json.loads((base / 'inputs/historical_published_top10_reference.json').read_text())
    historical = {name: compare_reference(reference, load_pinned_bundle(base, name)['receipt']) for name in ('current255', 'later256')}
    (out / 'HISTORICAL_WINNER_REFERENCE.json').write_text(json.dumps(historical, indent=2, sort_keys=True) + '\n')
    receipt = {
        'schema': 'work_d.current_trendrider.offline_validation.v1',
        'state': 'PASS' if result.wasSuccessful() and not result.skipped else 'FAIL',
        'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'elapsed_seconds': round(time.monotonic() - start, 6),
        'environment': {'python': sys.version, 'platform': platform.platform(), 'dependencies': 'Python standard library only'},
        'command': 'PYTHONDONTWRITEBYTECODE=1 python -B ' + str(base / 'run_verification.py') + ' --out ' + str(out),
        'offline_cli_commands': commands, 'all_source_and_input_sha256': input_hashes,
        'outputs_sha256': {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()},
        'economic_full': 'NOT_RUN', 'native_replay': 'NOT_RUN', 'market_api_calls': 0, 'actions_dispatches': 0,
        'orders': 0, 'old_K117_or_D_tests_repeated': 0, 'owner_mutations': 0,
        'test_result_is_profit_evidence': False,
    }
    (out / 'RUN_RECEIPT.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: receipt[k] for k in ('state', 'tests_run', 'failures', 'errors', 'skipped')}))
    print('RESULT_SHA256=' + sha(out / 'RESULT.json'))
    if receipt['state'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
