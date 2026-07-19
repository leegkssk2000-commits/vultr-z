from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TARGETS = (
    Path('/var/www/z-os-alimi/api/view_contract_latest.json'),
    Path('/var/www/z-os-alimi/api/q4r3_recent_ledger_trace_latest.json'),
    Path('/var/www/z-os-alimi/api/q4r3_shadow_closed_ledger_latest.json'),
)
PROTECTED = (
    Path('/home/z/z/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl'),
    Path('/home/z/z/runtime/exact25_edge_v1/shadow_aggregate_snapshot/latest.json'),
    Path('/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json'),
)
DEFAULT_PRIOR = Path('/home/z/z/runtime/exact25_edge_v1/r7a1a6c3b_false_positive_correction/status_latest.json')
OUT_REL = Path('runtime/exact25_edge_v1/r7a1a6c4_writer_origin_diagnosis/status_latest.json')
TEXT_EXT = {'.py', '.sh', '.service', '.timer', '.json', '.yaml', '.yml', '.toml', '.conf', '.md', '.txt'}
SKIP_PARTS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'site-packages', 'secrets', 'credentials', 'runtime', 'evidence', 'backups', '_backups', 'archive', '.archive'}
MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class Fingerprint:
    path: str
    resolved_path: str
    exists: bool
    dev: int | None
    inode: int | None
    mtime_ns: int | None
    size: int | None
    sha256: str | None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, '', str(exc))


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fp(path: Path) -> Fingerprint:
    try:
        resolved = str(path.resolve(strict=False))
    except OSError:
        resolved = str(path)
    try:
        st = path.stat()
        raw = path.read_bytes() if path.is_file() else b''
        return Fingerprint(str(path), resolved, True, int(st.st_dev), int(st.st_ino), int(st.st_mtime_ns), int(st.st_size), sha(raw))
    except OSError:
        return Fingerprint(str(path), resolved, False, None, None, None, None, None)


def snap(paths: Iterable[Path]) -> dict[str, Fingerprint]:
    return {str(p): fp(p) for p in paths}


def diff(before: dict[str, Fingerprint], after: dict[str, Fingerprint]) -> list[dict[str, Any]]:
    out = []
    for path in sorted(set(before) | set(after)):
        left, right = before.get(path), after.get(path)
        if left != right:
            out.append({'path': path, 'before': asdict(left) if left else None, 'after': asdict(right) if right else None})
    return out


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f'.{path.name}.', dir=str(path.parent))
    tmp = Path(raw)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write('\n')
            handle.flush(); os.fsync(handle.fileno())
        os.chmod(tmp, 0o600); os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def redact(text: str, limit: int = 2000) -> str:
    text = text.replace('\x00', ' ')
    text = re.sub(r'(?i)\b(authorization|password|passwd|secret|token|api[_-]?key)\b\s*[:=]\s*([^\s,;]+)', r'\1=<redacted>', text)
    text = re.sub(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer <redacted>', text)
    text = re.sub(r'\b\d{6,12}:[A-Za-z0-9_-]{20,}\b', '<telegram-token-redacted>', text)
    return text[:limit]


def normalized_json_hash(raw: bytes) -> str | None:
    try:
        obj = json.loads(raw.decode('utf-8'))
    except Exception:
        return None
    return sha(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())


def contract_valid(c: dict[str, Any]) -> bool:
    return c.get('official_stage') == 'R7.A1A6C4' and c.get('read_only') is True and c.get('service_mutation_allowed') is False and c.get('repair_allowed') is False and int(c.get('minimum_observe_seconds', 0)) >= 60


def prior_valid(p: dict[str, Any]) -> bool:
    blockers = set(p.get('blockers') or [])
    return p.get('official_stage') == 'R7.A1A6C3B' and p.get('state') == 'HOLD' and int(p.get('target_change_count', 0)) >= 2 and int(p.get('protected_change_count', -1)) == 0 and {'ACTUAL_TARGET_CHANGE_DURING_TRACE', 'EXACT_VERIFY_AFTER_TRACE_FAILED'} <= blockers


def terms() -> tuple[str, ...]:
    values = {str(p).lower() for p in TARGETS} | {p.name.lower() for p in TARGETS}
    values |= {'/var/www/z-os-alimi/api', 'view_contract_latest', 'recent_ledger_trace', 'shadow_closed_ledger', 'alimi.z-os.vip/api'}
    return tuple(sorted(values))


def _scan_ok(path: Path) -> bool:
    if any(part in SKIP_PARTS for part in path.parts):
        return False
    try:
        return path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES and (path.suffix.lower() in TEXT_EXT or path.name in {'Caddyfile', 'crontab'})
    except OSError:
        return False


def scan_refs(roots: Iterable[Path], needles: tuple[str, ...], limit: int = 1200) -> list[dict[str, Any]]:
    hits, seen = [], set()
    for root in roots:
        try:
            root = root.resolve(strict=False)
        except OSError:
            pass
        if str(root) in seen:
            continue
        seen.add(str(root))
        candidates = [root] if root.is_file() else root.rglob('*') if root.is_dir() else []
        try:
            for path in candidates:
                if not _scan_ok(path):
                    continue
                try:
                    text = path.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue
                low = text.lower()
                if not any(n in low for n in needles):
                    continue
                for no, line in enumerate(text.splitlines(), 1):
                    matched = [n for n in needles if n in line.lower()]
                    if matched:
                        hits.append({'path': str(path), 'line': no, 'matched_terms': matched[:8], 'text': redact(line, 1200)})
                        if len(hits) >= limit:
                            return hits
        except OSError:
            continue
    return hits


def _unit(pid: int) -> str:
    try:
        text = Path(f'/proc/{pid}/cgroup').read_text(errors='replace')
    except OSError:
        return ''
    found = re.findall(r'/([^/]+\.(?:service|scope))(?=$|/)', text)
    return found[-1] if found else ''


def proc_snapshot(needles: tuple[str, ...]) -> list[dict[str, Any]]:
    out, names, parent = [], {p.name for p in TARGETS}, str(TARGETS[0].parent)
    for d in Path('/proc').iterdir():
        if not d.name.isdigit():
            continue
        pid = int(d.name)
        try:
            cmd = ' '.join(x.decode('utf-8', 'replace') for x in (d/'cmdline').read_bytes().split(b'\0') if x)
        except OSError:
            cmd = ''
        try: exe = os.readlink(d/'exe')
        except OSError: exe = ''
        try: cwd = os.readlink(d/'cwd')
        except OSError: cwd = ''
        fds = []
        try:
            for fd in list((d/'fd').iterdir())[:512]:
                try: target = os.readlink(fd)
                except OSError: continue
                if target.startswith(parent) or Path(target).name in names:
                    fds.append(f'{fd.name}:{target}')
        except OSError:
            pass
        joined = f'{cmd} {exe} {cwd}'.lower()
        if fds or any(n in joined for n in needles):
            out.append({'pid': pid, 'unit': _unit(pid), 'exe': redact(exe), 'cwd': redact(cwd), 'command': redact(cmd, 1600), 'relevant_fds': sorted(fds)})
    return sorted(out, key=lambda x: x['pid'])


def journal(epoch: float, needles: tuple[str, ...]) -> list[str]:
    p = run(['journalctl', '--since', f'@{max(0, epoch-2):.3f}', '--until', f'@{epoch+3:.3f}', '--no-pager', '-o', 'short-iso'], 20)
    return [redact(line, 1800) for line in p.stdout.splitlines() if any(n in line.lower() for n in needles) or re.search(r'(q4r3|exact25|alimi|ledger|trace|view|display)', line, re.I)][-300:]


def historical(prior: dict[str, Any], needles: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for change in prior.get('target_changes') or []:
        ns = (change.get('after') or {}).get('mtime_ns')
        if not isinstance(ns, int):
            continue
        epoch = ns / 1_000_000_000
        key = int(epoch * 10)
        row = grouped.setdefault(key, {'epoch': epoch, 'detected_at': datetime.fromtimestamp(epoch, timezone.utc).isoformat(), 'paths': [], 'journal': journal(epoch, needles)})
        row['paths'].append(change.get('path'))
    return list(grouped.values())


def journal_units(events: Iterable[dict[str, Any]]) -> set[str]:
    out = set()
    for e in events:
        for line in e.get('journal') or []:
            out.update(re.findall(r'\b([A-Za-z0-9_.@-]+\.(?:service|timer))\b', line))
    return out


def _show(raw: str) -> dict[str, str]:
    return dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)


def systemd_inventory(refs: list[dict[str, Any]], needles: tuple[str, ...], extra: Iterable[str]) -> dict[str, Any]:
    units = set(extra)
    units |= {Path(h['path']).name for h in refs if Path(h['path']).name.endswith(('.service', '.timer'))}
    commands = (
        (['systemctl', 'list-units', '--type=service', '--state=active', '--no-legend', '--no-pager'], True),
        (['systemctl', 'list-units', '--type=timer', '--all', '--no-legend', '--no-pager'], True),
        (['systemctl', 'list-unit-files', '--type=service', '--no-legend', '--no-pager'], False),
        (['systemctl', 'list-unit-files', '--type=timer', '--no-legend', '--no-pager'], False),
    )
    for cmd, all_rows in commands:
        for line in run(cmd, 45).stdout.splitlines():
            f = line.split()
            if f and f[0].endswith(('.service', '.timer')) and (all_rows or any(n in line.lower() for n in needles) or re.search(r'(q4r3|exact25|alimi|ledger|trace|view|display|telegram)', line, re.I)):
                units.add(f[0])
    props = ('Id','ActiveState','SubState','UnitFileState','FragmentPath','ExecStart','WorkingDirectory','MainPID','TriggeredBy','Triggers','ExecMainStartTimestamp')
    rows = []
    for unit in sorted(units):
        cmd = ['systemctl', 'show', unit, '--no-pager']
        for prop in props: cmd += ['-p', prop]
        row = _show(run(cmd, 20).stdout)
        if row:
            row['ExecStart'] = redact(row.get('ExecStart',''), 2400); row['WorkingDirectory'] = redact(row.get('WorkingDirectory',''))
            rows.append(row)
    timers = [redact(x,1600) for x in run(['systemctl','list-timers','--all','--no-pager','--no-legend'],30).stdout.splitlines() if re.search(r'(q4r3|exact25|alimi|ledger|trace|view|display|telegram)', x, re.I)]
    return {'units': rows, 'timer_lines': timers}
