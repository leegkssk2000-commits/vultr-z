"""One R extension repair. No I/O, allocator, orders or alternative evaluator.

The native R lifecycle supplies every original decision and next-open fill.
Only a surviving extended held20 close becomes a fixed protection anchor.
"""
from math import isfinite
from unittest.mock import patch
from backend.research.rebuild import c63_transplant_v1 as parent

RULE_ID = 'C63_R_B20_PROTECTION_AFTER_PR1245_V1'
EXIT = 'RUNNER_B20_LOSS_CLOSE'


class RunnerState(parent.RunnerState):
    def __init__(self, entry):
        super().__init__(entry)
        self.b20 = None
        self.b20_available_at = None
        self.last_available_at = None

    def step(self, *, close, floor, momentum, held, ema20, ema50, available_at):
        if (type(available_at) is not int or available_at < 0 or
                (self.last_available_at is not None and available_at <= self.last_available_at)):
            raise ValueError('INVALID_OBSERVATION_CLOCK')
        if any(not isinstance(x, (int, float)) or not isfinite(x)
               for x in (close, floor, momentum)):
            raise ValueError('INVALID_B20_SOURCE')
        original = super().step(close=close, floor=floor, momentum=momentum,
            held=held, ema20=ema20, ema50=ema50, available_at=available_at)
        self.last_available_at = available_at
        reason = original
        if original is None and self.extended:
            if held == 20:
                if self.b20 is not None:
                    raise ValueError('B20_ALREADY_FIXED')
                self.b20, self.b20_available_at = close, available_at
            elif held >= 21:
                if self.b20 is None or self.b20_available_at >= available_at:
                    raise ValueError('MISSING_OR_FUTURE_B20')
                if close < self.b20:
                    reason = EXIT
        self.witnesses[-1].update(original_R_reason=original, reason=reason,
            b20=self.b20, b20_available_at=self.b20_available_at,
            b20_triggered=reason == EXIT)
        return reason


def replay(rows, *, eval_start_ms, eval_end_ms, enabled=True, runner_enabled=True):
    if type(enabled) is not bool or type(runner_enabled) is not bool:
        raise ValueError('INVALID_ENABLE_FLAG')
    kwargs = dict(eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms,
                  variant='R', enabled=runner_enabled)
    if not enabled or not runner_enabled:
        return parent.replay(rows, **kwargs)
    with patch.object(parent, 'RunnerState', RunnerState):
        result = parent.replay(rows, **kwargs)
    result['audit'].update(rule=RULE_ID, direct_parent=parent.RULES['R'],
        comparison_baseline='C63', b20_protection=True,
        earliest_b20_trigger_held=21, fixed_anchor_held=20,
        original_exit_priority_preserved=True, same_bar_anchor_trigger=False,
        source='INTERNAL_ZEL_REPAIR_NOT_EXTERNAL_TRADER_REPLICATION')
    return result
