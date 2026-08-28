#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_keltner_58pct_add_only_continuation_v1 as base
from backend.research.rebuild.a1_top5_additive_entry_union_v1 import evaluate

ROOT = Path(__file__).resolve().parents[3]
BOUNDARY = ROOT / 'backend/research/rebuild/a1_keltner_non_eu_future_boundary_v1.json'
ATTRIBUTION = ROOT / 'backend/research/rebuild/a1_keltner_loss_preentry_attribution_latest.json'
SCHEMA = 'zel.a1.keltner.non_eu_future.v1'
BOUNDARY_SCHEMA = 'zel.a1.keltner.non_eu_future_boundary.v1'
STRATEGY = 'keltner_trend'
FRESH_TARGET = 25
EU_HOURS = tuple(range(8, 16))


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise RuntimeError(f'OBJECT_REQUIRED:{path}')
    return value


def validate_attribution() -> dict[str, Any]:
    a = read(ATTRIBUTION)
    root = a.get('actionable_root_cause') or {}
    if a.get('strategy_id') != STRATEGY or a.get('state') != 'MATERIAL_PREENTRY_SEPARATOR_FOUND':
        raise RuntimeError('KELTNER_NON_EU_ATTRIBUTION_STATE_INVALID')
    if int(a.get('leakage_lookahead') or 0) != 0 or a.get('numeric_threshold_sweep') is not False:
        raise RuntimeError('KELTNER_NON_EU_ATTRIBUTION_INTEGRITY_INVALID')
    if root.get('axis') != 'SESSION' or root.get('value') != 'EU' or root.get('preentry_observable') is not True:
        raise RuntimeError('KELTNER_NON_EU_SESSION_ROOT_NOT_PROVEN')
    if float(root.get('loss_streak_share') or 0.0) < 0.8 or float(root.get('delta_share') or 0.0) <= 0.0:
        raise RuntimeError('KELTNER_NON_EU_SESSION_ROOT_TOO_WEAK')
    return a


def semantic_key(trade: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return str(trade['symbol']), int(trade['signal_ts']), int(trade['entry_ts']), str(trade['side'])


def row_key(row: Any) -> tuple[str, int, int, str]:
    if not isinstance(row, list) or len(row) != 4:
        raise RuntimeError('KELTNER_NON_EU_BOUNDARY_KEY_INVALID')
    return str(row[0]), int(row[1]), int(row[2]), str(row[3])


def validate_current(current: Mapping[str, Any]) -> list[dict[str, Any]]:
    if current.get('strategy_id') != STRATEGY:
        raise RuntimeError('KELTNER_NON_EU_CURRENT_STRATEGY_MISMATCH')
    trades = [dict(x) for x in current.get('trades') or []]
    if len(trades) != int(current.get('completed_trades') or -1):
        raise RuntimeError('KELTNER_NON_EU_CURRENT_COUNT_MISMATCH')
    keys = [semantic_key(x) for x in trades]
    if len(keys) != len(set(keys)):
        raise RuntimeError('KELTNER_NON_EU_CURRENT_DUPLICATE_KEY')
    return trades


def freeze(current: Mapping[str, Any]) -> dict[str, Any]:
    attribution = validate_attribution()
    trades = validate_current(current)
    keys = sorted((list(semantic_key(x)) for x in trades), key=str)
    result = {
        'schema_version': BOUNDARY_SCHEMA,
        'state': 'FROZEN_KELTNER_NON_EU_FUTURE_BOUNDARY',
        'strategy_id': STRATEGY,
        'frozen_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'current_parent_T': len(trades),
        'current_parent_receipt_sha256': current.get('receipt_sha256'),
        'semantic_trade_keys': keys,
        'semantic_trade_keys_sha256': stable(keys),
        'root_cause_source_path': str(ATTRIBUTION.relative_to(ROOT)),
        'root_cause_receipt_sha256': attribution.get('receipt_sha256'),
        'root_cause': attribution.get('actionable_root_cause'),
        'predicate': {'field': 'session_utc', 'op': 'not_eq', 'value': 'EU'},
        'eu_definition_utc_hours': list(EU_HOURS),
        'old_history_union': False,
        'retroactive_use_of_pre_boundary_trades_for_pass': False,
        'numeric_threshold_sweep': False,
        'selection_authority': False,
        'promotion_authority': False,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'live_trade_authority': 'BLOCKED',
        'action': 'hold',
    }
    result['receipt_sha256'] = stable(result)
    return result


def validate_boundary(boundary: Mapping[str, Any]) -> set[tuple[str, int, int, str]]:
    if boundary.get('schema_version') != BOUNDARY_SCHEMA or boundary.get('state') != 'FROZEN_KELTNER_NON_EU_FUTURE_BOUNDARY':
        raise RuntimeError('KELTNER_NON_EU_BOUNDARY_SCHEMA_INVALID')
    supplied = str(boundary.get('receipt_sha256') or '')
    core = dict(boundary); core.pop('receipt_sha256', None)
    if supplied != stable(core):
        raise RuntimeError('KELTNER_NON_EU_BOUNDARY_RECEIPT_MISMATCH')
    keys = {row_key(x) for x in boundary.get('semantic_trade_keys') or []}
    if len(keys) != int(boundary.get('current_parent_T') or -1):
        raise RuntimeError('KELTNER_NON_EU_BOUNDARY_COUNT_MISMATCH')
    if stable(sorted((list(x) for x in keys), key=str)) != str(boundary.get('semantic_trade_keys_sha256') or ''):
        raise RuntimeError('KELTNER_NON_EU_BOUNDARY_KEYS_SHA_MISMATCH')
    return keys


def is_non_eu(trade: Mapping[str, Any]) -> bool:
    hour = datetime.fromtimestamp(int(trade['signal_ts']) / 1000.0, tz=timezone.utc).hour
    return hour not in EU_HOURS


def payoff(trades: list[Mapping[str, Any]]) -> float | None:
    vals = [float(x['net_bps']) for x in trades]
    wins = [x for x in vals if x > 0.0]; losses = [-x for x in vals if x < 0.0]
    if not wins or not losses: return None
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def run(current: Mapping[str, Any], boundary: Mapping[str, Any]) -> dict[str, Any]:
    attribution = validate_attribution()
    base.validate_incumbent(base.read(base.INCUMBENT))
    incumbent = base.materialize_incumbent(base.read(base.INCUMBENT), base.read(base.BASE_PARENT))
    trades = validate_current(current)
    baseline = validate_boundary(boundary)
    current_by = {semantic_key(x): x for x in trades}
    if not baseline.issubset(set(current_by)):
        raise RuntimeError(f'KELTNER_NON_EU_BOUNDARY_KEYS_MISSING:{len(baseline-set(current_by))}')

    fresh_all = [current_by[k] for k in sorted(set(current_by)-baseline, key=str)]
    fresh_accepted = [x for x in fresh_all if is_non_eu(x)]
    fresh_rejected = [x for x in fresh_all if not is_non_eu(x)]
    additive = evaluate(incumbent, {'strategy_id': STRATEGY, 'trades': fresh_accepted})
    incumbent_trades = [dict(x) for x in incumbent.get('trades') or []]
    combined = incumbent_trades + fresh_accepted
    parent_payoff = payoff(incumbent_trades); combined_payoff = payoff(combined)
    payoff_non_decrease = parent_payoff is None or (combined_payoff is not None and combined_payoff >= parent_payoff)
    strict_economic_pass = additive['state'] == 'PASS_ADD_ONLY_ENTRY_LANE' and payoff_non_decrease
    mature = len(fresh_accepted) >= FRESH_TARGET

    blockers: list[str] = []
    if not fresh_accepted: blockers.append('NO_FUTURE_NON_EU_T')
    if fresh_accepted and additive['state'] != 'PASS_ADD_ONLY_ENTRY_LANE': blockers.extend(additive.get('failed_checks') or ['ADD_ONLY_ECONOMIC_GATE'])
    if fresh_accepted and not payoff_non_decrease: blockers.append('PAYOFF_DECREASE')
    if not mature: blockers.append(f'FRESH_ACCEPTED_LT_{FRESH_TARGET}')

    if strict_economic_pass and mature: state = 'PASS_KELTNER_NON_EU_FRESH25_DEVELOPMENT_READY'
    elif strict_economic_pass: state = 'COLLECT_KELTNER_NON_EU_ECONOMIC_PASS'
    elif not fresh_accepted: state = 'WAIT_KELTNER_NON_EU_FUTURE_SAMPLE'
    else: state = 'HOLD_KELTNER_NON_EU_FUTURE_ECONOMIC'

    result = {
        'schema_version': SCHEMA,
        'state': state,
        'strategy_id': STRATEGY,
        'changed_axis': 'PREENTRY_SESSION_NON_EU_ONLY',
        'predicate': {'field': 'signal_hour_utc', 'op': 'not_in', 'value': list(EU_HOURS)},
        'root_cause_receipt_sha256': attribution.get('receipt_sha256'),
        'root_cause': attribution.get('actionable_root_cause'),
        'boundary_receipt_sha256': boundary.get('receipt_sha256'),
        'boundary_parent_T': boundary.get('current_parent_T'),
        'current_parent_T': len(trades),
        'fresh_all_T': len(fresh_all),
        'fresh_accepted_T': len(fresh_accepted),
        'fresh_rejected_eu_T': len(fresh_rejected),
        'fresh_target_T': FRESH_TARGET,
        'fresh_sample_ready': mature,
        'strict_economic_pass': strict_economic_pass,
        'payoff': {'parent': parent_payoff, 'combined': combined_payoff, 'non_decrease': payoff_non_decrease},
        'additive_receipt': additive,
        'promotion_blockers': sorted(set(blockers)),
        'policy': {
            'separate_from_existing_us_open_child': True,
            'retroactive_pre_boundary_pass_evidence_forbidden': True,
            'append_only_new_trades': True,
            'parent_trade_delete_forbidden': True,
            'parent_trade_rewrite_forbidden': True,
            'numeric_threshold_sweep': False,
            'post_outcome_trade_deletion': False,
            'wr_pnl_expectancy_pf_payoff_non_decrease_required': True,
            'dd_non_increase_required': True,
            'fresh25_required_before_development_ready': True,
        },
        'production_mutated': False,
        'selection_authority': False,
        'promotion_authority': False,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'live_trade_authority': 'BLOCKED',
        'exchange_order_submitted': False,
        'protected_mutations': 0,
        'action': 'hold',
    }
    result['receipt_sha256'] = stable(result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--current-parent', type=Path)
    ap.add_argument('--boundary', type=Path, default=BOUNDARY)
    ap.add_argument('--freeze-current', action='store_true')
    ap.add_argument('--out', type=Path, default=Path('out/a1_keltner_non_eu_future_v1.json'))
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        a = validate_attribution()
        assert (a.get('actionable_root_cause') or {}).get('value') == 'EU'
        assert all(h in EU_HOURS for h in range(8,16)) and 7 not in EU_HOURS and 16 not in EU_HOURS
        print('PASS_A1_KELTNER_NON_EU_FUTURE_V1_SELF_TEST'); return 0
    if args.current_parent is None: raise RuntimeError('--current-parent required')
    current = read(args.current_parent)
    result = freeze(current) if args.freeze_current else run(current, read(args.boundary))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({k:result.get(k) for k in ('state','current_parent_T','boundary_parent_T','fresh_all_T','fresh_accepted_T','strict_economic_pass','promotion_blockers','receipt_sha256')}, sort_keys=True))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
