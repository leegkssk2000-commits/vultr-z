from __future__ import annotations

from typing import Any


def fast_supertrend_state(module: Any, bars: Any, cfg: Any) -> tuple[float, int]:
    module.validate_bars(bars, minimum=max(cfg.supertrend_len + 3, 20))
    highs = [module.f(b, "high") for b in bars]
    lows = [module.f(b, "low") for b in bars]
    closes = [module.f(b, "close") for b in bars]
    trs: list[float] = []
    prev_close_for_tr: float | None = None
    for high, low, close in zip(highs, lows, closes):
        tr = (
            high - low
            if prev_close_for_tr is None
            else max(
                high - low, abs(high - prev_close_for_tr), abs(low - prev_close_for_tr)
            )
        )
        trs.append(tr)
        prev_close_for_tr = close

    line = (highs[0] + lows[0]) / 2.0
    direction = 1
    final_upper = line
    final_lower = line
    prev_line = line
    prev_close = closes[0]
    length = int(cfg.supertrend_len)
    prefix_sum = trs[0]
    atr_current: float | None = None

    for i in range(1, len(bars)):
        prefix_sum += trs[i]
        if i + 1 < length:
            a = prefix_sum / float(i + 1)
        elif i + 1 == length:
            atr_current = prefix_sum / float(length)
            a = atr_current
        else:
            if atr_current is None:
                atr_current = sum(trs[:length]) / float(length)
            atr_current = ((length - 1) * atr_current + trs[i]) / float(length)
            a = atr_current

        hl2 = (highs[i] + lows[i]) / 2.0
        upper = hl2 + cfg.supertrend_mult * a
        lower = hl2 - cfg.supertrend_mult * a
        final_upper = (
            upper if upper < final_upper or prev_close > final_upper else final_upper
        )
        final_lower = (
            lower if lower > final_lower or prev_close < final_lower else final_lower
        )
        if prev_line == final_upper:
            if closes[i] <= final_upper:
                line, direction = final_upper, -1
            else:
                line, direction = final_lower, 1
        else:
            if closes[i] >= final_lower:
                line, direction = final_lower, 1
            else:
                line, direction = final_upper, -1
        prev_line, prev_close = line, closes[i]
    return float(line), int(direction)


def install(module: Any) -> bool:
    original = getattr(module, "_supertrend_state", None)
    if not callable(original):
        return False

    def accelerated(bars: Any, cfg: Any) -> tuple[float, int]:
        return fast_supertrend_state(module, bars, cfg)

    module._supertrend_state = accelerated
    return True
