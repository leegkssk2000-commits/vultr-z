from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "ZOS_R7A4D_INTEGRATED_SUPERTREND_PULLBACK_v1.json"
)

EXPECTED_STRATEGY_ID = "integrated_supertrend_pullback_v1"
EXPECTED_VIDEO_IDS = {"R2hZlnh37fQ", "g-PLctW8aU0", "cKKLujAdvzk"}
EXPECTED_ROLES = {
    "CONTEXT_AND_LOCATION_GATE",
    "EXECUTABLE_TREND_AND_POSITION_CORE",
    "ENTRY_CONFIRMATION_OVERLAY",
}
FORBIDDEN_STRATEGY_IDS = {
    "manual_pullback_confluence_v1",
    "manual_pullback_confluence_rsi_v1",
    "tradinglab_dema200_supertrend12x3_video_v1",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SystemExit(code)


def load_contract(path: Path = CONTRACT_PATH) -> Dict[str, Any]:
    _require(path.is_file(), f"CONTRACT_MISSING:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"CONTRACT_JSON_INVALID:{exc}") from exc
    _require(isinstance(payload, dict), "CONTRACT_ROOT_NOT_OBJECT")
    return payload


def validate_contract(payload: Dict[str, Any]) -> None:
    _require(payload.get("strategy_id") == EXPECTED_STRATEGY_ID, "CANONICAL_STRATEGY_ID_INVALID")

    sources = payload.get("source_videos")
    _require(isinstance(sources, list), "SOURCE_VIDEOS_NOT_LIST")
    _require(len(sources) == 3, "SOURCE_VIDEO_COUNT_NOT_THREE")

    video_ids = {item.get("video_id") for item in sources if isinstance(item, dict)}
    roles = {item.get("role") for item in sources if isinstance(item, dict)}
    _require(video_ids == EXPECTED_VIDEO_IDS, "SOURCE_VIDEO_SET_INVALID")
    _require(roles == EXPECTED_ROLES, "SOURCE_ROLE_SET_INVALID")
    _require(
        all(item.get("must_not_register_as_strategy") is True for item in sources),
        "SOURCE_MODULE_REGISTRATION_NOT_BLOCKED",
    )

    invariants = payload.get("registration_invariants")
    _require(isinstance(invariants, dict), "REGISTRATION_INVARIANTS_MISSING")
    _require(invariants.get("canonical_strategy_count") == 1, "CANONICAL_STRATEGY_COUNT_NOT_ONE")
    _require(
        invariants.get("canonical_strategy_ids") == [EXPECTED_STRATEGY_ID],
        "CANONICAL_STRATEGY_LIST_INVALID",
    )
    _require(
        set(invariants.get("forbidden_strategy_ids", [])) == FORBIDDEN_STRATEGY_IDS,
        "FORBIDDEN_STRATEGY_SET_INVALID",
    )
    _require(
        invariants.get("source_modules_are_non_promotable") is True,
        "SOURCE_MODULE_PROMOTION_NOT_BLOCKED",
    )

    pipeline = payload.get("single_strategy_pipeline")
    _require(isinstance(pipeline, dict), "SINGLE_STRATEGY_PIPELINE_MISSING")
    order = pipeline.get("order")
    _require(isinstance(order, list) and len(order) == 7, "PIPELINE_ORDER_INVALID")
    _require(order[0] == "REGIME_GATE", "PIPELINE_FIRST_STAGE_INVALID")
    _require(order[-1] == "POSITION_MANAGEMENT", "PIPELINE_LAST_STAGE_INVALID")

    guards = payload.get("implementation_guards")
    _require(isinstance(guards, dict), "IMPLEMENTATION_GUARDS_MISSING")
    for key in (
        "legacy_strategy_mutation_allowed",
        "registry_mutation_allowed",
        "router_mutation_allowed",
        "shadow_start_allowed",
        "paper_live_order_allowed",
        "parameter_optimization_allowed",
        "performance_claim_allowed",
    ):
        _require(guards.get(key) is False, f"GUARD_NOT_FALSE:{key}")
    _require(guards.get("unknown_geometry_must_fail_closed") is True, "UNKNOWN_GEOMETRY_NOT_FAIL_CLOSED")


def main() -> int:
    payload = load_contract()
    validate_contract(payload)
    print("STATE=PASS_INTEGRATED_SUPERTREND_PULLBACK_SINGLE_STRATEGY_CONTRACT")
    print(f"STRATEGY_ID={EXPECTED_STRATEGY_ID}")
    print("CANONICAL_STRATEGY_COUNT=1")
    print("SOURCE_VIDEO_COUNT=3")
    print("SOURCE_MODULE_STRATEGY_REGISTRATION_ALLOWED=false")
    print("NEXT_STAGE=IMPLEMENT_ONE_CHILD_AND_ONE_REPLAY_RUNNER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
