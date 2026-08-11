#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.production_terminal_ledger_audit.v1"
POLICY_SCHEMA = "zel.production_improvement_policy.v1"
TERMINAL_IDS = frozenset({"trend_momentum_v1", "relative_value_psa_v1"})
POLICY_PATH_KEYS = (
    "authority_path",
    "registry_path",
    "candidate_queue_path",
    "evidence_path",
)


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"{type(exc).__name__}:{str(exc)[:160]}"
    if not isinstance(row, dict):
        return None, "ROOT_NOT_OBJECT"
    return row, None


def strategy_hits(value: Any, *, prefix: str = "$") -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{prefix}.{key}"
            if key == "strategy_id":
                strategy_id = str(child or "").strip()
                if strategy_id in TERMINAL_IDS:
                    hits.append({"json_path": child_path, "strategy_id": strategy_id})
            hits.extend(strategy_hits(child, prefix=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(strategy_hits(child, prefix=f"{prefix}[{index}]"))
    return hits


def executable_claims(value: Any, *, prefix: str = "$") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        strategy_id = str(value.get("strategy_id") or "").strip()
        if strategy_id in TERMINAL_IDS:
            claim = {
                "json_path": prefix,
                "strategy_id": strategy_id,
                "alpha_state": value.get("alpha_state"),
                "promotion_authority": value.get("promotion_authority"),
                "execution_allowed": value.get("execution_allowed"),
                "runtime_bound": value.get("runtime_bound"),
            }
            runtime = value.get("runtime_authority")
            if isinstance(runtime, Mapping):
                claim["runtime_execution_authority"] = runtime.get("execution_authority")
                claim["runtime_order_authority"] = runtime.get("order_authority")
                claim["runtime_live_trade_authority"] = runtime.get("live_trade_authority")
            claims.append(claim)
        for key, child in value.items():
            claims.extend(executable_claims(child, prefix=f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(executable_claims(child, prefix=f"{prefix}[{index}]"))
    return claims


def audit(policy_path: Path) -> dict[str, Any]:
    policy, policy_error = read_object(policy_path)
    if policy_error is not None or policy is None:
        raise RuntimeError(f"TERMINAL_LEDGER_POLICY_INVALID:{policy_error or 'MISSING'}")
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("TERMINAL_LEDGER_POLICY_SCHEMA_INVALID")

    rows: dict[str, Any] = {}
    all_hits: list[dict[str, str]] = []
    all_claims: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    for key in POLICY_PATH_KEYS:
        raw = str(policy.get(key) or "").strip()
        if not raw:
            raise RuntimeError(f"TERMINAL_LEDGER_POLICY_PATH_UNBOUND:{key}")
        path = Path(raw)
        payload, error = read_object(path)
        hits = strategy_hits(payload) if payload is not None else []
        claims = executable_claims(payload) if payload is not None else []
        for hit in hits:
            hit["policy_key"] = key
            hit["file"] = str(path)
        for claim in claims:
            claim["policy_key"] = key
            claim["file"] = str(path)
        if error is not None:
            parse_errors.append(f"{key}:{error}")
        all_hits.extend(hits)
        all_claims.extend(claims)
        rows[key] = {
            "path": str(path),
            "exists": path.exists(),
            "parse_error": error,
            "terminal_hit_count": len(hits),
            "terminal_hits": hits,
            "terminal_executable_claim_count": len(claims),
            "terminal_executable_claims": claims,
        }

    if parse_errors:
        state = "HOLD_TERMINAL_LEDGER_AUDIT_UNREADABLE"
        blocker = "LEDGER_JSON_PARSE_ERROR"
    elif all_hits:
        state = "HOLD_TERMINAL_LEDGER_RESIDUE"
        blocker = "TERMINAL_STRATEGY_ID_PRESENT_IN_RUNTIME_LEDGER"
    else:
        state = "PASS_NO_TERMINAL_LEDGER_RESIDUE"
        blocker = None

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": state,
        "blocker": blocker,
        "terminal_strategy_ids": sorted(TERMINAL_IDS),
        "files": rows,
        "terminal_hit_count": len(all_hits),
        "terminal_executable_claim_count": len(all_claims),
        "terminal_hits": all_hits,
        "terminal_executable_claims": all_claims,
        "parse_errors": parse_errors,
        "mutation_performed": False,
        "registry_mutated": False,
        "authority_mutated": False,
        "candidate_queue_mutated": False,
        "evidence_mutated": False,
        "exchange_order_submitted": False,
        "live_trade_authority": "BLOCKED",
        "action": "hold" if state != "PASS_NO_TERMINAL_LEDGER_RESIDUE" else "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of production terminal alpha ledger residue")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.policy)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "terminal_hit_count": result["terminal_hit_count"],
        "terminal_executable_claim_count": result["terminal_executable_claim_count"],
        "mutation_performed": result["mutation_performed"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
