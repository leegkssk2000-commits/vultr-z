#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import g5_clean_runner_v1 as base

ROOT = base.ROOT
BASE_CONTRACT_PATH = ROOT / "backend/research/contracts/g5_clean_runner_contract_v1.json"
BASE_FREEZE_PATH = ROOT / "backend/research/rebuild/g5_clean_runner_strategy_freeze_v1.json"
CANONICAL_V2_PATH = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
TOP5_SSOT_PATH = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
PROSPECTIVE_V2_PATH = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
PRE_FIX_RUN_PATH = ROOT / "backend/research/rebuild/g5_clean_runner_binding_fix_v1.json"

BINDING_EPOCH = "KELTNER_V2_BINDING_FIX_V1"
KELTNER_ID = "keltner_trend"
KELTNER_CHILD = "keltner_replacement_trend_pull_long_4h_h12_v2"
OLD_KELTNER_CHILD = "keltner_range_owner_v1"
EXPECTED_RULE = "ema20 > ema50 and lag('close',1) <= lag('ema20',1) and close > ema20"

_ORIGINAL_ADAPTER = base.FrozenStrategyAdapter
_ORIGINAL_VALIDATE = base.validate_contract_assets
_ORIGINAL_BUILD = base.build_runtime_artifacts


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise base.IntegrityError(f"OBJECT_REQUIRED:{path}")
    return value


def _canonical_keltner() -> dict[str, Any]:
    canonical = _read(CANONICAL_V2_PATH)
    children = [
        row for row in canonical.get("children") or []
        if isinstance(row, Mapping) and row.get("parent_strategy_id") == KELTNER_ID
    ]
    if len(children) != 1:
        raise base.IntegrityError("CANONICAL_KELTNER_V2_EXACTLY_ONE_REQUIRED")
    child = dict(children[0])
    spec = child.get("executable_spec")
    if not isinstance(spec, Mapping):
        raise base.IntegrityError("CANONICAL_KELTNER_EXECUTABLE_SPEC_REQUIRED")
    if child.get("child_id") != KELTNER_CHILD:
        raise base.IntegrityError("CANONICAL_KELTNER_CHILD_DRIFT")
    if spec.get("entry_rule") != EXPECTED_RULE:
        raise base.IntegrityError("CANONICAL_KELTNER_ENTRY_RULE_DRIFT")
    if str(spec.get("side_rule")) != "long":
        raise base.IntegrityError("CANONICAL_KELTNER_SIDE_DRIFT")
    if str(spec.get("entry_timing")) != "next_bar_open":
        raise base.IntegrityError("CANONICAL_KELTNER_ENTRY_TIMING_DRIFT")
    if str(spec.get("exit_rule")) != "time_stop" or int(spec.get("max_hold_bars") or 0) != 12:
        raise base.IntegrityError("CANONICAL_KELTNER_EXIT_DRIFT")
    if abs(float(spec.get("cost_bps_per_trade") or 0.0) - 20.0) > 1e-12:
        raise base.IntegrityError("CANONICAL_KELTNER_COST_DRIFT")
    boundary = canonical.get("prospective_boundary") or {}
    if int(boundary.get("ms") or 0) != 1788048000000:
        raise base.IntegrityError("CANONICAL_KELTNER_BOUNDARY_DRIFT")
    return child


def _assert_top5_owner() -> None:
    top5 = _read(TOP5_SSOT_PATH)
    rows = [
        row for row in top5.get("top5") or []
        if isinstance(row, Mapping) and row.get("strategy_id") == KELTNER_ID
    ]
    if len(rows) != 1:
        raise base.IntegrityError("TOP5_KELTNER_EXACTLY_ONE_REQUIRED")
    replacement = rows[0].get("replacement_child") or {}
    if replacement.get("child_id") != KELTNER_CHILD:
        raise base.IntegrityError("TOP5_KELTNER_CURRENT_CHILD_DRIFT")
    reporting = top5.get("reporting_rules") or {}
    if reporting.get("replacement_child_current_owner") != "V2_ONLY":
        raise base.IntegrityError("TOP5_REPLACEMENT_OWNER_NOT_V2_ONLY")


def _semantic_hashes(child: Mapping[str, Any]) -> dict[str, str]:
    spec = dict(child["executable_spec"])
    return {
        "strategy_sha": base.sha_json({
            "child_id": child["child_id"],
            "architecture_family": child["architecture_family"],
            "executable_spec": spec,
        }),
        "entry_sha": base.sha_json({
            "entry_rule": spec["entry_rule"],
            "side_rule": spec["side_rule"],
            "entry_timing": spec["entry_timing"],
        }),
        "exit_sha": base.sha_json({
            "exit_rule": spec["exit_rule"],
            "max_hold_bars": spec["max_hold_bars"],
        }),
        "config_sha": base.sha_json(spec),
        "freeze_receipt_sha": base.sha_json(dict(child)),
    }


def _find_strategy(rows: Sequence[Mapping[str, Any]], strategy_id: str) -> dict[str, Any]:
    matches = [dict(row) for row in rows if row.get("strategy_id") == strategy_id]
    if len(matches) != 1:
        raise base.IntegrityError(f"STRATEGY_EXACTLY_ONE_REQUIRED:{strategy_id}")
    return matches[0]


def materialize_effective_assets(artifact_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    _assert_top5_owner()
    child = _canonical_keltner()
    spec = dict(child["executable_spec"])
    hashes = _semantic_hashes(child)

    contract = copy.deepcopy(_read(BASE_CONTRACT_PATH))
    freeze = copy.deepcopy(_read(BASE_FREEZE_PATH))
    old_keltner = _find_strategy(contract["active_strategies"], KELTNER_ID)
    if old_keltner.get("child_id") != OLD_KELTNER_CHILD:
        raise base.IntegrityError("PRE_FIX_KELTNER_BINDING_NOT_EXPECTED_OLD_CHILD")
    if old_keltner.get("classifier_rule") != "abs(full_history_ema20-full_history_ema50)/atr14 < 0.5":
        raise base.IntegrityError("PRE_FIX_KELTNER_CLASSIFIER_NOT_EXPECTED")

    for row in contract["active_strategies"]:
        if row.get("strategy_id") != KELTNER_ID:
            continue
        row.update({
            "child_id": KELTNER_CHILD,
            "adapter_id": "EMA20_RECLAIM_WITH_EMA50_TREND_OWNERSHIP_V2",
            **hashes,
            "boundary_ms": 1788048000000,
            "entry_rule": EXPECTED_RULE,
            "classifier_rule": None,
            "side": "long",
            "entry_timing": "next_bar_open",
            "exit_rule": "time_stop",
            "max_hold_bars": 12,
            "cost_bps_per_trade": 20.0,
        })
        row.pop("classifier_ema_semantics", None)
        row.pop("atr_semantics", None)

    contract["runner_id"] = "g5_clean_runner_keltner_v2_binding_fix_v1"
    contract["binding_provenance"] = {
        "binding_epoch": BINDING_EPOCH,
        "fix_reason": "RESTORE_CURRENT_TOP5_V2_KELTNER_OWNER_AND_REMOVE_NONCANONICAL_RANGE_CLASSIFIER",
        "canonical_top5_path": str(TOP5_SSOT_PATH.relative_to(ROOT)),
        "canonical_v2_freeze_path": str(CANONICAL_V2_PATH.relative_to(ROOT)),
        "canonical_keltner_child_id": KELTNER_CHILD,
        "canonical_keltner_entry_rule": EXPECTED_RULE,
        "previous_child_id": OLD_KELTNER_CHILD,
        "removed_noncanonical_classifier": old_keltner["classifier_rule"],
        "historical_backfill_forbidden": True,
        "state_log_reset": False,
        "corrected_child_state_keys_start_new": True,
        "prebinding_child_rows_excluded_from_corrected_shadow_gate": True,
    }

    frozen_assets = freeze.get("active_runner_assets") or {}
    names = [
        name for name, row in frozen_assets.items()
        if isinstance(row, Mapping) and row.get("strategy_id") == KELTNER_ID
    ]
    if len(names) != 1:
        raise base.IntegrityError("FREEZE_KELTNER_EXACTLY_ONE_REQUIRED")
    frozen_assets[names[0]].update({
        "child_id": KELTNER_CHILD,
        **hashes,
        "runtime_asset": "effective_contract#active_strategies/keltner_trend",
        "canonical_source": "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json#children/keltner_trend_main",
        "semantic_copy_only": True,
        "mutated": False,
    })
    freeze["binding_epoch"] = BINDING_EPOCH
    freeze["canonical_source_contract"] = str(CANONICAL_V2_PATH.relative_to(ROOT))

    prospective = _read(PROSPECTIVE_V2_PATH)
    lane = (prospective.get("lanes") or {}).get("keltner_trend_main") or {}
    pre_run = _read(PRE_FIX_RUN_PATH) if PRE_FIX_RUN_PATH.is_file() else {}
    diagnosis = base.receipt({
        "schema_version": "zel.g5.clean_runner.binding_fix.v1",
        "state": "FIX_APPLIED_CANONICAL_KELTNER_V2_BINDING",
        "binding_epoch": BINDING_EPOCH,
        "first_zero_stage": "RAW_SIGNAL_EMISSION",
        "pre_fix_latest_signal_count": int((pre_run.get("evaluation_counts") or {}).get("signal") or 0),
        "pre_fix_latest_opened": int((pre_run.get("lifecycle_counts") or {}).get("opened") or 0),
        "pre_fix_latest_ledger_written": int((pre_run.get("lifecycle_counts") or {}).get("ledger_written") or 0),
        "previous_keltner_child_id": old_keltner.get("child_id"),
        "previous_keltner_classifier_rule": old_keltner.get("classifier_rule"),
        "current_keltner_child_id": KELTNER_CHILD,
        "current_keltner_entry_rule": EXPECTED_RULE,
        "canonical_v2_keltner_closed_T_observed": int(lane.get("closed_T") or 0),
        "canonical_v2_keltner_net_pnl_bps_observed": (lane.get("metrics") or {}).get("net_pnl_bps"),
        "canonical_v2_keltner_net_expectancy_bps_observed": (lane.get("metrics") or {}).get("net_expectancy_bps"),
        "canonical_v2_keltner_profit_factor_observed": (lane.get("metrics") or {}).get("profit_factor"),
        "historical_backfill_performed": False,
        "formal_credit": 0,
        "strategy_retune": False,
        "threshold_sweep": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    })

    artifact_dir.mkdir(parents=True, exist_ok=True)
    contract_path = artifact_dir / "g5_clean_runner_contract_effective_v1.json"
    freeze_path = artifact_dir / "g5_clean_runner_strategy_freeze_effective_v1.json"
    base.write_json(contract_path, contract)
    base.write_json(freeze_path, freeze)
    base.write_json(artifact_dir / "g5_clean_runner_binding_fix_v1.json", diagnosis)
    return contract_path, freeze_path, diagnosis


class CurrentTop5FrozenStrategyAdapter(_ORIGINAL_ADAPTER):
    EXPECTED_CHILDREN = {
        "keltner_trend": KELTNER_CHILD,
        "supertrend_pullback": "supertrend_replacement_highvol_mom_long_4h_h12_v2",
        "break_and_continue": "break_replacement_breakout50_long_4h_h6_v2",
    }

    def evaluate(self, strategy_id: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if strategy_id != KELTNER_ID:
            return super().evaluate(strategy_id, rows)
        if strategy_id not in self.strategies:
            raise base.IntegrityError(f"UNKNOWN_STRATEGY:{strategy_id}")
        if len(rows) < int(self.contract["source"]["minimum_warmup_bars"]):
            raise base.IntegrityError(f"STRATEGY_WARMUP_INCOMPLETE:{strategy_id}:{len(rows)}")
        i = len(rows) - 1
        closes = [float(row["close"]) for row in rows]
        ema20 = base.windowed_ema(closes, 20, i)
        ema50 = base.windowed_ema(closes, 50, i)
        previous_ema20 = base.windowed_ema(closes, 20, i - 1)
        signal = bool(ema20 > ema50 and closes[i - 1] <= previous_ema20 and closes[i] > ema20)
        config = self.strategies[strategy_id]
        return {
            "strategy_id": strategy_id,
            "child_id": config["child_id"],
            "strategy_sha": config["strategy_sha"],
            "entry_sha": config["entry_sha"],
            "exit_sha": config["exit_sha"],
            "config_sha": config["config_sha"],
            "signal": signal,
            "side": config["side"] if signal else None,
            "result": "SIGNAL_EMITTED" if signal else "BAR_EVALUATED_NO_SIGNAL",
            "features": {
                "ema20": ema20,
                "ema50": ema50,
                "previous_ema20": previous_ema20,
                "parent_entry": signal,
            },
            "lookahead": 0,
        }


def current_binding_complete_closes(
    contract: Mapping[str, Any], store: base.StateStore
) -> tuple[list[int], int]:
    expected_child = {
        str(row["strategy_id"]): str(row["child_id"])
        for row in contract["active_strategies"]
    }
    evaluated = []
    for row in store.records():
        if row.get("status") != "EVALUATED":
            continue
        payload = row.get("payload") or {}
        strategy_id = str(payload.get("strategy_id") or "")
        if expected_child.get(strategy_id) != str(payload.get("child_id") or ""):
            continue
        evaluated.append(row)

    by_close: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in evaluated:
        by_close[int(row["payload"]["signal_bar_close_ts"])].append(row)

    expected_per_close = len(contract["active_strategies"]) * len(contract["source"]["symbols"])
    complete: list[int] = []
    for close_ts, rows in sorted(by_close.items()):
        keys = {
            (
                str(row["payload"]["strategy_id"]),
                str(row["payload"].get("symbol") or row["state_key"].split("|")[2]),
            )
            for row in rows
        }
        valid = all(
            row["payload"].get("source_seen") is True
            and row["payload"].get("closed_bar") is True
            and row["payload"].get("evaluated") is True
            and row["payload"].get("correct_child") is True
            and int(row["payload"].get("duplicate") or 0) == 0
            and int(row["payload"].get("lookahead") or 0) == 0
            and all(
                isinstance((row["payload"].get("telemetry") or {}).get(field), int)
                for field in base.TELEMETRY_FIELDS
            )
            for row in rows
        )
        if len(keys) == expected_per_close and valid:
            complete.append(close_ts)
    return complete, len(evaluated)


def _current_consecutive(complete: Sequence[int]) -> list[int]:
    consecutive: list[int] = []
    for close_ts in complete:
        if not consecutive or int(close_ts) - int(consecutive[-1]) == base.INTERVAL_MS:
            consecutive.append(int(close_ts))
        else:
            consecutive = [int(close_ts)]
    return consecutive


def build_runtime_artifacts_binding_safe(**kwargs: Any) -> dict[str, Any]:
    artifacts = _ORIGINAL_BUILD(**kwargs)
    contract = kwargs["contract"]
    store = kwargs["store"]
    artifact_dir = Path(kwargs["artifact_dir"])
    complete, binding_evaluated = current_binding_complete_closes(contract, store)
    consecutive = _current_consecutive(complete)
    last_three = consecutive[-3:] if len(consecutive) >= 3 else consecutive
    shadow_pass = len(last_three) >= 3

    shadow_core = dict(artifacts["shadow"])
    shadow_core.pop("receipt_sha256", None)
    shadow_core.update({
        "state": "CLEAN_RUNNER_SHADOW_PASS" if shadow_pass else "CLEAN_RUNNER_SHADOW_ACTIVE",
        "binding_epoch": BINDING_EPOCH,
        "binding_gate_current_child_only": True,
        "prebinding_child_rows_excluded": True,
        "binding_evaluation_receipts": binding_evaluated,
        "complete_bar_count": len(complete),
        "consecutive_complete_bar_count": len(consecutive),
        "bar1": base.utc(last_three[0]) if len(last_three) >= 1 else None,
        "bar2": base.utc(last_three[1]) if len(last_three) >= 2 else None,
        "bar3": base.utc(last_three[2]) if len(last_three) >= 3 else None,
        "shadow_3bar_pass": shadow_pass,
    })
    shadow = base.receipt(shadow_core)

    cutover_core = dict(artifacts["cutover"])
    cutover_core.pop("receipt_sha256", None)
    telemetry = artifacts["telemetry"]
    eligible = shadow_pass and int(telemetry.get("missing_tuples") or 0) == 0
    cutover_core.update({
        "state": "CLEAN_RUNNER_CUTOVER_READY" if eligible else "WAIT_CLEAN_RUNNER_3BAR",
        "eligible": eligible,
        "binding_epoch": BINDING_EPOCH,
        "binding_gate_current_child_only": True,
        "executed": False,
        "clean_runner_authority": False,
        "formal_credit": 0,
    })
    cutover = base.receipt(cutover_core)

    base.write_json(artifact_dir / "g5_clean_runner_shadow_v1.json", shadow)
    base.write_json(artifact_dir / "g5_clean_runner_cutover_receipt_v1.json", cutover)
    artifacts["shadow"] = shadow
    artifacts["cutover"] = cutover
    return artifacts


def validate_contract_assets_binding_safe() -> dict[str, Any]:
    _assert_top5_owner()
    _canonical_keltner()
    result = _ORIGINAL_VALIDATE()
    result_core = dict(result)
    result_core.pop("receipt_sha256", None)
    result_core["binding_epoch"] = BINDING_EPOCH
    result_core["canonical_keltner_v2_binding"] = True
    result_core["noncanonical_classifier_absent"] = True
    return base.receipt(result_core)


def install(artifact_dir: Path) -> dict[str, Any]:
    contract_path, freeze_path, diagnosis = materialize_effective_assets(artifact_dir)
    base.CONTRACT_PATH = contract_path
    base.FREEZE_PATH = freeze_path
    base.FrozenStrategyAdapter = CurrentTop5FrozenStrategyAdapter
    base.validate_contract_assets = validate_contract_assets_binding_safe
    base.build_runtime_artifacts = build_runtime_artifacts_binding_safe
    return diagnosis


def _artifact_dir_from_argv(argv: Sequence[str]) -> Path:
    for index, value in enumerate(argv):
        if value == "--artifact-dir" and index + 1 < len(argv):
            return Path(argv[index + 1])
    return base.DEFAULT_ARTIFACT_DIR


def main() -> int:
    install(_artifact_dir_from_argv(sys.argv[1:]))
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())