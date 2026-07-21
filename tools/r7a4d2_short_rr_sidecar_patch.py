#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "SHORT_EXECUTION_HARNESS_V1" not in source:
        raise RuntimeError("DUAL_SIDE_RUNNER_REQUIRED")
    if "SHORT_RR_SIDECAR_V1" in source:
        raise RuntimeError("RUNNER_ALREADY_RR_PATCHED")

    source = replace_once(
        source,
        'SHORT_ACTIVE_ACTIONS = frozenset({"enter", "add", "reduce", "exit", "close"})\n\n\n',
        '''SHORT_ACTIVE_ACTIONS = frozenset({"enter", "add", "reduce", "exit", "close"})
SHORT_RR_SIDECAR_V1 = True
SHORT_POLICY_ALLOWED_REGIMES = frozenset({"trend_down"})


def short_sidecar_admission(
    *,
    enabled: bool,
    strategy_id: str,
    target_ids: set[str],
    intent: str,
    legacy_side: str,
    legacy_action: str,
    regime: str,
    fields_ok: bool,
) -> tuple[bool, str]:
    candidate = (
        enabled
        and strategy_id in target_ids
        and fields_ok
        and intent == "hold"
        and legacy_side == "short"
        and legacy_action in SHORT_ACTIVE_ACTIONS
    )
    if not candidate:
        return False, "not_candidate"
    if regime not in SHORT_POLICY_ALLOWED_REGIMES:
        return False, "regime_block"
    return True, "admitted"


''',
        "INSERT_RR_POLICY_HELPERS",
    )

    source = replace_once(
        source,
        '''    short_execution_enabled = bool(contract.get("short_execution_enabled", False))
    short_target_strategy_ids = {
        str(item) for item in contract.get("short_target_strategy_ids", []) if str(item)
    }
    fee_rate = float(cost["fee_bps_per_side"]) / 10000.0
''',
        '''    short_execution_enabled = bool(contract.get("short_execution_enabled", False))
    short_target_strategy_ids = {
        str(item) for item in contract.get("short_target_strategy_ids", []) if str(item)
    }
    short_rr_sidecar_enabled = bool(contract.get("short_rr_sidecar_enabled", False))
    short_policy_loss_cap_r = float(contract.get("short_policy_loss_cap_r", 0.75))
    short_policy_full_tp_r = float(contract.get("short_policy_full_tp_r", 2.5))
    if short_rr_sidecar_enabled and not (
        0.0 < short_policy_loss_cap_r <= 1.0
        and short_policy_full_tp_r > short_policy_loss_cap_r
    ):
        raise ValueError("SHORT_RR_POLICY_INVALID")
    fee_rate = float(cost["fee_bps_per_side"]) / 10000.0
''',
        "RR_CONTRACT_FLAGS",
    )

    source = replace_once(
        source,
        '''    short_invalid_geometry_count = 0
    short_orphan_add_block_count = 0
    strategy_call_count = 0
''',
        '''    short_invalid_geometry_count = 0
    short_orphan_add_block_count = 0
    short_policy_candidate_count = 0
    short_policy_admitted_action_count = 0
    short_policy_regime_block_count = 0
    short_policy_add_suppressed_count = 0
    short_policy_reduce_suppressed_count = 0
    strategy_call_count = 0
''',
        "RR_POLICY_COUNTERS",
    )

    source = replace_once(
        source,
        '''            stop = float(signal.get("sl") or 0.0)
            tp = float(signal.get("tp") or 0.0)
            geometry_ok = (
                0 < tp < fill < stop
                if action_side == "short"
                else 0 < stop < fill < tp
            )
            if quantity <= 0 or not geometry_ok:
                invalid_signal_count += 1
                if action_side == "short":
                    short_invalid_geometry_count += 1
                return
            fee = quantity * fee_rate
            realized -= fee
            total_cost += fee
            risk_pct = quantity * (
                (stop - fill) / fill if action_side == "short" else (fill - stop) / fill
            ) * 100.0
''',
        '''            raw_stop = float(signal.get("sl") or 0.0)
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
                stop = fill + short_policy_loss_cap_r * raw_r_distance
                tp = max(fill - short_policy_full_tp_r * raw_r_distance, 1e-12)
                if not (0 < tp < fill < stop):
                    invalid_signal_count += 1
                    short_invalid_geometry_count += 1
                    return
            else:
                stop = raw_stop
                tp = raw_tp
            fee = quantity * fee_rate
            realized -= fee
            total_cost += fee
            risk_pct = quantity * raw_r_distance / fill * 100.0
''',
        "RR_SIDE_CAR_GEOMETRY",
    )

    source = replace_once(
        source,
        '''                    "entry_event": entry_event,
                    "entry_price": fill,
''',
        '''                    "entry_event": entry_event,
                    "entry_price": fill,
                    "raw_strategy_stop": raw_stop,
                    "raw_strategy_tp": raw_tp,
                    "policy_stop": stop,
                    "policy_tp": tp,
                    "raw_r_distance_pct": raw_r_distance / fill * 100.0,
                    "policy_loss_cap_r": short_policy_loss_cap_r if policy_applied else None,
                    "policy_full_tp_r": short_policy_full_tp_r if policy_applied else None,
''',
        "RR_TRADE_EVIDENCE_FIELDS",
    )

    source = replace_once(
        source,
        '''        short_execute = (
            short_execution_enabled
            and strategy_id in short_target_strategy_ids
            and bool(fields["ok"])
            and intent == "hold"
            and legacy_side == "short"
            and legacy_action in SHORT_ACTIVE_ACTIONS
        )
''',
        '''        short_candidate = (
            short_execution_enabled
            and strategy_id in short_target_strategy_ids
            and bool(fields["ok"])
            and intent == "hold"
            and legacy_side == "short"
            and legacy_action in SHORT_ACTIVE_ACTIONS
        )
        if short_rr_sidecar_enabled:
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
''',
        "RR_SIDECAR_ADMISSION",
    )

    source = replace_once(
        source,
        '''        if short_execute:
            short_kind = "exit" if legacy_action in {"exit", "close"} else legacy_action
''',
        '''        if short_execute:
            short_kind = "exit" if legacy_action in {"exit", "close"} else legacy_action
            if short_rr_sidecar_enabled and short_kind == "add":
                short_policy_add_suppressed_count += 1
                continue
            if short_rr_sidecar_enabled and short_kind == "reduce":
                short_policy_reduce_suppressed_count += 1
                continue
''',
        "RR_FULL_TP_PROFILE_SUPPRESSION",
    )

    source = replace_once(
        source,
        '''        "short_orphan_add_block_count": short_orphan_add_block_count,
        "short_closed_trade_count": sum(
            1 for trade in trades if str(trade.get("side") or "") == "short"
        ),
''',
        '''        "short_orphan_add_block_count": short_orphan_add_block_count,
        "short_policy_candidate_count": short_policy_candidate_count,
        "short_policy_admitted_action_count": short_policy_admitted_action_count,
        "short_policy_regime_block_count": short_policy_regime_block_count,
        "short_policy_add_suppressed_count": short_policy_add_suppressed_count,
        "short_policy_reduce_suppressed_count": short_policy_reduce_suppressed_count,
        "short_closed_trade_count": sum(
            1 for trade in trades if str(trade.get("side") or "") == "short"
        ),
        "short_trade_detail": [
            trade for trade in trades if str(trade.get("side") or "") == "short"
        ],
''',
        "RR_RESULT_FIELDS",
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
    print("STATE=PASS_SHORT_RR_SIDECAR_PATCH_BUILD")
    print("PATCHED_RUNNER=" + str(output_path))
    print("RAW_STRATEGY_SL_TP_PRESERVED=true")
    print("POLICY_LOSS_CAP_R=0.75")
    print("POLICY_FULL_TP_R=2.5")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
