from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    root = Path('/tmp/zel_historical_oos_exact25_replay_v1_1m')
    proc = subprocess.run(
        ['pgrep', '-af', 'zel_historical_oos_exact25_replay_v1.py'],
        capture_output=True,
        text=True,
        check=False,
    )
    processes = [line for line in proc.stdout.splitlines() if '--interval 1m' in line]
    filenames = ('report.json', 'summary.json', 'scoreboard.csv', 'trades.jsonl.gz')
    files = {
        name: {
            'exists': (root / name).is_file(),
            'bytes': (root / name).stat().st_size if (root / name).is_file() else 0,
        }
        for name in filenames
    }

    report_state = None
    completed = None
    failures = None
    closed = None
    generated = None
    if files['report.json']['exists']:
        try:
            report = json.loads((root / 'report.json').read_text())
            replay = report.get('replay') or {}
            report_state = report.get('state')
            completed = replay.get('strategy_count_completed')
            failures = replay.get('strategy_failure_count')
            closed = replay.get('closed_trade_count')
            generated = report.get('generated_at')
        except Exception as exc:
            report_state = f'UNREADABLE:{type(exc).__name__}'

    payload = {
        'schema_version': 'zel.data_b.1m.status_probe.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'process_running': bool(processes),
        'process_count': len(processes),
        'local_output_dir_exists': root.is_dir(),
        'local_files': files,
        'local_report_state': report_state,
        'strategy_count_completed': completed,
        'strategy_failure_count': failures,
        'closed_trade_count': closed,
        'local_report_generated_at': generated,
        'read_only': True,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'action': 'hold',
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
