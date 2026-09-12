"""Post-result P1 evidence repair for Issue #1294.

Repairs only top-level row seals on already-completed natural C54 donor rows after
`sleeve_role` was added. No strategy replay, no economic allocation, no metric
mutation. Existing U4 economic results remain unchanged.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

from backend.research.rebuild import kr3_c51_entry_context_study_v1 as c54study

ROOT = Path(__file__).resolve().parents[3]
SCOPE = 'SQUEEZE_KR3_CORE_PLUS_C54_NATIVE_SLEEVE_AFTER_PR1293_V1'
OUT = ROOT / 'research/development_evidence' / SCOPE
BRANCH = 'codex/squeeze-kr3-native-sleeve-1294'
PERIODS = ('DEV2025', 'SEEN2026')
ROLE = 'C54_NATIVE_DONOR_NATURAL'
p = c54study.p


def need(ok, msg):
    if not ok:
        raise RuntimeError(msg)


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def read(path):
    return json.loads(Path(path).read_text())


def read_gz(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canon(obj) + b'\n')


def put_gz(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(canon(obj), mtime=0))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, timeout=45).strip()


def reseal_natural_row(row):
    """Return the same economic row with only its canonical row seal refreshed."""
    out = deepcopy(row)
    need(out.get('sleeve_role') == ROLE, 'NOT_NATURAL_DONOR_ROW')
    field = 'trade_sha256' if 'exit_ts' in out else 'observation_sha256'
    out.pop('trade_sha256', None)
    out.pop('observation_sha256', None)
    out[field] = p.sha(out)
    return out


def verify_row(row):
    field = 'trade_sha256' if 'exit_ts' in row else 'observation_sha256'
    need(field in row, 'MISSING_ROW_SEAL')
    got = row[field]
    payload = deepcopy(row)
    payload.pop('trade_sha256', None)
    payload.pop('observation_sha256', None)
    need(got == p.sha(payload), 'ROW_SEAL_MISMATCH')


def verify_persisted(expected_total=167):
    total = 0
    per_counts = {}
    for per in PERIODS:
        result = read_gz(OUT / per / 'RESULT.json.gz')
        n = 0
        for name in ('trades', 'open_observations'):
            for row in result[name]:
                if row.get('sleeve_role') == ROLE:
                    verify_row(row)
                    n += 1
        per_counts[per] = n
        total += n
    need(total == expected_total, f'NATURAL_DONOR_COUNT_{total}_NE_{expected_total}')
    return per_counts


def persist(msg):
    git('add', '--', str(OUT.relative_to(ROOT)))
    rc = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode
    if rc == 0:
        return git('rev-parse', 'HEAD')
    git('commit', '-m', msg + ' [skip ci]')
    head = git('rev-parse', 'HEAD')
    git('push', 'origin', 'HEAD:refs/heads/' + BRANCH)
    remote = git('ls-remote', 'origin', 'refs/heads/' + BRANCH).split()[0]
    need(head == remote, 'REMOTE_READBACK_MISMATCH')
    return head


def main():
    repair_path = OUT / 'ROW_SEAL_REPAIR.json'
    if repair_path.exists():
        existing = read(repair_path)
        need(existing.get('state') == 'PASS_RESEALED_NATURAL_DONOR_ROWS', 'EXISTING_REPAIR_NOT_PASS')
        verify_persisted(int(existing['total_rows']))
        print('ROW_SEAL_REPAIR_ALREADY_VERIFIED')
        return

    report = {
        'schema': 'zel.squeeze_kr3.native_sleeve.row_seal_repair.v1',
        'scope': SCOPE,
        'review_finding': 'PR1295_r3996063642',
        'economic_replay': 0,
        'strategy_mutation': False,
        'metric_mutation': False,
        'periods': {},
    }
    total = 0
    for per in PERIODS:
        result_path = OUT / per / 'RESULT.json.gz'
        receipt_path = OUT / per / 'RECEIPT.json'
        old_result_sha = sha(result_path)
        result = read_gz(result_path)
        changed = 0
        for name in ('trades', 'open_observations'):
            rows = []
            for row in result[name]:
                if row.get('sleeve_role') == ROLE:
                    before = deepcopy(row)
                    fixed = reseal_natural_row(row)
                    before.pop('trade_sha256', None)
                    before.pop('observation_sha256', None)
                    after = deepcopy(fixed)
                    after.pop('trade_sha256', None)
                    after.pop('observation_sha256', None)
                    need(before == after, 'NON_SEAL_ROW_MUTATION')
                    verify_row(fixed)
                    rows.append(fixed)
                    changed += 1
                else:
                    rows.append(row)
            result[name] = rows
        need(changed > 0, 'NO_NATURAL_ROWS:' + per)
        put_gz(result_path, result)
        new_result_sha = sha(result_path)

        receipt = read(receipt_path)
        need(receipt['state'] == 'COMPLETED', 'RECEIPT_NOT_COMPLETED:' + per)
        need(receipt['result_sha256'] == old_result_sha, 'PRE_REPAIR_RECEIPT_RESULT_SHA_DRIFT:' + per)
        receipt['result_sha256'] = new_result_sha
        receipt['post_result_row_seal_repair'] = 'PR1295_r3996063642'
        put(receipt_path, receipt)

        report['periods'][per] = {
            'natural_rows_resealed': changed,
            'old_result_sha256': old_result_sha,
            'new_result_sha256': new_result_sha,
            'new_receipt_sha256': sha(receipt_path),
        }
        total += changed

    need(total == 167, f'EXPECTED_167_NATURAL_ROWS_GOT_{total}')
    report['total_rows'] = total
    report['state'] = 'PASS_RESEALED_NATURAL_DONOR_ROWS'
    put(repair_path, report)
    verify_persisted(total)
    commit = persist('Repair U4 natural donor row seals')
    print(json.dumps({'state': report['state'], 'rows': total, 'commit': commit}, sort_keys=True))


if __name__ == '__main__':
    main()
