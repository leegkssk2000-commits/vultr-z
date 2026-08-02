from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "ZEL_SKILL_COUNTERFACTUAL_ADAPTER_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_trade_schema(path: Path) -> set[str]:
    keys: set[str] = set()
    if path.suffix == ".gz":
        opener = lambda: gzip.open(path, "rt", encoding="utf-8")
    else:
        opener = lambda: path.open("r", encoding="utf-8")
    with opener() as handle:
        for raw in handle:
            if not raw.strip():
                continue
            value = json.loads(raw)
            if isinstance(value, dict):
                keys.update(str(key) for key in value)
                for nested in ("entry_features", "exit_features", "market_context"):
                    nested_value = value.get(nested)
                    if isinstance(nested_value, dict):
                        keys.update(str(key) for key in nested_value)
    return keys


def resolver_skill_ids(receipt: Mapping[str, Any]) -> list[str]:
    fields = (
        "effective_strategy_skill_ids",
        "effective_bot_skill_ids",
        "active_os_guard_skill_ids",
        "learning_only_skill_ids",
        "blocked_skill_ids",
    )
    values: list[str] = []
    for field in fields:
        raw = receipt.get(field)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item))
    rows = receipt.get("rows") if isinstance(receipt.get("rows"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for field in fields:
            raw = row.get(field)
            if isinstance(raw, list):
                values.extend(str(item) for item in raw if str(item))
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        for field in fields:
            raw = result.get(field)
            if isinstance(raw, list):
                values.extend(str(item) for item in raw if str(item))
    return sorted(set(values))


def family_for(skill_id: str, contract: Mapping[str, Any]) -> dict[str, Any] | None:
    families = contract.get("families") if isinstance(contract.get("families"), list) else []
    for row in families:
        if not isinstance(row, dict):
            continue
        prefixes = row.get("match_prefixes") if isinstance(row.get("match_prefixes"), list) else []
        if any(skill_id.startswith(str(prefix)) for prefix in prefixes):
            return row
    return None


def evidence_option_satisfied(option: Sequence[Any], trade_schema: set[str]) -> bool:
    return bool(option) and all(str(field) in trade_schema for field in option)


def classify_skill(skill_id: str, trade_schema: set[str], contract: Mapping[str, Any]) -> dict[str, Any]:
    family = family_for(skill_id, contract)
    if not family:
        return {
            "skill_id": skill_id,
            "state": "HOLD_UNKNOWN_SKILL_FAMILY",
            "counterfactual_mode": "UNKNOWN",
            "missing_evidence": ["explicit_family_contract"],
            "exact_replay_allowed": False,
            "direct_pnl_delta_allowed": False,
            "action": "hold",
        }
    mode = str(family.get("counterfactual_mode") or "UNKNOWN")
    parity_only = family.get("parity_only") is True
    options = family.get("required_evidence_any") if isinstance(family.get("required_evidence_any"), list) else []
    satisfied = any(
        isinstance(option, list) and evidence_option_satisfied(option, trade_schema)
        for option in options
    ) if options else True
    exact_allowed = bool(family.get("exact_replay_allowed_when_complete")) and satisfied and not parity_only
    missing: list[str] = []
    if not satisfied:
        for option in options:
            if isinstance(option, list):
                missing.extend(str(field) for field in option if str(field) not in trade_schema)
    if parity_only:
        state = "PASS_SKILL_PARITY_ONLY_NO_DIRECT_PNL"
    elif exact_allowed:
        state = "PASS_SKILL_EXACT_REPLAY_EVIDENCE_COMPLETE"
    else:
        state = "HOLD_SKILL_EXACT_REPLAY_EVIDENCE_MISSING"
    return {
        "skill_id": skill_id,
        "state": state,
        "counterfactual_mode": mode,
        "required_evidence_any": options,
        "missing_evidence": sorted(set(missing)),
        "exact_replay_allowed": exact_allowed,
        "direct_pnl_delta_allowed": exact_allowed,
        "action": "hold",
    }


def build(contract: Mapping[str, Any], skill_ids: Iterable[str], trade_schema: set[str]) -> dict[str, Any]:
    rows = [classify_skill(skill_id, trade_schema, contract) for skill_id in sorted(set(skill_ids))]
    exact = [row for row in rows if row["state"] == "PASS_SKILL_EXACT_REPLAY_EVIDENCE_COMPLETE"]
    parity = [row for row in rows if row["state"] == "PASS_SKILL_PARITY_ONLY_NO_DIRECT_PNL"]
    blocked = [row for row in rows if row["state"].startswith("HOLD_")]
    if not rows:
        state = "HOLD_NO_SKILLS_DISCOVERED"
    elif blocked:
        state = "HOLD_SKILL_COUNTERFACTUAL_PARTIAL_OR_BLOCKED"
    else:
        state = "PASS_SKILL_COUNTERFACTUAL_CONTRACTS"
    result: dict[str, Any] = {
        "schema_version": "zel.skill_counterfactual.adapter.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "trade_schema_keys": sorted(trade_schema),
        "trade_schema_sha256": stable_sha(sorted(trade_schema)),
        "skill_count": len(rows),
        "exact_replay_skill_count": len(exact),
        "parity_only_skill_count": len(parity),
        "blocked_skill_count": len(blocked),
        "exact_replay_skill_ids": [row["skill_id"] for row in exact],
        "parity_only_skill_ids": [row["skill_id"] for row in parity],
        "blocked_skill_ids": [row["skill_id"] for row in blocked],
        "skills": rows,
        "economic_superiority_claim_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> None:
    contract = {
        "families": [
            {
                "match_prefixes": ["SK_POS_"],
                "counterfactual_mode": "PATH_DEPENDENT_POSITION_MANAGEMENT",
                "required_evidence_any": [["bar_path", "position_size_path", "bar_timestamp_path"]],
                "exact_replay_allowed_when_complete": True,
            },
            {
                "match_prefixes": ["SK_EXEC_"],
                "counterfactual_mode": "GUARD_OR_EXECUTION_CONTEXT",
                "required_evidence_any": [],
                "exact_replay_allowed_when_complete": False,
                "parity_only": True,
            },
        ]
    }
    hold = build(contract, ["SK_POS_TRAILING_STOP"], {"entry_ts", "exit_ts"})
    assert hold["state"] == "HOLD_SKILL_COUNTERFACTUAL_PARTIAL_OR_BLOCKED", hold
    assert hold["exact_replay_skill_count"] == 0, hold
    passed = build(contract, ["SK_POS_TRAILING_STOP", "SK_EXEC_MARKOUT_GUARD"], {"bar_path", "position_size_path", "bar_timestamp_path"})
    assert passed["state"] == "PASS_SKILL_COUNTERFACTUAL_CONTRACTS", passed
    assert passed["exact_replay_skill_count"] == 1, passed
    assert passed["parity_only_skill_count"] == 1, passed
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--resolver-receipt", type=Path)
    parser.add_argument("--trades", type=Path)
    parser.add_argument("--skills", nargs="*")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.contract or not args.trades:
        parser.error("contract and trades are required")
    contract = load_json(args.contract)
    skill_ids = list(args.skills or [])
    if args.resolver_receipt:
        skill_ids.extend(resolver_skill_ids(load_json(args.resolver_receipt)))
    row = build(contract, skill_ids, load_trade_schema(args.trades))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
