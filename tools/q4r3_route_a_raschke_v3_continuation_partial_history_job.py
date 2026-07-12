from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import pandas as pd

BASE_PATH = Path(__file__).with_name("q4r3_route_a_raschke_v3_continuation_partial_history.py")
SPEC = importlib.util.spec_from_file_location("q4r3_continuation_partial_history_base", BASE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"IMPORT_SPEC_FAILED:{BASE_PATH}")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)

ORIGINAL_REPLAY = BASE.replay_policies
ORIGINAL_CONTINUATION = BASE.continuation_report


def is_proximity_core_event(event: Dict[str, Any]) -> bool:
    value = event.get("proximity_pass")
    return value is True or value == 1 or str(value).lower() == "true"


def conservative_first_touch_analysis(raw: pd.DataFrame, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    idx = BASE.event_index(raw, int(event.get("entry_ts", 0)))
    entry = BASE.safe_float(event.get("entry"))
    risk = BASE.safe_float(event.get("base_risk"))
    side = str(event.get("side", ""))
    if idx is None or entry is None or risk is None or risk <= 0 or side not in {"long", "short"}:
        return None
    last_idx = min(len(raw) - 1, idx + BASE.TIMEOUT_MIN - 1)
    if not BASE.path_contiguous(raw, idx, last_idx):
        return None

    touches: Dict[float, Optional[int]] = {0.5: None, 1.0: None, 1.5: None, 2.0: None}
    mae_before_15 = 0.0
    post_15_floor = 999.0
    continuation_outcome = "TIMEOUT_AFTER_1_5R"
    ambiguity = False

    for current in range(idx, last_idx + 1):
        bar = raw.iloc[current]
        high_r = BASE.directional_r(
            side,
            float(bar["high"] if side == "long" else bar["low"]),
            entry,
            risk,
        )
        low_r = BASE.directional_r(
            side,
            float(bar["low"] if side == "long" else bar["high"]),
            entry,
            risk,
        )
        stop_hit = low_r <= -BASE.LOSS_CAP_R
        target_2_hit = high_r >= 2.0
        trigger_15_hit = high_r >= 1.5

        if touches[1.5] is None:
            mae_before_15 = min(mae_before_15, low_r)
            if stop_hit and trigger_15_hit:
                ambiguity = True
                return None
            if stop_hit:
                return None
        else:
            post_15_floor = min(post_15_floor, low_r)
            if stop_hit and target_2_hit:
                ambiguity = True
                continuation_outcome = "SL_AFTER_1_5R_AMBIGUOUS"
                break
            if stop_hit:
                continuation_outcome = "SL_AFTER_1_5R"
                break
            if target_2_hit:
                touches[2.0] = current
                continuation_outcome = "TP_2R_AFTER_1_5R"
                break

        for threshold in (0.5, 1.0, 1.5):
            if touches[threshold] is None and high_r >= threshold:
                touches[threshold] = current
        if touches[1.5] is not None and target_2_hit:
            touches[2.0] = current
            continuation_outcome = "TP_2R_AFTER_1_5R"
            break

    if touches[1.5] is None:
        return None
    reached_2 = touches[2.0] is not None
    month = pd.to_datetime(int(event.get("entry_ts", 0)), unit="ms", utc=True).strftime("%Y-%m")
    time_to_15 = int(touches[1.5] - idx)
    speed_bucket = (
        "le_60m"
        if time_to_15 <= 60
        else ("61_120m" if time_to_15 <= 120 else ("121_240m" if time_to_15 <= 240 else "gt_240m"))
    )
    return {
        "event_id": event.get("event_id"),
        "window": event.get("window"),
        "symbol": event.get("symbol"),
        "side": side,
        "month": month,
        "entry_ts": int(event.get("entry_ts", 0)),
        "reached_2R": reached_2,
        "time_to_1_5R_min": time_to_15,
        "time_1_5R_to_2R_min": int(touches[2.0] - touches[1.5]) if reached_2 else None,
        "mae_before_1_5R": abs(float(mae_before_15)),
        "post_1_5R_floor_R": float(post_15_floor) if post_15_floor < 999.0 else None,
        "speed_bucket": speed_bucket,
        "continuation_outcome": continuation_outcome,
        "continuation_ambiguity": ambiguity,
        "final_class": BASE.class_name(event),
        "net_R_0.15": float(event.get("net_R_0.15", 0.0)),
        "features": event.get("features", {}),
    }


def replay_proximity_core(
    events: Sequence[Dict[str, Any]],
    raw_frames: Dict[Tuple[str, str], pd.DataFrame],
) -> Dict[str, Any]:
    selected = [event for event in events if is_proximity_core_event(event)]
    result = ORIGINAL_REPLAY(selected, raw_frames)
    result["input_lane"] = "v2_proximity_guard"
    result["input_events"] = len(selected)
    result["excluded_non_proximity_events"] = len(events) - len(selected)
    return result


def continuation_proximity_core(
    events: Sequence[Dict[str, Any]],
    raw_frames: Dict[Tuple[str, str], pd.DataFrame],
) -> Dict[str, Any]:
    selected = [event for event in events if is_proximity_core_event(event)]
    core = ORIGINAL_CONTINUATION(selected, raw_frames)
    all_signal_reference = ORIGINAL_CONTINUATION(events, raw_frames)
    core["input_lane"] = "v2_proximity_guard"
    core["input_events"] = len(selected)
    core["excluded_non_proximity_events"] = len(events) - len(selected)
    core["all_signal_reference"] = {
        "input_events": len(events),
        "continuation_all": all_signal_reference["groups"]["all"],
    }
    return core


BASE.first_touch_analysis = conservative_first_touch_analysis
BASE.replay_policies = replay_proximity_core
BASE.continuation_report = continuation_proximity_core


if __name__ == "__main__":
    BASE.main()
