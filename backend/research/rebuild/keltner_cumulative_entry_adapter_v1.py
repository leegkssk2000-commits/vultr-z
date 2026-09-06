"""One causal entry restriction on the unchanged PR1196 Keltner exit model.

This adapter neither loads prices nor implements a trade engine. Every admitted
trade is replayed by the frozen D model, including its early exit, original
12-bar timeout, exit-bar ownership and terminal observation conventions.
"""
from __future__ import annotations

from copy import deepcopy
import math

from backend.research.rebuild import parallel_exit_keltner_v1 as previous

BAR = previous.BAR
LANE = previous.LANE
RULE_ID = "KELTNER_CUMULATIVE_DIRECTIONAL_HALF_ENTRY_DEV_V1"
FEATURE = "close_on_directional_half"
FEATURE_SOURCE = "top5_development_repair_v1.geometry.close_on_directional_half"
VETO_REASON = "SIGNAL_CLOSE_BELOW_DIRECTIONAL_HALF"


def build_bundle(rows, parent_spec, *, eval_start_ms, eval_end_ms):
    """The original EMA calculation and reclaim signal remain unchanged."""
    return previous.build_bundle(rows, parent_spec, eval_start_ms=eval_start_ms,
                                 eval_end_ms=eval_end_ms)


def entry_observation(row):
    """The existing long-side geometry predicate, using this close only.

    Deliberately do not call the multi-feature geometry helper: that helper also
    reads previous bars for unrelated fields. No historical or future row is
    needed for this already defined current-bar primitive.
    """
    close, high, low = (row.get(name) for name in ("close", "high", "low"))
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v <= 0 for v in (close, high, low)):
        raise RuntimeError("KELTNER_ENTRY_GEOMETRY_NONFINITE_OR_MISSING")
    if not low <= close <= high:
        raise RuntimeError("KELTNER_ENTRY_GEOMETRY_INCONSISTENT")
    midpoint = (high + low) / 2
    if not math.isfinite(midpoint):
        raise RuntimeError("KELTNER_ENTRY_GEOMETRY_NONFINITE_OR_MISSING")
    return {FEATURE: close >= midpoint, "signal_close": close,
            "signal_high": high, "signal_low": low,
            "signal_midpoint": midpoint,
            "known_at_ts": row["bar_close_ts"], "source": FEATURE_SOURCE}


def replay(rows, bundle, *, eval_start_ms, eval_end_ms, enabled=True,
           common_signal_indices=None):
    """Replay the single entry change with the D exit always enabled.

    With ``enabled=False`` the entire raw result is exactly the frozen D result.
    A common-opportunity view must be supplied D's actually admitted origins. It
    applies this entry restriction to that set, with independent position paths;
    it is not an identical-entry exit comparison or the full occupancy replay.

    Full replay retains every original signal event. Entry eligibility takes
    precedence over occupancy exclusion, so each excluded signal has one reason.
    """
    if type(enabled) is not bool:
        raise RuntimeError("KELTNER_CUMULATIVE_ENABLE_BOOL_REQUIRED")
    if not enabled:
        return previous.replay(
            rows, bundle, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms,
            enable_change=True, fixed_signal_indices=common_signal_indices)

    # Validate even signals that the new entry predicate may veto. Empty fixed
    # origins exercise the frozen input/boundary checks without any trade path.
    previous.replay(rows, bundle, eval_start_ms=eval_start_ms,
                    eval_end_ms=eval_end_ms, enable_change=True,
                    fixed_signal_indices=[])
    all_signals = bundle["signals"]
    common = common_signal_indices is not None
    if common:
        wanted = list(common_signal_indices)
        if (any(type(i) is not int for i in wanted)
                or len(wanted) != len(set(wanted))
                or not set(wanted) <= {s["signal_index"] for s in all_signals}):
            raise RuntimeError("KELTNER_CUMULATIVE_COMMON_ORIGINS_INVALID")
        scope = [s for s in all_signals if s["signal_index"] in set(wanted)]
    else:
        scope = all_signals
    observations = {s["signal_index"]: entry_observation(rows[s["signal_index"]])
                    for s in scope}
    eligible = [s for s in scope if observations[s["signal_index"]][FEATURE]]
    filtered = dict(bundle, signals=eligible)
    result = previous.replay(
        rows, filtered, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms,
        enable_change=True,
        fixed_signal_indices=[s["signal_index"] for s in eligible] if common else None)
    accepted_events = {e["signal_index"]: e for e in result["events"]}
    events = []
    for signal in scope:
        i = signal["signal_index"]
        observation = observations[i]
        if observation[FEATURE]:
            event = deepcopy(accepted_events[i])
        else:
            event = dict(signal, admission=False, status="EXCLUDED",
                         exclusion_reason=VETO_REASON)
        event["entry_observation"] = deepcopy(observation)
        events.append(event)
    result["events"] = events
    vetoes = sum(e["exclusion_reason"] == VETO_REASON for e in events)
    excluded = sum(e["status"] == "EXCLUDED" for e in events)
    result["audit"].update(
        rule=RULE_ID, entry_change_enabled=True,
        exit_rule=previous.RULE_ID, exit_change_always_enabled=True,
        comparison_mode=("COMMON_D_ADMITTED_OPPORTUNITIES" if common
                         else "FULL_CHRONOLOGICAL"),
        comparison_type="ENTRY_FILTER", same_entry_exit_comparison=False,
        original_signal_count=len(all_signals), raw_signals=len(scope),
        eligible_signal_count=len(eligible), entry_veto_count=vetoes,
        excluded=excluded,
        occupancy_exclusion_count=sum(e["exclusion_reason"] == "SIGNAL_DURING_OPEN"
                                      for e in events),
        no_next_open_exclusion_count=sum(e["exclusion_reason"] == "NO_NEXT_OPEN_IN_CALENDAR"
                                        for e in events),
        original_signal_denominator_preserved=not common,
        common_opportunity_subset=common, entry_feature=FEATURE,
        feature_source=FEATURE_SOURCE, entry_threshold="(signal_high+signal_low)/2",
        entry_threshold_tie="ALLOW", signal_feature_time="COMPLETED_SIGNAL_BAR_CLOSE",
        entry_eligibility_before_occupancy=True,
        new_entry_timing="UNCHANGED_NEXT_ORIGINAL_4H_OPEN")
    if len(result["trades"]) + len(result["open_positions"]) + excluded != len(scope):
        raise RuntimeError("KELTNER_CUMULATIVE_OPPORTUNITY_ACCOUNTING")
    return result
