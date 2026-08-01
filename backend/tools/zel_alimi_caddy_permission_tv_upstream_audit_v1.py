from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CADDY = Path('/etc/caddy/Caddyfile')
CANDIDATE_PATHS = ('/', '/health', '/observe', '/tv/observe', '/api/observe', '/api/tv/observe', '/latest')


def run(args: list[str], timeout: int = 25) -> dict[str, Any]:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    return {'returncode': p.returncode, 'stdout': p.stdout[-30000:], 'stderr': p.stderr[-8000:]}


def curl(path: str) -> dict[str, Any]:
    p = run(['curl', '--silent', '--show-error', '--max-time', '10', '--write-out', '\n__META__%{http_code}|%{content_type}', 'http://127.0.0.1:8799' + path], 15)
    marker = '\n__META__'
    body, meta = p['stdout'].rsplit(marker, 1) if marker in p['stdout'] else (p['stdout'], '')
    parsed = False
    keys: list[str] = []
    try:
        value = json.loads(body)
        parsed = True
        if isinstance(value, dict): keys = sorted(value.keys())[:100]
    except Exception:
        pass
    return {'path': path, 'returncode': p['returncode'], 'meta': meta, 'bytes': len(body.encode()), 'json': parsed, 'keys': keys, 'prefix': body[:500]}


def find_pid() -> int | None:
    p = run(['bash', '-lc', "ss -ltnp 2>/dev/null | awk '/127.0.0.1:8799/ {print}'"])
    match = re.search(r'pid=(\d+)', p['stdout'])
    return int(match.group(1)) if match else None


def source_routes(path: Path | None) -> dict[str, Any]:
    if not path or not path.is_file() or path.suffix != '.py':
        return {'source': str(path) if path else None, 'routes': [], 'parse_error': None}
    text = path.read_text(errors='ignore')
    routes: list[dict[str, Any]] = []
    error = None
    try:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call): continue
            f = node.func
            name = None
            if isinstance(f, ast.Attribute): name = f.attr
            elif isinstance(f, ast.Name): name = f.id
            if name not in {'route', 'get', 'post', 'api_route', 'add_url_rule'}: continue
            value = None
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                value = node.args[0].value
            if value:
                routes.append({'decorator': name, 'path': value, 'line': node.lineno})
    except Exception as exc:
        error = str(exc)
    return {'source': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'routes': routes, 'parse_error': error}


def main() -> int:
    pid = find_pid()
    proc: dict[str, Any] = {'pid': pid}
    source: Path | None = None
    if pid:
        base = Path('/proc') / str(pid)
        proc['status'] = run(['bash', '-lc', f"sed -n '1,80p' /proc/{pid}/status"])
        proc['cmdline'] = (base / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='ignore') if (base / 'cmdline').exists() else ''
        proc['cwd'] = os.readlink(base / 'cwd') if (base / 'cwd').exists() else None
        proc['exe'] = os.readlink(base / 'exe') if (base / 'exe').exists() else None
        for token in proc['cmdline'].split():
            candidate = Path(token)
            if candidate.suffix == '.py' and candidate.is_file():
                source = candidate
                break
        proc['unit'] = run(['bash', '-lc', f"systemctl status $(systemctl | awk '$0 ~ /{pid}/ {{print $1; exit}}') --no-pager -l 2>/dev/null || true"])

    perms = {
        'stat': run(['stat', '-c', '%n|%U|%G|%a|%A|%s|%y', '/etc/caddy', '/etc/caddy/Caddyfile']),
        'namei': run(['namei', '-l', '/etc/caddy/Caddyfile']),
        'acl': run(['bash', '-lc', "command -v getfacl >/dev/null && getfacl -p /etc/caddy /etc/caddy/Caddyfile || true"]),
        'caddy_user': run(['id', 'caddy']),
        'service': run(['systemctl', 'show', 'caddy', '--property=User,Group,SupplementaryGroups,ExecStart,ExecReload,ActiveState,SubState,MainPID,FragmentPath']),
        'read_as_caddy': run(['bash', '-lc', "runuser -u caddy -- test -r /etc/caddy/Caddyfile; echo $?" ]),
        'validate_as_root': run(['caddy', 'validate', '--config', '/etc/caddy/Caddyfile']),
        'validate_as_caddy': run(['bash', '-lc', "runuser -u caddy -- caddy validate --config /etc/caddy/Caddyfile 2>&1; echo __RC__$?" ]),
    }
    endpoints = [curl(path) for path in CANDIDATE_PATHS]
    result = {
        'schema_version': 'zel.alimi.caddy_permission_tv_upstream.audit.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'state': 'PASS_READ_ONLY_PERMISSION_AND_UPSTREAM_AUDIT',
        'caddyfile_sha256': hashlib.sha256(CADDY.read_bytes()).hexdigest() if CADDY.exists() else None,
        'permissions': perms,
        'upstream_process': proc,
        'upstream_source': source_routes(source),
        'endpoint_probes': endpoints,
        'findings': {
            'caddy_user_can_read': perms['read_as_caddy']['stdout'].strip().endswith('0'),
            'working_upstream_paths': [x['path'] for x in endpoints if x['meta'].startswith('200|')],
            'pid_found': pid is not None,
            'source_found': source is not None,
        },
        'safety': {
            'read_only': True, 'caddy_mutated': False, 'service_mutated': False,
            'frontend_mutated': False, 'runtime_mutated': False,
            'execution_authority': 'NONE', 'order_authority': 'BLOCKED', 'action': 'hold'
        }
    }
    Path('/tmp/zel_alimi_caddy_permission_tv_upstream_audit_v1.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result['findings'], sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
