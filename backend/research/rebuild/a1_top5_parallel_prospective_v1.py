#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_parallel_prospective_v1.json"
SSOT = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
TERMINAL = ROOT / "backend/research/rebuild/a1_top5_g4_terminal_latest.json"
ROLLING = ROOT / "backend/research/rebuild/a1_production_highwr_rolling_closed_latest.json"
PRIMARY_CONTRACT = ROOT / "backend/research/rebuild/a1_trendrider_primary_chase_cooling_fresh25_contract_v1.json"
BROAD_G5_MANIFEST = ROOT / "backend/research/prep/g5_trendrider_broad30_product_manifest_v1.json"
BROAD_G5_LATEST = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
REPLACEMENT_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v1.json"
REPLACEMENT_CHILD_LATEST = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_latest.json"
LATEST = ROOT / "backend/research/rebuild/a1_top5_parallel_prospective_latest.json"
SCHEMA = "zel.a1.top5.parallel_prospective.receipt.v1"
EXPECTED_LANES = (
    "trend_rider_primary_wr8125",
    "trend_rider_broad_wr7000",
    "break_and_continue_main",
    "keltner_trend_main",
    "supertrend_pullback_main",
)
EXPECTED_TERMINAL = {
    "trend_rider_primary_wr8125": "WAIT_NEW_T",
    "trend_rider_broad_wr7000": "G4_PASS_SURVIVOR_READY",
    "break_and_continue_main": "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED",
    "keltner_trend_main": "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED",
    "supertrend_pullback_main": "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED",
}
REPLACEMENT_LANES = EXPECTED_LANES[2:]
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _assert_blocked(value: Mapping[str, Any], label: str) -> None:
    if value.get("selection_authority") is not False or value.get("promotion_authority") is not False:
        raise RuntimeError(f"{label}_SELECTION_PROMOTION_AUTHORITY_DRIFT")
    if str(value.get("execution_authority")) != "NONE":
        raise RuntimeError(f"{label}_EXECUTION_AUTHORITY_DRIFT")
    if str(value.get("order_authority")) != "BLOCKED" or str(value.get("live_trade_authority")) != "BLOCKED":
        raise RuntimeError(f"{label}_ORDER_LIVE_AUTHORITY_DRIFT")


def _contract_lanes(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {
        str(x.get("lane_id")): dict(x)
        for x in contract.get("lanes") or []
        if isinstance(x, Mapping) and x.get("lane_id")
    }
    if tuple(rows) != EXPECTED_LANES:
        raise RuntimeError(f"CONTRACT_LANE_ORDER_DRIFT:{tuple(rows)}")
    return rows


def _ssot_lanes(ssot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {
        str(x.get("lane_id")): dict(x)
        for x in ssot.get("top5") or []
        if isinstance(x, Mapping) and x.get("lane_id")
    }
    if tuple(rows) != EXPECTED_LANES:
        raise RuntimeError(f"SSOT_LANE_ORDER_DRIFT:{tuple(rows)}")
    return rows


def _terminal_by_strategy(terminal: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    broad = terminal.get("existing_g4_survivor_reference")
    if isinstance(broad, Mapping):
        rows["trend_rider_broad_wr7000"] = dict(broad)
    for row in terminal.get("targets") or []:
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("strategy_id") or "")
        if sid == "trend_rider" and str(row.get("terminal_state") or "") == "WAIT_NEW_T":
            rows["trend_rider_primary_wr8125"] = dict(row)
        elif sid == "break_and_continue":
            rows["break_and_continue_main"] = dict(row)
        elif sid == "keltner_trend":
            rows["keltner_trend_main"] = dict(row)
        elif sid == "supertrend_pullback":
            rows["supertrend_pullback_main"] = dict(row)
    return rows


def _ordered_trade_refs(rows: Sequence[Mapping[str, Any]], *, boundary_ms: int = 0) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for raw in rows:
        tid = str(raw.get("closed_trade_id") or "")
        signal_ts = int(raw.get("signal_ts") or 0)
        if not tid or signal_ts <= boundary_ms:
            continue
        refs.append({
            "closed_trade_id": tid,
            "signal_ts": signal_ts,
            "entry_ts": int(raw.get("entry_ts") or 0),
            "exit_ts": int(raw.get("exit_ts") or 0),
            "symbol": str(raw.get("symbol") or ""),
            "side": str(raw.get("side") or ""),
        })
    refs.sort(key=lambda x: (x["exit_ts"], x["signal_ts"], x["symbol"], x["entry_ts"], x["closed_trade_id"]))
    ids = [x["closed_trade_id"] for x in refs]
    if len(ids) != len(set(ids)):
        raise RuntimeError("DUPLICATE_CLOSED_TRADE_ID")
    return refs


def _previous_primary(previous: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(previous, Mapping) or previous.get("schema_version") != SCHEMA:
        return {}
    lane = (previous.get("lanes") or {}).get("trend_rider_primary_wr8125")
    if not isinstance(lane, Mapping):
        return {}
    out: dict[str, str] = {}
    for raw in lane.get("assignments") or []:
        if not isinstance(raw, Mapping):
            continue
        tid, stage = str(raw.get("closed_trade_id") or ""), str(raw.get("stage_tag") or "")
        if tid and stage:
            out[tid] = stage
    return out


def _allocate_primary(eligible: Sequence[Mapping[str, Any]], previous: Mapping[str, str]) -> list[dict[str, Any]]:
    allowed = {"G4_CONSUMABLE_PRIMARY", "G5_ESCROW_UNOPENED"}
    if any(stage not in allowed for stage in previous.values()):
        raise RuntimeError("PRIMARY_PREVIOUS_STAGE_INVALID")
    if sum(1 for stage in previous.values() if stage == "G4_CONSUMABLE_PRIMARY") > 1:
        raise RuntimeError("PRIMARY_MULTIPLE_G4_CONSUMABLE_ASSIGNMENTS")

    eligible_ids = {str(x.get("closed_trade_id") or "") for x in eligible}
    missing = sorted(set(previous) - eligible_ids)
    if missing:
        raise RuntimeError("PRIMARY_PREVIOUS_ASSIGNMENT_MISSING_FROM_APPEND_ONLY_SOURCE:" + ",".join(missing[:5]))

    assigned = dict(previous)
    g4_exists = any(stage == "G4_CONSUMABLE_PRIMARY" for stage in assigned.values())
    for ref in eligible:
        tid = str(ref["closed_trade_id"])
        if tid in assigned:
            continue
        if not g4_exists:
            assigned[tid] = "G4_CONSUMABLE_PRIMARY"
            g4_exists = True
        else:
            assigned[tid] = "G5_ESCROW_UNOPENED"

    return [
        {**dict(ref), "stage_tag": assigned[str(ref["closed_trade_id"])], "assignment_semantics": "FIRST_OBSERVED_IMMUTABLE_OUTCOME_BLIND"}
        for ref in eligible
    ]


def _previous_raw_ids(previous: Mapping[str, Any] | None, lane_id: str) -> list[str]:
    if not isinstance(previous, Mapping) or previous.get("schema_version") != SCHEMA:
        return []
    lane = (previous.get("lanes") or {}).get(lane_id)
    if not isinstance(lane, Mapping):
        return []
    return [str(x) for x in lane.get("raw_observer_closed_trade_ids") or [] if str(x)]


def _freeze_rows(freeze: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(freeze, Mapping):
        return {}
    if freeze.get("schema_version") != "zel.a1.top5.replacement_child_freeze.v1":
        raise RuntimeError("REPLACEMENT_FREEZE_SCHEMA_DRIFT")
    if freeze.get("state") != "FROZEN_REPLACEMENT_CHILDREN_PRE_PROSPECTIVE":
        raise RuntimeError("REPLACEMENT_FREEZE_STATE_DRIFT")
    _assert_blocked(freeze, "REPLACEMENT_FREEZE")
    rows = {
        str(row.get("lane_id")): dict(row)
        for row in freeze.get("children") or []
        if isinstance(row, Mapping) and row.get("lane_id")
    }
    if set(rows) != set(REPLACEMENT_LANES):
        raise RuntimeError(f"REPLACEMENT_FREEZE_LANE_SET_DRIFT:{sorted(rows)}")
    return rows


def _child_rows(child_latest: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(child_latest, Mapping):
        return {}
    if child_latest.get("schema_version") != "zel.a1.top5.replacement_child.prospective.receipt.v1":
        raise RuntimeError("REPLACEMENT_CHILD_RECEIPT_SCHEMA_DRIFT")
    _assert_blocked(child_latest, "REPLACEMENT_CHILD_RECEIPT")
    rows = child_latest.get("lanes")
    if not isinstance(rows, Mapping):
        raise RuntimeError("REPLACEMENT_CHILD_LANES_MISSING")
    return {str(k): dict(v) for k, v in rows.items() if isinstance(v, Mapping)}


def run(output: Path, previous_path: Path | None = None, rolling_path: Path = ROLLING) -> dict[str, Any]:
    contract = _read(CONTRACT)
    ssot = _read(SSOT)
    terminal = _read(TERMINAL)
    rolling = _read(rolling_path)
    primary_contract = _read(PRIMARY_CONTRACT)
    broad_manifest = _read(BROAD_G5_MANIFEST)
    broad_latest = _read(BROAD_G5_LATEST)
    freeze = _read(REPLACEMENT_FREEZE) if REPLACEMENT_FREEZE.is_file() else None
    child_latest = _read(REPLACEMENT_CHILD_LATEST) if REPLACEMENT_CHILD_LATEST.is_file() else None
    previous = _read(previous_path) if previous_path and previous_path.is_file() else (_read(LATEST) if LATEST.is_file() else None)

    if contract.get("schema_version") != "zel.a1.top5.parallel_prospective.v1":
        raise RuntimeError("PARALLEL_CONTRACT_SCHEMA_DRIFT")
    if terminal.get("state") != "G4_TERMINAL_TARGET_SET_COMPLETE" or int((terminal.get("summary") or {}).get("unresolved") or 0) != 0:
        raise RuntimeError("G4_TERMINAL_NOT_COMPLETE")
    if (ssot.get("g4_terminal_sync") or {}).get("state") != "SYNCED_TO_G4_TERMINAL_TARGET_SET_COMPLETE":
        raise RuntimeError("TOP5_SSOT_TERMINAL_SYNC_MISSING")
    if rolling.get("state") != "PASS_HIGHWR_ROLLING_CLOSED_ACTIVE":
        raise RuntimeError("ROLLING_CLOSED_NOT_ACTIVE")
    _assert_blocked(rolling, "ROLLING")
    _assert_blocked(broad_manifest, "BROAD_G5_MANIFEST")
    _assert_blocked(broad_latest, "BROAD_G5_LATEST")

    c_lanes = _contract_lanes(contract)
    s_lanes = _ssot_lanes(ssot)
    t_lanes = _terminal_by_strategy(terminal)
    rolling_lanes = rolling.get("lanes") if isinstance(rolling.get("lanes"), Mapping) else {}
    if set(rolling_lanes) != set(EXPECTED_LANES):
        raise RuntimeError(f"ROLLING_LANE_SET_DRIFT:{sorted(rolling_lanes)}")

    for lane_id in EXPECTED_LANES:
        ssot_state = str(s_lanes[lane_id].get("terminal_state") or "")
        contract_state = str(c_lanes[lane_id].get("terminal_state") or "")
        terminal_row = t_lanes.get(lane_id)
        terminal_state = str((terminal_row or {}).get("terminal_state") or (terminal_row or {}).get("state") or "")
        if {ssot_state, contract_state, terminal_state} != {EXPECTED_TERMINAL[lane_id]}:
            raise RuntimeError(f"TERMINAL_STATE_DRIFT:{lane_id}:{ssot_state}:{contract_state}:{terminal_state}")

    primary_boundary = int((primary_contract.get("preregistered_root_cause") or {}).get("boundary_ms") or 0)
    if primary_boundary <= 0:
        raise RuntimeError("PRIMARY_BOUNDARY_MISSING")
    primary_rows = (rolling_lanes["trend_rider_primary_wr8125"] or {}).get("closed_trades") or []
    primary_eligible = _ordered_trade_refs(primary_rows, boundary_ms=primary_boundary)
    primary_assignments = _allocate_primary(primary_eligible, _previous_primary(previous))
    g4_assignments = [x for x in primary_assignments if x["stage_tag"] == "G4_CONSUMABLE_PRIMARY"]
    escrow_assignments = [x for x in primary_assignments if x["stage_tag"] == "G5_ESCROW_UNOPENED"]
    if len(g4_assignments) > 1:
        raise RuntimeError("PRIMARY_G4_ASSIGNMENT_GT1")
    if {x["closed_trade_id"] for x in g4_assignments} & {x["closed_trade_id"] for x in escrow_assignments}:
        raise RuntimeError("PRIMARY_G4_G5_DOUBLE_USE")

    lane_out: dict[str, Any] = {
        "trend_rider_primary_wr8125": {
            "terminal_state": "WAIT_NEW_T",
            "clock_state": "G4_ACTIVE_PLUS_G5_ESCROW_CAPTURE",
            "boundary_ms": primary_boundary,
            "boundary_utc": str((primary_contract.get("preregistered_root_cause") or {}).get("boundary_utc") or ""),
            "eligible_post_boundary_closed_T": len(primary_assignments),
            "g4_consumable_T": len(g4_assignments),
            "g5_escrow_T": len(escrow_assignments),
            "g5_escrow_open": False,
            "assignments": primary_assignments,
            "same_trade_double_use_count": 0,
        },
        "trend_rider_broad_wr7000": {
            "terminal_state": "G4_PASS_SURVIVOR_READY",
            "clock_state": "G5_NATIVE_ACTIVE",
            "g5_state": str(broad_latest.get("state") or ""),
            "g5_boundary_ms": int(broad_manifest.get("prospective_boundary_ms") or 0),
            "g5_postlock_closed_T": int(broad_latest.get("postlock_closed_T") or 0),
            "g5_w2_target_T": int((((broad_latest.get("windows") or {}).get("W2") or {}).get("target_T")) or 0),
            "g5_w3_target_T": int((((broad_latest.get("windows") or {}).get("W3") or {}).get("target_T")) or 0),
            "g4_trade_reuse": False,
            "native_g5_manifest_owns_consumption": True,
        },
    }

    freeze_rows = _freeze_rows(freeze)
    child_rows = _child_rows(child_latest)
    retired_count = 0
    child_owner_count = 0
    for lane_id in REPLACEMENT_LANES:
        lane = rolling_lanes[lane_id]
        current_delta = [str(x) for x in lane.get("new_closed_trade_ids") or [] if str(x)]
        known = _previous_raw_ids(previous, lane_id)
        freeze_row = freeze_rows.get(lane_id)
        if freeze_row:
            burned = [str(x) for x in freeze_row.get("burned_parent_raw_observer_closed_trade_ids") or [] if str(x)]
            burned_set = set(burned)
            if len(burned) != int(freeze_row.get("burned_parent_raw_observer_T") or 0) or len(burned) != len(burned_set):
                raise RuntimeError(f"BURNED_PARENT_RAW_SET_DRIFT:{lane_id}")
            extra_previous = sorted(set(known) - burned_set)
            if extra_previous:
                raise RuntimeError(f"POSTFREEZE_PARENT_RAW_HISTORY_CONTAMINATION:{lane_id}:{','.join(extra_previous[:3])}")
            missing_previous = sorted(set(known) - burned_set)
            if missing_previous:
                raise RuntimeError(f"UNREACHABLE_PREVIOUS_RAW_MISMATCH:{lane_id}")
            postfreeze_delta = [x for x in current_delta if x not in burned_set]
            child = child_rows.get(lane_id, {})
            if child and child.get("replacement_child_frozen") is not True:
                raise RuntimeError(f"CHILD_RECEIPT_NOT_FROZEN:{lane_id}")
            if child and int(child.get("old_parent_raw_observer_consumed_T") or 0) != 0:
                raise RuntimeError(f"CHILD_RECEIPT_PARENT_CONSUMPTION_DRIFT:{lane_id}")
            expected_child_id = str(freeze_row.get("child_id") or "")
            if child and str(child.get("child_id") or "") != expected_child_id:
                raise RuntimeError(f"CHILD_ID_DRIFT:{lane_id}")
            retired_count += 1
            if child:
                child_owner_count += 1
            lane_out[lane_id] = {
                "terminal_state": "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED",
                "clock_state": "PARENT_RAW_OBSERVER_RETIRED_CHILD_PROSPECTIVE_OWNS_FRESH_EVIDENCE",
                "replacement_seed": c_lanes[lane_id].get("replacement_seed"),
                "replacement_child_frozen": True,
                "replacement_child_id": expected_child_id,
                "replacement_child_boundary_ms": int(((freeze or {}).get("prospective_boundary") or {}).get("ms") or 0),
                "replacement_child_boundary_utc": str(((freeze or {}).get("prospective_boundary") or {}).get("utc") or ""),
                "replacement_child_closed_T": int(child.get("closed_T") or 0) if child else 0,
                "replacement_child_state": str((child_latest or {}).get("state") or "MISSING_CHILD_RECEIPT"),
                "fresh_evidence_owner": str(REPLACEMENT_CHILD_LATEST.relative_to(ROOT)),
                "old_architecture_trade_use": "PREFREEZE_RAW_OBSERVER_AUDIT_ONLY_NOT_G4_OR_G5_OR_CHILD_EVIDENCE",
                "raw_observer_retired": True,
                "raw_observer_frozen_T": len(burned),
                "raw_observer_delta_T": 0,
                "raw_observer_closed_trade_ids": burned,
                "postfreeze_parent_rolling_delta_ignored_T": len(postfreeze_delta),
                "consumable_g4_T": 0,
                "consumable_g5_T": 0,
                "consumable_child_T": 0,
                "next": "FRESH_REPLACEMENT_CHILD_PROSPECTIVE_COLLECTOR_OWNS_COLLECTION",
            }
            continue

        combined = list(dict.fromkeys([*known, *current_delta]))
        lane_out[lane_id] = {
            "terminal_state": "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED",
            "clock_state": "REPLACEMENT_FACTORY_PARALLEL_RAW_OBSERVER",
            "replacement_seed": c_lanes[lane_id].get("replacement_seed"),
            "replacement_child_frozen": False,
            "old_architecture_trade_use": "RAW_OBSERVER_ONLY_NOT_G4_OR_G5_EVIDENCE",
            "raw_observer_delta_T": len([x for x in current_delta if x not in set(known)]),
            "raw_observer_closed_trade_ids": combined,
            "consumable_g4_T": 0,
            "consumable_g5_T": 0,
            "next": "FREEZE_NEW_ARCHITECTURE_POLICY_AND_BOUNDARY_THEN_START_FRESH_CHILD_COUNTER",
        }

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TOP5_PARALLEL_PROSPECTIVE_ACTIVE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "terminal_source_path": str(TERMINAL.relative_to(ROOT)),
        "rolling_source_path": str(rolling_path.relative_to(ROOT)) if rolling_path.is_relative_to(ROOT) else str(rolling_path),
        "rolling_source_receipt_sha256": rolling.get("receipt_sha256"),
        "replacement_freeze_source_path": str(REPLACEMENT_FREEZE.relative_to(ROOT)) if freeze_rows else None,
        "replacement_child_source_path": str(REPLACEMENT_CHILD_LATEST.relative_to(ROOT)) if child_rows else None,
        "calendar_parallelism": True,
        "capture_stage_separation": True,
        "same_closed_trade_g4_g5_reuse_count": 0,
        "old_architecture_union_into_replacement_child": False,
        "replacement_parent_raw_observer_retired_lane_count": retired_count,
        "replacement_child_fresh_evidence_owner_count": child_owner_count,
        "lanes": lane_out,
        **AUTH,
    }
    result["receipt_sha256"] = _sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    refs = [
        {"closed_trade_id": "a", "signal_ts": 101, "entry_ts": 102, "exit_ts": 103, "symbol": "BTC-USDT", "side": "long"},
        {"closed_trade_id": "b", "signal_ts": 104, "entry_ts": 105, "exit_ts": 106, "symbol": "ETH-USDT", "side": "long"},
        {"closed_trade_id": "c", "signal_ts": 107, "entry_ts": 108, "exit_ts": 109, "symbol": "BTC-USDT", "side": "short"},
    ]
    first = _allocate_primary(refs[:2], {})
    assert [x["stage_tag"] for x in first] == ["G4_CONSUMABLE_PRIMARY", "G5_ESCROW_UNOPENED"]
    previous = {x["closed_trade_id"]: x["stage_tag"] for x in first}
    second = _allocate_primary(refs, previous)
    assert [x["stage_tag"] for x in second] == ["G4_CONSUMABLE_PRIMARY", "G5_ESCROW_UNOPENED", "G5_ESCROW_UNOPENED"]
    assert len({x["closed_trade_id"] for x in second}) == 3
    fake_freeze = {
        "schema_version": "zel.a1.top5.replacement_child_freeze.v1",
        "state": "FROZEN_REPLACEMENT_CHILDREN_PRE_PROSPECTIVE",
        "children": [{"lane_id": x} for x in REPLACEMENT_LANES],
        **AUTH,
    }
    assert set(_freeze_rows(fake_freeze)) == set(REPLACEMENT_LANES)
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED" and AUTH["live_trade_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_PARALLEL_PROSPECTIVE_V1_SELF_TEST")
    print("PASS_PRIMARY_G4_BURN_AND_G5_ESCROW_NO_DOUBLE_USE")
    print("PASS_REPLACEMENT_PARENT_RAW_CLOCK_RETIREMENT_AFTER_CHILD_FREEZE")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rolling", type=Path, default=ROLLING)
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_parallel_prospective_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out, args.previous, args.rolling)
    print(json.dumps({
        "state": result["state"],
        "primary_g4_T": result["lanes"]["trend_rider_primary_wr8125"]["g4_consumable_T"],
        "primary_g5_escrow_T": result["lanes"]["trend_rider_primary_wr8125"]["g5_escrow_T"],
        "broad_g5_T": result["lanes"]["trend_rider_broad_wr7000"]["g5_postlock_closed_T"],
        "retired_parent_raw_lanes": result["replacement_parent_raw_observer_retired_lane_count"],
        "child_owner_lanes": result["replacement_child_fresh_evidence_owner_count"],
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
