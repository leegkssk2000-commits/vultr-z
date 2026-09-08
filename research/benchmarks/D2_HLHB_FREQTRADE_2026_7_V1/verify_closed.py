"""Read-only stdlib verifier. No market, strategy, engine, network or writers."""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

SPEC_SHA = 'f99d3bdc8a6edd0083b81ec5e9d4931511116213bdcc8c54d1224c0996fffaba'
SCOPE = 'ZEL_EXTERNAL_ENGINE_STRATEGY_BENCHMARK_AFTER_PR1218_V1'
RUNS = {'D2_DEV2025': 73, 'D2_SEEN2026': 74, 'HLHB_DEV2025': 75, 'HLHB_SEEN2026': 76}
FAILURES = {'D2_SEEN2026': 'D2_CALLBACK_ERRORS_OR_ENTRY_ACCOUNTING', 'HLHB_SEEN2026': 'ENTRY_OUTSIDE_APPROVED_PERIOD'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def near(a, b):
    return math.isfinite(float(a)) and math.isfinite(float(b)) and math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-7)


def checked_path(root, name):
    p = Path(name)
    require(not p.is_absolute() and '..' not in p.parts and p.parts, 'UNSAFE_MANIFEST_PATH')
    target = root / p
    require(target.resolve().is_relative_to(root.resolve()) and not target.is_symlink(), 'MANIFEST_PATH_ESCAPE')
    return target


def validate_manifest(root, raw, expected):
    require(bool(re.fullmatch('[0-9a-f]{64}', expected)), 'EXPLICIT_MANIFEST_SHA_REQUIRED')
    require(sha(raw) == expected, 'EXTERNAL_MANIFEST_HASH_MISMATCH')
    doc = json.loads(raw)
    files = doc['files']
    require(isinstance(files, dict) and files, 'EMPTY_MANIFEST')
    for name, expected_file in files.items():
        require(sha(checked_path(root, name).read_bytes()) == expected_file, 'FILE_HASH_MISMATCH:' + name)
    return files


def validate_record(r):
    require(r['engine_version'] == '2026.7' and r['formal_credit'] == 0 and not r['independent'], 'CREDIT_OR_ENGINE_CHANGED')
    ts, m = r['normalized_trades'], r['metrics']
    require(len({t['origin'] for t in ts}) == len(ts), 'DUPLICATE_ORIGIN')
    closed = [t for t in ts if t['closed']]
    wins = [t['net_bps'] for t in closed if t['net_bps'] > 0]
    losses = [-t['net_bps'] for t in closed if t['net_bps'] < 0]
    require((m['closed'], m['open'], m['wins'], m['losses']) == (len(closed), len(ts)-len(closed), len(wins), len(losses)), 'LEDGER_COUNTS')
    require(m['win_rate'] is None if not closed else near(m['win_rate'], len(wins)/len(closed)), 'WIN_RATE')
    for t in ts:
        require(t['entry_ts'] <= t['exit_ts_lower'] <= t['exit_ts'] and t['entry_price'] > 0, 'TRADE_TIME_OR_PRICE')
        require(near(t['gross_bps'], (t['exit_price']/t['entry_price']-1)*10000), 'GROSS_PRICE')
        require(near(t['net_bps'], t['gross_bps']-t['cost_bps']), 'NET_COST')
        require(near(t['cost2_bps'], t['gross_bps']-2*t['cost_bps']), 'COST2')
        require(t['cost_bps'] >= t['cost_lower_bps'] >= 20, 'COST_BOUNDS')
        require(t['reason'] != 'force_exit' or not t['closed'], 'FORCE_EXIT_REALIZED')
    for key, values in [('terminal_net', [t['net_bps'] for t in ts]), ('terminal_cost2', [t['cost2_bps'] for t in ts]),
                        ('closed_net', [t['net_bps'] for t in closed]), ('open_mark', [t['net_bps'] for t in ts if not t['closed']])]:
        require(near(m[key], sum(values)), 'LEDGER_TOTAL:' + key)
    if wins:
        require(near(m['average_win_bps'], sum(wins)/len(wins)), 'AVERAGE_WIN')
    if losses:
        require(near(m['average_loss_bps'], sum(losses)/len(losses)), 'AVERAGE_LOSS')
        require(near(m['PF'], sum(wins)/sum(losses)), 'PF')
    if wins and losses:
        require(near(m['payoff'], (sum(wins)/len(wins))/(sum(losses)/len(losses))), 'PAYOFF')
    for curvekey, ddkey, terminal in [('equity4h', 'mark4h_DD', 'terminal_net'), ('equity4h_cost2', 'mark4h_cost2_DD', 'terminal_cost2')]:
        peak = dd = 0.
        curve = m[curvekey]
        require([x[0] for x in curve] == sorted(set(x[0] for x in curve)), 'EQUITY_CLOCK')
        for _, value in curve:
            peak = max(peak, value); dd = max(dd, peak-value)
        require(near(dd, m[ddkey]), 'SAVED_EQUITY_DD')
        require(not ts or (curve and near(curve[-1][1], m[terminal])), 'SAVED_EQUITY_TERMINAL')
    bysymbol = {s: sum(t['net_bps'] for t in ts if t['symbol'] == s) for s in m['by_symbol']}
    require(all(near(v, m['by_symbol'][s]) for s, v in bysymbol.items()), 'SYMBOL_TOTALS')


def validate_budget(inherited, current):
    require((inherited['cumulative_actual'], inherited['cumulative_actual_evaluations']) == (48, 72), 'INHERITED_COUNTS')
    require((current['cumulative_actual'], current['cumulative_actual_evaluations']) == (49, 76), 'FINAL_COUNTS')
    allocation = current['d2_hlhb_external_allocation']
    require((allocation['used'], allocation['completed'], allocation['failed'], allocation['remaining'], allocation['max_executions']) == (4, 2, 2, 0, 4), 'ALLOCATION')
    require(allocation['retry'] is False and allocation['scope'] == SCOPE, 'ALLOCATION_RETRY')
    projection = deepcopy(current)
    del projection['d2_hlhb_external_allocation']
    projection['trials'] = [t for t in projection['trials'] if t.get('scope') != SCOPE]
    projection['candidate_trials'] = [t for t in projection['candidate_trials'] if t.get('scope') != SCOPE]
    projection['cumulative_actual'], projection['cumulative_actual_evaluations'] = 48, 72
    require(projection == inherited, 'INHERITED_BUDGET_MUTATION')
    trials = [t for t in current['trials'] if t.get('scope') == SCOPE]
    require(len(trials) == 4 and {t['actual_experiment_ordinal'] for t in trials} == {73, 74, 75, 76}, 'TRIAL_ORDINALS')
    return {t['run']: t for t in trials}


def verify(root, manifest_sha256):
    root = Path(root)
    files = validate_manifest(root, (root/'FINAL_HASHES.json').read_bytes(), manifest_sha256)
    required = {'SPEC.json', 'INHERITED_BUDGET_PR1219.json', 'BUDGET.json'}
    spec_raw = (root/'SPEC.json').read_bytes()
    require(sha(spec_raw) == SPEC_SHA, 'FROZEN_SPEC_HASH')
    spec = json.loads(spec_raw)
    require(spec['scope'] == SCOPE and spec['max_full_executions'] == 4 and spec['native_replays'] == 0, 'SPEC_SCOPE')
    for name, expected in spec['scientific_sha256'].items():
        required.add(name)
        require(sha(checked_path(root, name).read_bytes()) == expected, 'SCIENTIFIC_CODE_CHANGED:' + name)
    inherited_raw = (root/'INHERITED_BUDGET_PR1219.json').read_bytes()
    require(sha(inherited_raw) == spec['inherited_budget_sha256'], 'INHERITED_BYTES_CHANGED')
    trials = validate_budget(json.loads(inherited_raw), json.loads((root/'BUDGET.json').read_bytes()))
    require({p.name for p in (root/'attempts').glob('*.json')} == {n+'.json' for n in RUNS}, 'EXTRA_OR_MISSING_ATTEMPT')
    for name, ordinal in RUNS.items():
        attempt_path = f'attempts/{name}.json'
        required.add(attempt_path)
        at = json.loads((root/attempt_path).read_bytes())
        require(at['run'] == name and at['ordinal'] == at['actual_experiment_ordinal'] == ordinal and at['spec_sha256'] == SPEC_SHA and at['retry_allowed'] is False, 'ATTEMPT_IDENTITY')
        base = root/'results'/name
        required.update({f'results/{name}/LOCAL_START.json', f'results/{name}/RAW_ENGINE.json.gz'})
        start = json.loads((base/'LOCAL_START.json').read_bytes())
        claim = dict(start['claim']); remote = claim.pop('remote_readback_commit', None)
        require(claim == at and bool(re.fullmatch('[0-9a-f]{40}', remote or '')) and start['retry'] is False, 'LOCAL_START_RESERVATION')
        trial = trials[name]
        require(trial['ordinal'] == ordinal and trial['retry_allowed'] is False, 'TRIAL_IDENTITY')
        if name in FAILURES:
            required.add(f'results/{name}/FAILURE.json')
            f = json.loads((base/'FAILURE.json').read_bytes())
            require(f['status'] == trial['status'] == 'FAILED_CONSUMED' and f['message'] == trial['failure'] == FAILURES[name] and f['retry_allowed'] is False, 'FAILED_ATTEMPT_CHANGED')
            require(not (base/'RESULT.json').exists() and not (base/'RESULT.json.gz').exists() and not (base/'RECEIPT.json').exists(), 'FAILED_RESULT_FABRICATED')
        else:
            required.update({f'results/{name}/RECEIPT.json', f'results/{name}/RESULT.json.gz'})
            require(not (base/'FAILURE.json').exists(), 'VALID_HAS_FAILURE')
            raw = gzip.decompress((base/'RESULT.json.gz').read_bytes())
            receipt = json.loads((base/'RECEIPT.json').read_bytes())
            require(receipt['status'] == trial['status'] == 'COMPLETED' and receipt['run'] == name and receipt['ordinal'] == ordinal and receipt['spec_sha256'] == SPEC_SHA, 'RECEIPT_IDENTITY')
            require(sha(raw) == receipt['result_sha256'] == trial['result_sha256'], 'RESULT_RECEIPT_HASH')
            if (base/'RESULT.json').exists():
                require((base/'RESULT.json').read_bytes() == raw, 'RESULT_COMPRESSED_PARITY')
            r = json.loads(raw)
            require(r['run'] == name and r['scope'] == SCOPE, 'RESULT_SCOPE')
            require(sha(gzip.decompress((base/'RAW_ENGINE.json.gz').read_bytes())) == r['raw_result_sha256'], 'RAW_ENGINE_BINDING')
            validate_record(r)
    require(required <= set(files), 'MISSING_MANIFEST_REQUIRED_FILES:' + ','.join(sorted(required-set(files))))
    return {'status': 'STORED_4_CONSUMED_2_VALID_2_FAILED_VERIFIED', 'economic_replays': 0, 'market_reads': 0,
            'formal_credit': 0, 'inherited_counts': [48, 72], 'final_counts': [49, 76]}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    a = p.parse_args()
    print(json.dumps(verify(a.root, a.manifest_sha256), sort_keys=True))
