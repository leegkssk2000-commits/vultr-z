from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_LICO_PROVENANCE_ACQUISITION_PLANNER_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        return [row for row in value["rows"] if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def nested(row: Mapping[str, Any], key: str) -> Any:
    if row.get(key) not in (None, ""):
        return row.get(key)
    for container in ("entry_features", "market_context", "execution_evidence", "risk_context"):
        value = row.get(container)
        if isinstance(value, Mapping) and value.get(key) not in (None, ""):
            return value.get(key)
    return None


def field_present(row: Mapping[str, Any], field: str) -> bool:
    if "|" in field:
        return any(nested(row, part) not in (None, "") for part in field.split("|"))
    if field == "price":
        return nested(row, "price") not in (None, "") or nested(row, "entry_price") not in (None, "")
    return nested(row, field) not in (None, "")


def plan_row(row: Mapping[str, Any], contract: Mapping[str, Any], stale_ms: int | None) -> dict[str, Any]:
    join_required = contract.get("required_trade_join_keys") if isinstance(contract.get("required_trade_join_keys"), list) else []
    missing_join = [str(key) for key in join_required if row.get(str(key)) in (None, "")]
    field_contracts = contract.get("fields") if isinstance(contract.get("fields"), list) else []
    acquisition: list[dict[str, Any]] = []
    covered: list[str] = []
    for field_row in field_contracts:
        if not isinstance(field_row, dict):
            continue
        field = str(field_row.get("field") or "")
        if not field:
            continue
        if field_present(row, field):
            covered.append(field)
            continue
        join_keys = [str(value) for value in field_row.get("join_keys", [])]
        missing_field_join = [key for key in join_keys if row.get(key) in (None, "")]
        acquisition.append(
            {
                "field": field,
                "accepted_source_keys": [str(value) for value in field_row.get("accepted_source_keys", [])],
                "join_keys": join_keys,
                "missing_join_keys": missing_field_join,
                "temporal_rule": field_row.get("temporal_rule"),
                "stale_limit_ms": stale_ms,
                "request_allowed": not missing_field_join and stale_ms is not None,
                "request_method": "GET_OR_READ_ONLY_LOOKUP",
                "write_allowed": False,
                "action": "hold",
            }
        )
    blockers: list[str] = []
    if missing_join:
        blockers.append("TRADE_JOIN_KEYS_MISSING")
    if stale_ms is None:
        blockers.append("SSOT_DATA_STALE_MS_MISSING")
    if any(item["missing_join_keys"] for item in acquisition):
        blockers.append("FIELD_JOIN_KEYS_MISSING")
    state = "PASS_LICO_PROVENANCE_ACQUISITION_PLAN" if not blockers else "HOLD_LICO_PROVENANCE_ACQUISITION_PLAN"
    return {
        "event_id": row.get("event_id"),
        "strategy_id": row.get("strategy_id") or row.get("strategy"),
        "symbol": row.get("symbol"),
        "entry_ts": row.get("entry_ts"),
        "state": state,
        "covered_fields": sorted(covered),
        "missing_field_count": len(acquisition),
        "acquisition_requests": acquisition,
        "missing_trade_join_keys": sorted(set(missing_join)),
        "blockers": sorted(set(blockers)),
        "source_priority": list(contract.get("source_priority") or []),
        "future_observation_join_allowed": False,
        "interpolation_allowed": False,
        "source_key_fabrication_allowed": False,
        "historical_value_fabrication_allowed": False,
        "action": "hold",
    }


def build(contract: Mapping[str, Any], rows: list[dict[str, Any]], stale_ms: int | None) -> dict[str, Any]:
    plans = [plan_row(row, contract, stale_ms) for row in rows]
    states = Counter(plan["state"] for plan in plans)
    field_requests: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    for plan in plans:
        blockers.update(plan["blockers"])
        for request in plan["acquisition_requests"]:
            field_requests[str(request["field"])] += 1
    ready = sum(1 for plan in plans if plan["state"].startswith("PASS_"))
    state = "PASS_LICO_PROVENANCE_ACQUISITION_DATASET_PLAN" if plans and ready == len(plans) else "HOLD_LICO_PROVENANCE_ACQUISITION_DATASET_PLAN"
    result: dict[str, Any] = {
        "schema_version": "zel.lico.provenance_acquisition.plan.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "row_count": len(plans),
        "ready_plan_count": ready,
        "blocked_plan_count": len(plans) - ready,
        "state_counts": dict(sorted(states.items())),
        "field_request_counts": dict(sorted(field_requests.items())),
        "blocker_counts": dict(sorted(blockers.items())),
        "plans": plans,
        "ssot_data_stale_ms": stale_ms,
        "network_requested": False,
        "writes_requested": False,
        "historical_values_fabricated": False,
        "source_keys_fabricated": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha({key: value for key, value in result.items() if key != "receipt_sha256"})
    return result


def self_test() -> None:
    contract = load_json(Path(__file__).resolve().parents[1] / "research/zel_lico_provenance_acquisition_contract_v1.json")
    row = {
        "event_id": "e1",
        "strategy_id": "s1",
        "symbol": "BTCUSDT",
        "entry_ts": "2026-01-01T00:00:00Z",
        "entry_price": 100,
    }
    passed = build(contract, [row], 120000)
    assert passed["state"] == "PASS_LICO_PROVENANCE_ACQUISITION_DATASET_PLAN", passed
    assert passed["field_request_counts"]["pos_pct"] == 1, passed
    assert passed["writes_requested"] is False, passed
    held = build(contract, [{"event_id": "e2"}], None)
    assert held["state"] == "HOLD_LICO_PROVENANCE_ACQUISITION_DATASET_PLAN", held
    assert held["blocker_counts"]["SSOT_DATA_STALE_MS_MISSING"] == 1, held
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--ssot-data-stale-ms", type=int)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.contract or not args.input:
        parser.error("contract and input are required")
    result = build(
        load_json(args.contract),
        rows_from_value(load_json(args.input)),
        args.ssot_data_stale_ms,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(result, sort_keys=True))
    return 0 if result["state"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
