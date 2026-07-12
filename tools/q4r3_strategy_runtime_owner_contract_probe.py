from __future__ import annotations

import argparse
import ast
import csv
import html
import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

ROOT = Path('/home/z/z')
RUNTIME = ROOT / 'runtime'
COMPLETENESS = RUNTIME / 'q4r3_strategy_canonical_completeness_latest.json'
OWNER_AUDIT = RUNTIME / 'q4r3_strategy_owner_writer_test_audit_latest.json'
TARGET_OWNER = 'range_fade'
TARGET_WRITERS = ('grid_rebalance', 'rbreaker_like', 'vol_spike_fade')

SCAN_ROOTS = ('backend', 'config', 'data', 'services', 'systemd', 'tests', 'tools')
EXCLUDED_PARTS = {
    '.git', '.venv', 'venv', 'node_modules', 'site-packages', '__pycache__',
    'frontend', 'static', 'templates', 'logs', 'journal', 'processed', 'backup',
    'backups', 'archive', 'archives', 'quarantine', 'dist', 'build',
}
ALLOWED_SUFFIXES = {'.py', '.sh', '.service', '.json', '.yaml', '.yml', '.toml'}
MAX_FILE_BYTES = 4 * 1024 * 1024

WRITER_TERMS = (
    'write_text(', 'json.dump(', 'json.dumps(', 'atomic_json', 'atomic_write',
    '.replace(', 'open(', '.append(', 'journal', 'ledger', 'close_ts', 'exit_ts',
)
RISK_TERMS = (
    'initial_risk_usdt', 'risk_usdt', 'initial_stop', 'stop_price',
    'realized_r', 'pnl_r', 'realized_pnl', 'closed_pnl',
)
CONTRACT_TERMS = (
    'strategy_id', 'symbol', 'side', 'entry_price', 'entry_ts', 'initial_stop',
    'initial_risk_usdt', 'exit_ts', 'realized_pnl', 'realized_r',
)
ENTRY_CALLABLE_HINTS = (
    'generate_signal', 'signal', 'evaluate', 'run', 'decide', 'entry', 'on_candle',
    'compute', 'strategy', 'apply',
)


@dataclass(frozen=True)
class CodeRecord:
    path: Path
    relative: str
    module: str
    text: str
    lower: str
    imports: frozenset[str]
    strings: frozenset[str]
    functions: frozenset[str]
    classes: frozenset[str]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(errors='ignore'))


def normalize(value: Any) -> str:
    text = str(value or '').strip().lower()
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', text).strip('_'))


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except Exception:
        return str(path)


def excluded(path: Path) -> bool:
    for part in path.parts:
        low = part.lower()
        if low in EXCLUDED_PARTS:
            return True
        if low.startswith(('_trash', 'backup_', 'archive_', 'quarantine_')):
            return True
    return False


def iter_source_files() -> Iterator[Path]:
    for root_name in SCAN_ROOTS:
        base = ROOT / root_name
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if not excluded(current_path / name)]
            for name in files:
                path = current_path / name
                if excluded(path) or path.suffix.lower() not in ALLOWED_SUFFIXES:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if 0 < size <= MAX_FILE_BYTES:
                    yield path


def module_name(path: Path) -> str:
    try:
        return '.'.join(path.relative_to(ROOT).with_suffix('').parts)
    except Exception:
        return ''


def parse_python(path: Path, text: str) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    imports: Set[str] = set()
    strings: Set[str] = set()
    functions: Set[str] = set()
    classes: Set[str] = set()
    if path.suffix != '.py':
        return imports, strings, functions, classes
    try:
        tree = ast.parse(text)
    except Exception:
        return imports, strings, functions, classes
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if base:
                imports.add(base)
            imports.update(f'{base}.{alias.name}'.strip('.') for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if value and len(value) <= 300:
                strings.add(value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)
    return imports, strings, functions, classes


def load_records() -> List[CodeRecord]:
    records: List[CodeRecord] = []
    for path in iter_source_files():
        try:
            text = path.read_text(errors='ignore')
        except OSError:
            continue
        imports, strings, functions, classes = parse_python(path, text)
        records.append(CodeRecord(
            path=path,
            relative=rel(path),
            module=module_name(path),
            text=text,
            lower=text.lower(),
            imports=frozenset(imports),
            strings=frozenset(strings),
            functions=frozenset(functions),
            classes=frozenset(classes),
        ))
    return records


def load_expected() -> List[str]:
    payload = read_json(COMPLETENESS)
    selected = ((payload.get('expected_universe') or {}).get('selected') or {})
    return [normalize(item) for item in selected.get('names', []) if normalize(item)]


def module_aliases(module: str) -> Set[str]:
    aliases = {module, module.split('.')[-1]}
    if module.endswith('_legendary'):
        aliases.add(module.split('.')[-1].removesuffix('_legendary'))
    return aliases


def string_module_targets(value: str, known_modules: Set[str]) -> Set[str]:
    found: Set[str] = set()
    normalized_path = value.replace('/', '.').removesuffix('.py').strip('.')
    if normalized_path in known_modules:
        found.add(normalized_path)
    for module in known_modules:
        if value == module or value.endswith(module) or value.endswith(module + '.py'):
            found.add(module)
    return found


def build_graph(records: Sequence[CodeRecord]) -> Tuple[Dict[str, CodeRecord], Dict[str, Set[str]], Dict[str, Set[str]]]:
    by_module = {record.module: record for record in records if record.module}
    known = set(by_module)
    forward: Dict[str, Set[str]] = defaultdict(set)
    reverse: Dict[str, Set[str]] = defaultdict(set)
    for record in records:
        if not record.module:
            continue
        targets = {target for target in record.imports if target in known}
        for value in record.strings:
            targets.update(string_module_targets(value, known))
        for target in targets:
            if target == record.module:
                continue
            forward[record.module].add(target)
            reverse[target].add(record.module)
    return by_module, forward, reverse


def systemd_snapshot() -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    try:
        listed = subprocess.run(
            ['systemctl', 'list-units', '--type=service', '--state=running', '--no-legend', '--no-pager'],
            capture_output=True, text=True, timeout=12, check=False,
        ).stdout
    except Exception:
        return units
    for line in listed.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        try:
            shown = subprocess.run(
                ['systemctl', 'show', unit, '-p', 'MainPID', '-p', 'ExecStart', '-p', 'WorkingDirectory'],
                capture_output=True, text=True, timeout=4, check=False,
            ).stdout
        except Exception:
            continue
        fields: Dict[str, str] = {}
        for row in shown.splitlines():
            key, _, value = row.partition('=')
            fields[key] = value
        haystack = ' '.join(fields.values())
        if '/home/z/z' not in haystack and not unit.startswith(('z-', 'zel', 'q4r3')):
            continue
        units.append({
            'unit': unit,
            'main_pid': int(fields.get('MainPID') or 0),
            'exec_start': fields.get('ExecStart') or '',
            'working_directory': fields.get('WorkingDirectory') or '',
        })
    return units


def process_snapshot() -> List[Dict[str, Any]]:
    processes: List[Dict[str, Any]] = []
    proc = Path('/proc')
    if not proc.exists():
        return processes
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        try:
            cmdline = (item / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='ignore').strip()
        except Exception:
            continue
        if '/home/z/z' not in cmdline and 'python' not in cmdline.lower():
            continue
        try:
            cwd = os.readlink(item / 'cwd')
        except Exception:
            cwd = ''
        try:
            cgroup = (item / 'cgroup').read_text(errors='ignore')
        except Exception:
            cgroup = ''
        if '/home/z/z' not in cmdline and '/home/z/z' not in cwd and 'z-' not in cgroup:
            continue
        processes.append({'pid': int(item.name), 'cmdline': cmdline, 'cwd': cwd, 'cgroup': cgroup[:1000]})
    return processes


def py_spy_snapshots(processes: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    binary = shutil.which('py-spy')
    if not binary:
        return []
    snapshots: List[Dict[str, Any]] = []
    for process in processes:
        pid = int(process.get('pid') or 0)
        if pid <= 1 or 'python' not in str(process.get('cmdline', '')).lower():
            continue
        try:
            completed = subprocess.run(
                [binary, 'dump', '--pid', str(pid), '--nonblocking'],
                capture_output=True, text=True, timeout=8, check=False,
            )
        except Exception as exc:
            snapshots.append({'pid': pid, 'status': 'ERROR', 'error': repr(exc), 'stack': ''})
            continue
        stack = (completed.stdout or '') + '\n' + (completed.stderr or '')
        snapshots.append({'pid': pid, 'status': 'PASS' if completed.returncode == 0 else f'EXIT_{completed.returncode}', 'stack': stack[:50000]})
    return snapshots


def record_references_strategy(record: CodeRecord, strategy: str) -> bool:
    pattern = re.compile(rf'(?<![a-z0-9]){re.escape(strategy)}(?![a-z0-9])', re.I)
    return bool(pattern.search(record.lower) or pattern.search(record.relative.lower()))


def strategy_modules(strategy: str, by_module: Mapping[str, CodeRecord]) -> List[str]:
    candidates = [
        f'backend.strategies.{strategy}',
        f'backend.legendary_rebuild.strategies.{strategy}_legendary',
        f'backend.strategies_v4.{strategy}_v4',
    ]
    return [module for module in candidates if module in by_module]


def runtime_text(units: Sequence[Mapping[str, Any]], processes: Sequence[Mapping[str, Any]], stacks: Sequence[Mapping[str, Any]]) -> str:
    chunks = []
    chunks.extend(str(unit.get('exec_start', '')) + ' ' + str(unit.get('working_directory', '')) for unit in units)
    chunks.extend(str(process.get('cmdline', '')) + ' ' + str(process.get('cwd', '')) + ' ' + str(process.get('cgroup', '')) for process in processes)
    chunks.extend(str(snapshot.get('stack', '')) for snapshot in stacks)
    return '\n'.join(chunks).lower()


def registry_evidence(strategy: str, records: Sequence[CodeRecord], module_candidates: Sequence[str]) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    for record in records:
        if not any(token in record.relative.lower() for token in ('registry', 'catalog', 'manifest', 'policy', 'profile')):
            continue
        if not record_references_strategy(record, strategy):
            continue
        matched_modules = []
        for module in module_candidates:
            aliases = module_aliases(module)
            if any(alias.lower() in record.lower for alias in aliases):
                matched_modules.append(module)
        evidence.append({'path': record.relative, 'matched_modules': sorted(set(matched_modules))})
    return evidence[:100]


def reachable_importers(start: str, reverse: Mapping[str, Set[str]], max_depth: int = 6) -> Dict[str, int]:
    result = {start: 0}
    queue = deque([(start, 0)])
    while queue:
        module, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for importer in reverse.get(module, set()):
            if importer in result:
                continue
            result[importer] = depth + 1
            queue.append((importer, depth + 1))
    return result


def owner_probe(strategy: str, records: Sequence[CodeRecord], by_module: Mapping[str, CodeRecord], reverse: Mapping[str, Set[str]], runtime_blob: str) -> Dict[str, Any]:
    modules = strategy_modules(strategy, by_module)
    registry = registry_evidence(strategy, records, modules)
    candidates: List[Dict[str, Any]] = []
    for module in modules:
        record = by_module[module]
        importers = reachable_importers(module, reverse)
        direct_runtime = module.lower() in runtime_blob or record.relative.lower() in runtime_blob
        importer_runtime = [name for name in importers if name.lower() in runtime_blob or by_module.get(name, record).relative.lower() in runtime_blob]
        registry_hits = [item['path'] for item in registry if module in item.get('matched_modules', [])]
        score = 0
        score += 100 if direct_runtime else 0
        score += min(80, len(importer_runtime) * 20)
        score += min(60, len(registry_hits) * 15)
        score += min(25, max(0, 6 - min(importers.values(), default=6)) * 5)
        candidates.append({
            'module': module,
            'path': record.relative,
            'score': score,
            'direct_runtime': direct_runtime,
            'runtime_importers': sorted(importer_runtime)[:30],
            'registry_paths': sorted(set(registry_hits))[:30],
            'static_importer_count': len(importers) - 1,
            'functions': sorted(record.functions),
            'classes': sorted(record.classes),
        })
    candidates.sort(key=lambda item: (item['score'], item['static_importer_count']), reverse=True)
    if len(candidates) == 1:
        verdict = 'SINGLE_OWNER_CONFIRMED'
        owner = candidates[0]['module']
    elif len(candidates) >= 2 and candidates[0]['score'] >= 80 and candidates[0]['score'] - candidates[1]['score'] >= 30:
        verdict = 'RUNTIME_OR_REGISTRY_OWNER_CONFIRMED'
        owner = candidates[0]['module']
    elif len(candidates) >= 2:
        verdict = 'DUAL_OWNER_STILL_UNRESOLVED'
        owner = None
    else:
        verdict = 'OWNER_MODULE_MISSING'
        owner = None
    return {'strategy': strategy, 'verdict': verdict, 'owner_module': owner, 'candidates': candidates, 'registry_evidence': registry}


def writer_characteristics(record: CodeRecord) -> Dict[str, Any]:
    writer_hits = sorted(term for term in WRITER_TERMS if term in record.lower)
    risk_hits = sorted(term for term in RISK_TERMS if term in record.lower)
    contract_hits = sorted(term for term in CONTRACT_TERMS if term in record.lower)
    return {
        'writer_hits': writer_hits,
        'risk_hits': risk_hits,
        'contract_hits': contract_hits,
        'writer_like': bool(writer_hits and risk_hits),
    }


def writer_probe(strategy: str, owner_modules: Sequence[str], by_module: Mapping[str, CodeRecord], reverse: Mapping[str, Set[str]], runtime_blob: str) -> Dict[str, Any]:
    candidates: Dict[str, Dict[str, Any]] = {}
    for owner in owner_modules:
        for module, depth in reachable_importers(owner, reverse).items():
            record = by_module.get(module)
            if record is None:
                continue
            characteristics = writer_characteristics(record)
            if not characteristics['writer_like']:
                continue
            runtime_hit = module.lower() in runtime_blob or record.relative.lower() in runtime_blob
            score = (100 if runtime_hit else 0) + max(0, 60 - depth * 10) + len(characteristics['contract_hits']) * 2
            existing = candidates.get(module)
            item = {
                'module': module,
                'path': record.relative,
                'depth': depth,
                'runtime_hit': runtime_hit,
                'score': score,
                **characteristics,
            }
            if existing is None or item['score'] > existing['score']:
                candidates[module] = item
    ranked = sorted(candidates.values(), key=lambda item: item['score'], reverse=True)
    if any(item['depth'] == 0 for item in ranked):
        verdict = 'DIRECT_WRITER_CONFIRMED'
    elif any(item['runtime_hit'] for item in ranked):
        verdict = 'RUNTIME_COMMON_WRITER_CONFIRMED'
    elif ranked:
        verdict = 'STATIC_COMMON_WRITER_CANDIDATES_FOUND'
    else:
        verdict = 'WRITER_PATH_UNRESOLVED'
    return {'strategy': strategy, 'verdict': verdict, 'candidates': ranked[:30]}


def callable_surface(record: CodeRecord) -> List[str]:
    preferred = [name for name in record.functions if any(hint in name.lower() for hint in ENTRY_CALLABLE_HINTS)]
    return sorted(preferred or record.functions)


def contract_surface(expected: Sequence[str], records: Sequence[CodeRecord], by_module: Mapping[str, CodeRecord]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for strategy in expected:
        modules = strategy_modules(strategy, by_module)
        module_rows = []
        for module in modules:
            record = by_module[module]
            characteristics = writer_characteristics(record)
            module_rows.append({
                'module': module,
                'path': record.relative,
                'callables': callable_surface(record),
                'classes': sorted(record.classes),
                'contract_hits': characteristics['contract_hits'],
            })
        registry = registry_evidence(strategy, records, modules)
        rows.append({
            'strategy': strategy,
            'module_count': len(modules),
            'modules': module_rows,
            'registry_evidence_count': len(registry),
            'has_callable': any(item['callables'] or item['classes'] for item in module_rows),
            'has_contract_terms': any(len(item['contract_hits']) >= 3 for item in module_rows),
        })
    summary = {
        'exact_25': len(rows) == 25,
        'missing_module_count': sum(row['module_count'] == 0 for row in rows),
        'multi_module_count': sum(row['module_count'] > 1 for row in rows),
        'missing_callable_count': sum(not row['has_callable'] for row in rows),
        'missing_contract_surface_count': sum(not row['has_contract_terms'] for row in rows),
        'missing_registry_evidence_count': sum(row['registry_evidence_count'] == 0 for row in rows),
    }
    return {'summary': summary, 'strategies': rows}


def existing_test_surface(expected: Sequence[str], records: Sequence[CodeRecord]) -> Dict[str, Any]:
    tests = [record for record in records if 'tests/' in record.relative or Path(record.relative).name.startswith('test_')]
    direct: Dict[str, List[str]] = defaultdict(list)
    shared: List[Dict[str, Any]] = []
    for record in tests:
        mentioned = [strategy for strategy in expected if record_references_strategy(record, strategy)]
        for strategy in mentioned:
            direct[strategy].append(record.relative)
        low = record.lower
        contract_hits = sorted(term for term in CONTRACT_TERMS if term in low)
        registry_driven = 'parametrize' in low and any(token in low for token in ('registry', 'expected_strategy', 'by_strategy'))
        if len(mentioned) >= 20 or registry_driven:
            shared.append({'path': record.relative, 'mentioned_count': len(mentioned), 'registry_driven': registry_driven, 'contract_hits': contract_hits})
    return {
        'test_file_count': len(tests),
        'direct_covered_count': sum(bool(direct.get(strategy)) for strategy in expected),
        'direct_paths': {strategy: sorted(paths) for strategy, paths in direct.items()},
        'shared_harness_candidates': shared,
    }


def render_html(result: Mapping[str, Any]) -> str:
    owner = result.get('range_fade_owner', {})
    writer_rows = ''.join(
        '<tr><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
            html.escape(str(item.get('strategy'))),
            html.escape(str(item.get('verdict'))),
            len(item.get('candidates', [])),
        )
        for item in result.get('writer_probes', [])
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Runtime Owner Contract Probe</title>"
        "<style>body{font-family:Arial;background:#111;color:#eee;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #444;padding:8px}</style></head><body>"
        f"<h1>{html.escape(str(result.get('verdict')))}</h1>"
        f"<p>range_fade: {html.escape(str(owner.get('verdict')))}</p>"
        "<table><thead><tr><th>Strategy</th><th>Writer verdict</th><th>Candidates</th></tr></thead><tbody>"
        + writer_rows + "</tbody></table></body></html>"
    )


def write_csv(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer_map = {item['strategy']: item for item in result.get('writer_probes', [])}
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['strategy', 'module_count', 'has_callable', 'has_contract_terms', 'registry_evidence_count', 'writer_verdict'])
        for row in result.get('contract_surface', {}).get('strategies', []):
            writer.writerow([
                row.get('strategy'), row.get('module_count'), row.get('has_callable'),
                row.get('has_contract_terms'), row.get('registry_evidence_count'),
                (writer_map.get(row.get('strategy')) or {}).get('verdict', ''),
            ])


def run(output_dir: Path) -> Dict[str, Any]:
    expected = load_expected()
    records = load_records()
    by_module, forward, reverse = build_graph(records)
    units = systemd_snapshot()
    processes = process_snapshot()
    stacks = py_spy_snapshots(processes)
    blob = runtime_text(units, processes, stacks)

    owner = owner_probe(TARGET_OWNER, records, by_module, reverse, blob)
    writer_probes = []
    for strategy in TARGET_WRITERS:
        owners = strategy_modules(strategy, by_module)
        writer_probes.append(writer_probe(strategy, owners, by_module, reverse, blob))
    contracts = contract_surface(expected, records, by_module)
    tests = existing_test_surface(expected, records)

    unresolved = []
    if owner['verdict'] not in {'SINGLE_OWNER_CONFIRMED', 'RUNTIME_OR_REGISTRY_OWNER_CONFIRMED'}:
        unresolved.append('range_fade_owner')
    unresolved.extend(item['strategy'] + '_writer' for item in writer_probes if item['verdict'] == 'WRITER_PATH_UNRESOLVED')
    if contracts['summary']['missing_module_count'] or contracts['summary']['multi_module_count']:
        unresolved.append('canonical_module_ownership')
    if tests['direct_covered_count'] < 25 and not tests['shared_harness_candidates']:
        unresolved.append('shared_contract_harness')

    verdict = 'RUNTIME_OWNER_CONTRACT_EVIDENCE_COMPLETE' if not unresolved else 'RUNTIME_OWNER_CONTRACT_GAPS_REMAIN'
    result: Dict[str, Any] = {
        'schema': 'q4r3_strategy_runtime_owner_contract_probe_v1',
        'status': 'PASS_Q4R3_STRATEGY_RUNTIME_OWNER_CONTRACT_PROBE',
        'verdict': verdict,
        'action': 'HOLD',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'expected_strategy_count': len(expected),
        'active_source_file_count': len(records),
        'running_unit_count': len(units),
        'candidate_process_count': len(processes),
        'py_spy_available': bool(shutil.which('py-spy')),
        'py_spy_snapshot_count': len(stacks),
        'range_fade_owner': owner,
        'writer_probes': writer_probes,
        'contract_surface': contracts,
        'existing_test_surface': tests,
        'unresolved': unresolved,
        'next_action': 'PATCH_ONLY_RUNTIME_CONFIRMED_OWNER_AND_WRITER_GAPS_THEN_ADD_ONE_SHARED_CONTRACT_HARNESS',
        'runtime_evidence': {
            'units': units,
            'processes': processes,
            'py_spy': [{k: v for k, v in item.items() if k != 'stack'} | {'stack_match_terms': [term for term in (TARGET_OWNER, *TARGET_WRITERS) if term in str(item.get('stack', '')).lower()]} for item in stacks],
        },
        'safety': {
            'read_only': True,
            'strategy_modified': False,
            'registry_modified': False,
            'paper_live_order_modified': False,
            'persistent_forward_r_watcher_modified': False,
            'source_excerpts_published': False,
            'raw_trade_rows_published': False,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / 'q4r3_strategy_runtime_owner_contract_probe_latest.json', result)
    atomic_json(output_dir / 'q4r3_strategy_runtime_owner_contract_decision_latest.json', {
        'verdict': verdict,
        'action': 'HOLD',
        'range_fade_owner_verdict': owner['verdict'],
        'range_fade_owner_module': owner['owner_module'],
        'writer_verdicts': {item['strategy']: item['verdict'] for item in writer_probes},
        'contract_summary': contracts['summary'],
        'existing_test_covered_count': tests['direct_covered_count'],
        'shared_harness_candidate_count': len(tests['shared_harness_candidates']),
        'unresolved': unresolved,
        'next_action': result['next_action'],
    })
    write_csv(output_dir / 'q4r3_strategy_runtime_contract_matrix_latest.csv', result)
    (output_dir / 'q4r3_strategy_runtime_owner_contract_probe_latest.html').write_text(render_html(result), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output_dir)
    print(json.dumps({
        'status': result['status'],
        'verdict': result['verdict'],
        'range_fade_owner_verdict': result['range_fade_owner']['verdict'],
        'range_fade_owner_module': result['range_fade_owner']['owner_module'],
        'writer_verdicts': {item['strategy']: item['verdict'] for item in result['writer_probes']},
        'contract_summary': result['contract_surface']['summary'],
        'existing_test_covered_count': result['existing_test_surface']['direct_covered_count'],
        'unresolved': result['unresolved'],
        'next_action': result['next_action'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
