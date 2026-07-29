from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_role_boundary_zbot_zico_lico_zlice_v1 import (
    RoleBoundaryError,
    role_manifest,
    validate_message,
)

OUT = Path("artifacts/strategy11_role_boundary_v1")


def base(role: str, action: str, payload: dict) -> dict:
    return {
        "role": role,
        "action": action,
        "payload": payload,
        "confidence": 0.75,
        "abstain": action == "ABSTAIN",
        "stale": False,
        "latency_ms": 12.0,
        "reason_codes": ["FIXTURE_VALID"],
        "sbot_veto_active": False,
        "lineage": {
            "strategy_id": "alpha_combo",
            "method_id": "trend",
            "skill_id": "time_exit",
            "team_id": "Alpha",
            "event_ts": "2026-07-29T07:10:00Z",
            "source_ids": ["proposal:fixture", "market:fixture"],
            "contract_version": "1.0.0",
            "source_manifest_sha": "a" * 64,
        },
        "authority": {
            "research_only": True,
            "promotion_authority": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "runtime_bound": False,
        },
    }


def reject(name: str, value: dict, code: str) -> dict:
    try:
        validate_message(value)
    except RoleBoundaryError as exc:
        text = str(exc)
        assert text.startswith(code), (name, text)
        return {"name": name, "status": "PASS_REJECTED", "code": text}
    raise AssertionError(f"{name}: invalid message accepted")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    valid = {
        "ZBOT": validate_message(base("ZBOT", "ADVISE", {
            "advice": "HOLD_RESEARCH_ONLY",
            "alternatives": ["TIME54", "TIME60"],
            "counterfactual": "retain_incumbent",
        })),
        "ZICO": validate_message(base("ZICO", "EMIT_LIFECYCLE_CONTEXT", {
            "intent_state": "RESEARCH",
            "lifecycle_state": "W1_WAIT",
            "control_context": "no_runtime_transition",
        })),
        "LICO": validate_message(base("LICO", "EMIT_CONTEXT_ENVELOPE", {
            "liquidity": "NORMAL",
            "macro": "UNKNOWN",
            "fx": "NEUTRAL",
            "freshness": "FRESH",
            "cost_capacity": {"capacity": "FIXTURE", "cost": "FIXTURE"},
        })),
        "ZLICE": validate_message(base("ZLICE", "PROJECT_EVIDENCE", {
            "evidence_lineage": ["row:001"],
            "lifecycle_trace": ["proposal", "classification", "shadow_target"],
            "source_ids": ["source:fixture"],
        })),
    }
    assert len({row["message_sha"] for row in valid.values()}) == 4
    assert all(row["capabilities"]["can_execute_order"] is False for row in valid.values())
    assert valid["ZICO"]["capabilities"]["can_request_rollback"] is True
    assert valid["ZBOT"]["capabilities"]["can_request_rollback"] is False

    invalid_order = base("LICO", "OPEN_ORDER", {})
    invalid_weight = base("ZBOT", "SET_PORTFOLIO_WEIGHT", {})
    invalid_strategy = base("ZICO", "GENERATE_STRATEGY", {})
    invalid_decision = base("ZLICE", "FINAL_TRADE_DECISION", {})
    veto_override = base("ZBOT", "ADVISE", {
        "advice": "proceed",
        "alternatives": [],
        "counterfactual": "none",
    })
    veto_override["sbot_veto_active"] = True
    cross_role = base("ZLICE", "ADVISE", {
        "evidence_lineage": [], "lifecycle_trace": [], "source_ids": []
    })
    stale = base("LICO", "EMIT_CONTEXT_ENVELOPE", {
        "liquidity": "UNKNOWN", "macro": "UNKNOWN", "fx": "UNKNOWN",
        "freshness": "STALE", "cost_capacity": {},
    })
    stale["stale"] = True

    negative = [
        reject("order", invalid_order, "PRIVATE_AUTHORITY_ACTION_FORBIDDEN"),
        reject("weight", invalid_weight, "PRIVATE_AUTHORITY_ACTION_FORBIDDEN"),
        reject("strategy", invalid_strategy, "PRIVATE_AUTHORITY_ACTION_FORBIDDEN"),
        reject("decision", invalid_decision, "PRIVATE_AUTHORITY_ACTION_FORBIDDEN"),
        reject("sbot_veto", veto_override, "SBOT_VETO_PRECEDENCE"),
        reject("cross_role", cross_role, "ACTION_OUTSIDE_ROLE"),
        reject("stale", stale, "STALE_INPUT_MUST_ABSTAIN"),
    ]

    manifest = role_manifest()
    summary = {
        "state": "PASS_ROLE_BOUNDARY_ZBOT_ZICO_LICO_ZLICE",
        "valid_roles": sorted(valid),
        "valid_message_sha": {role: row["message_sha"] for role, row in valid.items()},
        "negative_fixture_count": len(negative),
        "negative_fixtures": negative,
        "sbot_hard_veto_precedence": manifest["sbot_hard_veto_precedence"],
        "cross_role_substitution_forbidden": manifest["cross_role_substitution_forbidden"],
        "next": "MODEL_RISK_GOVERNANCE",
        "runtime_bound": False,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "valid_messages.json").write_text(json.dumps(valid, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
