#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_common_regime_selector_pareto_router_v1 as base

ROOT = Path(__file__).resolve().parents[3]
BRIDGE = ROOT / "backend/research/rebuild/a1_common_regime_selector_validated_evidence_v1.json"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "exchange_order_submitted": False,
}


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def read_bridge() -> dict[str, Any]:
    value = json.loads(BRIDGE.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("state") != "PASS_VALIDATED_EVIDENCE_BRIDGE":
        raise RuntimeError("VALIDATED_EVIDENCE_BRIDGE_INVALID")
    if value.get("selection_authority") is not False or value.get("promotion_authority") is not False:
        raise RuntimeError("VALIDATED_EVIDENCE_AUTHORITY_INVALID")
    if value.get("execution_authority") != "NONE" or value.get("order_authority") != "BLOCKED":
        raise RuntimeError("VALIDATED_EVIDENCE_EXECUTION_AUTHORITY_INVALID")
    return value


def by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(x["strategy_id"]): x for x in rows}


def apply_break(row: dict[str, Any], evidence: Mapping[str, Any]) -> None:
    parent = evidence["parent"]
    child = evidence["child"]
    relation = base.pareto(parent, child)
    expected = str(evidence.get("validated_relation") or "")
    if relation["relation"] != expected:
        raise RuntimeError(f"BREAK_VALIDATED_RELATION_MISMATCH:{relation['relation']}:{expected}")
    row["good_regime_candidate"] = {
        "child_id": "break_and_continue_box_break_child_v1",
        "changed_axis": evidence.get("changed_axis"),
        "child_policy_path": evidence.get("child_policy_path"),
        "child_policy_sha": evidence.get("child_policy_sha"),
        "preentry_only": True,
        "runtime_enabled": False,
        "fresh_proof_required": True,
        "validated_frozen_evidence": True,
    }
    row["pareto"] = relation
    row["partial_success_preserved"] = True
    row["trigger_classes"] = sorted(set(row.get("trigger_classes") or []) | {
        "GOOD_REGIME_OR_PARTIAL_SUCCESS_CANDIDATE",
        "DD_TRADEOFF_MONITOR_REQUIRED",
    })
    row["validated_evidence"] = evidence
    row["route"] = (
        "PRESERVE_BREAK_BOX_PARTIAL_SUCCESS; COLLECT_FRESH; RUN_IDENTITY_H4_H5_AT_25; "
        "MONITOR_AUTH_REALIZED_DD_AND_COMMON_MODE; DO_NOT_RETUNE"
    )


def apply_breadth_common_mode(row: dict[str, Any], evidence: Mapping[str, Any]) -> None:
    lifecycle = evidence.get("lifecycle") if isinstance(evidence.get("lifecycle"), Mapping) else {}
    if lifecycle.get("conclusion") != "NO_LIFECYCLE_BUG_FOUND_IMMATURE_HORIZON_ONLY":
        raise RuntimeError(f"LIFECYCLE_NOT_RESOLVED:{row['strategy_id']}")

    row["trigger_classes"] = [
        x for x in (row.get("trigger_classes") or []) if x != "EXIT_CLOSURE_LAG"
    ]
    row["trigger_classes"] = sorted(set(row["trigger_classes"]) | {
        "UNIVERSE_BREADTH_BOTTLENECK_VALIDATED",
        "COMMON_MODE_STACKING_CONFIRMED",
    })
    row["stale_trigger_superseded"] = {
        "trigger": "EXIT_CLOSURE_LAG",
        "superseded_by": "PR990_LIFECYCLE_IMMATURE_HORIZON_ONLY",
    }
    row["breadth_discovery_candidate"] = {
        "universe": ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT"],
        "metrics": evidence.get("liquid6"),
        "economic_upgrade_claim": False,
        "runtime_enabled": False,
        "fresh_oos_required": True,
        "purpose": "Increase event coverage and expose strategy-specific GOOD/BAD regimes without changing entry/risk/exit parameters.",
    }
    row["common_mode_risk_context"] = evidence.get("common_mode")
    row["validated_evidence"] = evidence
    row["partial_success_preserved"] = False
    row["breadth_candidate_preserved"] = True
    row["route"] = (
        "PRESERVE_BTCETH_PARENT_AND_LIQUID6_DISCOVERY; BUILD_STRATEGY_SPECIFIC_GOOD_REGIME_SELECTOR; "
        "FRESH_OOS; ADD_EXPOSURE_CONTEXT; DO_NOT_USE_NAIVE_OVERLAP_BLOCK"
    )


def run(out: Path) -> dict[str, Any]:
    bridge = read_bridge()
    with tempfile.TemporaryDirectory(prefix="common_selector_v2_") as td:
        raw = base.run(Path(td) / "base.json")

    rows = [dict(x) for x in raw["strategies"]]
    index = by_id(rows)
    validated = bridge.get("strategies") if isinstance(bridge.get("strategies"), Mapping) else {}

    apply_break(index["break_and_continue"], validated["break_and_continue"])
    apply_breadth_common_mode(index["supertrend_pullback"], validated["supertrend_pullback"])
    apply_breadth_common_mode(index["trend_ma_macd"], validated["trend_ma_macd"])

    raw["schema_version"] = "zel.a1.common_regime_selector_pareto.validated.v2"
    raw["state"] = "PASS_COMMON_REGIME_SELECTOR_VALIDATED_EVIDENCE_ACTIVE"
    raw["authority_precedence"] = [
        "VALIDATED_FROZEN_EVIDENCE_BRIDGE",
        "CURRENT_ROLLING_PREENTRY_DIAGNOSTICS",
        "CURRENT_FRESH_STATUS",
    ]
    raw["validated_bridge_path"] = str(BRIDGE.relative_to(ROOT))
    raw["validated_bridge_sha256"] = stable(bridge)
    raw["validated_sources"] = bridge.get("sources")
    raw["stale_rolling_evidence_cannot_override_validated_finding"] = True
    raw["break_partial_success_preserved"] = True
    raw["supertrend_liquid6_economic_upgrade_claim"] = False
    raw["trendma_liquid6_economic_upgrade_claim"] = False
    raw["naive_overlap_block_promotion_forbidden"] = True
    raw["strategies"] = rows
    raw.update(AUTH)
    raw["receipt_sha256"] = stable({k: v for k, v in raw.items() if k != "receipt_sha256"})

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(raw, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return raw


def self_test() -> int:
    parent = {
        "win_rate": 0.50,
        "net_pnl_bps": 5916.88228000881,
        "net_expectancy_bps": 493.0735233340675,
        "realized_exit_bucket_max_drawdown_bps": 271.944799183461,
    }
    child = {
        "win_rate": 0.5238095238095238,
        "net_pnl_bps": 11150.637971241846,
        "net_expectancy_bps": 530.982760535326,
        "realized_exit_bucket_max_drawdown_bps": 358.6480209467463,
    }
    r = base.pareto(parent, child)
    assert r["relation"] == "PARTIAL_SUCCESS_PRESERVE_AND_EXTEND", r
    assert set(r["improved_metrics"]) >= {"win_rate", "net_pnl_bps", "net_expectancy_bps"}, r
    assert "realized_exit_bucket_max_drawdown_bps" in r["worsened_metrics"], r
    print("PASS_A1_COMMON_REGIME_SELECTOR_PARETO_VALIDATED_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_common_regime_selector_pareto_validated_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result["state"],
        "routes": {x["strategy_id"]: x["route"] for x in result["strategies"]},
        "break_relation": next(x for x in result["strategies"] if x["strategy_id"] == "break_and_continue")["pareto"]["relation"],
        "st_trigger": next(x for x in result["strategies"] if x["strategy_id"] == "supertrend_pullback")["trigger_classes"],
        "tm_trigger": next(x for x in result["strategies"] if x["strategy_id"] == "trend_ma_macd")["trigger_classes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
