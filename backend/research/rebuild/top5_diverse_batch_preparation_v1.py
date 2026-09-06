"""Two distinct proposed adapters. Economic execution remains unallocated.

This preparation does not reset any existing trial budget and has no data-loader
or operating import. Tests use generated bars only; no new DEV result is claimed.
"""
from __future__ import annotations
import argparse
import copy
from backend.research.rebuild import top5_development_repair_v1 as old

PROPOSAL = 'backend/research/contracts/top5_diverse_batch_pending_v1.json'
KELTNER = 'keltner_trend_main'
SUPERTREND = 'supertrend_pullback_main'
KELTNER_PARENT = "ema20 > ema50 and lag('close',1) <= lag('ema20',1) and close > ema20"
KELTNER_REMOVAL = "lag('close',1) <= lag('ema20',1) and close > ema20"


def candidate_spec(parent):
    """Return one exact semantic change; never mutate the sealed parent."""
    child = copy.deepcopy(parent)
    lane = child['lane_id']
    spec = child['executable_spec']
    if lane == KELTNER:
        if spec['entry_rule'] != KELTNER_PARENT:
            raise RuntimeError('FROZEN_PARENT_RULE_CHANGED')
        spec['entry_rule'] = KELTNER_REMOVAL
        delay = 0
    elif lane == SUPERTREND:
        # Existing evaluator already supports an explicit whole-bar entry delay.
        delay = 1
    else:
        raise RuntimeError('LANE_NOT_PROPOSED')
    return child, delay


def causal_signals(rows, spec):
    converted = [dict(r, ts=r['bar_open_ts']) for r in rows]
    _, engine = old.dsl._features(converted, spec)
    return [i for i in range(239, len(rows)) if bool(engine.eval(spec['entry_rule'], i))]


def replay_prepared_rows(rows, parent, *, candidate=False, selected_signals=None):
    """Arithmetic adapter shared by eventual DEV runner and synthetic unit tests.

    No costs, performance gate, dataset acquisition, trial allocation or output
    persistence occurs here. An actual DEV runner must first obtain allocation.
    selected_signals supports source-signal-matched timing comparisons; it never
    selects signals using child outcomes.
    """
    spec, delay = candidate_spec(parent) if candidate else (copy.deepcopy(parent), 0)
    cfg = spec['executable_spec']
    signals = causal_signals(rows, cfg) if selected_signals is None else list(selected_signals)
    return old.common.evaluate_development_events(
        rows, signals, split_start_ms=rows[0]['bar_open_ts'],
        split_end_ms=rows[-1]['bar_close_ts'], interval_ms=14_400_000,
        hold_bars=cfg['max_hold_bars'], entry_delay_bars=delay, side='long')


def require_existing_allocation():
    # No caller-provided budget, alternate experiment name or CLI override.
    proposal = old.read(PROPOSAL)
    if proposal['status'] != 'DRAFT_UNALLOCATED' or proposal['allocated_new_trials'] != 0:
        raise RuntimeError('UNREVIEWED_PROPOSAL_OR_ALLOCATION_CHANGE')
    raise RuntimeError('NEW_TRIAL_ALLOCATION_NOT_ESTABLISHED; EXISTING_18_APPLICATIONS_PRESERVED')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check-allocation',action='store_true',required=True)
    p.parse_args()
    require_existing_allocation()
