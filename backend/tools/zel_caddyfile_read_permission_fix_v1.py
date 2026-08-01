from __future__ import annotations

import grp
import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PATH = Path('/etc/caddy/Caddyfile')


def run(args: list[str], timeout: int = 30) -> dict:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    return {'returncode': p.returncode, 'stdout': p.stdout[-20000:], 'stderr': p.stderr[-8000:]}


def metadata() -> dict:
    st = PATH.stat()
    return {'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(st.st_mode), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit('ROOT_REQUIRED')
    before = metadata()
    backup = Path('/tmp/Caddyfile.permission_fix_v1.backup')
    shutil.copy2(PATH, backup)
    caddy_gid = grp.getgrnam('caddy').gr_gid
    changed = before['gid'] != caddy_gid or before['mode'] != 0o640
    if changed:
        os.chown(PATH, 0, caddy_gid)
        os.chmod(PATH, 0o640)
    after = metadata()
    validate_root = run(['caddy', 'validate', '--config', str(PATH)])
    validate_caddy = run(['runuser', '-u', 'caddy', '--', 'caddy', 'validate', '--config', str(PATH)])
    reload_result = run(['systemctl', 'reload', 'caddy'])
    active = run(['systemctl', 'is-active', 'caddy'])
    if validate_root['returncode'] or validate_caddy['returncode'] or reload_result['returncode'] or active['stdout'].strip() != 'active':
        shutil.copy2(backup, PATH)
        os.chown(PATH, before['uid'], before['gid'])
        os.chmod(PATH, before['mode'])
        raise SystemExit('CADDY_PERMISSION_FIX_FAILED_AND_ROLLED_BACK:' + json.dumps({'validate_root': validate_root, 'validate_caddy': validate_caddy, 'reload': reload_result, 'active': active}))
    result = {
        'schema_version': 'zel.caddyfile.read_permission.fix.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'state': 'PASS_CADDYFILE_ROOT_CADDY_0640_AND_RELOAD',
        'changed': changed,
        'before': before,
        'after': after,
        'target': {'uid': 0, 'gid': caddy_gid, 'mode': 0o640},
        'validate_root': validate_root,
        'validate_caddy': validate_caddy,
        'reload': reload_result,
        'active': active,
        'config_content_changed': before['size'] != after['size'] or before['mtime_ns'] != after['mtime_ns'],
        'frontend_mutated': False,
        'runtime_strategy_mutated': False,
        'shadow_start_allowed': False,
        'paper_start_allowed': False,
        'live_enabled': False,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'action': 'hold'
    }
    Path('/tmp/zel_caddyfile_read_permission_fix_v1.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': result['state'], 'before': before, 'after': after}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
