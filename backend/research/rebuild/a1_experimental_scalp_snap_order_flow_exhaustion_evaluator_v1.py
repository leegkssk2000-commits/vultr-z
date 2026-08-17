from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.production.zel_production_a1_jump_liquidity_economic_v1 import _finite, _load_jsonl, _sign, _source_complete
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as baseline
from backend.research.rebuild.a1_exact25_hardening_evidence_adapter_v1 import load_verified_hardening_evidence
from backend.research.rebuild.a1_exact25_survivor_gate_v1 import attach_survivor_gate, stable_sha

EXPERIMENT_ID = "scalp_snap_v2_order_flow_exhaustion_confirmation"
CONFIG_SCHEMA = "zel.a1_experimental_scalp_snap_order_flow_exhaustion_config.v1"
POLICY_SCHEMA = "zel.a1_experimental_scalp_snap_order_flow_exhaustion_policy.v1"
RECEIPT_SCHEMA = "zel.a1_experimental_scalp_snap_order_flow_exhaustion_receipt.v1"
ROW_SCHEMA = "zel.production_bingx_ws_microstructure_row.v1"


def load_object(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return row


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_contract(config: dict[str, Any], policy: dict[str, Any]) -> None:
    if config.get("schema_version") != CONFIG_SCHEMA or config.get("experiment_id") != EXPERIMENT_ID:
        raise RuntimeError("EXPERIMENT_CONFIG_INVALID")
    if policy.get("schema_version") != POLICY_SCHEMA or policy.get("experiment_id") != EXPERIMENT_ID:
        raise RuntimeError("EXPERIMENT_POLICY_INVALID")
    if config.get("baseline_strategy_id") != "scalp_snap" or policy.get("baseline_strategy_id") != "scalp_snap":
        raise RuntimeError("BASELINE_STRATEGY_DRIFT")
    if policy.get("selected_axis") != "ORDER_FLOW_EXHAUSTION_CONFIRMATION":
        raise RuntimeError("EXPERIMENT_AXIS_DRIFT")
    confirm = policy.get("entry_time_confirmation") or {}
    if int(confirm.get("bucket_ms") or 0) != 5000:
        raise RuntimeError("MICRO_BUCKET_DRIFT")
    if confirm.get("threshold_search") is not False or confirm.get("magnitude_threshold") is not None:
        raise RuntimeError("EXPERIMENT_THRESHOLD_SEARCH_FORBIDDEN")
    if confirm.get("lookahead") is not False or confirm.get("future_outcome_fields") is not False:
        raise RuntimeError("EXPERIMENT_LOOKAHEAD_FORBIDDEN")
    for row in (config, policy):
        auth = row.get("authority") or {}
        if auth.get("selection_authority") is not False or auth.get("promotion_authority") is not False:
            raise RuntimeError("EXPERIMENT_SELECTION_PROMOTION_FORBIDDEN")
        if auth.get("execution_authority") != "NONE" or auth.get("order_authority") != "BLOCKED" or auth.get("live_trade_authority") != "BLOCKED":
            raise RuntimeError("EXPERIMENT_EXECUTION_AUTHORITY_INVALID")
        if int(auth.get("protected_mutations") or 0) != 0:
            raise RuntimeError("EXPERIMENT_PROTECTED_MUTATION_FORBIDDEN")
    if config.get("parameter_search") is not False or config.get("best_horizon_selection") is not False or config.get("threshold_tuning") is not False:
        raise RuntimeError("EXPERIMENT_SEARCH_FORBIDDEN")
    if config.get("baseline_clock_reset") is not False:
        raise RuntimeError("BASELINE_CLOCK_RESET_FORBIDDEN")


def micro_index(rows: list[dict[str, Any]], symbols: list[str]) -> dict[str, tuple[list[int], list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if symbol in grouped and row.get("schema_version") == ROW_SCHEMA and _source_complete(row):
            grouped[symbol].append(row)
    out: dict[str, tuple[list[int], list[dict[str, Any]]]] = {}
    for symbol, items in grouped.items():
        items.sort(key=lambda x: int(x.get("bucket_end_ms") or 0))
        out[symbol] = ([int(x.get("bucket_end_ms") or 0) for x in items], items)
    return out


def exhaustion_confirmation(index: dict[str, tuple[list[int], list[dict[str, Any]]]], symbol: str, entry_ts: int, side_name: str, bucket_ms: int = 5000) -> dict[str, Any]:
    side = 1 if side_name == "long" else -1 if side_name == "short" else 0
    if side == 0 or symbol not in index:
        return {"passed": False, "reason": "INVALID_SIDE_OR_SYMBOL"}
    ends, rows = index[symbol]
    pos = bisect.bisect_right(ends, int(entry_ts)) - 1
    if pos < 1:
        return {"passed": False, "reason": "INSUFFICIENT_PREENTRY_MICRO_BUCKETS"}
    current, previous = rows[pos], rows[pos - 1]
    current_end = int(current.get("bucket_end_ms") or 0)
    current_start = int(current.get("bucket_start_ms") or 0)
    previous_start = int(previous.get("bucket_start_ms") or 0)
    if current_end > int(entry_ts) or int(entry_ts) - current_end > bucket_ms:
        return {"passed": False, "reason": "PREENTRY_MICRO_BUCKET_STALE"}
    if current_start - previous_start != bucket_ms:
        return {"passed": False, "reason": "MICRO_BUCKETS_NOT_CONSECUTIVE"}
    prev_flow = _sign(_finite(previous.get("trade_imbalance")))
    current_flow = _sign(_finite(current.get("trade_imbalance")))
    current_book = _sign(_finite(current.get("imbalance_top20_mean")))
    passed = prev_flow == -side and current_flow == side and current_book == side
    return {
        "passed": passed,
        "reason": "ORDER_FLOW_EXHAUSTION_CONFIRMED" if passed else "ORDER_FLOW_EXHAUSTION_NOT_CONFIRMED",
        "previous_bucket_start_ms": previous_start,
        "current_bucket_start_ms": current_start,
        "current_bucket_end_ms": current_end,
        "previous_trade_flow_sign": prev_flow,
        "current_trade_flow_sign": current_flow,
        "current_book_imbalance_sign": current_book,
        "required_previous_trade_flow_sign": -side,
        "required_current_sign": side,
    }


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net = [float(x["net_bps"]) for x in trades]
    gross = [float(x["gross_bps"]) for x in trades]
    wins = [x for x in net if x > 0]
    losses = [-x for x in net if x < 0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    return {
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": sum(net) / len(net) if net else None,
        "net_profit_factor": gp / gl if gl > 0 else (math.inf if gp > 0 else None),
        "net_payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
        "win_rate": len(wins) / len(net) if net else None,
        "max_drawdown_bps": baseline.max_drawdown(net),
    }


def run_baseline_candidates(boundary: str, symbols: list[str], out_path: Path) -> dict[str, Any]:
    ledger = {
        "active_strategy_id": "scalp_snap",
        "strategies": {"scalp_snap": {"status": "ACTIVE", "prospective_boundary_utc": boundary}},
    }
    with tempfile.TemporaryDirectory(prefix="a1-scalp-exp-") as td:
        ledger_path = Path(td) / "ledger.json"
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        old_ledger = baseline.LEDGER_PATH
        old_argv = sys.argv[:]
        try:
            baseline.LEDGER_PATH = ledger_path
            sys.argv = ["a1_exact25_generic_evaluator_v1.py", "--strategy-id", "scalp_snap", "--symbols", ",".join(symbols), "--out", str(out_path)]
            baseline.main()
        finally:
            baseline.LEDGER_PATH = old_ledger
            sys.argv = old_argv
    return load_object(out_path)


def evaluate(config_path: Path, policy_path: Path, out_path: Path) -> dict[str, Any]:
    config, policy = load_object(config_path), load_object(policy_path)
    validate_contract(config, policy)
    boundary = str(config.get("fresh_prospective_boundary_utc") or "")
    if not boundary:
        raise RuntimeError("FRESH_PROSPECTIVE_BOUNDARY_REQUIRED")
    symbols = [str(x) for x in config.get("symbols") or []]
    if symbols != ["BTC-USDT", "ETH-USDT"]:
        raise RuntimeError("EXPERIMENT_SYMBOLS_DRIFT")
    history_path = Path(str(config["microstructure_history_path"]))
    if not history_path.is_file():
        raise RuntimeError(f"MICROSTRUCTURE_HISTORY_MISSING:{history_path}")

    baseline_out = out_path.with_suffix(".baseline_candidates.json")
    base = run_baseline_candidates(boundary, symbols, baseline_out)
    rows = _load_jsonl(history_path)
    idx = micro_index(rows, symbols)
    confirmed: list[dict[str, Any]] = []
    rejected = 0
    confirmations: list[dict[str, Any]] = []
    for trade in base.get("trades") or []:
        if not isinstance(trade, dict):
            continue
        check = exhaustion_confirmation(idx, str(trade.get("symbol")), int(trade.get("entry_ts") or 0), str(trade.get("side")), int(config["microstructure_bucket_ms"]))
        confirmations.append({"symbol": trade.get("symbol"), "entry_ts": trade.get("entry_ts"), "side": trade.get("side"), **check})
        if check["passed"]:
            confirmed.append(dict(trade, experimental_confirmation=check))
        else:
            rejected += 1

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "state": "WAIT_FRESH_PROSPECTIVE_DATA" if not confirmed else "A1_EXPERIMENTAL_ECONOMICS_ACTIVE",
        "experiment_id": EXPERIMENT_ID,
        "baseline_strategy_id": "scalp_snap",
        "experimental_not_baseline": True,
        "boundary_utc": boundary,
        "policy_path": str(policy_path),
        "policy_sha256": file_sha256(policy_path),
        "config_path": str(config_path),
        "config_sha256": file_sha256(config_path),
        "baseline_policy_sha": base.get("policy_sha"),
        "baseline_config_sha": base.get("config_sha"),
        "cost_authority_sha256": base.get("cost_authority_sha256"),
        "execution_snapshots": base.get("execution_snapshots") or {},
        "source": {
            "baseline_ohlcv": base.get("source"),
            "microstructure_history_path": str(history_path),
            "microstructure_rows_total": len(rows),
            "microstructure_source_authority_pr": 773,
            "entry_time_only": True,
        },
        "baseline_candidate_completed_trades": int(base.get("completed_trades") or 0),
        "confirmed_completed_trades": len(confirmed),
        "completed_trades": len(confirmed),
        "intent_count": len(confirmed),
        "confirmation_rejected_completed_candidates": rejected,
        "metrics": metrics(confirmed),
        "trades": confirmed,
        "confirmation_audit": confirmations,
        "integrity_defects": list(base.get("integrity_defects") or []),
        "leakage_lookahead": int(base.get("leakage_lookahead") or 0),
        "parameter_search": False,
        "best_horizon_selection": False,
        "threshold_tuning": False,
        "baseline_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    receipt = attach_survivor_gate(receipt, hardening_evidence=load_verified_hardening_evidence())
    receipt["negative_control_state"] = str(receipt.get("negative_control_gate") or "PENDING_H4_NEGATIVE_CONTROL_SUPERIORITY")
    receipt["receipt_sha256"] = stable_sha({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False, default=str), encoding="utf-8")
    return receipt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    receipt = evaluate(args.config, args.policy, args.out)
    print(json.dumps({
        "state": receipt["state"],
        "experiment_id": receipt["experiment_id"],
        "completed_trades": receipt["completed_trades"],
        "net_expectancy_bps": receipt["metrics"].get("net_expectancy_bps"),
        "survivor_gate_state": (receipt.get("survivor_gate") or {}).get("state"),
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
