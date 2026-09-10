"""Two frozen F exit compositions; original engines own signals, fills and slots."""
from math import isfinite
from unittest.mock import patch
from backend.research.rebuild import c63_r_b20_v1 as b20

engine = b20.parent.engine
SCOPE = 'C63_INITIAL_FAILURE_F_AFTER_PR1247_V1'
VARIANTS = ('F_ONLY', 'B20_F')
RULES = {v: SCOPE + '_' + v for v in VARIANTS}
EXIT = 'INITIAL_FAILURE_F_CLOSE'


class FailureState:
    def __init__(self):
        self.observations = []

    def step(self, *, held, available_at, close, momentum, ema20, original):
        prior = self.observations
        if type(held) is not int or held != len(prior) + 1:
            raise ValueError('F_NON_SEQUENTIAL_HELD')
        if (type(available_at) is not int or available_at < 0 or
                (prior and available_at != prior[-1]['available_at'] + engine.BAR)):
            raise ValueError('F_OBSERVATION_CLOCK')
        if any(type(x) not in (int, float) or not isfinite(x) for x in (close, momentum)):
            raise ValueError('F_NONFINITE_SOURCE')
        active = 3 <= held <= 19
        if active and (type(ema20) not in (int, float) or not isfinite(ema20)):
            raise ValueError('F_MISSING_NATIVE_EMA20')
        hit = bool(active and prior[-2]['momentum'] > prior[-1]['momentum'] > momentum > 0
                   and close < ema20)
        reason = original if original is not None else EXIT if hit else None
        prior.append(dict(held=held, available_at=available_at, close=close,
            momentum=momentum, ema20=ema20, active=active, predicate=hit,
            parent_reason=original, reason=reason))
        return reason


def position(bars, signal, variant, features, end, original_position):
    if variant != 'M1':
        raise ValueError('F_NATIVE_VARIANT')
    ei = signal['signal_index'] + 1
    ema = engine.f._average([b.close for b in bars], 20, 2 / 21)
    state = FailureState()
    original_exit = engine.exit_reason

    def reason(v, close, floor, target, momentum, held):
        j = ei + held - 1
        if v != 'M1' or close != bars[j].close or momentum != features[j]['momentum']:
            raise ValueError('F_OBSERVATION_BINDING')
        stamp = bars[j].open_ts + engine.BAR
        if features[j].get('available_at', stamp) != stamp:
            raise ValueError('F_FEATURE_TIMESTAMP_MISMATCH')
        parent_reason = original_exit(v, close, floor, target, momentum, held)
        return state.step(held=held, available_at=stamp, close=close,
            momentum=momentum, ema20=ema[j], original=parent_reason)

    with patch.object(engine, 'exit_reason', reason):
        trade, opened, trace = original_position(bars, signal, variant, features, end)
    obj = trade if trade is not None else opened
    obj['f_context'] = dict(observations=state.observations,
        actual_extended_held_bars=sum(x['held'] >= 21 for x in state.observations),
        next_open_fill=trade is not None, full_position_exit=True)
    return trade, opened, trace


def replay(rows, *, eval_start_ms, eval_end_ms, variant, enabled=True):
    if variant not in VARIANTS or type(enabled) is not bool:
        raise ValueError('F_VARIANT_OR_ENABLE')
    parent = b20.parent.c63 if variant == 'F_ONLY' else b20
    kwargs = dict(eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
    if not enabled:
        return parent.replay(rows, **kwargs)
    native_position = engine._position
    def wrapped(bars, signal, v, features, end):
        return position(bars, signal, v, features, end, native_position)
    # B20's runner_position wraps this hook. Its original reason is evaluated
    # first inside F; native next-open fills and FULL occupancy remain owners.
    with patch.object(engine, '_position', wrapped):
        result = parent.replay(rows, **kwargs)
    result['audit'].update(rule=RULES[variant], variant=variant,
        initial_failure_F=True, parent_exit_priority_preserved=True,
        no_new_signal_generator=True, sizing_cost_model_unchanged=True,
        formal_credit=0, independent=False)
    return result
