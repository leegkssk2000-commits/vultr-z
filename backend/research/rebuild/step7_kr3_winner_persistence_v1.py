"""Operational caller around the immutable historical economic executor.

No new allocation, retry, rule change, or market calculation in settlement.
The original frozen command/results remain historical evidence.
"""
import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path

from . import step7_kr3_winner_repair_v1 as frozen


def settle(root=None):
    root = Path(root) if root is not None else frozen.ROOT
    path = root / frozen.BUDGET
    output = root / frozen.OUTPUT
    with path.with_suffix('.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        budget = json.loads(path.read_bytes())
        allocation = budget['kr3_winner_repair_allocation']
        if allocation['scope_key'] != frozen.SCOPE or allocation['runs'] != list(frozen.RUNS):
            raise ValueError('WRONG_PERSISTENCE_SCOPE')
        spec_sha = allocation['specification_sha256']
        selected = [t for t in budget['trials'] if t.get('scope') == frozen.SCOPE]
        if len(selected) != allocation['used']:
            raise ValueError('RESERVATION_COUNT_MISMATCH')
        for trial in selected:
            name = trial['run']
            if name not in frozen.RUNS:
                raise ValueError('UNKNOWN_RESERVED_RUN')
            folder = output / name
            receipt_path, failure_path = folder/'RECEIPT.json', folder/'FAILURE.json'
            if receipt_path.exists() and failure_path.exists():
                raise ValueError('CONFLICTING_TERMINAL_RECEIPTS')
            terminal = receipt_path if receipt_path.exists() else failure_path if failure_path.exists() else None
            if terminal is None:
                if trial['status'] in ('COMPLETED', 'FAILED_CONSUMED'):
                    raise ValueError('TERMINAL_EVIDENCE_MISSING')
                continue
            receipt = json.loads(terminal.read_bytes())
            for key in ('run', 'scope', 'actual_experiment_ordinal', 'candidate_ordinal', 'specification_sha256'):
                if receipt.get(key) != trial.get(key):
                    raise ValueError('TERMINAL_IDENTITY_MISMATCH:'+key)
            if receipt['specification_sha256'] != spec_sha or receipt.get('retry_allowed') is not False:
                raise ValueError('UNBOUND_TERMINAL_RECEIPT')
            expected = 'COMPLETED' if terminal == receipt_path else 'FAILED_CONSUMED'
            if receipt['status'] != expected:
                raise ValueError('INVALID_TERMINAL_STATUS')
            if expected == 'COMPLETED':
                if hashlib.sha256((folder/'RESULT.json.gz').read_bytes()).hexdigest() != receipt['artifact_sha256']:
                    raise ValueError('RESULT_HASH_MISMATCH')
                if not isinstance(receipt.get('finished_unix_ns'), int):
                    raise ValueError('TERMINAL_TIME_MISSING')
            if trial['status'] not in ('RESERVED_BEFORE_REPLAY', expected):
                raise ValueError('TERMINAL_STATUS_CONFLICT')
            trial['reservation_status'] = 'RESERVED_BEFORE_REPLAY'
            trial['status'] = expected
            for key in ('finished_unix_ns', 'artifact_sha256', 'error', 'error_type'):
                if key in receipt:
                    trial[key] = receipt[key]
        allocation['completed'] = sum(t['status'] == 'COMPLETED' for t in selected)
        allocation['failed'] = sum(t['status'] == 'FAILED_CONSUMED' for t in selected)
        allocation['running'] = allocation['used']-allocation['completed']-allocation['failed']
        allocation['remaining'] = allocation['max_executions']-allocation['used']
        payload = (json.dumps(budget, sort_keys=True, indent=2)+'\n').encode()
        if payload != path.read_bytes():
            temp = path.with_suffix('.settlement.pending')
            with temp.open('xb') as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
        return dict(allocation)


def execute(packets, spec, outdir):
    """One-shot historical executor; finally settle even a partial failed batch.

    Original scope/attempt O_EXCL claims and budget ceilings are still the
    authoritative dispatch gates. Settlement alone can never start a replay.
    """
    try:
        return frozen.execute(packets, spec, outdir)
    finally:
        settle()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--execute', action='store_true')
    action.add_argument('--settle', action='store_true')
    args = parser.parse_args()
    if args.settle:
        print(json.dumps(settle(), sort_keys=True)); return
    if args.input is None:
        parser.error('--input is required with --execute')
    packets = json.loads(gzip.decompress(args.input.read_bytes()))
    spec = json.loads((frozen.ROOT/frozen.OUTPUT/'SPEC.json').read_bytes())
    execute(packets, spec, frozen.ROOT/frozen.OUTPUT)


if __name__ == '__main__':
    main()
