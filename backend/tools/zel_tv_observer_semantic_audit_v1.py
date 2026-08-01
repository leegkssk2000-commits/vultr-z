from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE = Path('/usr/local/bin/z_tv_observer_w221b.py')
UNIT = Path('/etc/systemd/system/z-tv-observer-w221b.service')

SENSITIVE = re.compile(r'(token|secret|key|password|authorization|signature)', re.I)


def safe_string(value: str) -> str:
    if SENSITIVE.search(value) and len(value) > 24:
        return '[REDACTED_SENSITIVE_LITERAL]'
    return value[:500]


def extract_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    strings = []
    calls = []
    comparisons = []
    writes = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            strings.append({'line': getattr(child, 'lineno', None), 'value': safe_string(child.value)})
        elif isinstance(child, ast.Call):
            name = None
            if isinstance(child.func, ast.Name): name = child.func.id
            elif isinstance(child.func, ast.Attribute): name = child.func.attr
            if name:
                calls.append({'line': getattr(child, 'lineno', None), 'name': name})
                if name in {'write_text', 'write_bytes', 'open', 'replace', 'rename', 'unlink'}:
                    writes.append({'line': getattr(child, 'lineno', None), 'name': name})
        elif isinstance(child, ast.Compare):
            try:
                comparisons.append({'line': child.lineno, 'expr': ast.unparse(child)[:500]})
            except Exception:
                pass
    return {
        'name': node.name,
        'line': node.lineno,
        'strings': strings[:200],
        'calls': calls[:200],
        'comparisons': comparisons[:100],
        'writes': writes[:100],
    }


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit('SOURCE_MISSING')
    text = SOURCE.read_text(errors='ignore')
    tree = ast.parse(text)
    functions = []
    classes = []
    imports = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            try: imports.append(ast.unparse(node))
            except Exception: pass
        elif isinstance(node, ast.ClassDef):
            method_names = [x.name for x in node.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes.append({'name': node.name, 'line': node.lineno, 'methods': method_names})
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(extract_function(child))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(extract_function(node))
    handler_methods = [f for f in functions if f['name'] in {'do_GET', 'do_POST', 'do_PUT', 'do_DELETE', 'do_OPTIONS', 'handle', 'serve'}]
    literals = [safe_string(x.value) for x in ast.walk(tree) if isinstance(x, ast.Constant) and isinstance(x.value, str)]
    observer_role = 'UNKNOWN'
    if any(f['name'] == 'do_POST' for f in functions) and any(token in ' '.join(literals).lower() for token in ('webhook', 'event', 'signal')):
        observer_role = 'WEBHOOK_SIGNAL_INGESTION'
    if any(token in ' '.join(literals).lower() for token in ('candles', 'ohlcv', 'chart data', 'bars')):
        observer_role = 'CHART_DATA_API' if observer_role == 'UNKNOWN' else 'MIXED'
    result = {
        'schema_version': 'zel.tv_observer.semantic.audit.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'state': 'PASS_READ_ONLY_TV_OBSERVER_SEMANTIC_AUDIT',
        'source': str(SOURCE),
        'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'source_bytes': SOURCE.stat().st_size,
        'unit': {'path': str(UNIT), 'exists': UNIT.exists(), 'content': UNIT.read_text(errors='ignore')[:5000] if UNIT.exists() else None},
        'imports': imports,
        'classes': classes,
        'handler_methods': handler_methods,
        'semantic_role': observer_role,
        'capabilities': {
            'has_get': any(f['name'] == 'do_GET' for f in functions),
            'has_post': any(f['name'] == 'do_POST' for f in functions),
            'has_put': any(f['name'] == 'do_PUT' for f in functions),
            'has_delete': any(f['name'] == 'do_DELETE' for f in functions),
            'mentions_chart_library': any(x in text.lower() for x in ('tradingview.widget', 'lightweight-charts', 'createchart', 'addcandlestickseries')),
            'mentions_ohlcv': any(x in text.lower() for x in ('ohlcv', 'candles', 'kline', 'bars')),
            'mentions_event': 'event' in text.lower(),
            'mentions_signal': 'signal' in text.lower(),
            'writes_files': any(f['writes'] for f in functions),
        },
        'conclusion': {
            'safe_to_use_as_chart_data_source': observer_role in {'CHART_DATA_API', 'MIXED'},
            'safe_to_use_as_webhook_ingress': observer_role in {'WEBHOOK_SIGNAL_INGESTION', 'MIXED'},
            'ui_chart_restoration_requires_separate_frontend_chart_source': observer_role == 'WEBHOOK_SIGNAL_INGESTION',
        },
        'safety': {
            'read_only': True, 'source_mutated': False, 'service_mutated': False,
            'frontend_mutated': False, 'runtime_mutated': False,
            'execution_authority': 'NONE', 'order_authority': 'BLOCKED', 'action': 'hold'
        }
    }
    Path('/tmp/zel_tv_observer_semantic_audit_v1.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': result['state'], 'semantic_role': observer_role, 'capabilities': result['capabilities'], 'conclusion': result['conclusion']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
