#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"FILL_REBASE_PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "SHORT_RR_SIDECAR_V1 = True" not in source:
        raise RuntimeError("SHORT_RR_SIDECAR_REQUIRED")
    if "SHORT_RETURN_SPACE_RR_EXACT" in source:
        raise RuntimeError("UNEXPECTED_MARKER_IN_RUNNER")
    if "SHORT_FILL_REBASE_V1" in source:
        raise RuntimeError("RUNNER_ALREADY_FILL_REBASE_PATCHED")

    source = replace_once(
        source,
        '''SHORT_RR_SIDECAR_V1 = True
SHORT_POLICY_ALLOWED_REGIMES = frozenset({"trend_down"})


''',
        '''SHORT_RR_SIDECAR_V1 = True
SHORT_FILL_REBASE_V1 = True
SHORT_POLICY_ALLOWED_REGIMES = frozenset({"trend_down"})


def short_fill_rebased_geometry(
    *,
    fill: float,
    signal_entry: float,
    raw_stop: float,
    loss_cap_r: float,
    full_tp_r: float,
) -> tuple[float, float, float]:
    if not (0.0 < signal_entry < raw_stop and fill > 0.0):
        raise ValueError("SHORT_FILL_REBASE_INPUT_INVALID")
    raw_r_fraction = (raw_stop - signal_entry) / signal_entry
    stop_denominator = 1.0 - loss_cap_r * raw_r_fraction
    if raw_r_fraction <= 0.0 or stop_denominator <= 0.0:
        raise ValueError("SHORT_FILL_REBASE_DENOMINATOR_INVALID")
    stop = fill / stop_denominator
    tp = fill / (1.0 + full_tp_r * raw_r_fraction)
    if not (0.0 < tp < fill < stop):
        raise ValueError("SHORT_FILL_REBASE_GEOMETRY_INVALID")
    return stop, tp, raw_r_fraction


''',
        "HELPER_INSERT",
    )

    source = replace_once(
        source,
        '''    short_policy_full_tp_r = float(contract.get("short_policy_full_tp_r", 2.5))
    if short_rr_sidecar_enabled and not (
''',
        '''    short_policy_full_tp_r = float(contract.get("short_policy_full_tp_r", 2.5))
    short_fill_rebase_enabled = bool(contract.get("short_fill_rebase_enabled", False))
    if short_fill_rebase_enabled and not short_rr_sidecar_enabled:
        raise ValueError("SHORT_FILL_REBASE_REQUIRES_RR_SIDECAR")
    if short_rr_sidecar_enabled and not (
''',
        "CONTRACT_FLAG",
    )

    old_geometry = '''            raw_stop = float(signal.get("sl") or 0.0)
            raw_tp = float(signal.get("tp") or 0.0)
            raw_geometry_ok = (
                0 < raw_tp < fill < raw_stop
                if action_side == "short"
                else 0 < raw_stop < fill < raw_tp
            )
            if quantity <= 0 or not raw_geometry_ok:
                invalid_signal_count += 1
                if action_side == "short":
                    short_invalid_geometry_count += 1
                return
            raw_r_distance = (
                raw_stop - fill if action_side == "short" else fill - raw_stop
            )
            if raw_r_distance <= 0:
                invalid_signal_count += 1
                if action_side == "short":
                    short_invalid_geometry_count += 1
                return
            policy_applied = action_side == "short" and short_rr_sidecar_enabled
            if policy_applied:
                raw_r_fraction = raw_r_distance / fill
                stop_denominator = 1.0 - short_policy_loss_cap_r * raw_r_fraction
                if stop_denominator <= 0:
                    invalid_signal_count += 1
                    short_invalid_geometry_count += 1
                    return
                stop = fill / stop_denominator
                tp = fill / (1.0 + short_policy_full_tp_r * raw_r_fraction)
                if not (0 < tp < fill < stop):
                    invalid_signal_count += 1
                    short_invalid_geometry_count += 1
                    return
            else:
                stop = raw_stop
                tp = raw_tp
'''
    new_geometry = '''            raw_stop = float(signal.get("sl") or 0.0)
            raw_tp = float(signal.get("tp") or 0.0)
            raw_signal_entry = float(signal.get("entry") or 0.0)
            fill_rebase_applied = (
                action_side == "short"
                and short_rr_sidecar_enabled
                and short_fill_rebase_enabled
            )
            policy_applied = action_side == "short" and short_rr_sidecar_enabled
            if fill_rebase_applied:
                raw_signal_geometry_ok = 0 < raw_tp < raw_signal_entry < raw_stop
                if quantity <= 0 or not raw_signal_geometry_ok:
                    invalid_signal_count += 1
                    short_invalid_geometry_count += 1
                    return
                try:
                    stop, tp, raw_r_fraction = short_fill_rebased_geometry(
                        fill=fill,
                        signal_entry=raw_signal_entry,
                        raw_stop=raw_stop,
                        loss_cap_r=short_policy_loss_cap_r,
                        full_tp_r=short_policy_full_tp_r,
                    )
                except ValueError:
                    invalid_signal_count += 1
                    short_invalid_geometry_count += 1
                    return
                raw_r_distance = raw_r_fraction * fill
            else:
                raw_geometry_ok = (
                    0 < raw_tp < fill < raw_stop
                    if action_side == "short"
                    else 0 < raw_stop < fill < raw_tp
                )
                if quantity <= 0 or not raw_geometry_ok:
                    invalid_signal_count += 1
                    if action_side == "short":
                        short_invalid_geometry_count += 1
                    return
                raw_r_distance = (
                    raw_stop - fill if action_side == "short" else fill - raw_stop
                )
                if raw_r_distance <= 0:
                    invalid_signal_count += 1
                    if action_side == "short":
                        short_invalid_geometry_count += 1
                    return
                if policy_applied:
                    raw_r_fraction = raw_r_distance / fill
                    stop_denominator = 1.0 - short_policy_loss_cap_r * raw_r_fraction
                    if stop_denominator <= 0:
                        invalid_signal_count += 1
                        short_invalid_geometry_count += 1
                        return
                    stop = fill / stop_denominator
                    tp = fill / (1.0 + short_policy_full_tp_r * raw_r_fraction)
                    if not (0 < tp < fill < stop):
                        invalid_signal_count += 1
                        short_invalid_geometry_count += 1
                        return
                else:
                    stop = raw_stop
                    tp = raw_tp
'''
    source = replace_once(source, old_geometry, new_geometry, "GEOMETRY_BRANCH")

    source = replace_once(
        source,
        '''                    "policy_full_tp_r": short_policy_full_tp_r if policy_applied else None,
''',
        '''                    "policy_full_tp_r": short_policy_full_tp_r if policy_applied else None,
                    "raw_signal_entry": raw_signal_entry,
                    "fill_rebase_applied": fill_rebase_applied,
''',
        "TRADE_EVIDENCE",
    )
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    patched = apply_patch(input_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False
    ) as handle:
        handle.write(patched)
        temp_path = Path(handle.name)
    temp_path.replace(output_path)
    py_compile.compile(str(output_path), doraise=True)
    print("STATE=PASS_SHORT_FILL_REBASE_COUNTERFACTUAL_PATCH")
    print("SHORT_FILL_REBASE_DEFAULT_ENABLED=false")
    print("RAW_SIGNAL_PREDICATES_PRESERVED=true")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
