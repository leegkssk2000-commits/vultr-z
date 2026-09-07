"""TPQ1: one signal-close eligibility axis over unchanged TPC1 FULL replay.

Only the completed signal candle's signed body is an execution input. FIXED
comparisons belong to the caller's stored-parent subset, never a market replay.
The parent owns all paths, actual occupancy, cooldown, and uncharged results.
Replay is serial-only because TPC1 temporarily binds the native path function.
"""
from copy import deepcopy
from hashlib import sha256
from math import isfinite

from backend.research.rebuild import trend_primary_combined_v1 as parent

RULE = (
    'TPQ1 G5_DEV_NO_CREDIT; parent exact TPC1 FULL. At the original completed '
    'signal close reject iff sign*(signal close-signal open)<0, sign=+1 long '
    'and -1 short. Doji and aligned bodies pass. Current signal bar only; '
    'signal_ts must equal its bar_close_ts. No threshold, delay, second axis, '
    'or changes to next-open entry, SL, TP, extension, protection, sizing, '
    'ownership, cooldown, costs, or censoring. Remove vetoes before unchanged '
    'TPC1 replay; reinsert explicit VETOED raw events without trades. All-pass '
    'and enabled=False return exact complete parent replay output. FIXED is '
    'a caller-owned stored-parent subset, not an independently replayed path. '
    'No independent OOS claim, formal promotion, or execution authority.'
)
API = 'eligible(rows,event,*,enabled=True)->bool; replay(rows,tape,cache,cost_binding,*,enabled=True)->TPC1_output'
RULE_SHA256 = sha256(RULE.encode()).hexdigest()
API_SHA256 = sha256(API.encode()).hexdigest()
VETO_REASON = 'TPQ1_ADVERSE_SIGNAL_BODY'


def _validate_enabled(enabled):
    if type(enabled) is not bool:
        raise RuntimeError('TPQ1_ENABLED_BOOL')


def _signal_body(rows, event):
    i = event['signal_index']
    if type(i) is not int or not 0 <= i < len(rows):
        raise RuntimeError('TPQ1_SIGNAL_INDEX')
    row = rows[i]
    if event['signal_ts'] != row['bar_close_ts']:
        raise RuntimeError('TPQ1_SIGNAL_CLOSE_BINDING')
    if event['side'] not in ('long', 'short'):
        raise RuntimeError('TPQ1_SIDE')
    opening, closing = float(row['open']), float(row['close'])
    if not isfinite(opening) or not isfinite(closing):
        raise RuntimeError('TPQ1_SIGNAL_PRICE_FINITE')
    sign = 1 if event['side'] == 'long' else -1
    return sign * (closing - opening)


def eligible(rows, event, *, enabled=True):
    """Pure bool, bound to this event's completed signal close; no future read."""
    _validate_enabled(enabled)
    return True if not enabled else _signal_body(rows, event) >= 0


def replay(rows, tape, cache, cost_binding, *, enabled=True):
    """Replay retained intents through TPC1; retain every original raw event.

    Native replay overwrites admission, so veto events must be physically
    absent from the delegated tape. A veto neither acquires nor releases a
    slot. ``excluded`` retains its native ownership/cooldown meaning; vetoes
    have a separate count and never become zero-profit trades.
    """
    _validate_enabled(enabled)
    if not enabled:
        return parent.replay(rows, tape, cache, cost_binding)
    decisions = [eligible(rows, event) for event in tape]
    if all(decisions):
        return parent.replay(rows, tape, cache, cost_binding)
    retained = [event for event, keep in zip(tape, decisions) if keep]
    out = parent.replay(rows, retained, cache, cost_binding)
    native_events = iter(out['events'])
    events = []
    for source, keep in zip(tape, decisions):
        if keep:
            events.append(next(native_events))
        else:
            event = deepcopy(source)
            event.update(admission=False, status='VETOED', exclusion_reason=VETO_REASON,
                         entry_quality_available_at=source['signal_ts'],
                         entry_quality_signed_body=_signal_body(rows, source))
            events.append(event)
    out['events'] = events
    out['audit'].update(raw_signals=len(tape), retained_signals=len(retained),
                        entry_quality_vetoed=len(tape)-len(retained),
                        native_blocked=out['audit']['excluded'],
                        entry_quality_rule='TPQ1', entry_quality_rule_sha256=RULE_SHA256)
    return out
