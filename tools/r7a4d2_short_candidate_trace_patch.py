#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"TRACE_PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "SHORT_RR_SIDECAR_V1" not in source:
        raise RuntimeError("RR_SIDECAR_RUNNER_REQUIRED")
    if "SHORT_CANDIDATE_TRACE_V1" in source:
        raise RuntimeError("RUNNER_ALREADY_TRACE_PATCHED")

    source = replace_once(
        source,
        "SHORT_RR_SIDECAR_V1 = True\n",
        "SHORT_RR_SIDECAR_V1 = True\nSHORT_CANDIDATE_TRACE_V1 = True\n",
        "TRACE_MARKER",
    )

    source = replace_once(
        source,
        '''    short_policy_reduce_suppressed_count = 0
    strategy_call_count = 0
''',
        '''    short_policy_reduce_suppressed_count = 0
    short_candidate_trace: list[dict[str, Any]] = []
    strategy_call_count = 0
''',
        "TRACE_BUFFER",
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
            if short_candidate:
                short_policy_candidate_count += 1
                if short_policy_reason == "regime_block":
                    short_policy_regime_block_count += 1
                elif short_execute:
                    short_policy_admitted_action_count += 1
        else:
            short_execute = short_candidate
            short_policy_reason = "legacy_direct" if short_candidate else "not_candidate"
        if short_candidate:
            position_qty = float(position.get("qty") or 0.0)
            position_side = str(position.get("side") or "")
            position_is_short = position_qty > 0 and position_side == "short"
            pending_short_enter = any(
                str(item.get("kind") or "") == "enter"
                and str(item.get("side") or "") == "short"
                for item in pending
                if isinstance(item, dict)
            )
            if legacy_action == "enter":
                candidate_state = (
                    "ENTER_WHILE_POSITION_OR_PENDING"
                    if position_is_short or pending_short_enter
                    else "FLAT_ENTER"
                )
            elif legacy_action in {"add", "reduce", "exit", "close"}:
                candidate_state = (
                    "POSITION_MANAGEMENT"
                    if position_is_short
                    else "ORPHAN_MANAGEMENT"
                )
            else:
                candidate_state = "OTHER"
            short_candidate_trace.append({
                "scenario_id": str(scenario.get("scenario_id") or ""),
                "strategy_id": strategy_id,
                "segment_id": str(scenario.get("segment_id") or ""),
                "regime": regime,
                "bar_index": index,
                "evaluation_index": index - evaluation_start,
                "legacy_action": legacy_action,
                "legacy_reason": str(legacy.get("why") or fields.get("reason") or ""),
                "target_qty": float(fields.get("target_qty") or legacy.get("size") or 0.0),
                "admitted": bool(short_execute),
                "admission_reason": short_policy_reason,
                "candidate_state": candidate_state,
                "position_qty": position_qty,
                "position_side": position_side,
                "entry_strategy_id": str(position.get("entry_strategy_id") or ""),
                "pending_short_enter": pending_short_enter,
            })
'''
    source = replace_once(source, old, new, "TRACE_APPEND")

    source = replace_once(
        source,
        '''        "short_policy_reduce_suppressed_count": short_policy_reduce_suppressed_count,
        "short_closed_trade_count": sum(
''',
        '''        "short_policy_reduce_suppressed_count": short_policy_reduce_suppressed_count,
        "short_candidate_trace": short_candidate_trace,
        "short_closed_trade_count": sum(
''',
        "TRACE_RESULT_FIELD",
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
        "w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        delete=False,
    ) as handle:
        handle.write(patched)
        temp_path = Path(handle.name)
    temp_path.replace(output_path)
    py_compile.compile(str(output_path), doraise=True)
    print("STATE=PASS_SHORT_CANDIDATE_TRACE_PATCH")
    print("TRACE_MUTATION_SCOPE=temporary_runner_only")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
