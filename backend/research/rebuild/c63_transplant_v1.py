"""C63 source-mechanism transplants, research only; no orders or I/O.

G: completed daily21 gate ONLY for non-escape ER admissions. All original
strict range escapes keep C63 eligibility. R: transplant KR1's one-time,
profitable EMA20/50 trend extension to C63's native 20-bar clock. GR combines
these frozen components. Neither symbol, year, final PnL nor a trade ID is a
feature. Old M1 fixed floor and nonpositive momentum retain first priority.
"""
from copy import deepcopy
from contextlib import ExitStack
from math import isfinite
from unittest.mock import patch
from backend.research.rebuild import c63_daily_ema21_entry_v1 as daily

c63 = daily.parent
engine = c63.er.parent
VARIANTS = ('G', 'R', 'GR')
RULES = {v: 'C63_TRANSPLANT_' + v + '_AFTER_PR1244_V1' for v in VARIANTS}
VETO = 'NON_ESCAPE_WITHOUT_COMPLETED_DAILY21_SUPPORT'


def gate(original, daily_obs):
    """C63's structural escape overrides this NEW direction filter, not safety."""
    out = deepcopy(original)
    escape = original['range_context']['strict_escape']
    eligible = bool(original['eligible'] and (escape or daily_obs['eligible']))
    reason = original['reason'] if not original['eligible'] else (
        None if eligible else daily.MISSING if daily_obs['value'] is None else VETO)
    out.update(c63_eligible=original['eligible'], c63_reason=original['reason'],
               eligible=eligible, reason=reason, daily_context=deepcopy(daily_obs),
               transplant_gate=dict(strict_escape_preserved=bool(escape and original['eligible']),
                   filter_applies=bool(original['eligible'] and not escape),
                   available_at=daily_obs['available_at']))
    return out


class RunnerState:
    """One causal decision at held=19, maximum held=40; never resets the clock."""
    def __init__(self, entry):
        if not isfinite(entry) or entry <= 0:
            raise ValueError('INVALID_ENTRY')
        self.entry = entry
        self.decided = False
        self.extended = False
        self.last_held = 0
        self.witnesses = []

    def step(self, *, close, floor, momentum, held, ema20, ema50, available_at):
        if type(held) is not int or held != self.last_held + 1:
            raise ValueError('NON_SEQUENTIAL_HOLD_CLOCK')
        self.last_held = held
        if any(not isfinite(x) for x in (close, floor, momentum)):
            raise ValueError('INVALID_RUNNER_SOURCE')
        protected = engine.exit_reason('M1', close, floor, None, momentum, 0)
        if protected is not None:
            reason = protected
        else:
            if held == 19:
                self.decided = True
                self.extended = bool(ema20 is not None and ema50 is not None
                    and isfinite(ema20) and isfinite(ema50)
                    and close > self.entry and close > ema20 > ema50)
            if held >= 40:
                reason = 'RUNNER_MAX_TIME_CLOSE'
            elif held >= 20 and not self.extended:
                reason = 'FIXED_TIME_CLOSE'
            elif held >= 20 and (ema20 is None or not isfinite(ema20) or close <= ema20):
                reason = 'RUNNER_EMA20_LOSS_CLOSE'
            else:
                reason = None
        self.witnesses.append(dict(held=held, available_at=available_at,
            close=close, ema20=ema20, ema50=ema50, decision_at_19=self.decided,
            extended=self.extended, reason=reason))
        return reason


def runner_position(bars, signal, variant, features, end, original_position):
    if variant != 'M1':
        return original_position(bars, signal, variant, features, end)
    ei = signal['signal_index'] + 1
    closes = [b.close for b in bars]
    ema20 = engine.f._average(closes, 20, 2 / 21)
    ema50 = engine.f._average(closes, 50, 2 / 51)
    state = RunnerState(bars[ei].open)
    original_exit = engine.exit_reason

    def reason(v, close, floor, target, momentum, held):
        if v != 'M1':
            return original_exit(v, close, floor, target, momentum, held)
        j = ei + held - 1
        with patch.object(engine, 'exit_reason', original_exit):
            return state.step(close=close, floor=floor, momentum=momentum,
                held=held, ema20=ema20[j], ema50=ema50[j],
                available_at=bars[j].open_ts + engine.BAR)

    with patch.object(engine, 'exit_reason', reason):
        trade, opened, trace = original_position(bars, signal, variant, features, end)
    obj = trade if trade is not None else opened
    obj['runner_context'] = dict(decision_made=state.decided, extended=state.extended,
        original_hold_cap=20, extension_cap=20, max_total_hold=40,
        clock_reset=False, observations=state.witnesses)
    return trade, opened, trace


def replay(rows, *, eval_start_ms, eval_end_ms, variant, enabled=True):
    if variant not in VARIANTS or type(enabled) is not bool:
        raise ValueError('INVALID_TRANSPLANT_VARIANT')
    if not enabled:
        return c63.replay(rows, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
    original_context = c63.context
    original_position = engine._position
    with ExitStack() as stack:
        if variant in ('G', 'GR'):
            def context(bars, signal, er_context):
                return gate(original_context(bars, signal, er_context),
                            daily.observation(bars, signal['signal_index']))
            stack.enter_context(patch.object(c63, 'context', context))
        if variant in ('R', 'GR'):
            def position(bars, signal, v, features, end):
                return runner_position(bars, signal, v, features, end, original_position)
            stack.enter_context(patch.object(engine, '_position', position))
        result = c63.replay(rows, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
    result['audit'].update(rule=RULES[variant], direct_parent=c63.RULE_ID,
        variant=variant, original_exit_unchanged=variant == 'G',
        original_M1_exits_unchanged=variant == 'G',
        gate_transplant=variant in ('G', 'GR'), runner_transplant=variant in ('R', 'GR'),
        strategy_source='ZEL_RECOMBINATION_NOT_TRADER_ORIGINAL',
        comparison_mode='FULL_CHRONOLOGICAL', no_new_signal_generator=True,
        sizing_cost_model_unchanged=True, same_symbol_max_positions=1,
        formal_credit=0, independent=False)
    return result
