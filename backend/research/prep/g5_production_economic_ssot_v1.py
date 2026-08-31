#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import g5_trendrider_broad30_product_oos_v1 as base

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/prep/g5_production_economic_contract_v1.json"
DURABLE = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
LEDGER = ROOT / "backend/research/prep/g5_economic_evidence_ledger_v1.jsonl"
CONTRACT_SCHEMA = "zel.g5.production_economic_contract.v1"
EVIDENCE_SCHEMA = "zel.g5.economic_evidence_row.v1"
SSOT_SCHEMA = "zel.g5.production_economic_ssot.v1"


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode()
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def validate_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        raise RuntimeError("G5_PRODUCTION_ECONOMIC_CONTRACT_SCHEMA_MISMATCH")
    if contract.get("stage") != "G5" or contract.get("state") != "FROZEN_G5_PRODUCTION_ECONOMIC_CONTRACT":
        raise RuntimeError("G5_PRODUCTION_ECONOMIC_CONTRACT_NOT_FROZEN")
    if (contract.get("ai_gate") or {}).get("scope") != "G5_ONLY":
        raise RuntimeError("G5_ONLY_AI_GATE_REQUIRED")
    if (contract.get("ledger") or {}).get("append_only") is not True:
        raise RuntimeError("G5_APPEND_ONLY_LEDGER_REQUIRED")
    required = contract.get("required_provenance") or {}
    if (required.get("cost") or {}).get("point_in_time_at_trade") is not True:
        raise RuntimeError("G5_POINT_IN_TIME_COST_REQUIRED")
    if (required.get("funding") or {}).get("signed_settlement_lineage") is not True:
        raise RuntimeError("G5_SIGNED_FUNDING_LINEAGE_REQUIRED")
    if (required.get("execution") or {}).get("intrabar_order_observed") is not True:
        raise RuntimeError("G5_INTRABAR_EXECUTION_PROVENANCE_REQUIRED")


def runtime_rows(raw_receipt: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    boundary_ms = int(manifest["prospective_boundary_ms"])
    rows = sorted(
        [
            dict(row)
            for row in (raw_receipt.get("trades") or [])
            if isinstance(row, Mapping)
            and int(row.get("signal_ts") or 0) > boundary_ms
            and int(row.get("exit_ts") or 0) > boundary_ms
        ],
        key=lambda row: (int(row["signal_ts"]), str(row["symbol"]), str(row["side"])),
    )
    dedup: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for row in rows:
        dedup[base.trade_key(row)] = row
    return list(dedup.values())


def trade_id(row: Mapping[str, Any]) -> str:
    return stable(
        {
            "symbol": str(row.get("symbol") or ""),
            "signal_ts": int(row.get("signal_ts") or 0),
            "entry_ts": int(row.get("entry_ts") or 0),
            "exit_ts": int(row.get("exit_ts") or 0),
            "side": str(row.get("side") or ""),
            "intent_sha": str(row.get("intent_sha") or ""),
        }
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def classify_trade(row: Mapping[str, Any], *, source_receipt_sha256: str) -> dict[str, Any]:
    mode = str(row.get("economic_origin") or row.get("economic_mode") or "REPLAY_CURRENT_PROXY")
    cost_p = _mapping(row.get("cost_provenance"))
    fee_p = _mapping(row.get("fee_provenance"))
    funding_p = _mapping(row.get("funding_provenance"))
    execution_p = _mapping(row.get("execution_provenance"))

    if mode == "FORWARD_REAL":
        reasons: list[str] = []
        if cost_p.get("point_in_time_at_trade") is not True or fee_p.get("point_in_time_at_trade") is not True:
            reasons.append("CURRENT_DEPTH_OR_COST_SNAPSHOT_APPLIED_TO_HISTORICAL_REPLAY")
        if funding_p.get("signed_settlement_lineage") is not True:
            reasons.append("SIGNED_FUNDING_SETTLEMENT_LINEAGE_MISSING")
        if execution_p.get("intrabar_order_observed") is not True:
            reasons.append("INTRABAR_EXECUTION_ORDER_NOT_OBSERVED")
    else:
        reasons = [
            "CURRENT_DEPTH_OR_COST_SNAPSHOT_APPLIED_TO_HISTORICAL_REPLAY",
            "SIGNED_FUNDING_SETTLEMENT_LINEAGE_MISSING",
            "INTRABAR_EXECUTION_ORDER_NOT_OBSERVED",
        ]

    eligible = mode == "FORWARD_REAL" and not reasons
    evidence: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA,
        "stage": "G5",
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_broad_wr7000",
        "trade_id": trade_id(row),
        "source_receipt_sha256": source_receipt_sha256,
        "economic_origin": mode,
        "production_grade": eligible,
        "production_fail_closed_reasons": reasons,
        "trade": {
            "symbol": str(row.get("symbol") or ""),
            "signal_ts": int(row.get("signal_ts") or 0),
            "entry_ts": int(row.get("entry_ts") or 0),
            "exit_ts": int(row.get("exit_ts") or 0),
            "side": str(row.get("side") or ""),
            "entry": row.get("entry"),
            "exit": row.get("exit"),
            "reason": row.get("reason"),
            "gross_bps": row.get("gross_bps"),
            "realized_cost_bps": row.get("realized_cost_bps"),
            "net_bps": row.get("net_bps"),
        },
        "cost_provenance": dict(cost_p) if cost_p else {
            "mode": "CURRENT_EXECUTION_SNAPSHOT_APPLIED_TO_REPLAY",
            "point_in_time_at_trade": False,
            "cost_snapshot_sha": str(row.get("cost_snapshot_sha") or ""),
            "component_decomposition_verified": False,
        },
        "fee_provenance": dict(fee_p) if fee_p else {
            "point_in_time_at_trade": False,
            "source": "CURRENT_COST_AUTHORITY_PROXY",
        },
        "funding_provenance": dict(funding_p) if funding_p else {
            "signed_settlement_lineage": False,
            "source": "ABSOLUTE_OR_CURRENT_FUNDING_PROXY",
        },
        "execution_provenance": dict(execution_p) if execution_p else {
            "intrabar_order_observed": False,
            "source": "OHLC_REPLAY_SL_FIRST_TOUCH_PRECEDENCE",
            "gap_and_touch_sequence_verified": False,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    evidence["evidence_row_sha256"] = stable(evidence)
    return evidence


def evidence_rows(raw_receipt: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    source_sha = str(raw_receipt.get("receipt_sha256") or "")
    if not source_sha:
        raise RuntimeError("G5_SOURCE_RECEIPT_SHA_REQUIRED")
    return [classify_trade(row, source_receipt_sha256=source_sha) for row in runtime_rows(raw_receipt, manifest)]


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError(f"G5_LEDGER_OBJECT_REQUIRED:{line_no}")
        supplied = str(value.get("evidence_row_sha256") or "")
        core = dict(value)
        core.pop("evidence_row_sha256", None)
        if not supplied or supplied != stable(core):
            raise RuntimeError(f"G5_LEDGER_ROW_SHA_MISMATCH:{line_no}")
        if supplied in seen:
            raise RuntimeError(f"G5_LEDGER_DUPLICATE_ROW:{line_no}:{supplied}")
        seen.add(supplied)
        rows.append(value)
    return rows


def merge_ledger(current_path: Path, new_rows: list[Mapping[str, Any]], out_path: Path) -> dict[str, Any]:
    existing = read_ledger(current_path)
    known = {str(row["evidence_row_sha256"]) for row in existing}
    merged = list(existing)
    appended = 0
    for raw in new_rows:
        row = dict(raw)
        supplied = str(row.get("evidence_row_sha256") or "")
        core = dict(row)
        core.pop("evidence_row_sha256", None)
        if not supplied or supplied != stable(core):
            raise RuntimeError("G5_NEW_LEDGER_ROW_SHA_MISMATCH")
        if supplied in known:
            continue
        known.add(supplied)
        merged.append(row)
        appended += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n" for row in merged)
    out_path.write_text(text, encoding="utf-8")
    return {
        "existing_rows": len(existing),
        "appended_rows": appended,
        "total_rows": len(merged),
        "ledger_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def durable_observation(durable: Mapping[str, Any] | None, ids: list[str]) -> dict[str, Any]:
    runtime_set_sha = stable(sorted(ids))
    if durable is None:
        durable_t = 0
        durable_set_sha = ""
        durable_receipt = ""
    else:
        durable_t = int(durable.get("postlock_closed_T") or 0)
        ssot = _mapping(durable.get("economic_ssot"))
        durable_set_sha = str(ssot.get("runtime_trade_set_sha256") or "")
        durable_receipt = str(durable.get("receipt_sha256") or "")
    match = durable_t == len(ids) and bool(durable_set_sha) and durable_set_sha == runtime_set_sha
    return {
        "runtime_trade_count": len(ids),
        "runtime_trade_set_sha256": runtime_set_sha,
        "durable_trade_count": durable_t,
        "durable_trade_set_sha256": durable_set_sha,
        "durable_receipt_sha256": durable_receipt,
        "durable_matches_runtime": match,
        "count_only_match_is_insufficient": True,
    }


def harden(
    result: Mapping[str, Any],
    evidence: list[Mapping[str, Any]],
    durable: Mapping[str, Any] | None,
    ledger_info: Mapping[str, Any],
) -> dict[str, Any]:
    out = json.loads(json.dumps(result))
    ids = [str(row["trade_id"]) for row in evidence]
    durable_obs = durable_observation(durable, ids)
    prod_t = sum(1 for row in evidence if row.get("production_grade") is True)
    proxy_t = len(evidence) - prod_t
    production_ready = bool(evidence) and prod_t == len(evidence) and durable_obs["durable_matches_runtime"] is True
    research_state = str(out.get("state") or "")
    terminal_research_pass = research_state == "PASS_G5_PRODUCT_OOS_WALK_FORWARD_STRESS"
    terminal_eligible = production_ready and terminal_research_pass

    if durable_obs["durable_matches_runtime"] is not True:
        state = "HOLD_G5_ECONOMIC_SSOT_MISMATCH"
        ssot_state = "HOLD_RUNTIME_DURABLE_MISMATCH"
    elif not production_ready:
        state = "WAIT_G5_FORWARD_REAL_ECONOMICS"
        ssot_state = "WAIT_FORWARD_REAL_PRODUCTION_EVIDENCE"
    else:
        state = research_state
        ssot_state = "PASS_PRODUCTION_ECONOMIC_PROVENANCE"

    out["research_state"] = research_state
    out["state"] = state
    out["economic_ssot"] = {
        "schema_version": SSOT_SCHEMA,
        "state": ssot_state,
        **durable_obs,
        "production_grade_T": prod_t,
        "replay_or_proxy_T": proxy_t,
        "production_grade_ready": production_ready,
        "replay_forward_cost_provenance_verified": production_ready,
        "fail_closed_provenance_rows": proxy_t,
        "three_provenance_fail_closed": {
            "current_snapshot_historical_replay_blocked": True,
            "unsigned_or_absolute_funding_blocked": True,
            "ohlc_intrabar_ambiguity_blocked": True,
        },
        "ledger": dict(ledger_info),
        "contract_path": "backend/research/prep/g5_production_economic_contract_v1.json",
    }
    out["economic_trade_evidence"] = [
        {
            "trade_id": row["trade_id"],
            "evidence_row_sha256": row["evidence_row_sha256"],
            "economic_origin": row["economic_origin"],
            "production_grade": row["production_grade"],
            "production_fail_closed_reasons": row["production_fail_closed_reasons"],
        }
        for row in evidence
    ]
    out["ai_gate"] = {
        "scope": "G5_ONLY",
        "production_grade_claim_eligible": production_ready,
        "proxy_replay_production_pass_forbidden": True,
        "g6_promotion_eligible": terminal_eligible,
        "g6_promotion_forbidden": not terminal_eligible,
        "reason": (
            "G5_TERMINAL_PRODUCTION_GRADE_VERIFIED"
            if terminal_eligible
            else "G5_PRODUCTION_ECONOMIC_EVIDENCE_NOT_TERMINAL"
        ),
    }
    out["promotion_authority"] = False
    out["selection_authority"] = False
    out["action"] = "hold"
    out.pop("receipt_sha256", None)
    out["receipt_sha256"] = base.stable(out)
    return out


def self_test() -> int:
    contract = read_json(CONTRACT)
    validate_contract(contract)
    replay = {
        "symbol": "BTC-USDT", "signal_ts": 10, "entry_ts": 20, "exit_ts": 30, "side": "long",
        "entry": 100.0, "exit": 101.0, "gross_bps": 100.0, "realized_cost_bps": 10.0,
        "net_bps": 90.0, "intent_sha": "i", "cost_snapshot_sha": "c",
    }
    proxy = classify_trade(replay, source_receipt_sha256="r")
    assert proxy["production_grade"] is False
    assert len(proxy["production_fail_closed_reasons"]) == 3

    forward = dict(replay)
    forward.update({
        "economic_origin": "FORWARD_REAL",
        "cost_provenance": {"point_in_time_at_trade": True},
        "fee_provenance": {"point_in_time_at_trade": True},
        "funding_provenance": {"signed_settlement_lineage": True},
        "execution_provenance": {"intrabar_order_observed": True},
    })
    real = classify_trade(forward, source_receipt_sha256="r2")
    assert real["production_grade"] is True and real["production_fail_closed_reasons"] == []

    obs = durable_observation({"postlock_closed_T": 6, "receipt_sha256": "old"}, [str(i) for i in range(8)])
    assert obs["runtime_trade_count"] == 8 and obs["durable_trade_count"] == 6
    assert obs["durable_matches_runtime"] is False

    with tempfile.TemporaryDirectory(prefix="g5-economic-selftest-") as td:
        root = Path(td)
        current, out1, out2 = root / "current.jsonl", root / "out1.jsonl", root / "out2.jsonl"
        info1 = merge_ledger(current, [proxy, real], out1)
        assert info1["existing_rows"] == 0 and info1["appended_rows"] == 2 and info1["total_rows"] == 2
        info2 = merge_ledger(out1, [proxy, real], out2)
        assert info2["existing_rows"] == 2 and info2["appended_rows"] == 0 and info2["total_rows"] == 2
    print("PASS_G5_PRODUCTION_ECONOMIC_SSOT_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/g5_trendrider_broad30_product_latest.json"))
    ap.add_argument("--durable-current", type=Path, default=DURABLE)
    ap.add_argument("--ledger-current", type=Path, default=LEDGER)
    ap.add_argument("--ledger-out", type=Path, default=Path("out/g5_economic_evidence_ledger_v1.jsonl"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    contract = read_json(CONTRACT)
    validate_contract(contract)
    seal, manifest = base.read(base.SEAL), base.read(base.MANIFEST)
    base.validate_seal(seal)
    with tempfile.TemporaryDirectory(prefix="g5-production-economic-") as td:
        raw_receipt = base.current_policy_replay(
            out_path=Path(td) / "raw_replay_receipt.json",
            boundary_utc=str(manifest["prospective_boundary_utc"]),
        )
    base_result = base.evaluate(raw_receipt, seal, manifest)
    evidence = evidence_rows(raw_receipt, manifest)
    ledger_info = merge_ledger(args.ledger_current, evidence, args.ledger_out)
    durable = read_json(args.durable_current) if args.durable_current.exists() else None
    result = harden(base_result, evidence, durable, ledger_info)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "research_state": result["research_state"],
        "runtime_T": result["economic_ssot"]["runtime_trade_count"],
        "durable_T": result["economic_ssot"]["durable_trade_count"],
        "durable_matches_runtime": result["economic_ssot"]["durable_matches_runtime"],
        "production_grade_T": result["economic_ssot"]["production_grade_T"],
        "proxy_T": result["economic_ssot"]["replay_or_proxy_T"],
        "ledger_total": result["economic_ssot"]["ledger"]["total_rows"],
        "ai_g6_eligible": result["ai_gate"]["g6_promotion_eligible"],
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
