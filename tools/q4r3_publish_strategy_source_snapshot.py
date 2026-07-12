from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

DEFAULT_ROOT = Path('/home/z/z')
ALLOWED_SUFFIXES = {'.py', '.json', '.yaml', '.yml', '.toml'}
EXCLUDED_PARTS = {
    '.git', '.venv', 'venv', 'node_modules', 'site-packages', '__pycache__',
    'frontend', 'static', 'templates', 'runtime', 'logs', 'journal', 'processed',
    'backup', 'backups', 'archive', 'archives', 'quarantine', 'dist', 'build',
}
SENSITIVE_NAMES = {
    'api_key', 'apikey', 'secret', 'secret_key', 'password', 'passwd', 'private_key',
    'access_token', 'refresh_token', 'auth_token', 'telegram_token', 'bot_token',
}
PLACEHOLDER_WORDS = {
    '', 'none', 'null', 'changeme', 'change_me', 'placeholder', 'example', 'test',
    'dummy', 'redacted', 'masked', 'your_key_here', 'your_token_here', 'env',
}
PEM_RE = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----')
BEARER_RE = re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}')
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
MAX_FILES = 350
MAX_IMPORT_DEPTH = 2

SUPPORT_PATHS = (
    'backend/config/strategies_registry.json',
    'backend/engine/strategy_registry.py',
    'backend/bots/strategy_catalog.py',
    'backend/contracts/ZOS_SKILL_REGISTRY_v1.json',
    'backend/trade_methods/policy.py',
    'backend/trade_methods/profiles.py',
    'backend/legendary_rebuild/legendary_manifest.json',
    'data/strategy_registry_latest.json',
)


def normalize(value: Any) -> str:
    text = str(value or '').strip().lower()
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', text).strip('_'))


def excluded(path: Path, root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except Exception:
        return True
    for part in rel.parts:
        low = part.lower()
        if low in EXCLUDED_PARTS:
            return True
        if low.startswith(('_trash', 'backup_', 'archive_', 'quarantine_')):
            return True
    return False


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(errors='ignore'))


def extract_strategy_map(probe: Mapping[str, Any]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    contract = probe.get('contract_surface') or {}
    for item in contract.get('strategies') or []:
        strategy = normalize(item.get('strategy'))
        if not strategy:
            continue
        paths: List[str] = []
        for module in item.get('modules') or []:
            path = str(module.get('path') or '').strip()
            if path and path not in paths:
                paths.append(path)
        result[strategy] = paths
    return result


def dotted_to_path(root: Path, module: str) -> Optional[Path]:
    module = module.strip('.')
    if not module:
        return None
    candidate = root.joinpath(*module.split('.')).with_suffix('.py')
    if candidate.is_file():
        return candidate
    package = root.joinpath(*module.split('.'), '__init__.py')
    if package.is_file():
        return package
    return None


def resolve_relative_module(current: Path, level: int, module: Optional[str], root: Path) -> Optional[Path]:
    try:
        rel = current.resolve().relative_to(root.resolve())
    except Exception:
        return None
    package_parts = list(rel.with_suffix('').parts[:-1])
    if current.name == '__init__.py':
        package_parts = list(rel.parts[:-1])
    climb = max(0, level - 1)
    if climb > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - climb]
    if module:
        base_parts.extend(module.split('.'))
    dotted = '.'.join(base_parts)
    return dotted_to_path(root, dotted)


def local_imports(path: Path, root: Path) -> List[Path]:
    if path.suffix != '.py':
        return []
    try:
        tree = ast.parse(path.read_text(errors='ignore'))
    except Exception:
        return []
    found: List[Path] = []
    for node in ast.walk(tree):
        candidate: Optional[Path] = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                candidate = dotted_to_path(root, alias.name)
                if candidate and candidate not in found:
                    found.append(candidate)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                candidate = resolve_relative_module(path, node.level, node.module, root)
                if candidate and candidate not in found:
                    found.append(candidate)
                if node.module is None:
                    for alias in node.names:
                        candidate = resolve_relative_module(path, node.level, alias.name, root)
                        if candidate and candidate not in found:
                            found.append(candidate)
            elif node.module:
                candidate = dotted_to_path(root, node.module)
                if candidate and candidate not in found:
                    found.append(candidate)
    return found


def is_placeholder(value: str) -> bool:
    normalized = normalize(value)
    if normalized in PLACEHOLDER_WORDS:
        return True
    return any(token in normalized for token in ('placeholder', 'redacted', 'dummy', 'example', 'your_key', 'your_token'))


def python_sensitive_findings(path: Path, text: str) -> List[str]:
    findings: List[str] = []
    if PEM_RE.search(text):
        findings.append('pem_private_key')
    if BEARER_RE.search(text):
        findings.append('bearer_token')
    try:
        tree = ast.parse(text)
    except Exception:
        return findings

    def names_from_target(target: ast.AST) -> List[str]:
        if isinstance(target, ast.Name):
            return [normalize(target.id)]
        if isinstance(target, ast.Attribute):
            return [normalize(target.attr)]
        if isinstance(target, (ast.Tuple, ast.List)):
            out: List[str] = []
            for item in target.elts:
                out.extend(names_from_target(item))
            return out
        return []

    for node in ast.walk(tree):
        targets: List[ast.AST] = []
        value: Optional[ast.AST] = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None or not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        literal = value.value.strip()
        if len(literal) < 8 or is_placeholder(literal):
            continue
        target_names = [name for target in targets for name in names_from_target(target)]
        if any(name in SENSITIVE_NAMES or any(token in name for token in SENSITIVE_NAMES) for name in target_names):
            findings.append('literal_secret_assignment')
    return sorted(set(findings))


def json_sensitive_findings(value: Any, path: Tuple[str, ...] = ()) -> List[str]:
    findings: List[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_norm = normalize(key)
            next_path = path + (str(key),)
            if isinstance(item, str) and len(item.strip()) >= 8 and not is_placeholder(item):
                if key_norm in SENSITIVE_NAMES or any(token in key_norm for token in SENSITIVE_NAMES):
                    findings.append('literal_secret_json:' + '.'.join(next_path))
            findings.extend(json_sensitive_findings(item, next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(json_sensitive_findings(item, path + (str(index),)))
    return findings


def sensitive_findings(path: Path, data: bytes) -> List[str]:
    text = data.decode('utf-8', errors='ignore')
    if path.suffix == '.py':
        return python_sensitive_findings(path, text)
    findings: List[str] = []
    if PEM_RE.search(text):
        findings.append('pem_private_key')
    if BEARER_RE.search(text):
        findings.append('bearer_token')
    if path.suffix == '.json':
        try:
            findings.extend(json_sensitive_findings(json.loads(text)))
        except Exception:
            pass
    return sorted(set(findings))


def collect_paths(root: Path, strategy_map: Mapping[str, Sequence[str]]) -> Tuple[Dict[Path, Set[str]], Dict[str, List[str]]]:
    selected: Dict[Path, Set[str]] = {}
    missing: Dict[str, List[str]] = {}
    queue: deque[Tuple[Path, int, str]] = deque()

    for strategy, paths in strategy_map.items():
        if not paths:
            missing.setdefault(strategy, []).append('NO_MODULE_PATH')
        for rel_path in paths:
            source = root / rel_path
            if source.is_file() and not excluded(source, root):
                selected.setdefault(source, set()).add('strategy:' + strategy)
                queue.append((source, 0, 'dependency:' + strategy))
            else:
                missing.setdefault(strategy, []).append(rel_path)

    for rel_path in SUPPORT_PATHS:
        source = root / rel_path
        if source.is_file() and not excluded(source, root):
            selected.setdefault(source, set()).add('support')
            queue.append((source, 0, 'support_dependency'))

    visited_depth: Dict[Path, int] = {}
    while queue:
        source, depth, reason = queue.popleft()
        old_depth = visited_depth.get(source)
        if old_depth is not None and old_depth <= depth:
            continue
        visited_depth[source] = depth
        if depth >= MAX_IMPORT_DEPTH:
            continue
        for imported in local_imports(source, root):
            if excluded(imported, root) or imported.suffix not in ALLOWED_SUFFIXES:
                continue
            try:
                rel = imported.resolve().relative_to(root.resolve())
            except Exception:
                continue
            if not rel.parts or rel.parts[0] not in {'backend', 'config', 'data'}:
                continue
            selected.setdefault(imported, set()).add(reason)
            queue.append((imported, depth + 1, reason))
            if len(selected) > MAX_FILES:
                raise RuntimeError(f'SNAPSHOT_FILE_LIMIT_EXCEEDED:{len(selected)}>{MAX_FILES}')
    return selected, missing


def publish(root: Path, probe_path: Path, output_dir: Path) -> Dict[str, Any]:
    probe = load_json(probe_path)
    strategy_map = extract_strategy_map(probe)
    selected, missing = collect_paths(root, strategy_map)

    source_root = output_dir / 'source'
    if output_dir.exists():
        shutil.rmtree(output_dir)
    source_root.mkdir(parents=True, exist_ok=True)

    entries: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    total_bytes = 0
    copied_direct: Dict[str, int] = {strategy: 0 for strategy in strategy_map}

    for source in sorted(selected, key=lambda item: str(item)):
        rel = source.resolve().relative_to(root.resolve())
        if source.suffix.lower() not in ALLOWED_SUFFIXES:
            skipped.append({'path': str(rel), 'reason': 'suffix_not_allowed'})
            continue
        data = source.read_bytes()
        if not data or len(data) > MAX_FILE_BYTES:
            skipped.append({'path': str(rel), 'reason': 'invalid_size', 'size_bytes': len(data)})
            continue
        findings = sensitive_findings(source, data)
        if findings:
            skipped.append({'path': str(rel), 'reason': 'sensitive_literal_detected', 'findings': findings})
            continue
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_BYTES:
            raise RuntimeError(f'SNAPSHOT_TOTAL_BYTES_EXCEEDED:{total_bytes}>{MAX_TOTAL_BYTES}')
        destination = source_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        reasons = sorted(selected[source])
        for reason in reasons:
            if reason.startswith('strategy:'):
                copied_direct[reason.split(':', 1)[1]] = copied_direct.get(reason.split(':', 1)[1], 0) + 1
        entries.append({
            'path': str(rel),
            'sha256': sha256_bytes(data),
            'size_bytes': len(data),
            'reasons': reasons,
        })

    direct_complete = all(copied_direct.get(strategy, 0) == len(paths) and len(paths) > 0 for strategy, paths in strategy_map.items())
    exact_25 = len(strategy_map) == 25
    verdict = 'STRATEGY_SOURCE_SNAPSHOT_READY' if exact_25 and direct_complete else 'STRATEGY_SOURCE_SNAPSHOT_INCOMPLETE'
    result = {
        'schema': 'q4r3_strategy_source_snapshot_v1',
        'status': 'PASS_Q4R3_STRATEGY_SOURCE_SNAPSHOT_PUBLISH',
        'verdict': verdict,
        'action': 'HOLD',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'probe_source': str(probe_path),
        'expected_strategy_count': len(strategy_map),
        'strategy_module_count': sum(len(paths) for paths in strategy_map.values()),
        'published_file_count': len(entries),
        'published_total_bytes': total_bytes,
        'skipped_file_count': len(skipped),
        'direct_strategy_snapshot_complete': direct_complete,
        'strategy_map': strategy_map,
        'copied_direct_counts': copied_direct,
        'missing_strategy_paths': missing,
        'files': entries,
        'skipped': skipped,
        'next_action': 'GITHUB_DIRECT_REVIEW_ALL_25_STRATEGY_SOURCES_AND_DEFINE_CANONICAL_OWNER_MATRIX',
        'safety': {
            'read_only_source': True,
            'raw_trade_rows_published': False,
            'runtime_files_published': False,
            'credentials_published': False,
            'strategy_modified': False,
            'registry_modified': False,
            'paper_live_order_modified': False,
            'persistent_forward_r_watcher_modified': False,
        },
    }
    atomic_json(output_dir / 'manifest.json', result)
    atomic_json(output_dir / 'strategy_map.json', strategy_map)
    atomic_json(output_dir / 'review_queue.json', {
        'verdict': verdict,
        'strategies': [
            {
                'strategy': strategy,
                'module_paths': paths,
                'module_count': len(paths),
                'copied_count': copied_direct.get(strategy, 0),
                'review_required': True,
            }
            for strategy, paths in sorted(strategy_map.items())
        ],
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = publish(args.root, args.probe, args.output_dir)
    print(json.dumps({
        'status': result['status'],
        'verdict': result['verdict'],
        'expected_strategy_count': result['expected_strategy_count'],
        'strategy_module_count': result['strategy_module_count'],
        'published_file_count': result['published_file_count'],
        'published_total_bytes': result['published_total_bytes'],
        'skipped_file_count': result['skipped_file_count'],
        'direct_strategy_snapshot_complete': result['direct_strategy_snapshot_complete'],
        'next_action': result['next_action'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
