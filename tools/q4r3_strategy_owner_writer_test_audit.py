from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

ROOT = Path('/home/z/z')
RUNTIME = ROOT / 'runtime'
COMPLETENESS = RUNTIME / 'q4r3_strategy_canonical_completeness_latest.json'
TARGET_DUPLICATE = 'range_fade'
TARGET_WRITERS = ('grid_rebalance', 'rbreaker_like', 'vol_spike_fade')
WRITER_TOKENS = ('write_text(', 'json.dump(', 'json.dumps(', '.replace(', 'open(', 'append(', 'atomic_json', 'journal', 'ledger')
RISK_TOKENS = ('initial_risk_usdt', 'risk_usdt', 'realized_r', 'pnl_r', 'realized_pnl')
EXCLUDED = {'.git', '.venv', 'venv', 'node_modules', 'site-packages', '__pycache__', '_TRASH_ZEL_20260602T155011Z', 'static', 'frontend', 'templates'}


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(errors='ignore'))


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except Exception:
        return str(path)


def excluded(path: Path) -> bool:
    return any(part in EXCLUDED or part.lower().startswith(('backup', 'archive', 'quarantine')) for part in path.parts)


def iter_code_files() -> Iterator[Path]:
    roots = [ROOT / 'backend', ROOT / 'tools', ROOT / 'tests', ROOT / 'services', ROOT / 'systemd', ROOT / 'config', ROOT / 'data']
    for base in roots:
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base):
            current_path = Path(current)
            dirs[:] = [d for d in dirs if not excluded(current_path / d)]
            for name in files:
                path = current_path / name
                if excluded(path) or path.suffix.lower() not in {'.py', '.sh', '.service', '.json', '.yaml', '.yml', '.toml'}:
                    continue
                try:
                    if 0 < path.stat().st_size <= 4 * 1024 * 1024:
                        yield path
                except OSError:
                    pass


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors='ignore')
    except OSError:
        return ''


def sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def normalized_ast_hash(path: Path) -> Optional[str]:
    if path.suffix != '.py':
        return None
    try:
        tree = ast.parse(path.read_text(errors='ignore'))
        dump = ast.dump(tree, annotate_fields=True, include_attributes=False)
        return hashlib.sha256(dump.encode()).hexdigest()
    except Exception:
        return None


def module_name(path: Path) -> str:
    try:
        parts = list(path.relative_to(ROOT).with_suffix('').parts)
    except Exception:
        return ''
    return '.'.join(parts)


def import_targets(path: Path) -> Set[str]:
    if path.suffix != '.py':
        return set()
    try:
        tree = ast.parse(path.read_text(errors='ignore'))
    except Exception:
        return set()
    imports: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            imports.add(base)
            imports.update(f'{base}.{alias.name}'.strip('.') for alias in node.names)
    return imports


def active_process_paths() -> List[str]:
    paths: Set[str] = set()
    proc = Path('/proc')
    if proc.exists():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmd = (entry / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='ignore')
            except Exception:
                continue
            for match in re.findall(r'/home/z/z/[^\s]+', cmd):
                paths.add(match.rstrip('"\''))
    try:
        output = subprocess.run(
            ['systemctl', 'list-units', '--type=service', '--state=running', '--no-legend', '--no-pager'],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
        for unit in [line.split()[0] for line in output.splitlines() if line.split()]:
            show = subprocess.run(['systemctl', 'show', unit, '-p', 'ExecStart', '--value'], capture_output=True, text=True, timeout=3, check=False).stdout
            for match in re.findall(r'/home/z/z/[^\s;}]+' , show):
                paths.add(match.rstrip('"\''))
    except Exception:
        pass
    return sorted(paths)


def load_expected() -> Tuple[List[str], Mapping[str, Any]]:
    payload = read_json(COMPLETENESS)
    selected = ((payload.get('expected_universe') or {}).get('selected') or {})
    names = [str(x) for x in selected.get('names', [])]
    return names, payload


def build_index(files: Sequence[Path]) -> Tuple[Dict[str, Path], Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, str]]:
    module_to_path: Dict[str, Path] = {}
    imports_by_module: Dict[str, Set[str]] = {}
    reverse: Dict[str, Set[str]] = defaultdict(set)
    texts: Dict[str, str] = {}
    for path in files:
        mod = module_name(path)
        if not mod:
            continue
        module_to_path[mod] = path
        text = read_text(path)
        texts[mod] = text
        imports = import_targets(path)
        imports_by_module[mod] = imports
        for imported in imports:
            reverse[imported].add(mod)
    return module_to_path, imports_by_module, reverse, texts


def module_refs(target_module: str, texts: Mapping[str, str]) -> List[str]:
    leaf = target_module.split('.')[-1]
    pattern = re.compile(rf'(?<![A-Za-z0-9_])(?:{re.escape(target_module)}|{re.escape(leaf)})(?![A-Za-z0-9_])')
    return sorted(mod for mod, text in texts.items() if mod != target_module and pattern.search(text))


def runtime_score(module: str, active_paths: Sequence[str], reverse: Mapping[str, Set[str]], max_depth: int = 3) -> Tuple[int, List[str]]:
    queue = deque([(module, 0)])
    seen = {module}
    evidence: Set[str] = set()
    score = 0
    while queue:
        current, depth = queue.popleft()
        for importer in reverse.get(current, set()):
            if importer in seen:
                continue
            seen.add(importer)
            importer_path = ROOT / Path(*importer.split('.')).with_suffix('.py')
            importer_rel = rel(importer_path)
            if any(importer_rel in p or p.endswith(importer_path.name) for p in active_paths):
                score += 100 - depth * 10
                evidence.add(importer_rel)
            elif importer.startswith(('backend.engine', 'backend.bots', 'backend.scripts', 'backend.worker')):
                score += 20 - depth * 3
                evidence.add(importer_rel)
            if depth + 1 < max_depth:
                queue.append((importer, depth + 1))
    return score, sorted(evidence)


def duplicate_owner_audit(strategy: str, files: Sequence[Path], reverse: Mapping[str, Set[str]], texts: Mapping[str, str], active_paths: Sequence[str]) -> Dict[str, Any]:
    candidates = [
        ROOT / 'backend' / 'strategies' / f'{strategy}.py',
        ROOT / 'backend' / 'legendary_rebuild' / 'strategies' / f'{strategy}_legendary.py',
    ]
    details = []
    for path in candidates:
        mod = module_name(path)
        score, runtime_evidence = runtime_score(mod, active_paths, reverse)
        details.append({
            'path': rel(path),
            'exists': path.exists(),
            'sha256': sha256(path),
            'normalized_ast_sha256': normalized_ast_hash(path),
            'module': mod,
            'static_ref_modules': module_refs(mod, texts)[:50],
            'runtime_reachability_score': score,
            'runtime_evidence': runtime_evidence[:30],
        })
    existing = [d for d in details if d['exists']]
    exact_duplicate = len(existing) == 2 and existing[0]['sha256'] == existing[1]['sha256']
    semantic_duplicate = len(existing) == 2 and existing[0]['normalized_ast_sha256'] == existing[1]['normalized_ast_sha256']
    ranked = sorted(existing, key=lambda d: (d['runtime_reachability_score'], len(d['static_ref_modules'])), reverse=True)
    if len(ranked) < 2:
        verdict = 'SINGLE_IMPLEMENTATION_ONLY'
        owner = ranked[0]['path'] if ranked else None
    elif ranked[0]['runtime_reachability_score'] > ranked[1]['runtime_reachability_score']:
        verdict = 'OWNER_CANDIDATE_SEPARATED'
        owner = ranked[0]['path']
    else:
        verdict = 'DUAL_OWNER_UNRESOLVED'
        owner = None
    return {
        'strategy': strategy,
        'verdict': verdict,
        'owner_candidate': owner,
        'exact_duplicate': exact_duplicate,
        'semantic_duplicate': semantic_duplicate,
        'candidates': details,
    }


def writer_characteristics(text: str) -> Dict[str, Any]:
    low = text.lower()
    writer_hits = sorted({token for token in WRITER_TOKENS if token in low})
    risk_hits = sorted({token for token in RISK_TOKENS if token in low})
    return {'writer_tokens': writer_hits, 'risk_tokens': risk_hits, 'writer_like': bool(writer_hits and risk_hits)}


def reachable_modules(start: str, reverse: Mapping[str, Set[str]], depth: int = 4) -> Dict[str, int]:
    result = {start: 0}
    queue = deque([(start, 0)])
    while queue:
        current, d = queue.popleft()
        if d >= depth:
            continue
        for importer in reverse.get(current, set()):
            if importer not in result:
                result[importer] = d + 1
                queue.append((importer, d + 1))
    return result


def writer_audit(strategy: str, reverse: Mapping[str, Set[str]], texts: Mapping[str, str], active_paths: Sequence[str]) -> Dict[str, Any]:
    canonical = f'backend.strategies.{strategy}'
    starts = [canonical, f'backend.legendary_rebuild.strategies.{strategy}_legendary']
    candidates: List[Dict[str, Any]] = []
    for start in starts:
        for mod, depth in reachable_modules(start, reverse).items():
            text = texts.get(mod, '')
            characteristics = writer_characteristics(text)
            if not characteristics['writer_like']:
                continue
            path = ROOT / Path(*mod.split('.')).with_suffix('.py')
            active = any(rel(path) in p or p.endswith(path.name) for p in active_paths)
            candidates.append({
                'module': mod,
                'path': rel(path),
                'depth': depth,
                'active_process_or_service_match': active,
                **characteristics,
            })
    dedup = {item['module']: item for item in candidates}
    ranked = sorted(dedup.values(), key=lambda x: (x['active_process_or_service_match'], -x['depth'], len(x['risk_tokens'])), reverse=True)
    if any(item['depth'] == 0 for item in ranked):
        verdict = 'DIRECT_STRATEGY_WRITER_PRESENT'
    elif ranked:
        verdict = 'COMMON_INDIRECT_WRITER_EVIDENCE'
    else:
        verdict = 'WRITER_PATH_UNRESOLVED'
    return {'strategy': strategy, 'verdict': verdict, 'writer_candidates': ranked[:30]}


def test_coverage(expected: Sequence[str], files: Sequence[Path]) -> Dict[str, Any]:
    test_files = [p for p in files if 'tests' in p.parts or p.name.startswith('test_')]
    direct: Dict[str, List[str]] = {strategy: [] for strategy in expected}
    shared: List[Dict[str, Any]] = []
    dynamic: List[str] = []
    for path in test_files:
        text = read_text(path)
        low = text.lower()
        mentioned = [s for s in expected if re.search(rf'(?<![a-z0-9]){re.escape(s)}(?![a-z0-9])', low)]
        for strategy in mentioned:
            direct[strategy].append(rel(path))
        if len(mentioned) >= 20:
            shared.append({'path': rel(path), 'mentioned_count': len(mentioned), 'missing': sorted(set(expected) - set(mentioned))})
        if 'parametrize' in low and any(token in low for token in ('strategies_registry', 'strategy_registry', 'by_strategy', 'expected_strategy')):
            dynamic.append(rel(path))
    covered = sorted(strategy for strategy, paths in direct.items() if paths)
    if len(covered) == len(expected):
        verdict = 'ALL_25_DIRECTLY_COVERED'
    elif shared or dynamic:
        verdict = 'SHARED_HARNESS_CANDIDATE_REQUIRES_EXECUTION_PROOF'
    else:
        verdict = 'NO_25_STRATEGY_CONTRACT_HARNESS_FOUND'
    return {
        'verdict': verdict,
        'test_file_count': len(test_files),
        'direct_covered_count': len(covered),
        'direct_missing': sorted(set(expected) - set(covered)),
        'direct_paths': {k: v[:20] for k, v in direct.items() if v},
        'shared_harness_candidates': shared,
        'dynamic_registry_harness_candidates': sorted(set(dynamic)),
    }


def run(output_dir: Path) -> Dict[str, Any]:
    expected, completeness = load_expected()
    files = list(iter_code_files())
    module_to_path, imports_by_module, reverse, texts = build_index(files)
    active_paths = active_process_paths()
    duplicate = duplicate_owner_audit(TARGET_DUPLICATE, files, reverse, texts, active_paths)
    writers = [writer_audit(strategy, reverse, texts, active_paths) for strategy in TARGET_WRITERS]
    tests = test_coverage(expected, files)

    unresolved = []
    if duplicate['verdict'] in {'DUAL_OWNER_UNRESOLVED'}:
        unresolved.append('range_fade_owner')
    unresolved.extend(f"{item['strategy']}_writer" for item in writers if item['verdict'] == 'WRITER_PATH_UNRESOLVED')
    if tests['verdict'] != 'ALL_25_DIRECTLY_COVERED':
        unresolved.append('strategy_contract_tests')

    verdict = 'OWNER_WRITER_TEST_EVIDENCE_COMPLETE' if not unresolved else 'OWNER_WRITER_TEST_GAPS_REMAIN'
    result = {
        'schema': 'q4r3_strategy_owner_writer_test_audit_v1',
        'status': 'PASS_Q4R3_STRATEGY_OWNER_WRITER_TEST_AUDIT',
        'verdict': verdict,
        'action': 'HOLD',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'expected_strategy_count': len(expected),
        'source_completeness_verdict': completeness.get('verdict'),
        'active_code_file_count': len(files),
        'active_process_path_count': len(active_paths),
        'duplicate_owner': duplicate,
        'writer_audits': writers,
        'test_coverage': tests,
        'unresolved': unresolved,
        'next_action': 'PATCH_ONLY_CONFIRMED_GAPS_THEN_BUILD_SHARED_CONTRACT_HARNESS' if unresolved else 'BUILD_AND_RUN_25_STRATEGY_CONTRACT_HARNESS',
        'safety': {
            'read_only': True,
            'strategy_modified': False,
            'registry_modified': False,
            'paper_live_order_modified': False,
            'persistent_forward_r_watcher_modified': False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / 'q4r3_strategy_owner_writer_test_audit_latest.json', result)
    atomic_json(output_dir / 'q4r3_strategy_owner_writer_test_decision_latest.json', {
        'verdict': verdict,
        'action': 'HOLD',
        'unresolved': unresolved,
        'range_fade_owner_verdict': duplicate['verdict'],
        'writer_verdicts': {item['strategy']: item['verdict'] for item in writers},
        'test_verdict': tests['verdict'],
        'next_action': result['next_action'],
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output_dir)
    print(json.dumps({
        'status': result['status'],
        'verdict': result['verdict'],
        'unresolved': result['unresolved'],
        'range_fade_owner_verdict': result['duplicate_owner']['verdict'],
        'writer_verdicts': {item['strategy']: item['verdict'] for item in result['writer_audits']},
        'test_verdict': result['test_coverage']['verdict'],
        'next_action': result['next_action'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
