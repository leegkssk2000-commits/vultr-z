from __future__ import annotations

import argparse
import json
import random
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_regime_conditioned_flow_momentum_evaluator_v1 as rcfm
from backend.research.rebuild import a1_exact25_v3_universal_controls_v2 as universal
from backend.production.zel_production_a1_jump_liquidity_economic_v1 import _source_complete

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "backend/research/architecture_factory/a1_regime_conditioned_flow_momentum_policy_v1.json"
PREREG = ROOT / "backend/research/architecture_factory/a1_regime_conditioned_flow_momentum_prereg_v1.json"
CONTRACT = ROOT / "backend/research/architecture_factory/a1_rcfm_causal_control_contract_v1.json"
CANDIDATE_ID = "NEW_RCFM_001"
MECHANISM_FEATURES = ["price", "volume", "multi_hour_momentum", "trade_flow", "l2_order_book", "source_freshness"]
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _heartbeat_pass(heartbeat: Mapping[str, Any]) -> None:
    if heartbeat.get("state") != "PASS_BINGX_WS_MICROSTRUCTURE_V2_ACCUMULATING":
        raise RuntimeError("RCFM_HEARTBEAT_STATE_INVALID")
    age = int(time.time() * 1000) - int(heartbeat.get("updated_at_ms") or 0)
    if age < 0 or age > 120000:
        raise RuntimeError(f"RCFM_HEARTBEAT_STALE:{age}")
    if heartbeat.get("selection_authority") is not False or heartbeat.get("promotion_authority") is not False:
        raise RuntimeError("RCFM_HEARTBEAT_AUTHORITY_INVALID")
    if heartbeat.get("execution_authority") != "NONE" or heartbeat.get("order_authority") != "BLOCKED" or heartbeat.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("RCFM_HEARTBEAT_EXECUTION_AUTHORITY_INVALID")


def _validate(receipt: Mapping[str, Any], heartbeat: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    policy, prereg, contract = read(POLICY), read(PREREG), read(CONTRACT)
    _heartbeat_pass(heartbeat)
    if contract.get("state") != "FROZEN_BEFORE_RCFM_CAUSAL_CONTROL_OUTCOME" or contract.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("RCFM_CAUSAL_CONTRACT_INVALID")
    if receipt.get("candidate_id") != CANDIDATE_ID or receipt.get("experiment_id") != "regime_conditioned_flow_momentum_v1":
        raise RuntimeError("RCFM_RECEIPT_IDENTITY_INVALID")
    boundary = str(policy.get("fresh_prospective_boundary_utc") or "")
    if receipt.get("boundary_utc") != boundary or prereg.get("fresh_prospective_boundary_utc") != boundary or contract.get("prospective_boundary_utc") != boundary:
        raise RuntimeError("RCFM_BOUNDARY_LINEAGE_INVALID")
    if receipt.get("policy_sha") != rcfm.git_blob_sha(POLICY) or receipt.get("prereg_sha") != rcfm.git_blob_sha(PREREG):
        raise RuntimeError("RCFM_POLICY_PREREG_SHA_MISMATCH")
    if list(receipt.get("integrity_defects") or []) or int(receipt.get("leakage_lookahead") or 0) != 0 or int(receipt.get("duplicate_count") or 0) != 0:
        raise RuntimeError("RCFM_RECEIPT_INTEGRITY_INVALID")
    if receipt.get("selection_authority") is not False or receipt.get("promotion_authority") is not False or receipt.get("execution_authority") != "NONE" or receipt.get("order_authority") != "BLOCKED":
        raise RuntimeError("RCFM_RECEIPT_AUTHORITY_INVALID")
    if policy.get("parameter_search") is not False or policy.get("threshold_tuning") is not False or policy.get("best_horizon_selection") is not False:
        raise RuntimeError("RCFM_POLICY_SEARCH_INVALID")
    declared = set(str(x) for x in policy.get("controls") or [])
    if not {"DIRECTION_FLIP", "ONE_BAR_DELAY", "MICRO_SIGN_PERMUTATION"}.issubset(declared):
        raise RuntimeError("RCFM_PREDECLARED_CONTROL_SET_INVALID")
    return policy, prereg, contract


def _canonical(receipt: Mapping[str, Any], heartbeat: Mapping[str, Any]) -> dict[str, Any]:
    policy_sha = str(receipt["policy_sha"])
    prereg_sha = str(receipt["prereg_sha"])
    cfg_sha = universal.stable_sha({"candidate_id": CANDIDATE_ID, "policy_sha": policy_sha, "prereg_sha": prereg_sha})
    trades = []
    for row in receipt.get("trades") or []:
        if not isinstance(row, Mapping):
            continue
        trades.append({
            "symbol": str(row["symbol"]),
            "side": str(row["side"]),
            "signal_ts": int(row["signal_ts_ms"]),
            "entry_ts": int(row["entry_ts_ms"]),
            "exit_ts": int(row["exit_ts_ms"]),
            "gross_bps": float(row["gross_bps"]),
            "realized_cost_bps": float(row["realized_cost_bps"]),
            "net_bps": float(row["net_bps"]),
            "intent_sha": str(row["intent_sha"]),
        })
    out = {
        "schema_version": "zel.a1.rcfm.canonical_causal_receipt.v1",
        "strategy_id": CANDIDATE_ID,
        "boundary_utc": receipt["boundary_utc"],
        "policy_sha": policy_sha,
        "config_sha": cfg_sha,
        "source": {"interval": "5m", "source_owner": "BINGX_WS_MICROSTRUCTURE_V2_PLUS_PUBLIC_KLINE"},
        "source_quality_gate": {
            "state": "PASS",
            "heartbeat_state": heartbeat.get("state"),
            "heartbeat_updated_at_ms": heartbeat.get("updated_at_ms"),
        },
        "integrity_defects": [],
        "leakage_lookahead": 0,
        "trades": trades,
        "original_receipt_sha256": receipt.get("receipt_sha256"),
        **AUTH,
    }
    out["receipt_sha256"] = universal.stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out


def _run_universal(canonical: Mapping[str, Any]) -> dict[str, Any]:
    original_read = universal.read
    def patched(path: Path) -> dict[str, Any]:
        data = original_read(path)
        if path == universal.OWNERSHIP:
            data = json.loads(json.dumps(data))
            data.setdefault("strategies", {})[CANDIDATE_ID] = {
                "mechanism_features": list(MECHANISM_FEATURES),
                "source": "RCFM_PREREG_AND_POLICY",
            }
        return data
    universal.read = patched
    try:
        return universal.evaluate(canonical)
    finally:
        universal.read = original_read


def _complete_indices(rows: list[dict[str, Any]], symbol: str) -> list[int]:
    return [i for i, row in enumerate(rows) if str(row.get("symbol") or "") == symbol and _source_complete(row)]


def _permuted_micro(rows: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    out = [dict(x) for x in rows]
    rng = random.Random(seed)
    for symbol in sorted({str(x.get("symbol") or "") for x in out if x.get("symbol")}):
        idx = _complete_indices(out, symbol)
        pairs = [(float(out[i].get("trade_imbalance") or 0.0), float(out[i].get("imbalance_top20_mean") or 0.0)) for i in idx]
        rng.shuffle(pairs)
        for i, pair in zip(idx, pairs):
            out[i]["trade_imbalance"], out[i]["imbalance_top20_mean"] = pair
    return out


def _independent_stats(candidate: list[float], control: list[float], seed: int, n_boot: int = 10000) -> tuple[float, float, float]:
    if not candidate or len(candidate) != len(control):
        raise RuntimeError("RCFM_MICRO_CONTROL_BUDGET_INVALID")
    rng = random.Random(seed)
    obs = sum(candidate) / len(candidate) - sum(control) / len(control)
    pooled = list(candidate) + list(control)
    ge = 1
    n = len(candidate)
    for _ in range(n_boot):
        shuffled = list(pooled)
        rng.shuffle(shuffled)
        diff = sum(shuffled[:n]) / n - sum(shuffled[n:]) / n
        if diff >= obs:
            ge += 1
    p = ge / (n_boot + 1)
    boots = []
    for _ in range(n_boot):
        a = sum(candidate[rng.randrange(n)] for __ in range(n)) / n
        b = sum(control[rng.randrange(n)] for __ in range(n)) / n
        boots.append(a - b)
    boots.sort()
    ci_low = boots[max(0, int(0.05 * n_boot) - 1)]
    return obs, ci_low, p


def _micro_control(receipt: Mapping[str, Any], micro_path: Path, policy: Mapping[str, Any], prereg: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    rows = rcfm._load_jsonl(micro_path)
    seed = int(universal.stable_sha({
        "candidate_id": CANDIDATE_ID,
        "policy_sha": receipt.get("policy_sha"),
        "prereg_sha": receipt.get("prereg_sha"),
        "boundary": receipt.get("boundary_utc"),
        "control": "micro_sign_permutation",
    })[:16], 16)
    permuted = _permuted_micro(rows, seed)
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8", delete=False) as fh:
        temp = Path(fh.name)
        for row in permuted:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    try:
        ctrl = rcfm.evaluate(str(receipt["boundary_utc"]), temp, list(policy["symbols"]))
    finally:
        temp.unlink(missing_ok=True)
    if ctrl.get("policy_sha") != receipt.get("policy_sha") or ctrl.get("prereg_sha") != receipt.get("prereg_sha"):
        raise RuntimeError("RCFM_MICRO_CONTROL_LINEAGE_MISMATCH")
    if list(ctrl.get("integrity_defects") or []) or int(ctrl.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("RCFM_MICRO_CONTROL_INTEGRITY_FAIL")
    frozen_n = int(contract["cohort"]["trade_count"])
    candidate_trades = sorted(
        [dict(x) for x in receipt.get("trades") or [] if isinstance(x, Mapping)],
        key=lambda x: (int(x["entry_ts_ms"]), str(x["symbol"]), str(x["intent_sha"])),
    )[:frozen_n]
    control_trades = sorted(
        [dict(x) for x in ctrl.get("trades") or [] if isinstance(x, Mapping)],
        key=lambda x: (int(x["entry_ts_ms"]), str(x["symbol"]), str(x["intent_sha"])),
    )[:frozen_n]
    if len(candidate_trades) < frozen_n or len(control_trades) < frozen_n:
        return {
            "state": "HOLD_MICRO_PERMUTATION_SAMPLE",
            "pass": False,
            "candidate_trade_count": len(candidate_trades),
            "control_trade_count": len(control_trades),
            "seed": seed,
            "control_receipt_sha256": ctrl.get("receipt_sha256"),
        }
    candidate = [float(x["net_bps"]) / 100.0 for x in candidate_trades]
    control = [float(x["net_bps"]) / 100.0 for x in control_trades]
    stats_seed = seed ^ 0x5243464D
    obs, ci, p = _independent_stats(candidate, control, stats_seed)
    passed = p <= 0.05 and ci > 0.0
    return {
        "state": "PASS" if passed else "FAIL",
        "pass": passed,
        "p_value": p,
        "candidate_minus_control_mean_R": obs,
        "candidate_minus_control_ci_low_R": ci,
        "candidate_net_R": sum(candidate),
        "control_net_R": sum(control),
        "candidate_trade_count": len(candidate),
        "control_trade_count": len(control),
        "seed": seed,
        "control_receipt_sha256": ctrl.get("receipt_sha256"),
        "candidate_cohort_sha256": universal.stable_sha([{k: x.get(k) for k in ("symbol", "entry_ts_ms", "exit_ts_ms", "intent_sha", "net_bps")} for x in candidate_trades]),
        "control_cohort_sha256": universal.stable_sha([{k: x.get(k) for k in ("symbol", "entry_ts_ms", "exit_ts_ms", "intent_sha", "net_bps")} for x in control_trades]),
        "permutation_unit": "WITHIN_SYMBOL_COMPLETE_MICRO_ROWS",
        "timestamps_frozen": True,
        "best_permutation_selection": False,
    }


def evaluate(receipt: Mapping[str, Any], heartbeat: Mapping[str, Any], micro_path: Path) -> dict[str, Any]:
    policy, prereg, contract = _validate(receipt, heartbeat)
    canonical = _canonical(receipt, heartbeat)
    universal_result = _run_universal(canonical)
    micro = _micro_control(receipt, micro_path, policy, prereg, contract)
    universal_pass = universal_result.get("state") == "PASS_V3_UNIVERSAL_HARD_CONTROLS"
    micro_pass = micro.get("state") == "PASS"
    terminal_fail = (
        universal_result.get("state") == "HOLD_V3_UNIVERSAL_HARD_CONTROLS"
        and any(v == "FAIL" for v in (universal_result.get("hard_control_states") or {}).values())
    ) or micro.get("state") == "FAIL"
    wait = universal_result.get("state") == "WAIT_V3_CONTROL_SAMPLE" or micro.get("state") == "HOLD_MICRO_PERMUTATION_SAMPLE"
    state = "PASS_RCFM_V3_CAUSAL_CONTROLS" if universal_pass and micro_pass else "WAIT_RCFM_V3_CAUSAL_CONTROLS" if wait and not terminal_fail else "FAIL_RCFM_V3_CAUSAL_CONTROLS"
    result = {
        "schema_version": "zel.a1.rcfm.v3_causal_controls.v1",
        "state": state,
        "candidate_id": CANDIDATE_ID,
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "canonical_receipt": canonical,
        "universal_controls": universal_result,
        "micro_sign_permutation": micro,
        "hard_control_states": {
            **dict(universal_result.get("hard_control_states") or {}),
            "micro_sign_permutation": micro.get("state"),
        },
        "same_identity_retest_forbidden": state in {"PASS_RCFM_V3_CAUSAL_CONTROLS", "FAIL_RCFM_V3_CAUSAL_CONTROLS"},
        "next_route": "A1_V3_CAUSAL_READY_EVALUATION" if state == "PASS_RCFM_V3_CAUSAL_CONTROLS" else "WAIT_ONLY" if state.startswith("WAIT_") else "BOUNDED_REDESIGN_OR_SYNTHESIS_NEW_IDENTITY",
        "contract_sha256": universal.stable_sha(contract),
        **AUTH,
    }
    result["receipt_sha256"] = universal.stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    contract = read(CONTRACT)
    policy = read(POLICY)
    assert contract["candidate_id"] == CANDIDATE_ID
    assert int(contract["cohort"]["trade_count"]) == 25
    assert "MICRO_SIGN_PERMUTATION" in set(policy["controls"])
    assert contract["anti_tuning"]["control_seed_sweep"] is False
    print("PASS_A1_RCFM_V3_CAUSAL_CONTROLS_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--heartbeat", type=Path)
    ap.add_argument("--micro", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_rcfm_v3_causal_controls_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.receipt or not args.heartbeat or not args.micro:
        raise SystemExit("--receipt --heartbeat --micro required")
    result = evaluate(read(args.receipt), read(args.heartbeat), args.micro)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "candidate_id": result["candidate_id"],
        "hard_control_states": result["hard_control_states"],
        "universal": result["universal_controls"].get("hard_control_states"),
        "micro": result["micro_sign_permutation"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
