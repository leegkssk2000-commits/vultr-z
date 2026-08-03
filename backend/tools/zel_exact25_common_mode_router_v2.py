from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import zel_exact25_common_mode_router_v1 as v1

VERSION = "ZEL_EXACT25_COMMON_MODE_ROUTER_V2"
SCHEMA = "zel.exact25.common_mode_router.receipt.v2"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def run(
    policy: dict[str, Any],
    terminal_root: Path,
    source_owner_receipt: dict[str, Any],
) -> dict[str, Any]:
    if source_owner_receipt.get("state") != "PASS_EXACT25_SOURCE_OWNER_AUDIT":
        raise RuntimeError("SOURCE_OWNER_PREFLIGHT_NOT_PASS")
    registered_count = int(source_owner_receipt.get("strategy_count") or 0)
    quarantined = source_owner_receipt.get("quarantined_strategy_ids") or []
    if registered_count != int(policy["expected_strategy_count"]):
        raise RuntimeError(
            f"REGISTERED_STRATEGY_COUNT_MISMATCH:{registered_count}:"
            f"{policy['expected_strategy_count']}"
        )
    if quarantined:
        raise RuntimeError(f"SOURCE_OWNER_QUARANTINE_NONEMPTY:{quarantined}")

    raw_rows = v1.load_rows(terminal_root / "trades.jsonl.gz")
    active_ids = sorted(
        {
            str(row.get("strategy_id") or "")
            for row in raw_rows
            if str(row.get("strategy_id") or "")
        }
    )
    if not active_ids:
        raise RuntimeError("NO_ACTIVE_CLOSED_TRADE_STRATEGIES")

    effective_policy = json.loads(json.dumps(policy))
    effective_policy["registered_strategy_count_expected"] = int(
        policy["expected_strategy_count"]
    )
    effective_policy["expected_strategy_count"] = len(active_ids)
    receipt = v1.run(effective_policy, terminal_root)
    receipt["schema_version"] = SCHEMA
    receipt["version"] = VERSION
    receipt["registered_strategy_count"] = registered_count
    receipt["active_closed_trade_strategy_count"] = len(active_ids)
    receipt["active_closed_trade_strategy_ids"] = active_ids
    receipt["source_owner_receipt_sha256"] = source_owner_receipt.get(
        "receipt_sha256"
    )
    receipt["checks"]["registered_strategy_count_25"] = registered_count == 25
    receipt["checks"]["active_closed_trade_strategy_count_nonzero"] = len(active_ids) > 0
    receipt["checks"].pop("strategy_count", None)
    passed = all(receipt["checks"].values())
    receipt["state"] = (
        "PASS_COMMON_MODE_ROUTE_SELECTED"
        if passed
        else "HOLD_COMMON_MODE_INPUT_INTEGRITY"
    )
    if not passed:
        receipt["selected_route"] = "INTEGRITY_AND_UNIT_REPAIR"
        receipt["selected_route_evidence"] = {"checks": receipt["checks"]}
        receipt["next"] = "BUILD_EXACT_SOURCE_INTEGRITY_AND_UNIT_REPAIR"
    receipt["receipt_sha256"] = v1.stable_sha(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    return receipt


def self_test() -> int:
    source = {
        "state": "PASS_EXACT25_SOURCE_OWNER_AUDIT",
        "strategy_count": 25,
        "quarantined_strategy_ids": [],
        "receipt_sha256": "a" * 64,
    }
    assert source["strategy_count"] == 25
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--source-owner", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.policy or not args.terminal_root or not args.source_owner:
        parser.error("--policy, --terminal-root and --source-owner are required")
    receipt = run(
        read_json(args.policy),
        args.terminal_root.resolve(),
        read_json(args.source_owner),
    )
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
