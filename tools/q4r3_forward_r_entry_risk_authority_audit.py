from __future__ import annotations

import html
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

ROOT = Path('/home/z/z')
RUNTIME = ROOT / 'runtime'
AUTHORITY_IN = RUNTIME / 'q4r3_forward_r_source_authority_latest.json'
LINEAGE_IN = RUNTIME / 'q4r3_forward_r_writer_lineage_latest.json'
DECISION_IN = RUNTIME / 'q4r3_forward_r_source_lineage_decision_latest.json'

AUDIT_OUT = RUNTIME / 'q4r3_forward_r_entry_risk_authority_latest.json'
DECISION_OUT = RUNTIME / 'q4r3_forward_r_entry_risk_decision_latest.json'
HTML_OUT = RUNTIME / 'q4r3_forward_r_entry_risk_authority_latest.html'

MAX_JSON_BYTES = 120 * 1024 * 1024
MAX_CODE_BYTES = 3 * 1024 * 1024
MAX_DEPTH = 10

IDENTITY_KEYS = ('trade_id', 'position_id', 'event_id', 'request_id', 'order_id', 'client_order_id')
ENTRY_TS_KEYS = ('entry_ts', 'open_ts', 'opened_at', 'signal_ts', 'created_at')
ENTRY_PRICE_KEYS = ('entry_price', 'avg_entry_price', 'open_price', 'fill_price', 'price')
STOP_PRICE_KEYS = ('stop_price', 'stop_loss', 'sl_price', 'sl', 'initial_stop_price')
QTY_KEYS = ('quantity', 'qty', 'position_qty', 'size', 'contracts')
NOTIONAL_KEYS = ('notional_usdt', 'position_notional_usdt', 'exposure_usdt')
RISK_KEYS = ('initial_risk_usdt', 'position_risk_usdt', 'risk_usdt', 'planned_risk_usdt')
STATUS_KEYS = ('status', 'state', 'trade_status', 'position_status')
OPEN_STATUS = {'open', 'active', 'running', 'pending', 'opened', 'new'}

CODE_ROOTS = (ROOT / 'backend', ROOT / 'tools', ROOT / 'services', ROOT / 'scripts', ROOT / 'systemd', Path('/etc/systemd/system'))
CODE_SUFFIXES = {'.py', '.sh', '.service', '.timer'}
DIAGNOSTIC_TOKENS = ('test', 'probe', 'replay', 'audit', 'forensic', 'tournament', 'diagnostic', 'research', 'capture', 'backfill', 'route_a', 'raschke_v', 'snapshot')
WRITER_TERMS = ('write_text', 'json.dump', 'json.dumps', 'open(', 'append', 'replace(', 'os.replace', 'rename(')
IDENTITY_TERMS = IDENTITY_KEYS
ENTRY_TERMS = ENTRY_TS_KEYS + ENTRY_PRICE_KEYS
STOP_TERMS = STOP_PRICE_KEYS
QTY_TERMS = QTY_KEYS + NOTIONAL_KEYS
RISK_TERMS = RISK_KEYS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(errors='ignore'))


def normalize(value: Any) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def first_key(obj: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
    return next((key for key in keys if key in obj and obj[key] not in (None, '')), None)


def is_open_row(obj: Dict[str, Any]) -> bool:
    status_key = first_key(obj, STATUS_KEYS)
    status = normalize(obj.get(status_key)) if status_key else ''
    return status in OPEN_STATUS or obj.get('is_open') is True or obj.get('open') is True


def iter_open_rows(obj: Any, source: str, depth: int = 0) -> Iterator[Dict[str, Any]]:
    if depth > MAX_DEPTH:
        return
    if isinstance(obj, dict):
        if is_open_row(obj):
            identity_key = first_key(obj, IDENTITY_KEYS)
            entry_key = first_key(obj, ENTRY_PRICE_KEYS)
            stop_key = first_key(obj, STOP_PRICE_KEYS)
            qty_key = first_key(obj, QTY_KEYS)
            notional_key = first_key(obj, NOTIONAL_KEYS)
            risk_key = next((key for key in RISK_KEYS if safe_float(obj.get(key)) is not None and float(obj[key]) > 0), None)
            entry = safe_float(obj.get(entry_key)) if entry_key else None
            stop = safe_float(obj.get(stop_key)) if stop_key else None
            qty = safe_float(obj.get(qty_key)) if qty_key else None
            notional = safe_float(obj.get(notional_key)) if notional_key else None
            formula_ready = bool(entry is not None and stop is not None and qty is not None and qty > 0 and abs(entry - stop) > 0)
            yield {
                'source': source,
                'identity_key': identity_key,
                'entry_price_key': entry_key,
                'stop_price_key': stop_key,
                'qty_key': qty_key,
                'notional_key': notional_key,
                'risk_key': risk_key,
                'formula_ready_from_price_stop_qty': formula_ready,
                'explicit_risk_usdt': float(obj[risk_key]) if risk_key else None,
            }
        for value in obj.values():
            yield from iter_open_rows(value, source, depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_open_rows(value, source, depth + 1)


def code_paths() -> List[Path]:
    paths: List[Path] = []
    for root in CODE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if 0 < size <= MAX_CODE_BYTES:
                paths.append(path)
    return sorted(set(paths))


def line_hits(text: str, terms: Iterable[str]) -> List[int]:
    lowered = tuple(term.lower() for term in terms)
    return [index for index, line in enumerate(text.splitlines(), start=1) if any(term in line.lower() for term in lowered)]


def service_references(paths: Sequence[Path]) -> Dict[str, List[str]]:
    refs: Dict[str, List[str]] = defaultdict(list)
    for path in paths:
        if path.suffix not in {'.service', '.timer'}:
            continue
        try:
            text = path.read_text(errors='ignore')
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('ExecStart=') or stripped.startswith('ExecStartPre='):
                for token in re.findall(r'/[A-Za-z0-9_./-]+\.(?:py|sh)', stripped):
                    refs[Path(token).name].append(str(path))
    return refs


def audit() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    authority = load_json(AUTHORITY_IN)
    lineage = load_json(LINEAGE_IN)
    prior_decision = load_json(DECISION_IN)
    authoritative = [item for item in authority.get('authoritative_files', []) if int(item.get('open_rows', 0)) > 0]
    basenames = {Path(item['path']).name for item in authoritative}

    source_rows = []
    all_open_rows: List[Dict[str, Any]] = []
    for item in authoritative:
        path = Path(item['path'])
        record = {'path': str(path), 'exists': path.exists(), 'open_rows_reported': int(item.get('open_rows', 0))}
        if path.exists() and 0 < path.stat().st_size <= MAX_JSON_BYTES:
            try:
                rows = list(iter_open_rows(load_json(path), str(path)))
                all_open_rows.extend(rows)
                record.update({
                    'parsed': True,
                    'open_rows_extracted': len(rows),
                    'identity_ready': sum(1 for row in rows if row['identity_key']),
                    'explicit_risk_ready': sum(1 for row in rows if row['risk_key']),
                    'formula_ready': sum(1 for row in rows if row['formula_ready_from_price_stop_qty']),
                    'entry_price_ready': sum(1 for row in rows if row['entry_price_key']),
                    'stop_price_ready': sum(1 for row in rows if row['stop_price_key']),
                    'qty_ready': sum(1 for row in rows if row['qty_key']),
                })
            except Exception as exc:
                record.update({'parsed': False, 'error': repr(exc)})
        source_rows.append(record)

    paths = code_paths()
    unit_refs = service_references(paths)
    candidates = []
    for path in paths:
        if path.suffix.lower() not in {'.py', '.sh', '.service'}:
            continue
        try:
            text = path.read_text(errors='ignore')
        except OSError:
            continue
        lower_path = str(path).lower()
        diagnostic = any(token in lower_path for token in DIAGNOSTIC_TOKENS)
        source_refs = sorted(name for name in basenames if name in text)
        writer = line_hits(text, WRITER_TERMS)
        identity = line_hits(text, IDENTITY_TERMS)
        entry = line_hits(text, ENTRY_TERMS)
        stop = line_hits(text, STOP_TERMS)
        qty = line_hits(text, QTY_TERMS)
        risk = line_hits(text, RISK_TERMS)
        if not source_refs and not writer:
            continue
        services = sorted(set(unit_refs.get(path.name, [])))
        score = min(len(source_refs), 3) * 10
        score += 5 if writer else 0
        score += 5 if identity else 0
        score += 5 if entry else 0
        score += 6 if stop else 0
        score += 6 if qty else 0
        score += 8 if risk else 0
        score += 6 if services else 0
        score -= 15 if diagnostic else 0
        candidates.append({
            'path': str(path), 'score': score, 'diagnostic_or_replay': diagnostic,
            'authoritative_open_source_refs': source_refs, 'writer_lines': writer[:20],
            'identity_lines': identity[:20], 'entry_lines': entry[:20], 'stop_lines': stop[:20],
            'qty_lines': qty[:20], 'risk_lines': risk[:20], 'service_units': services,
        })
    candidates.sort(key=lambda row: (not row['diagnostic_or_replay'], int(row['score']), len(row['service_units'])), reverse=True)
    production = [row for row in candidates if not row['diagnostic_or_replay'] and row['score'] > 0]
    top = production[0] if production else None
    second_score = int(production[1]['score']) if len(production) > 1 else 0
    dominant = bool(top and int(top['score']) >= 24 and int(top['score']) >= second_score + 5 and (top['authoritative_open_source_refs'] or top['service_units']))

    explicit = sum(1 for row in all_open_rows if row['risk_key'])
    formula = sum(1 for row in all_open_rows if row['formula_ready_from_price_stop_qty'])
    total = len(all_open_rows)
    report = {
        'status': 'PASS_Q4R3_FORWARD_R_ENTRY_RISK_AUTHORITY_AUDIT',
        'prior_verdict': prior_decision.get('verdict'),
        'stable_id_join_rate_pct': lineage.get('runtime', {}).get('stable_id_join_rate_pct'),
        'authoritative_open_source_count': len(authoritative),
        'authoritative_open_row_count': total,
        'explicit_risk_ready_count': explicit,
        'formula_ready_from_price_stop_qty_count': formula,
        'entry_price_ready_count': sum(1 for row in all_open_rows if row['entry_price_key']),
        'stop_price_ready_count': sum(1 for row in all_open_rows if row['stop_price_key']),
        'qty_ready_count': sum(1 for row in all_open_rows if row['qty_key']),
        'source_rows': source_rows,
        'dominant_single_entry_writer': dominant,
        'dominant_entry_writer': top,
        'second_score': second_score,
        'production_candidates': production[:20],
        'excluded_diagnostic_candidates': [row for row in candidates if row['diagnostic_or_replay']][:20],
        'updated_at': utc_now(),
    }

    if explicit > 0:
        verdict = 'ENTRY_RISK_ALREADY_PRESENT_RECHECK_CLOSE_JOIN'
        next_action = 'RERUN_FORWARD_R_LINEAGE_WITH_EXPLICIT_RISK'
    elif formula > 0 and dominant:
        verdict = 'ENTRY_RISK_SINGLE_WRITER_PATCH_READY'
        next_action = 'PATCH_INITIAL_RISK_USDT_AT_DOMINANT_ENTRY_WRITER_CANARY'
    elif formula > 0:
        verdict = 'ENTRY_RISK_FORMULA_READY_WRITER_DISTRIBUTED'
        next_action = 'INSTALL_ENTRY_RISK_APPEND_ONLY_SIDECAR_CANARY'
    elif dominant:
        verdict = 'ENTRY_WRITER_FOUND_BUT_RISK_COMPONENTS_INCOMPLETE'
        next_action = 'PATCH_ENTRY_STOP_QTY_CONTRACT_BEFORE_RISK_CALCULATION'
    else:
        verdict = 'ENTRY_RISK_AUTHORITY_NOT_SINGLETON'
        next_action = 'TRACE_TOP_ENTRY_WRITER_CANDIDATES_BEFORE_ANY_PATCH'

    decision = {
        'status': 'PASS_Q4R3_FORWARD_R_ENTRY_RISK_DECISION',
        'verdict': verdict,
        'action': 'HOLD',
        'next_action': next_action,
        'stable_id_join_rate_pct': report['stable_id_join_rate_pct'],
        'authoritative_open_row_count': total,
        'explicit_risk_ready_count': explicit,
        'formula_ready_from_price_stop_qty_count': formula,
        'dominant_single_entry_writer': dominant,
        'dominant_entry_writer': top,
        'next_modules': [next_action, 'FORWARD_R_ENTRY_RISK_CANARY', 'RERUN_SOURCE_LINEAGE_AFTER_NEW_OPENS'],
        'authority': {
            'order_authority': 'blocked', 'execution_authority': 'none', 'real_order_enabled': False,
            'paper_request_written': False, 'live_execution_allowed': False,
            'production_strategy_modified': False, 'final_holdout_opened': False,
        },
    }
    return report, decision


def write_html(report: Dict[str, Any], decision: Dict[str, Any]) -> None:
    HTML_OUT.write_text(
        '<!doctype html><html><head><meta charset="utf-8"><title>Entry risk authority</title></head><body>'
        '<h1>Forward R entry-risk authority</h1><pre>' + html.escape(json.dumps(report, ensure_ascii=False, indent=2)) +
        '</pre><h2>Decision</h2><pre>' + html.escape(json.dumps(decision, ensure_ascii=False, indent=2)) + '</pre></body></html>',
        encoding='utf-8',
    )


def main() -> None:
    report, decision = audit()
    write_html(report, decision)
    atomic_json(AUDIT_OUT, report)
    atomic_json(DECISION_OUT, decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
