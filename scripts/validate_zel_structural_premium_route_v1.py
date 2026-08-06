#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXPECTED_MAIN = [
    {"strategy_id": "vwap_revert", "side": "enter_long", "role": "MAIN"},
    {"strategy_id": "support_resistance", "side": "enter_long", "role": "MAIN"},
]
EXPECTED_RESERVE = [
    {"strategy_id": "liquidity_sweep", "side": "enter_long", "role": "RESERVE"},
    {"strategy_id": "trend_rider", "side": "enter_long", "role": "RESERVE"},
]
EXPECTED_FILTER_ONLY = [
    {"strategy_id": "market_structure", "side": "enter_long", "role": "FILTER_ONLY"},
]
EXPECTED_MARKERS = ["POST129", "BEST_ALLOW", "allow", "admission"]
EXPECTED_REPLAY_GATES = [
    "RUNNER_ASSIGNED",
    "THIRD_GENERATION_SOURCE_BOUND",
    "POST129_PRESENT",
    "BEST_ALLOW_PRESENT",
    "ALLOW_PRESENT",
    "ADMISSION_PRESENT",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), "route root must be an object")
    return payload


def validate(route: dict[str, Any]) -> dict[str, Any]:
    require(route.get("schema_version") == "zel.structural_premium.route.v1", "schema mismatch")
    require(route.get("active_family") == "THIRD_GENERATION_STRUCTURAL_PREMIUM", "wrong active family")
    require(route.get("supersedes") == ["MOMENTUM_GEN2"], "Momentum Gen2 must be superseded")
    require(route.get("generation") == 4, "generation must be 4")
    require(route.get("inherit_from_generation") == 3, "generation-3 inheritance missing")

    contract = route.get("strategy_contract")
    require(isinstance(contract, dict), "strategy_contract missing")
    require(contract.get("main") == EXPECTED_MAIN, "MAIN contract mismatch")
    require(contract.get("reserve") == EXPECTED_RESERVE, "RESERVE contract mismatch")
    require(contract.get("filter_only") == EXPECTED_FILTER_ONLY, "FILTER_ONLY contract mismatch")

    all_rows = EXPECTED_MAIN + EXPECTED_RESERVE + EXPECTED_FILTER_ONLY
    identities = [(row["strategy_id"], row["side"]) for row in all_rows]
    require(len(identities) == len(set(identities)), "duplicate strategy-side identity")
    require(route.get("required_inheritance_markers") == EXPECTED_MARKERS, "inheritance marker mismatch")

    runner = route.get("runner_gate")
    require(isinstance(runner, dict), "runner_gate missing")
    require(runner.get("github_hosted_labels") == ["ubuntu-latest"], "runner label mismatch")
    require(runner.get("state") == "BLOCKED_GITHUB_HOSTED_RUNNER_UNASSIGNED", "runner must fail closed")
    require(runner.get("replay_allowed_after") == EXPECTED_REPLAY_GATES, "replay gate order mismatch")
    require(isinstance(runner.get("queue_observed"), int) and runner["queue_observed"] >= 0, "queue count invalid")
    require(
        isinstance(runner.get("in_progress_observed"), int) and runner["in_progress_observed"] >= 0,
        "in-progress count invalid",
    )

    forbidden = set(route.get("forbidden", []))
    require("momentum_gen2_replay" in forbidden, "Momentum replay must remain forbidden")
    require("market_structure_as_entry_owner" in forbidden, "market_structure entry ownership must be forbidden")
    require({"paper", "live", "orders"}.issubset(forbidden), "execution boundaries incomplete")

    require(route.get("selection_authority") is False, "selection authority must be false")
    require(route.get("promotion_authority") is False, "promotion authority must be false")
    require(route.get("execution_authority") == "NONE", "execution authority must be NONE")
    require(route.get("order_authority") == "BLOCKED", "order authority must be BLOCKED")
    require(route.get("protected_mutations") == 0, "protected mutations must be zero")
    require(route.get("action") == "route_change", "action must be route_change")

    return {
        "state": "PASS_STRUCTURAL_PREMIUM_ROUTE_CONTRACT_VALIDATED",
        "main_count": len(EXPECTED_MAIN),
        "reserve_count": len(EXPECTED_RESERVE),
        "filter_only_count": len(EXPECTED_FILTER_ONLY),
        "inheritance_markers": EXPECTED_MARKERS,
        "runner_state": runner["state"],
        "execution_authority": route["execution_authority"],
        "order_authority": route["order_authority"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--route",
        type=Path,
        default=Path("backend/research/zel_structural_premium_route_v1.json"),
    )
    args = parser.parse_args()
    result = validate(load_json(args.route))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
