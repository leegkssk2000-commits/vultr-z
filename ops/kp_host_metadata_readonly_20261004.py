"""Authorized read-only K.P metadata projection. Never imports a strategy."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

PARENT = '389550fddc888266eaf336cdec83a63b05f0e5da198fe21d07a2cf171e4f5710'
CANDIDATE = 'scalp7_keltner_hg_parent_utc30m_v2'
R = Path('/home/z/z/runtime/scalp7_broad_v2_20260915')
W = Path('/home/z/worktrees/scalp7-broad-v2-20260915')
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()
report = {'schema': 'kp.current_host_metadata_projection.v1', 'observed_at_utc': NOW,
          'candidate': CANDIDATE, 'parent_identity': PARENT,
          'source_price_or_performance_bodies_exported': False, 'service_changes': 0,
          'economic_runs': 0, 'origin': 'USER_AUTHORIZED_GITHUB_ACTIONS_EXISTING_VPS_SSH',
          'source_use_history_complete': False, 'unused_source_certified': False}


def run(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=25)
        return p.returncode, p.stdout
    except Exception as e:
        return -1, type(e).__name__


def info(p):
    try:
        s = p.lstat()
        return {'path': str(p), 'bytes': s.st_size, 'mtime_ns': s.st_mtime_ns,
                'is_symlink': p.is_symlink(), 'is_file': p.is_file()}
    except Exception as e:
        return {'path': str(p), 'error': type(e).__name__}


# Runtime state is parsed locally, but no prices, fill bodies, returns or PnL
# are transmitted. This projection does not claim a complete use-history census.
FIELDS = {'schema', 'schema_version', 'identity', 'identity_key', 'candidate', 'candidate_id',
          'parent_identity', 'parent_identity_key', 'status', 'state', 'phase', 'scope', 'owner',
          'timestamp_utc', 'recorded_at_utc', 'updated_at_utc', 'started_at_utc', 'source_id',
          'source_identity_sha256', 'config_sha256', 'freeze_sha256', 'last_processed_ts_ms',
          'source_cursor', 'last_source_ts_ms', 'source_ts_ms', 'received_at_ms', 'processed_at_ms',
          'usable_at_ms', 'start_ms', 'end_ms', 'end_exclusive_ms', 'start_utc', 'end_utc',
          't0_ms', 'root', 'source_root', 'row_count', 'rows', 'last_ts_ms', 'first_ts_ms',
          'volume_unit', 'volume_units', 'complete', 'complete_use_history', 'usage_inventory_complete',
          'inspection_complete', 'seen', 'body_sha256', 'sha256', 'prefix_sha256', 'content_sha256',
          'last_observed_at_ms', 'gaps', 'missing', 'stale', 'blocked', 'blockers', 'reason',
          'collected_at_ms', 'order_authority', 'live_authority', 'input_kind', 'mode'}


def projection(d, depth=0):
    if depth > 4:
        return {'omitted': 'DEPTH_BOUND'}
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            if k in FIELDS:
                if k == 'rows' and isinstance(v, (list, dict)):
                    out[k] = {'count_only': len(v)}
                else:
                    out[k] = projection(v, depth + 1)
            elif k in ('positions', 'closed_trades', 'trades', 'fills', 'events', 'ledger'):
                out[k + '_body'] = 'NOT_EXPORTED'
            elif k in ('models', 'identities', 'lanes', 'candidates') and isinstance(v, dict):
                out[k] = {x: projection(y, depth + 1) for x, y in v.items()
                          if x in (PARENT, CANDIDATE, 'K.P') or CANDIDATE in x}
        return out
    if isinstance(d, list):
        return [projection(x, depth + 1) for x in d[:100]] if all(isinstance(x, dict) for x in d) else {'item_count': len(d), 'values': 'NOT_EXPORTED'}
    if isinstance(d, str):
        if len(d) > 500 or re.search(r'(?:https?://|bearer\s|password|secret|api[_-]?key|access[_-]?token)', d, re.I):
            return '[REDACTED]'
    return d


report['inventory'] = []
for root in (R,):
    for base, dirs, files in os.walk(root, followlinks=False):
        rel = Path(base).relative_to(root)
        dirs[:] = sorted(x for x in dirs if not (Path(base) / x).is_symlink()) if len(rel.parts) < 2 else []
        for name in sorted(files):
            if len(report['inventory']) >= 500:
                report['inventory_truncated'] = True
                break
            report['inventory'].append(info(Path(base) / name))
report['metadata_documents'] = []
allowed_names = {'INDEX.json', 'MANIFEST.json', 'IDENTITY.json', 'SOURCE_IDENTITY.json', 'STATE.json',
                 'STATUS.json', 'COVERAGE.json', 'USAGE_HISTORY.json', 'USE_HISTORY.json', 'SOURCE_USAGE.json',
                 'SOURCE_RECEIPT.json', 'FREEZE.json', 'SOURCE_FREEZE.json', 'RECEIPT.json'}
for item in report['inventory']:
    p = Path(item['path'])
    if p.name not in allowed_names or item.get('is_symlink') or not item.get('is_file'):
        continue
    if item['bytes'] > 4000000:
        report['metadata_documents'].append({**item, 'body_status': 'SIZE_LIMIT_NOT_OPENED'})
        continue
    try:
        raw = p.read_bytes()
        d = json.loads(raw)
        report['metadata_documents'].append({**item, 'sha256': hashlib.sha256(raw).hexdigest(),
             'stat_stable_during_read': info(p).get('mtime_ns') == item['mtime_ns'],
             'top_level_keys': sorted(d) if isinstance(d, dict) else None,
             'metadata_projection': projection(d)})
    except Exception as e:
        report['metadata_documents'].append({**item, 'error': type(e).__name__})
p = W / 'backend/research/rebuild/scalp7_positive_lanes_v2.py'
report['parent_module'] = info(p)
if p.is_file() and not p.is_symlink():
    report['parent_module']['sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
    report['parent_module']['frozen_match'] = report['parent_module']['sha256'] == 'b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2'
p = R / 'campaign.sqlite3'
report['candidate_registry'] = {'source': info(p), 'economic_columns_exported': False}
if p.is_file() and not p.is_symlink():
    try:
        con = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        report['candidate_registry']['tables'] = sorted(tables)
        for table, cols in [('claims', ['identity_key', 'scope', 'candidate_id', 'state']), ('events', ['sequence', 'identity_key', 'event', 'created_at'])]:
            if table not in tables:
                continue
            existing = {r[1] for r in con.execute('PRAGMA table_info(' + table + ')')}
            safe = [x for x in cols if x in existing]
            if 'identity_key' in existing:
                report['candidate_registry'][table] = [dict(x) for x in con.execute('SELECT ' + ','.join(safe) + ' FROM ' + table + ' WHERE identity_key=?', (PARENT,))]
        con.rollback()
        con.close()
    except Exception as e:
        report['candidate_registry']['error'] = type(e).__name__
locks = Path('/proc/locks').read_text().splitlines()
report['locks'] = []
for item in report['inventory']:
    p = Path(item['path'])
    if p.name.endswith('.lock') and p.is_file() and not p.is_symlink():
        s = p.stat()
        key = f'{os.major(s.st_dev):02x}:{os.minor(s.st_dev):02x}:{s.st_ino}'
        report['locks'].append({**item, 'kernel_entries': [x for x in locks if key in x],
                                'candidate_exclusive_ownership_certified': False})
rc, text = run(['systemctl', 'show', 'desktop-commander-remote.service', '--no-pager', '-p', 'MainPID', '-p', 'ActiveState', '-p', 'SubState', '-p', 'NRestarts', '-p', 'ControlGroup'])
report['dc_service'] = {'returncode': rc, 'properties': dict(x.split('=', 1) for x in text.splitlines() if '=' in x)}
p = Path('/root/dc-node22/node_modules/@wonderwhy-er/desktop-commander/package.json')
if p.is_file():
    package = json.loads(p.read_text())
    report['installed_dc_version'] = package.get('version')
# Compare only the public registered-device identifier. No token or key values.
p = Path('/root/.desktop-commander-device/device.json')
report['device_registration'] = {'file_present': p.is_file(), 'credential_values_exported': False}
if p.is_file() and not p.is_symlink():
    try:
        d = json.loads(p.read_text())
        report['device_registration']['top_level_field_names'] = sorted(d)

        def identities(v, depth=0):
            out = []
            if isinstance(v, dict) and depth < 4:
                for k, x in v.items():
                    if re.search('token|secret|password|key', k, re.I):
                        continue
                    if re.search('device.?id|^id$', k, re.I) and isinstance(x, str):
                        out.append({'field': k, 'matches_registered_vultr': x == '18e0412c-ac50-4e46-99ed-5c78a36cbd94'})
                    elif isinstance(x, dict):
                        out.extend(identities(x, depth + 1))
            return out

        report['device_registration']['id_comparisons'] = identities(d)
    except Exception as e:
        report['device_registration']['error'] = type(e).__name__
rc, text = run(['journalctl', '-u', 'desktop-commander-remote.service', '--no-pager', '-n', '500', '-o', 'json'])
report['service_failure_details'] = []
for line in text.splitlines() if rc == 0 else []:
    try:
        d = json.loads(line)
        m = str(d.get('MESSAGE', ''))
        if re.search('error|exception|failed|exited|disconnect|device.?id|register|heartbeat|timeout', m, re.I):
            m = re.sub(r'https?://\S+', '[URL]', m)
            m = re.sub(r'(?i)(bearer\s+)[^\s]+', r'\1[REDACTED]', m)
            m = re.sub(r'(?i)((?:token|password|secret|api[_-]?key|authorization)[\"\s:=]+)[^,\s}]+', r'\1[REDACTED]', m)
            m = re.sub(r'[A-Za-z0-9+/=_\-.]{24,}', '[LONG_VALUE]', m)
            m = re.sub(r'\b[\w.+-]+@[\w.-]+\b', '[EMAIL]', m)
            report['service_failure_details'].append({'realtime_us': d.get('__REALTIME_TIMESTAMP'), 'message_redacted': m[:500]})
    except ValueError:
        pass
report['service_failure_details'] = report['service_failure_details'][-35:]
print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
