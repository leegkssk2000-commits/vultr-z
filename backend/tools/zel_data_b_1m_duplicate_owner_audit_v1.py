from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PATTERN = 'zel_historical_oos_exact25_replay_v1.py'
OUTDIR = Path('/tmp/zel_historical_oos_exact25_replay_v1_1m')


def run(cmd: list[str], timeout: int = 30) -> dict[str, Any]:
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    return {'returncode': p.returncode, 'stdout': p.stdout[-50000:], 'stderr': p.stderr[-10000:]}


def proc_rows() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    now = time.time()
    for entry in Path('/proc').glob('[0-9]*'):
        try:
            pid = int(entry.name)
            raw = (entry / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='ignore').strip()
            if PATTERN not in raw or '--interval 1m' not in raw:
                continue
            stat = (entry / 'stat').read_text().split()
            ppid = int(stat[3])
            status = (entry / 'status').read_text(errors='ignore')
            uid = re.search(r'^Uid:\s+(\d+)', status, re.M)
            start = run(['ps', '-o', 'lstart=', '-p', str(pid)])['stdout'].strip()
            etimes = run(['ps', '-o', 'etimes=', '-p', str(pid)])['stdout'].strip()
            cwd = os.readlink(entry / 'cwd') if (entry / 'cwd').exists() else None
            result.append({
                'pid': pid, 'ppid': ppid, 'cmdline': raw, 'cwd': cwd,
                'uid': int(uid.group(1)) if uid else None,
                'lstart': start, 'elapsed_sec': int(etimes) if etimes.isdigit() else None,
                'open_output_files': run(['bash', '-lc', f"ls -l /proc/{pid}/fd 2>/dev/null | grep '{OUTDIR}' || true"])['stdout'].splitlines(),
            })
        except (OSError, ValueError, IndexError):
            continue
    return sorted(result, key=lambda x: x['pid'])


def ancestry(pid: int) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    current = pid
    for _ in range(12):
        if current <= 1 or current in seen:
            break
        seen.add(current)
        base = Path('/proc') / str(current)
        try:
            cmd = (base / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='ignore').strip()
            stat = (base / 'stat').read_text().split()
            ppid = int(stat[3])
            rows.append({'pid': current, 'ppid': ppid, 'cmdline': cmd[:2000]})
            current = ppid
        except Exception:
            break
    return rows


def output_inventory() -> dict[str, Any]:
    rows = []
    if OUTDIR.exists():
        for path in sorted(OUTDIR.rglob('*')):
            if path.is_file():
                try:
                    st = path.stat()
                    rows.append({'path': str(path.relative_to(OUTDIR)), 'bytes': st.st_size, 'mtime': datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(), 'age_sec': round(time.time() - st.st_mtime, 3)})
                except OSError:
                    pass
    return {'exists': OUTDIR.exists(), 'files': rows[:500], 'file_count': len(rows), 'terminal_files': {name: (OUTDIR / name).exists() for name in ('report.json','summary.json','scoreboard.csv','trades.jsonl.gz')}}


def main() -> int:
    rows = proc_rows()
    parents = sorted({row['ppid'] for row in rows})
    root_groups: dict[str, list[int]] = {}
    ancestries = {}
    for row in rows:
        chain = ancestry(row['pid'])
        ancestries[str(row['pid'])] = chain
        root = next((x['pid'] for x in reversed(chain) if 'sshd:' in x['cmdline'] or 'bash -c' in x['cmdline'] or 'bash -se' in x['cmdline']), row['ppid'])
        root_groups.setdefault(str(root), []).append(row['pid'])
    distinct_commands = sorted({row['cmdline'] for row in rows})
    duplicate_owner = len(root_groups) > 1
    result = {
        'schema_version': 'zel.data_b.1m.duplicate_owner.audit.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'state': 'HOLD_DUPLICATE_DATA_B_1M_OWNERS' if duplicate_owner else ('PASS_SINGLE_DATA_B_1M_OWNER' if rows else 'HOLD_NO_DATA_B_1M_PROCESS'),
        'process_count': len(rows),
        'parent_pids': parents,
        'root_groups': root_groups,
        'distinct_command_count': len(distinct_commands),
        'processes': rows,
        'ancestries': ancestries,
        'output': output_inventory(),
        'integrity': {
            'duplicate_owner_detected': duplicate_owner,
            'same_output_dir': str(OUTDIR),
            'economic_result_trust_allowed': False if duplicate_owner else None,
            'terminal_publication_allowed': False if duplicate_owner else None,
        },
        'safety': {
            'read_only': True, 'process_killed': False, 'output_deleted': False,
            'runtime_mutated': False, 'canonical_mutated': False,
            'execution_authority': 'NONE', 'order_authority': 'BLOCKED', 'action': 'hold'
        }
    }
    Path('/tmp/zel_data_b_1m_duplicate_owner_audit_v1.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': result['state'], 'process_count': len(rows), 'root_groups': root_groups, 'terminal_files': result['output']['terminal_files']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
