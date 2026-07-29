from __future__ import annotations

import argparse
import copy
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "strategy11.pre_shadow_path_optimize_plan.v1"
VERSION = "STRATEGY11_PRE_SHADOW_PATH_OPTIMIZE_PLANNER_V1"
AXES = (
    "ENTRY_CONTEXT_GATE",
    "CANDLE_STRUCTURE_GATE",
    "TREND_REGIME_GATE",
    "VOLATILITY_GATE",
    "VOLUME_FLOW_GATE",
    "MOMENTUM_GATE",
    "SESSION_GATE",
    "SYMBOL_EXCLUSION",
    "STOP",
    "TARGET",
    "BREAKEVEN",
    "PARTIAL",
    "MFE_TRAILING",
    "TIME_STOP",
)
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


class PathPlannerError(ValueError):
    pass


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PathPlannerError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PathPlannerError(f"STRING_REQUIRED:{name}")
    return value.strip()


def integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PathPlannerError(f"INTEGER_REQUIRED:{name}")
    return value


def number(value: Any, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PathPlannerError(f"NUMBER_REQUIRED:{name}")
    result = float(value)
    if not math.isfinite(result):
        raise PathPlannerError(f"NUMBER_NOT_FINITE:{name}")
    if minimum is not None and result < minimum:
        raise PathPlannerError(f"NUMBER_BELOW_MIN:{name}")
    return result


def assert_safety(value: Mapping[str, Any], name: str) -> None:
    for key, expected in SAFETY.items():
        if value.get(key) != expected:
            raise PathPlannerError(f"SAFETY_MISMATCH:{name}:{key}")


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(value)
    assert_safety(policy, "policy")
    if policy.get("schema_version") != "strategy11.pre_shadow_path_optimize_policy.v1":
        raise PathPlannerError("POLICY_SCHEMA_MISMATCH")
    minimum_event_count = integer(policy.get("minimum_event_count"), "minimum_event_count", 1)
    min_count = integer(policy.get("fingerprint_min_count"), "fingerprint_min_count", 1)
    min_share = number(policy.get("fingerprint_min_share"), "fingerprint_min_share", 0.0)
    concentration_count = integer(policy.get("concentration_min_loss_count"), "concentration_min_loss_count", 1)
    concentration_share = number(policy.get("concentration_min_share"), "concentration_min_share", 0.0)
    generation_limit = integer(policy.get("max_axis_generations_per_data_epoch"), "max_axis_generations_per_data_epoch", 1)
    if generation_limit > 2:
        raise PathPlannerError("AXIS_GENERATION_LIMIT_ABOVE_TWO")
    if min_share > 1.0 or concentration_share > 1.0:
        raise PathPlannerError("SHARE_LIMIT_INVALID")
    thresholds = policy.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise PathPlannerError("THRESHOLDS_OBJECT_REQUIRED")
    required_thresholds = {
        "entry_too_early_first3_mae_r",
        "entry_too_late_pre_entry_mfe_r",
        "entry_too_late_post_entry_mfe_r_max",
        "stop_too_tight_post_stop_mfe_r",
        "stop_too_wide_distance_atr",
        "breakeven_missed_mfe_r",
        "mfe_giveback_mfe_r",
        "target_undershoot_post_exit_mfe_r",
        "time_exposure_bars",
        "time_exposure_mfe_r_max",
        "minimum_first3_observation_bars",
        "minimum_post_exit_observation_bars",
    }
    if set(thresholds) != required_thresholds:
        raise PathPlannerError("THRESHOLD_KEYS_MISMATCH")
    normalized_thresholds = {
        key: integer(value, f"thresholds.{key}", 0) if key.endswith("_bars") else number(value, f"thresholds.{key}", 0.0)
        for key, value in thresholds.items()
    }
    priority = policy.get("fingerprint_priority")
    if not isinstance(priority, list) or not priority:
        raise PathPlannerError("FINGERPRINT_PRIORITY_REQUIRED")
    priority = [text(value, "fingerprint_priority[]").upper() for value in priority]
    if len(priority) != len(set(priority)):
        raise PathPlannerError("FINGERPRINT_PRIORITY_DUPLICATE")
    catalog_raw = policy.get("candidate_catalog")
    if not isinstance(catalog_raw, Mapping):
        raise PathPlannerError("CANDIDATE_CATALOG_REQUIRED")
    if set(priority) != set(catalog_raw):
        raise PathPlannerError("CATALOG_PRIORITY_KEYS_MISMATCH")
    catalog: dict[str, list[dict[str, Any]]] = {}
    candidate_ids: set[str] = set()
    for fingerprint, rows in catalog_raw.items():
        if not isinstance(rows, list) or not rows:
            raise PathPlannerError(f"CATALOG_ROWS_REQUIRED:{fingerprint}")
        normalized = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or set(row) != {"candidate_id", "axis", "parameters", "why"}:
                raise PathPlannerError(f"CATALOG_ROW_SHAPE:{fingerprint}:{index}")
            candidate_id = text(row["candidate_id"], f"catalog.{fingerprint}.candidate_id")
            if candidate_id in candidate_ids:
                raise PathPlannerError(f"CANDIDATE_ID_DUPLICATE:{candidate_id}")
            candidate_ids.add(candidate_id)
            axis = text(row["axis"], f"catalog.{fingerprint}.axis").upper()
            if axis not in AXES:
                raise PathPlannerError(f"CATALOG_AXIS_UNKNOWN:{axis}")
            parameters = row["parameters"]
            if not isinstance(parameters, Mapping) or not parameters:
                raise PathPlannerError(f"CATALOG_PARAMETERS_REQUIRED:{candidate_id}")
            normalized.append({
                "candidate_id": candidate_id,
                "axis": axis,
                "parameters": copy.deepcopy(dict(parameters)),
                "why": text(row["why"], f"catalog.{fingerprint}.why"),
            })
        catalog[str(fingerprint).upper()] = normalized
    normalized = {
        "schema_version": policy["schema_version"],
        "policy_id": text(policy.get("policy_id"), "policy_id"),
        "minimum_event_count": minimum_event_count,
        "fingerprint_min_count": min_count,
        "fingerprint_min_share": min_share,
        "concentration_min_loss_count": concentration_count,
        "concentration_min_share": concentration_share,
        "max_axis_generations_per_data_epoch": generation_limit,
        "thresholds": normalized_thresholds,
        "fingerprint_priority": priority,
        "candidate_catalog": catalog,
        **SAFETY,
    }
    normalized["policy_sha"] = canonical_sha(normalized)
    return normalized


def validate_triage(value: Mapping[str, Any]) -> dict[str, Any]:
    triage = dict(value)
    assert_safety(triage, "triage")
    if triage.get("state") != "PASS_SOURCE_BOUND_REPLAY_TRIAGE":
        raise PathPlannerError("TRIAGE_NOT_PASS")
    rows = triage.get("rows")
    if not isinstance(rows, list):
        raise PathPlannerError("TRIAGE_ROWS_REQUIRED")
    if int(triage.get("duplicate_strategy_axis_config_data_count") or 0) != 0:
        raise PathPlannerError("TRIAGE_DUPLICATE_AXIS_DATA")
    return triage


def validate_ledger(value: Mapping[str, Any]) -> dict[str, Any]:
    ledger = dict(value)
    assert_safety(ledger, "search_ledger")
    rows = ledger.get("rows")
    if not isinstance(rows, list):
        raise PathPlannerError("SEARCH_LEDGER_ROWS_REQUIRED")
    if int(ledger.get("duplicate_strategy_axis_data_runs") or 0) != 0:
        raise PathPlannerError("SEARCH_LEDGER_DUPLICATE_AXIS_DATA")
    return ledger


def select_basis(triage_row: Mapping[str, Any]) -> tuple[str | None, str, list[str]]:
    survivors = [str(value) for value in triage_row.get("l090_survivor_ids") or []]
    near = [str(value) for value in triage_row.get("near_pass_ids") or []]
    if len(survivors) > 1:
        return None, "HOLD_BASIS_AMBIGUITY", ["MULTIPLE_L090_SURVIVORS"]
    if len(survivors) == 1:
        return survivors[0], "L090_SURVIVOR", []
    if len(near) > 1:
        return None, "HOLD_BASIS_AMBIGUITY", ["MULTIPLE_NEAR_PASS_VARIANTS"]
    if len(near) == 1:
        return near[0], "NEAR_PASS_LOSS_SHAPE", []
    return "NO_CHANGE_CONTROL", "CONTROL_FALLBACK", []


def load_bundle(path_root: Path, strategy_id: str, variant_id: str) -> dict[str, Any]:
    path = path_root / strategy_id / variant_id / "path_evidence.json"
    if not path.exists():
        raise PathPlannerError(f"PATH_BUNDLE_MISSING:{strategy_id}:{variant_id}")
    bundle = read_json(path)
    assert_safety(bundle, f"path_bundle:{strategy_id}:{variant_id}")
    if bundle.get("strategy_id") != strategy_id or bundle.get("variant_id") != variant_id:
        raise PathPlannerError(f"PATH_BUNDLE_ID_MISMATCH:{strategy_id}:{variant_id}")
    if bundle.get("state") not in {"PASS_TRADE_PATH_EVIDENCE", "WAIT_NO_TRADES"}:
        raise PathPlannerError(f"PATH_BUNDLE_NOT_PASS:{strategy_id}:{variant_id}:{bundle.get('state')}")
    events = bundle.get("events")
    if not isinstance(events, list):
        raise PathPlannerError(f"PATH_EVENTS_REQUIRED:{strategy_id}:{variant_id}")
    if int(bundle.get("duplicate_event_count") or 0) != 0:
        raise PathPlannerError(f"PATH_DUPLICATE_EVENTS:{strategy_id}:{variant_id}")
    return bundle


def concentration(events: Sequence[Mapping[str, Any]], key: str, policy: Mapping[str, Any]) -> dict[str, Any] | None:
    losses = [row for row in events if float(row["pnl_r"]) < 0.0]
    if len(losses) < policy["concentration_min_loss_count"]:
        return None
    counts = Counter(str(row[key]) for row in losses)
    value, count = counts.most_common(1)[0]
    share = count / len(losses)
    if share < policy["concentration_min_share"]:
        return None
    event_ids = sorted(str(row["event_id"]) for row in losses if str(row[key]) == value)
    return {
        "event_count": count,
        "event_share": share,
        "loss_r_abs": sum(abs(min(0.0, float(row["pnl_r"]))) for row in losses if str(row[key]) == value),
        "dominant_value": value,
        "event_ids": event_ids,
        "support_sha": canonical_sha(event_ids),
    }


def fingerprint_events(events: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    threshold = policy["thresholds"]
    matched: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in events:
        pnl_r = float(row["pnl_r"])
        mfe_r = float(row["mfe_r"])
        if (
            pnl_r < 0.0
            and int(row["first3_observation_bars"]) >= threshold["minimum_first3_observation_bars"]
            and float(row["first3_mae_r"]) >= threshold["entry_too_early_first3_mae_r"]
        ):
            matched["ENTRY_TOO_EARLY"].append(row)
        if (
            float(row["pre_entry_mfe_r"]) >= threshold["entry_too_late_pre_entry_mfe_r"]
            and mfe_r <= threshold["entry_too_late_post_entry_mfe_r_max"]
        ):
            matched["ENTRY_TOO_LATE"].append(row)
        if (
            str(row["exit_reason"]).upper() in {"SL", "STOP", "STOP_LOSS"}
            and int(row["post_exit_observation_bars"]) >= threshold["minimum_post_exit_observation_bars"]
            and float(row["post_stop_mfe_r"]) >= threshold["stop_too_tight_post_stop_mfe_r"]
        ):
            matched["STOP_TOO_TIGHT"].append(row)
        if pnl_r < 0.0 and float(row["stop_distance_atr"]) >= threshold["stop_too_wide_distance_atr"]:
            matched["STOP_TOO_WIDE"].append(row)
        if pnl_r <= 0.0 and mfe_r >= threshold["mfe_giveback_mfe_r"]:
            matched["MFE_GIVEBACK"].append(row)
        elif pnl_r < 0.0 and mfe_r >= threshold["breakeven_missed_mfe_r"]:
            matched["BREAKEVEN_MISSED"].append(row)
        if (
            str(row["exit_reason"]).upper() in {"TP", "TARGET", "PARTIAL"}
            and int(row["post_exit_observation_bars"]) >= threshold["minimum_post_exit_observation_bars"]
            and float(row["post_exit_mfe_r"]) >= threshold["target_undershoot_post_exit_mfe_r"]
        ):
            matched["TARGET_UNDERSHOOT"].append(row)
        if (
            pnl_r <= 0.0
            and int(row["bars_held"]) >= threshold["time_exposure_bars"]
            and mfe_r <= threshold["time_exposure_mfe_r_max"]
        ):
            matched["TIME_EXPOSURE"].append(row)
    total = max(1, len(events))
    result: dict[str, dict[str, Any]] = {}
    for fingerprint, rows in matched.items():
        unique = {str(row["event_id"]): row for row in rows}
        selected = list(unique.values())
        count = len(selected)
        share = count / total
        if count < policy["fingerprint_min_count"] or share < policy["fingerprint_min_share"]:
            continue
        event_ids = sorted(unique)
        result[fingerprint] = {
            "fingerprint": fingerprint,
            "event_count": count,
            "event_share": share,
            "loss_r_abs": sum(abs(min(0.0, float(row["pnl_r"]))) for row in selected),
            "mean_mfe_r": sum(float(row["mfe_r"]) for row in selected) / count,
            "mean_mae_r": sum(float(row["mae_r"]) for row in selected) / count,
            "event_ids": event_ids,
            "support_sha": canonical_sha(event_ids),
        }
    for fingerprint, key in (
        ("REGIME_CONCENTRATION", "regime"),
        ("SESSION_CONCENTRATION", "window_id"),
        ("SYMBOL_CONCENTRATION", "symbol"),
    ):
        row = concentration(events, key, policy)
        if row is not None:
            result[fingerprint] = {"fingerprint": fingerprint, **row}
    return result


def select_fingerprint(rows: Mapping[str, Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any] | None:
    priority = {name: index for index, name in enumerate(policy["fingerprint_priority"])}
    candidates = list(rows.values())
    if not candidates:
        return None
    candidates.sort(key=lambda row: (
        priority.get(str(row["fingerprint"]), len(priority)),
        -float(row.get("loss_r_abs") or 0.0),
        -int(row["event_count"]),
        str(row["fingerprint"]),
    ))
    return copy.deepcopy(candidates[0])


def normalized_generation_count(ledger_row: Mapping[str, Any]) -> dict[str, int]:
    value = ledger_row.get("axis_generation_count")
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for axis, count in value.items():
        result[str(axis).upper()] = int(count)
    return result


def select_candidate(
    fingerprint: Mapping[str, Any],
    *,
    strategy_id: str,
    basis_variant_id: str,
    basis_bundle: Mapping[str, Any],
    ledger_row: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any] | None:
    tested_ids = {str(value) for value in ledger_row.get("tested_candidate_ids") or []}
    selected_ids = {str(value) for value in ledger_row.get("selected_candidate_ids") or []}
    generation = normalized_generation_count(ledger_row)
    remaining = {str(value).upper() for value in ledger_row.get("remaining_axes") or []}
    next_axis = str(ledger_row.get("next_axis") or "").upper()
    for catalog_row in policy["candidate_catalog"][fingerprint["fingerprint"]]:
        candidate_id = catalog_row["candidate_id"]
        axis = catalog_row["axis"]
        if candidate_id in tested_ids or candidate_id in selected_ids:
            continue
        if generation.get(axis, 0) >= policy["max_axis_generations_per_data_epoch"]:
            continue
        if remaining and axis not in remaining and axis != next_axis:
            continue
        proposal = {
            "strategy_id": strategy_id,
            "basis_variant_id": basis_variant_id,
            "basis_bundle_sha": basis_bundle["bundle_sha"],
            "basis_source_sha": basis_bundle["source_sha"],
            "candidate_id": candidate_id,
            "axis": axis,
            "parameters": copy.deepcopy(catalog_row["parameters"]),
            "why": catalog_row["why"],
            "failure_fingerprint": fingerprint["fingerprint"],
            "failure_support_sha": fingerprint["support_sha"],
            "generation": generation.get(axis, 0) + 1,
            "single_axis": True,
            "control_required": True,
            "independent_ab_required": True,
            "duplicate_zero_required": True,
            "observed_2x_cost_p95_funding_plus_one_required": True,
            "pareto_hard_risk_retention_required": True,
            "ai_router_stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
            "ai_router_plan_required": True,
            "ai_router_execute_required": True,
            "replay_required": True,
            "replay_started": False,
            "incumbent_retained": True,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        }
        proposal["candidate_sha"] = canonical_sha(proposal)
        return proposal
    return None


def plan_strategy(
    triage_row: Mapping[str, Any],
    ledger_row: Mapping[str, Any],
    path_root: Path,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    strategy_id = text(triage_row.get("strategy_id"), "triage.strategy_id")
    if ledger_row.get("strategy_id") != strategy_id:
        raise PathPlannerError(f"LEDGER_STRATEGY_MISMATCH:{strategy_id}")
    basis_variant, basis_reason, blockers = select_basis(triage_row)
    if basis_variant is None:
        return {
            "strategy_id": strategy_id,
            "state": "HOLD_BASIS_AMBIGUITY",
            "basis_variant_id": None,
            "basis_reason": basis_reason,
            "blocker_codes": blockers,
            "selected_fingerprint": None,
            "next_candidate_proposal": None,
            "incumbent_retained": True,
        }
    bundle = load_bundle(path_root, strategy_id, basis_variant)
    events = bundle["events"]
    if len(events) < policy["minimum_event_count"]:
        return {
            "strategy_id": strategy_id,
            "state": "WAIT_TRIGGER_EVIDENCE",
            "basis_variant_id": basis_variant,
            "basis_reason": basis_reason,
            "basis_bundle_sha": bundle["bundle_sha"],
            "event_count": len(events),
            "blocker_codes": ["PATH_EVENT_SAMPLE_COUNT_LOW"],
            "selected_fingerprint": None,
            "next_candidate_proposal": None,
            "incumbent_retained": True,
        }
    fingerprints = fingerprint_events(events, policy)
    selected = select_fingerprint(fingerprints, policy)
    if selected is None:
        return {
            "strategy_id": strategy_id,
            "state": "WAIT_NEW_PATH_EVIDENCE",
            "basis_variant_id": basis_variant,
            "basis_reason": basis_reason,
            "basis_bundle_sha": bundle["bundle_sha"],
            "event_count": len(events),
            "blocker_codes": [],
            "fingerprints": [],
            "selected_fingerprint": None,
            "next_candidate_proposal": None,
            "incumbent_retained": True,
        }
    proposal = select_candidate(
        selected,
        strategy_id=strategy_id,
        basis_variant_id=basis_variant,
        basis_bundle=bundle,
        ledger_row=ledger_row,
        policy=policy,
    )
    if proposal is None:
        state = "WAIT_NEW_EVIDENCE_AXIS_EXHAUSTED"
    else:
        state = "PASS_PRE_SHADOW_PATH_OPTIMIZE_PLAN"
    return {
        "strategy_id": strategy_id,
        "state": state,
        "basis_variant_id": basis_variant,
        "basis_reason": basis_reason,
        "basis_bundle_sha": bundle["bundle_sha"],
        "basis_source_sha": bundle["source_sha"],
        "event_count": len(events),
        "blocker_codes": [],
        "fingerprints": [copy.deepcopy(fingerprints[key]) for key in sorted(fingerprints)],
        "selected_fingerprint": selected,
        "next_candidate_proposal": proposal,
        "incumbent_retained": True,
    }


def build_plan(
    *,
    path_index: Mapping[str, Any],
    path_root: Path,
    triage: Mapping[str, Any],
    ledger: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    assert_safety(path_index, "path_index")
    if path_index.get("state") != "PASS_TRADE_PATH_EVIDENCE_INDEX":
        raise PathPlannerError("PATH_INDEX_NOT_PASS")
    if int(path_index.get("hold_bundle_count") or 0) != 0:
        raise PathPlannerError("PATH_INDEX_HAS_HOLD_BUNDLES")
    triage = validate_triage(triage)
    ledger = validate_ledger(ledger)
    policy = validate_policy(policy)
    triage_rows = {str(row["strategy_id"]): row for row in triage["rows"]}
    ledger_rows = {str(row["strategy_id"]): row for row in ledger["rows"]}
    if set(triage_rows) != set(ledger_rows):
        raise PathPlannerError("TRIAGE_LEDGER_STRATEGY_SET_MISMATCH")
    rows = [plan_strategy(triage_rows[strategy_id], ledger_rows[strategy_id], path_root, policy) for strategy_id in sorted(triage_rows)]
    proposals = [row["next_candidate_proposal"] for row in rows if row.get("next_candidate_proposal")]
    if len(proposals) != len({(row["strategy_id"], row["axis"], row["candidate_id"]) for row in proposals}):
        raise PathPlannerError("PROPOSAL_DUPLICATE")
    result = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_PRE_SHADOW_PATH_OPTIMIZE_BATCH_PLAN" if proposals else "WAIT_NEW_PATH_EVIDENCE",
        "strategy_count": len(rows),
        "candidate_count": len(proposals),
        "hold_strategy_count": sum(str(row["state"]).startswith("HOLD_") for row in rows),
        "wait_strategy_count": sum(str(row["state"]).startswith("WAIT_") for row in rows),
        "ready_strategy_count": sum(row["state"] == "PASS_PRE_SHADOW_PATH_OPTIMIZE_PLAN" for row in rows),
        "rows": rows,
        "path_index_sha": path_index["index_sha"],
        "triage_sha": triage["triage_sha"],
        "search_ledger_sha": canonical_sha(ledger),
        "policy_sha": policy["policy_sha"],
        "single_axis_per_strategy": True,
        "automatic_replay_start_allowed": False,
        "ml_light_consumed": False,
        "failure_learning_consumed": False,
        "observer_connection_stage": "AFTER_REAL_SHADOW300_AND_100C_BURNIN",
        "runtime_bridge_allowed": False,
        "paper_30d_allowed": False,
        "live_activation_allowed": False,
        "order_submission_allowed": False,
        "next": "AI_ROUTER_THEN_ISOLATED_REPLAY" if proposals else "WAIT_NEW_PATH_EVIDENCE",
        **SAFETY,
    }
    result["plan_sha"] = canonical_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path-index", type=Path, required=True)
    parser.add_argument("--path-root", type=Path, required=True)
    parser.add_argument("--triage", type=Path, required=True)
    parser.add_argument("--search-ledger", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build_plan(
        path_index=read_json(args.path_index),
        path_root=args.path_root,
        triage=read_json(args.triage),
        ledger=read_json(args.search_ledger),
        policy=read_json(args.policy),
    )
    write_json(args.out, result)
    print(result["state"], "strategies=", result["strategy_count"], "candidates=", result["candidate_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
