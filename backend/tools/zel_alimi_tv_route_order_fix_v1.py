from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CADDY = Path('/etc/caddy/Caddyfile')
TV_BLOCK = '''    # W221D_TV_OBSERVER_PROXY
    handle /api/tv/observe {
        reverse_proxy 127.0.0.1:8799
    }

'''
GENERIC = '''    handle {
        root * /var/www/z-os-alimi
        try_files {path} {path}/ /index.html
        file_server
    }
'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def curl_status() -> dict:
    p = run(['curl', '-L', '--silent', '--show-error', '--max-time', '20', '--write-out', '\n__META__%{http_code}|%{content_type}', 'https://alimi.z-os.vip/api/tv/observe'])
    marker = '\n__META__'
    body, meta = (p.stdout.rsplit(marker, 1) if marker in p.stdout else (p.stdout, ''))
    parsed = False
    try:
        json.loads(body)
        parsed = True
    except Exception:
        pass
    return {'returncode': p.returncode, 'meta': meta, 'bytes': len(body.encode()), 'json_parseable': parsed, 'body_prefix': body[:300]}


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit('ROOT_REQUIRED')
    before_process = run(['bash', '-lc', "pgrep -af 'zel_historical_oos_exact25_replay_v1|historical-oos-v1' | sort || true"]).stdout
    before = CADDY.read_text()
    before_sha = sha(CADDY)
    if before.count(TV_BLOCK) != 1:
        raise SystemExit(f'TV_BLOCK_COUNT_{before.count(TV_BLOCK)}')
    if before.count(GENERIC) != 1:
        raise SystemExit(f'GENERIC_BLOCK_COUNT_{before.count(GENERIC)}')
    if before.find(TV_BLOCK) < before.find(GENERIC):
        state = 'PASS_ALREADY_ORDERED'
        changed = False
        backup = None
    else:
        backup = Path(f'/tmp/Caddyfile.zel_tv_route_fix.{int(time.time())}.bak')
        shutil.copy2(CADDY, backup)
        after = before.replace(TV_BLOCK, '', 1).replace(GENERIC, TV_BLOCK + GENERIC, 1)
        CADDY.write_text(after)
        changed = True
        validate = run(['caddy', 'validate', '--config', str(CADDY)])
        if validate.returncode != 0:
            shutil.copy2(backup, CADDY)
            raise SystemExit('CADDY_VALIDATE_FAILED:' + validate.stderr[-500:])
        reload_result = run(['systemctl', 'reload', 'caddy'])
        if reload_result.returncode != 0:
            shutil.copy2(backup, CADDY)
            run(['systemctl', 'reload', 'caddy'])
            raise SystemExit('CADDY_RELOAD_FAILED:' + reload_result.stderr[-500:])
        time.sleep(2)
        probe = curl_status()
        if not probe['meta'].startswith('200|') or not probe['json_parseable']:
            shutil.copy2(backup, CADDY)
            run(['caddy', 'validate', '--config', str(CADDY)])
            run(['systemctl', 'reload', 'caddy'])
            raise SystemExit('TV_ENDPOINT_FAILED_AFTER_PATCH:' + json.dumps(probe))
        state = 'PASS_TV_ROUTE_REORDERED'
    probe = curl_status()
    after_process = run(['bash', '-lc', "pgrep -af 'zel_historical_oos_exact25_replay_v1|historical-oos-v1' | sort || true"]).stdout
    if before_process != after_process:
        if changed and backup:
            shutil.copy2(backup, CADDY)
            run(['caddy', 'validate', '--config', str(CADDY)])
            run(['systemctl', 'reload', 'caddy'])
        raise SystemExit('DATA_B_PROCESS_TOPOLOGY_CHANGED')
    result = {
        'schema_version': 'zel.alimi.tv.route_order_fix.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'state': state,
        'changed': changed,
        'before_sha256': before_sha,
        'after_sha256': sha(CADDY),
        'tv_before_generic': CADDY.read_text().find(TV_BLOCK) < CADDY.read_text().find(GENERIC),
        'endpoint': probe,
        'data_b_process_topology_unchanged': True,
        'backup_path': str(backup) if backup else None,
        'runtime_mutated': False,
        'frontend_mutated': False,
        'service_reloaded': 'caddy' if changed else None,
        'shadow_start_allowed': False,
        'paper_start_allowed': False,
        'live_enabled': False,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'action': 'hold'
    }
    Path('/tmp/zel_alimi_tv_route_order_fix_v1.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': state, 'endpoint': probe, 'changed': changed}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
