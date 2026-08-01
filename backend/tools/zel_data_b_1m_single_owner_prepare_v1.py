from __future__ import annotations

import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

PATTERN = 'zel_historical_oos_exact25_replay_v1.py'
INTERVAL = '--interval 1m'
OUTPUT_ARG = '--output-dir /tmp/zel_historical_oos_exact25_replay_v1_1m'
CANONICAL = Path('/tmp/zel_historical_oos_exact25_replay_v1_1m')


def targets() -> dict[int, int]:
    out: dict[int, int] = {}
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            pid = int(proc.name)
            cmd = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='ignore')
            if PATTERN not in cmd or INTERVAL not in cmd or OUTPUT_ARG not in cmd:
                continue
            ppid = int((proc / 'stat').read_text().split()[3])
            out[pid] = ppid
        except Exception:
            continue
    return out


def main() -> int:
    before = targets()
    for pid in sorted(before, reverse=True):
        try: os.kill(pid, signal.SIGTERM)
        except ProcessLookupError: pass
    deadline = time.time() + 20
    while time.time() < deadline and targets():
        time.sleep(0.5)
    remaining = targets()
    for pid in sorted(remaining, reverse=True):
        try: os.kill(pid, signal.SIGKILL)
        except ProcessLookupError: pass
    time.sleep(1)
    after = targets()
    if after:
        raise SystemExit('EXACT_REPLAY_PROCESSES_REMAIN:' + repr(after))

    quarantine = None
    if CANONICAL.exists():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        quarantine = CANONICAL.with_name(CANONICAL.name + '.contaminated.' + stamp)
        CANONICAL.rename(quarantine)
    CANONICAL.mkdir(parents=True, exist_ok=False)

    receipt = {
        'schema_version': 'zel.data_b.1m.single_owner.prepare.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'state': 'PASS_DUPLICATE_OWNERS_REMOVED_AND_OUTPUT_QUARANTINED',
        'matched_processes_before': before,
        'matched_count_before': len(before),
        'matched_processes_after': after,
        'quarantine_path': str(quarantine) if quarantine else None,
        'fresh_output_dir': str(CANONICAL),
        'canonical_strategy_mutated': False,
        'formal_ledger_mutated': False,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'action': 'hold'
    }
    Path('/tmp/zel_data_b_1m_single_owner_prepare_v1.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': receipt['state'], 'matched_count_before': len(before), 'quarantine_path': receipt['quarantine_path']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
