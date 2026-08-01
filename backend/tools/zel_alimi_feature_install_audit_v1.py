from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOTS = (
    Path('/var/www/z-os-alimi'),
    Path('/usr/local/bin'),
    Path('/home/z/z/backend'),
    Path('/home/z/z/tools'),
    Path('/home/z/z/runtime'),
    Path('/opt/zico-ceo-canonical-adapter'),
)
EXCLUDE = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.cache', '.deploy_backups', 'backup', 'backups', 'archive', 'archives', 'quarantine'}
TEXT_SUFFIXES = {'.html', '.htm', '.js', '.mjs', '.jsx', '.ts', '.tsx', '.css', '.py', '.json', '.jsonl', '.service', '.conf'}
COMPONENTS = {
    'account_balance': ('history.live_balance', 'live_balance', 'bingx', 'balance', 'usdt'),
    'health_freshness': ('data health', 'health', 'stale', 'age', 'generated_at', 'updated_at'),
    'strategy_queue': ('strategy queue', 'promotion', 'alpha scanner', 'replay gate', 'queue'),
    'lico': ('lico',),
    'zico': ('zico', 'oms'),
    'zlice': ('zlice', 'lineage'),
    'team_bots': ('team bots', 'teambot', 'lbot', 'mbot', 'obot', 'sbot'),
    'paper_position': ('paper position', 'position monitor', 'position_size_pct', 'entry_price', 'closed'),
    'performance': ('performance edge', 'profit factor', 'max dd', 'win rate', 'pnl'),
    'alerts': ('alert state', 'violation', 'critical', 'severity'),
    'paper_control': ('zel control', 'next position', 'hold next', 'stop next', 'lev 10x', 'size 5%'),
}
UI_LABELS = {
    'live_balance_label': ('LIVE', 'BINGX', 'USDT'),
    'health_ok': ('HEALTH', 'OK'),
    'unbound': ('unbound',),
    'paper_closed': ('PAPER POSITION', 'CLOSED'),
    'performance': ('PERFORMANCE EDGE',),
    'queue': ('STRATEGY QUEUE',),
}
SENSITIVE = re.compile(r'(token|secret|password|api[_-]?key|authorization|signature)', re.I)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_text(text: str, limit: int = 1600) -> str:
    lines = []
    for line in text.splitlines():
        if SENSITIVE.search(line) and any(ch in line for ch in ('=', ':')):
            continue
        lines.append(line[:500])
        if sum(len(x) for x in lines) >= limit:
            break
    return '\n'.join(lines)[:limit]


def run(args: list[str], timeout: int = 25) -> dict[str, Any]:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    return {'returncode': p.returncode, 'stdout': p.stdout[-30000:], 'stderr': p.stderr[-8000:]}


def walk_files() -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for root in ROOTS:
        if not root.exists():
            continue
        for current, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in EXCLUDE and not any(x in d.lower() for x in ('backup', 'archive', 'quarantine'))]
            for name in names:
                path = Path(current) / name
                try:
                    resolved = str(path.resolve())
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 5_000_000:
                        continue
                    files.append(path)
                except OSError:
                    continue
    return files


def active_html(files: list[Path]) -> list[dict[str, Any]]:
    rows = []
    now = time.time()
    for path in files:
        if path.suffix.lower() not in {'.html', '.htm'}:
            continue
        try:
            text = path.read_text(errors='ignore')
            if 'ZEL ALIMI' not in text.upper():
                continue
            st = path.stat()
            score = 0
            for token in ('FINAL OPS', 'RUNTIME STATUS', 'STRATEGY QUEUE', 'ZEL CONTROL', 'PERFORMANCE EDGE'):
                if token in text.upper():
                    score += 1
            rows.append({'path': str(path), 'sha256': sha(path), 'bytes': st.st_size, 'age_sec': round(now - st.st_mtime, 3), 'score': score})
        except OSError:
            continue
    return sorted(rows, key=lambda x: (-x['score'], x['age_sec']))


def file_index(files: list[Path]) -> list[dict[str, Any]]:
    rows = []
    now = time.time()
    for path in files:
        try:
            text = path.read_text(errors='ignore')
            low = text.lower()
            hits = {name: [token for token in tokens if token in low] for name, tokens in COMPONENTS.items()}
            hits = {k: v for k, v in hits.items() if v}
            if not hits:
                continue
            st = path.stat()
            rows.append({
                'path': str(path),
                'sha256': sha(path),
                'bytes': st.st_size,
                'age_sec': round(now - st.st_mtime, 3),
                'hits': hits,
            })
        except OSError:
            continue
    return rows


def fetch_calls(text: str) -> list[str]:
    patterns = [
        r'fetch\(\s*[`\'\"]([^`\'\"]+)',
        r'axios\.(?:get|post)\(\s*[`\'\"]([^`\'\"]+)',
        r'XMLHttpRequest[^\n]{0,500}[`\'\"](/[^`\'\"]+)',
    ]
    out: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = match.group(1)
            if value.startswith('/') or value.startswith('http'):
                out.append(value)
    return sorted(set(out))[:200]


def local_paths(text: str) -> list[str]:
    out = set()
    for match in re.finditer(r'[`\'\"](/(?:home|var|opt|usr|tmp)/[^`\'\"\s]+)', text):
        value = match.group(1).rstrip('),;')
        if not SENSITIVE.search(value):
            out.add(value)
    return sorted(out)[:300]


def snippets(text: str, tokens: tuple[str, ...]) -> list[str]:
    rows = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if any(token.lower() in line.lower() for token in tokens):
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            value = safe_text('\n'.join(lines[start:end]), 1000)
            if value and value not in rows:
                rows.append(value)
        if len(rows) >= 10:
            break
    return rows


def probe_url(url: str) -> dict[str, Any]:
    p = run(['curl', '-L', '--silent', '--show-error', '--max-time', '15', '--write-out', '\n__META__%{http_code}|%{content_type}|%{time_total}', url], 20)
    marker = '\n__META__'
    body, meta = p['stdout'].rsplit(marker, 1) if marker in p['stdout'] else (p['stdout'], '')
    parsed = False
    keys: list[str] = []
    try:
        value = json.loads(body)
        parsed = True
        if isinstance(value, dict):
            keys = sorted(value.keys())[:100]
    except Exception:
        pass
    return {'url': url, 'returncode': p['returncode'], 'meta': meta, 'bytes': len(body.encode()), 'json_parseable': parsed, 'keys': keys, 'prefix': safe_text(body, 500)}


def classify_component(name: str, active_text: str, indexed: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = COMPONENTS[name]
    ui_present = any(token in active_text.lower() for token in tokens)
    candidates = [row for row in indexed if name in row['hits'] and row['path'] not in {'/var/www/z-os-alimi/index.html'}]
    source_candidates = [row for row in candidates if not row['path'].startswith('/var/www/z-os-alimi/') or Path(row['path']).suffix.lower() in {'.json', '.jsonl', '.py'}]
    fresh = [row for row in source_candidates if row['age_sec'] <= 3600]
    if ui_present and fresh:
        state = 'INSTALLED_AND_SOURCE_PRESENT'
    elif ui_present and source_candidates:
        state = 'INSTALLED_SOURCE_STALE_OR_UNBOUND'
    elif ui_present:
        state = 'UI_ONLY_IMPLEMENTATION_UNPROVED'
    elif source_candidates:
        state = 'SOURCE_PRESENT_UI_MISSING'
    else:
        state = 'MISSING'
    return {
        'state': state,
        'ui_present': ui_present,
        'source_candidate_count': len(source_candidates),
        'fresh_source_count_1h': len(fresh),
        'top_sources': source_candidates[:20],
        'snippets': snippets(active_text, tokens),
    }


def main() -> int:
    files = walk_files()
    htmls = active_html(files)
    if not htmls:
        raise SystemExit('ACTIVE_ALIMI_HTML_NOT_FOUND')
    active = Path(htmls[0]['path'])
    text = active.read_text(errors='ignore')
    indexed = file_index(files)
    calls = fetch_calls(text)
    paths = local_paths(text)
    probes = [probe_url('https://alimi.z-os.vip/')]
    for call in calls:
        if call.startswith('/'):
            probes.append(probe_url('https://alimi.z-os.vip' + call))
        elif call.startswith('https://alimi.z-os.vip'):
            probes.append(probe_url(call))
        if len(probes) >= 25:
            break

    components = {name: classify_component(name, text, indexed) for name in COMPONENTS}
    labels = {name: all(token.lower() in text.lower() for token in tokens) for name, tokens in UI_LABELS.items()}
    services = run(['bash', '-lc', "systemctl list-units --all --type=service --no-legend | grep -Ei 'alimi|lico|zico|zlice|team|paper|position|bingx|q4r3|zel' | head -n 250 || true"])
    timers = run(['bash', '-lc', "systemctl list-timers --all --no-legend | grep -Ei 'alimi|lico|zico|zlice|team|paper|position|bingx|q4r3|zel' | head -n 250 || true"])

    result = {
        'schema_version': 'zel.alimi.feature_install.audit.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'state': 'PASS_READ_ONLY_ALIMI_FEATURE_INSTALL_AUDIT',
        'active_html': htmls[0],
        'other_alimi_html': htmls[1:20],
        'fetch_calls': calls,
        'local_paths': paths,
        'labels': labels,
        'components': components,
        'endpoint_probes': probes,
        'services': services,
        'timers': timers,
        'policy': {
            'account_balance_semantics': 'REAL_BINGX_LIVE_ACCOUNT_BALANCE_READ_ONLY',
            'account_balance_hide_or_zero': False,
            'live_order_authority': 'BLOCKED',
            'execution_authority': 'NONE',
            'view_mutation_allowed': False,
            'alimi_patch_allowed_after_single_cause': True,
        },
        'safety': {
            'read_only': True,
            'frontend_mutated': False,
            'view_mutated': False,
            'runtime_mutated': False,
            'service_mutated': False,
            'execution_authority': 'NONE',
            'order_authority': 'BLOCKED',
            'action': 'hold',
        },
    }
    Path('/tmp/zel_alimi_feature_install_audit_v1.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': result['state'], 'active_html': result['active_html'], 'components': {k: v['state'] for k, v in components.items()}}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
