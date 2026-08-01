from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

CADDY = Path('/etc/caddy/Caddyfile')


def run(args: list[str], timeout: int = 30) -> dict:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    return {'returncode': p.returncode, 'stdout': p.stdout[-30000:], 'stderr': p.stderr[-10000:]}


def main() -> int:
    text = CADDY.read_text(errors='ignore') if CADDY.exists() else ''
    generic = text.find('\n    handle {', text.find('alimi.z-os.vip'))
    tv = text.find('handle /api/tv/observe', text.find('alimi.z-os.vip'))
    result = {
        'schema_version': 'zel.alimi.caddy.reload.diagnose.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'state': 'PASS_READ_ONLY_CADDY_DIAGNOSIS',
        'caddyfile_exists': CADDY.exists(),
        'caddyfile_sha256': hashlib.sha256(CADDY.read_bytes()).hexdigest() if CADDY.exists() else None,
        'tv_index': tv,
        'generic_index': generic,
        'tv_route_shadowed': generic >= 0 and tv > generic,
        'validate': run(['caddy', 'validate', '--config', str(CADDY)]),
        'adapt': run(['caddy', 'adapt', '--pretty', '--config', str(CADDY)]),
        'is_active': run(['systemctl', 'is-active', 'caddy']),
        'show': run(['systemctl', 'show', 'caddy', '--property=Id,ActiveState,SubState,MainPID,NRestarts,ExecReload,ExecStart,FragmentPath,Result,ReloadResult']),
        'status': run(['systemctl', 'status', 'caddy', '--no-pager', '-l']),
        'journal': run(['journalctl', '-u', 'caddy', '--since', '-15 min', '--no-pager', '-n', '250']),
        'admin_config': run(['curl', '--silent', '--show-error', '--max-time', '10', 'http://127.0.0.1:2019/config/']),
        'public_tv': run(['curl', '-L', '--silent', '--show-error', '--max-time', '20', '--write-out', '\n__HTTP__%{http_code}|%{content_type}', 'https://alimi.z-os.vip/api/tv/observe']),
        'local_tv': run(['curl', '--silent', '--show-error', '--max-time', '20', '--write-out', '\n__HTTP__%{http_code}|%{content_type}', 'http://127.0.0.1:8799/']),
        'safety': {
            'read_only': True,
            'caddy_mutated': False,
            'service_mutated': False,
            'frontend_mutated': False,
            'runtime_mutated': False,
            'execution_authority': 'NONE',
            'order_authority': 'BLOCKED',
            'action': 'hold'
        }
    }
    Path('/tmp/zel_alimi_caddy_reload_diagnose_v1.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': result['state'], 'tv_route_shadowed': result['tv_route_shadowed'], 'is_active': result['is_active']['stdout'].strip()}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
