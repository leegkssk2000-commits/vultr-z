#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"OBSERVER_PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "SHORT_RR_SIDECAR_V1" not in source:
        raise RuntimeError("RR_SIDECAR_RUNNER_REQUIRED")
    if "SHORT_OBSERVER_TARGET_V1" in source:
        raise RuntimeError("RUNNER_ALREADY_OBSERVER_PATCHED")

    source = replace_once(
        source,
        "SHORT_RR_SIDECAR_V1 = True\n",
        "SHORT_RR_SIDECAR_V1 = True\nSHORT_OBSERVER_TARGET_V1 = True\n",
        "OBSERVER_MARKER",
    )

    source = replace_once(
        source,
        '''    short_rr_sidecar_enabled = bool(contract.get("short_rr_sidecar_enabled", False))
    short_policy_loss_cap_r = float(contract.get("short_policy_loss_cap_r", 0.75))
    short_policy_full_tp_r = float(contract.get("short_policy_full_tp_r", 2.5))
''',
        '''    short_rr_sidecar_enabled = bool(contract.get("short_rr_sidecar_enabled", False))
    short_policy_loss_cap_r = float(contract.get("short_policy_loss_cap_r", 0.75))
    short_policy_full_tp_r = float(contract.get("short_policy_full_tp_r", 2.5))
    short_observer_target_enabled = bool(contract.get("short_observer_target_enabled", False))
    short_observer_target_scenario_id = str(contract.get("short_observer_target_scenario_id") or "")
    short_observer_target_strategy_id = str(contract.get("short_observer_target_strategy_id") or "")
    short_observer_target_bar_index = int(contract.get("short_observer_target_bar_index", -1))
''',
        "OBSERVER_CONTRACT_FIELDS",
    )

    source = replace_once(
        source,
        '''    short_policy_reduce_suppressed_count = 0
    strategy_call_count = 0
''',
        '''    short_policy_reduce_suppressed_count = 0
    short_observer_target_match_count = 0
    short_observer_non_target_suppressed_count = 0
    strategy_call_count = 0
''',
        "OBSERVER_COUNTERS",
    )

    old = '''        if short_rr_sidecar_enabled:
            short_execute, short_policy_reason = short_sidecar_admission(
                enabled=short_execution_enabled,
                strategy_id=strategy_id,
                target_ids=short_target_strategy_ids,
                intent=intent,
                legacy_side=legacy_side,
                legacy_action=legacy_action,
                regime=regime,
                fields_ok=bool(fields["ok"]),
            )
            if short_candidate:
                short_policy_candidate_count += 1
                if short_policy_reason == "regime_block":
                    short_policy_regime_block_count += 1
                elif short_execute:
                    short_policy_admitted_action_count += 1
        else:
            short_execute = short_candidate
'''
    new = '''        if short_rr_sidecar_enabled:
            short_execute, short_policy_reason = short_sidecar_admission(
                enabled=short_execution_enabled,
                strategy_id=strategy_id,
                target_ids=short_target_strategy_ids,
                intent=intent,
                legacy_side=legacy_side,
                legacy_action=legacy_action,
                regime=regime,
                fields_ok=bool(fields["ok"]),
            )
            if short_observer_target_enabled:
                observer_match = (
                    short_candidate
                    and legacy_action == "enter"
                    and str(scenario.get("scenario_id") or "") == short_observer_target_scenario_id
                    and strategy_id == short_observer_target_strategy_id
                    and index == short_observer_target_bar_index
                )
                if observer_match:
                    short_execute = True
                    short_policy_reason = "observer_target"
                    short_observer_target_match_count += 1
                else:
                    if short_candidate:
                        short_observer_non_target_suppressed_count += 1
                    short_execute = False
                    short_policy_reason = "observer_non_target"
            if short_candidate:
                short_policy_candidate_count += 1
                if short_policy_reason == "regime_block":
                    short_policy_regime_block_count += 1
                elif short_execute:
                    short_policy_admitted_action_count += 1
        else:
            short_execute = short_candidate
'''
    source = replace_once(source, old, new, "OBSERVER_TARGET_GATE")

    source = replace_once(
        source,
        '''        "short_policy_reduce_suppressed_count": short_policy_reduce_suppressed_count,
        "short_closed_trade_count": sum(
''',
        '''        "short_policy_reduce_suppressed_count": short_policy_reduce_suppressed_count,
        "short_observer_target_match_count": short_observer_target_match_count,
        "short_observer_non_target_suppressed_count": short_observer_non_target_suppressed_count,
        "short_closed_trade_count": sum(
''',
        "OBSERVER_RESULT_FIELDS",
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
    print("STATE=PASS_SHORT_OBSERVER_TARGET_PATCH")
    print("OBSERVER_SCOPE=single_scenario_single_strategy_single_bar_enter_only")
    print("REGIME_GATE_OVERRIDE=observer_only")
    print("PRODUCTION_ADMISSION_MUTATION_ALLOWED=false")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
