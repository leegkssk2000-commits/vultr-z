"""HGL1: frozen, long-only ZEL interpretation; synthetic/reference execution only.

This is not Raschke's complete discretionary method. No I/O, exchange client,
network, portfolio accounting, parameter search, or automatic execution lives here.
The caller must enforce the input/provenance contract before calling ``run``.
"""
from math import isfinite


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("nonfinite/non-numeric " + label)
    return float(value)


def _validate(bars, tick=None):
    if tick is not None and _number(tick, "tick") <= 0:
        raise ValueError("tick must be positive")
    for i, bar in enumerate(bars):
        values = {k: _number(bar[k], k) for k in ("open", "high", "low", "close")}
        if min(values.values()) <= 0 or not (
            values["low"] <= min(values["open"], values["close"])
            <= max(values["open"], values["close"]) <= values["high"]
        ):
            raise ValueError("invalid OHLC at " + str(i))
        if ("timestamp_ms" in bar) != ("available_at_ms" in bar):
            raise ValueError("timestamp and availability must be supplied together")
        if "timestamp_ms" in bar:
            if type(bar["timestamp_ms"]) is not int or type(bar["available_at_ms"]) is not int:
                raise ValueError("timestamps must be integer milliseconds")
            if bar["available_at_ms"] < bar["timestamp_ms"] + 3600000:
                raise ValueError("availability precedes hourly completion")
            if i and bars[i-1].get("timestamp_ms", -1) >= bar["timestamp_ms"]:
                raise ValueError("non-increasing bar time")
            if i and bars[i-1].get("available_at_ms", -1) > bar["available_at_ms"]:
                raise ValueError("out-of-order availability would expose unavailable prefix inputs")
    if bars and any(("timestamp_ms" in x) != ("timestamp_ms" in bars[0]) for x in bars):
        raise ValueError("mixed timestamp modes")


def indicators(bars):
    """SMA-seeded EMA20 and explicitly seeded Wilder ADX14; no future rows."""
    _validate(bars)
    n = len(bars)
    ema = [None] * n
    adx = [None] * n
    if n >= 20:
        ema[19] = sum(float(x["close"]) for x in bars[:20]) / 20.0
        for i in range(20, n):
            ema[i] = ema[i-1] + (2.0 / 21.0) * (float(bars[i]["close"]) - ema[i-1])
    if n <= 14:
        return {"ema20": ema, "adx14": adx}
    tr, plus, minus = [], [], []
    for i in range(1, n):
        b, p = bars[i], bars[i-1]
        up, down = b["high"] - p["high"], p["low"] - b["low"]
        tr.append(max(b["high"]-b["low"], abs(b["high"]-p["close"]), abs(b["low"]-p["close"])))
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
    st, sp, sm = sum(tr[:14]), sum(plus[:14]), sum(minus[:14])
    dx = []
    for i in range(14, n):
        if i > 14:
            st, sp, sm = st-st/14+tr[i-1], sp-sp/14+plus[i-1], sm-sm/14+minus[i-1]
        pdi, mdi = ((100*sp/st, 100*sm/st) if st else (0.0, 0.0))
        value = 100 * abs(pdi-mdi) / (pdi+mdi) if pdi+mdi else 0.0
        dx.append(value)
        if i == 27:
            adx[i] = sum(dx) / 14.0
        elif i > 27:
            adx[i] = (13*adx[i-1] + value) / 14.0
    return {"ema20": ema, "adx14": adx}


def costs(gross_bp):
    """One frozen modeled roundtrip deduction; neither actual fees nor NAV."""
    gross_bp = _number(gross_bp, "gross_bp")
    return {"gross_bp": gross_bp, "net1_bp": gross_bp - 20.0, "net2_bp": gross_bp - 40.0}


def run(bars, tick):
    """Production entry: native indicators and immutable 240-bar warmup."""
    ind = indicators(bars)
    return _run(bars, tick, ind["ema20"], ind["adx14"], 240)


def fixture_run(bars, tick, ema20, adx14, warmup=0):
    """Synthetic-test seam. Never use injected indicators for an economic run."""
    return _run(bars, tick, ema20, adx14, warmup)


def _run(bars, tick, ema, adx, warmup):
    _validate(bars, tick)
    if len(bars) != len(ema) or len(bars) != len(adx):
        raise ValueError("indicator length mismatch")
    for label, arr in (("ema", ema), ("adx", adx)):
        for value in arr:
            if value is not None:
                _number(value, label)
    state, trades, events = "IDLE", [], []
    peak = peak_i = arm_i = pending = position = None
    ambiguities = 0

    def event(kind, i, **extra):
        row = {"kind": kind, "bar_index": i}
        if "timestamp_ms" in bars[i]:
            row["bar_open_ms"] = bars[i]["timestamp_ms"]
            row["bar_available_ms"] = bars[i]["available_at_ms"]
        row.update(extra)
        events.append(row)

    def finish(i, price, reason):
        nonlocal position, state
        row = dict(position)
        row.update(exit_index=i, exit_price=price, exit_reason=reason)
        row.update(costs(10000.0 * (price / row["entry_price"] - 1.0)))
        trades.append(row)
        event("EXIT", i, price=price, reason=reason)
        position, state = None, "RESET_WAIT"

    for i, b in enumerate(bars):
        if i < warmup:
            continue
        if position is not None:
            # Pessimistic OHLC stop-first convention where the path is unobserved.
            if b["open"] <= position["stop"]:
                finish(i, b["open"], "GAP_STOP")
            elif b["open"] >= position["target"]:
                # Opening print is observed before any later intrabar low.
                finish(i, position["target"], "GAP_TARGET")
            elif b["low"] <= position["stop"]:
                finish(i, position["stop"], "STOP")
            elif b["high"] >= position["target"]:
                finish(i, position["target"], "TARGET")
            continue
        if state == "PENDING":
            if "timestamp_ms" in b and b["timestamp_ms"] < pending["activate_not_before_ms"]:
                event("WAIT_AVAILABILITY", i, touch_index=pending["touch_index"])
                continue
            event("PENDING_ACTIVE", i, touch_index=pending["touch_index"])
            if b["open"] >= pending["target"]:
                event("SKIP_GAP_BEYOND_TARGET", i)
            elif b["open"] <= pending["stop"]:
                event("CANCEL_GAP_BELOW_STOP", i)
            elif b["high"] >= pending["trigger"]:
                position = dict(pending)
                position.update(entry_index=i, entry_price=max(b["open"], pending["trigger"]))
                event("ENTRY", i, price=position["entry_price"])
                state = "OPEN"
                if b["low"] <= position["stop"]:
                    finish(i, position["stop"], "ENTRY_BAR_STOP")
                elif b["high"] >= position["target"]:
                    if b["open"] >= position["trigger"]:
                        finish(i, position["target"], "ENTRY_AT_OPEN_TARGET")
                    else:
                        ambiguities += 1
                        event("DEFER_AMBIGUOUS_ENTRY_BAR_TARGET", i)
                pending = None
                continue
            else:
                event("EXPIRED_ONE_ELIGIBLE_BAR", i)
            pending, state = None, "RESET_WAIT"
            continue
        if state == "RESET_WAIT":
            if adx[i] is not None and adx[i] <= 30:
                state = "IDLE"
                event("RESET", i)
            continue
        if ema[i] is None or adx[i] is None or i == 0:
            continue
        if state == "IDLE":
            if adx[i-1] is not None and ema[i-1] is not None and adx[i] > 30 and adx[i] > adx[i-1] and b["low"] > ema[i] and b["close"] > ema[i] and ema[i] > ema[i-1]:
                state, peak, peak_i, arm_i = "WAIT_FIRST_TOUCH", b["high"], i, i
                event("ARM", i)
            continue
        if state == "WAIT_FIRST_TOUCH":
            if b["high"] < ema[i]:
                state = "RESET_WAIT"
                event("INVALID_GAP_BELOW_EMA", i)
                continue
            if b["low"] <= ema[i] <= b["high"]:
                trigger = bars[i-1]["high"] + tick
                stop = min(x["low"] for x in bars[peak_i:i+1]) - tick
                if stop <= 0 or trigger <= stop or peak <= trigger:
                    state = "RESET_WAIT"
                    event("INVALID_CONSUMED", i, trigger=trigger, stop=stop, target=peak)
                    continue
                pending = {"arm_index": arm_i, "touch_index": i, "peak_index": peak_i,
                           "trigger": trigger, "stop": stop, "target": peak}
                if "available_at_ms" in b:
                    pending["activate_not_before_ms"] = b["available_at_ms"]
                state = "PENDING"
                event("FIRST_TOUCH", i, **pending)
            elif b["high"] >= peak:
                peak, peak_i = b["high"], i
    censored = []
    if position is not None:
        row = dict(position)
        row.update(kind="OPEN_POSITION", final_index=len(bars)-1,
                   mark_price=bars[-1]["close"],
                   mark_gross_bp=10000.0 * (bars[-1]["close"] / position["entry_price"] - 1.0))
        censored.append(row)
    if pending is not None:
        censored.append(dict(pending, kind="PENDING_NOT_YET_ELIGIBLE", final_index=len(bars)-1))
    return {"trades": trades, "events": events, "censored": censored, "state": state,
            "ambiguous_entry_targets": ambiguities}
