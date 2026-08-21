#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as econ
from backend.research.architecture_factory import a1_gen2_incumbent_hardening_v1 as incumbent
from backend.research.architecture_factory import a1_gen2_fresh_boundary_replay_v1 as strict_fresh
from backend.research.architecture_factory import a1_gen2_pass_robustness_audit_v1 as audit
from backend.research.architecture_factory import a1_gen2_prospective_data_v1 as prospective

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "backend/research/contracts/a1_gen2_repair_short_sma50_family_v1.json"
LEDGER_PATH = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def metrics(rows: list[dict[str, Any]], cost: float = 14.0) -> dict[str, Any]:
    values = [float(row["gross_bps"]) - cost for row in rows]
    count = len(values)
    return {
        "trades": count,
        "net_expectancy_bps": sum(values) / count if count else None,
        "net_pnl_bps": sum(values),
        "profit_factor": econ._pf(values) if count else None,
        "payoff": econ._payoff(values) if count else None,
        "win_rate": sum(x > 0 for x in values) / count if count else None,
        "drawdown_bps": econ._dd(values) if count else 0.0,
        "cost_bps_per_trade": cost,
    }


def parent_trades(loader: Callable[[str, str], list[dict[str, float]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    entry_rule = "ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
    side_rule = "long if ret(1) < -0.02 else short"
    for symbol in econ.SYMBOLS:
        bars = loader(symbol, "1d")
        engine = econ.Expr(bars, {})
        index = 30
        while index < len(bars) - 1:
            try:
                fire = bool(engine.eval(entry_rule, index))
            except Exception:
                fire = False
            if not fire:
                index += 1
                continue
            side = econ._side(side_rule, engine, index)
            entry_index = index + 1
            exit_index = min(entry_index + 11, len(bars) - 1)
            entry = float(bars[entry_index]["open"])
            exit_price = float(bars[exit_index]["close"])
            gross = (exit_price / entry - 1.0) * 10000.0 * (1.0 if side == "long" else -1.0)
            sma_window = bars[max(0, index - 49):index + 1]
            sma50 = sum(float(row["close"]) for row in sma_window) / len(sma_window)
            out.append({
                "symbol": symbol,
                "side": side,
                "signal_ts": int(bars[index]["ts"]),
                "entry_ts": int(bars[entry_index]["ts"]),
                "exit_ts": int(bars[exit_index]["ts"]),
                "gross_bps": gross,
                "regime": "ABOVE_SMA50" if float(bars[index]["close"]) >= sma50 else "BELOW_SMA50",
                "year": datetime.fromtimestamp(int(bars[index]["ts"]) / 1000, tz=timezone.utc).year,
            })
            index = max(index + 1, exit_index + 1)
    return out


def grouped(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[key]), []).append(row)
    return {name: metrics(items) for name, items in sorted(groups.items())}


def run(output: Path) -> dict[str, Any]:
    contract = json.loads(CONTRACT_PATH.read_text())
    if contract.get("state") != "FROZEN_PROSPECTIVE_REPAIR_FAMILY_CONTRACT":
        raise RuntimeError("FROZEN_REPAIR_FAMILY_CONTRACT_REQUIRED")

    audit_receipt = audit.run(Path("out/a1_gen2_pass_robustness_audit_v1.json"))
    parent = dict(audit_receipt["second_axis_repair"])
    repair = parent.get("repair") if isinstance(parent.get("repair"), dict) else {}
    if repair.get("candidate_id") != contract["parent_candidate_id"]:
        raise RuntimeError("PARENT_CANDIDATE_ID_MISMATCH")
    if parent.get("state") != "PASS_PARETO_IMPROVEMENT":
        raise RuntimeError("PARENT_PARETO_GATE_NOT_PASS")

    development_rows = parent_trades(econ.bars)
    development = metrics(development_rows)
    expected = parent["new_metrics"]
    for name in ("trades", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps"):
        if name == "trades":
            if development[name] != expected[name]:
                raise RuntimeError(f"PARENT_PATH_IDENTITY_MISMATCH:{name}")
        elif abs(float(development[name]) - float(expected[name])) > 1e-6:
            raise RuntimeError(f"PARENT_PATH_IDENTITY_MISMATCH:{name}")

    strict = incumbent.run(Path("out/a1_gen2_incumbent_hardening_v1.json"))
    if strict.get("candidate_id") != contract["strict_child_candidate_id"]:
        raise RuntimeError("STRICT_CHILD_ID_MISMATCH")
    strict_prospective = strict_fresh.run(Path("out/a1_gen2_fresh_boundary_replay_v1.json"))

    boundary_ms = int(
        datetime.fromisoformat(contract["frozen_at_utc"].replace("Z", "+00:00")).timestamp() * 1000
    )
    all_parent = parent_trades(prospective.bars)
    fresh_parent_rows = [row for row in all_parent if int(row["signal_ts"]) > boundary_ms]
    fresh_parent = metrics(fresh_parent_rows)
    fresh_symbols = sorted({str(row["symbol"]) for row in fresh_parent_rows})
    parent_mature = (
        fresh_parent["trades"] >= int(contract["minimum_fresh_trades"])
        and len(fresh_symbols) >= int(contract["minimum_fresh_symbols"])
    )
    parent_fresh_pass = bool(
        parent_mature
        and float(fresh_parent["net_expectancy_bps"]) > 0
        and float(fresh_parent["profit_factor"]) > 1
    )

    ledger = json.loads(LEDGER_PATH.read_text())
    gen1_done = int(ledger.get("done_count") or 0)
    gen1_total = int(ledger.get("total_count") or len(ledger.get("strategies") or {}))
    alpha_proof_unlocked = gen1_done == gen1_total == 25
    if not strict.get("hardening_pass"):
        state = "HOLD_STRICT_CHILD_HARDENING"
    elif strict_prospective.get("state") == "WAIT_FRESH_SAMPLE":
        state = "WAIT_FRESH_SAMPLE"
    elif not strict_prospective.get("prospective_pass"):
        state = "HOLD_PROSPECTIVE_ECONOMICS"
    elif not alpha_proof_unlocked:
        state = "HOLD_GEN1_ALPHA_PROOF_GATE"
    else:
        state = "READY_FOR_H4_H5"

    receipt = {
        "schema_version": "zel.a1_gen2.repair_short_sma50_family_receipt.v1",
        "state": state,
        "family_id": contract["family_id"],
        "contract_sha256": stable(contract),
        "parent": {
            "candidate_id": contract["parent_candidate_id"],
            "development_metrics": development,
            "cost_stress": {str(cost): metrics(development_rows, cost) for cost in (14.0, 28.0, 40.0)},
            "by_symbol": grouped(development_rows, "symbol"),
            "by_side": grouped(development_rows, "side"),
            "by_year": grouped(development_rows, "year"),
            "by_regime": grouped(development_rows, "regime"),
            "pareto_state": parent["state"],
            "fresh": {
                "boundary_utc": contract["frozen_at_utc"],
                "metrics": fresh_parent,
                "symbols": fresh_symbols,
                "mature": parent_mature,
                "prospective_pass": parent_fresh_pass,
            },
        },
        "strict_child": {
            "candidate_id": strict["candidate_id"],
            "development_hardening": strict,
            "prospective": strict_prospective,
        },
        "gen1_gate": {
            "done_count": gen1_done,
            "total_count": gen1_total,
            "alpha_proof_unlocked": alpha_proof_unlocked,
        },
        "next_gate": "H4_H5" if state == "READY_FOR_H4_H5" else state,
        "threshold_sweep": False,
        "future_information_used": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    receipt["receipt_sha256"] = stable(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print("A1_GEN2_REPAIR_SHORT_SMA50_FAMILY=" + json.dumps({
        "state": state,
        "parent": development,
        "parent_fresh": fresh_parent,
        "strict_child": strict.get("metrics"),
        "strict_fresh": strict_prospective.get("fresh_metrics"),
        "gen1_gate": receipt["gen1_gate"],
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return receipt


if __name__ == "__main__":
    run(Path("out/a1_gen2_repair_short_sma50_family_v1.json"))
