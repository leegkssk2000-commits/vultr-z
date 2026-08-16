from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
LEDGER_PATH = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY_PATH = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
HARDENING_PATH = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
COST_PATH = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def save(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_output(name: str, value: Any) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    with open(output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={text}\n")


def policy_meta(strategy_id: str, inventory: dict[str, Any]) -> dict[str, Any]:
    item = inventory["strategies"][strategy_id]
    policy_path = ROOT / str(item["policy_owner"])
    evidence_path = ROOT / str(item["evidence_packet"])
    return {
        "policy_owner": str(item["policy_owner"]),
        "policy_sha": git_blob_sha(policy_path),
        "evidence_sha": git_blob_sha(evidence_path),
    }


def receipt_cost(receipt: dict[str, Any]) -> float | None:
    snaps = receipt.get("execution_snapshots") or {}
    values = []
    if isinstance(snaps, dict):
        for snap in snaps.values():
            if isinstance(snap, dict):
                x = finite(snap.get("pretrade_verified_cost_bps"))
                if x is not None:
                    values.append(x)
    return max(values) if values else None


def controls_state(receipt: dict[str, Any]) -> str:
    return str(receipt.get("negative_control_gate") or "PENDING")


def terminal_disposition(receipt: dict[str, Any], hardening: dict[str, Any]) -> tuple[str | None, str | None]:
    defects = receipt.get("integrity_defects") or []
    leakage = int(receipt.get("leakage_lookahead") or 0)
    if leakage != 0:
        return None, "IMPLEMENTATION_INTEGRITY_REQUIRES_REPAIR"
    if defects:
        return None, "IMPLEMENTATION_INTEGRITY_REQUIRES_REPAIR"
    trades = int(receipt.get("completed_trades") or 0)
    intents = int(receipt.get("intent_count") or 0)
    metrics = receipt.get("metrics") or {}
    gross_exp = finite(metrics.get("gross_expectancy_bps"))
    net_exp = finite(metrics.get("net_expectancy_bps"))
    net_pnl = finite(metrics.get("net_pnl_bps"))
    pf = finite(metrics.get("net_profit_factor"))
    payoff = finite(metrics.get("net_payoff"))
    cost = receipt_cost(receipt)
    control = controls_state(receipt)

    # Existing user-approved resource-allocation gate carried into rebuilt sweep:
    # once a real sample exists, gross edge below 25% of verified realistic cost
    # is resource-futile. It is not mislabeled as terminal economic rejection.
    if trades >= 15 and gross_exp is not None and cost is not None and cost > 0 and gross_exp / cost < 0.25:
        return "A1_COST_FUTILITY", f"GROSS_EDGE_COST_RATIO_LT_0_25:{gross_exp / cost:.6f}"

    # Causal-control disposition only when the frozen control evaluator itself
    # returns a terminal fail state; PENDING never fails a strategy.
    if control.startswith(("FAIL", "REJECT")):
        return "A1_CAUSAL_CONTROL_FAIL", f"NEGATIVE_CONTROL_GATE:{control}"

    gate = hardening.get("survivor_gate") or {}
    economics_ok = (
        net_pnl is not None and net_pnl > float(gate.get("minimum_net_R", 0.0))
        and net_exp is not None and net_exp > float(gate.get("minimum_expectancy_R", 0.0))
        and pf is not None and pf >= float(gate.get("minimum_profit_factor", 1.0))
        and payoff is not None and payoff >= float(gate.get("minimum_payoff_ratio", 1.0))
    )
    # Never infer the SSOT sample/retention/OOS/falsification gate. Survivor is
    # sealed only when a downstream receipt explicitly proves it.
    explicit_survivor_gate = receipt.get("survivor_gate")
    if economics_ok and isinstance(explicit_survivor_gate, dict) and explicit_survivor_gate.get("state") == "PASS":
        return "A1_SURVIVOR", "PROSPECTIVE_COST_ADJUSTED_SSOT_SURVIVOR_GATE_PASS"

    explicit_terminal = receipt.get("baseline_disposition")
    if explicit_terminal in {
        "A1_ECONOMIC_FAIL", "A1_SPARSE_EVENT_FUTILITY", "A1_DATA_BLOCKED", "HOLD_USER_AUTHORITY"
    }:
        return str(explicit_terminal), str(receipt.get("baseline_terminal_reason") or explicit_terminal)

    if intents == 0 or trades == 0:
        return None, None
    return None, None


def format_metric(value: Any, suffix: str = "") -> str:
    x = finite(value)
    return "-" if x is None else f"{x:.6f}{suffix}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", required=True)
    ap.add_argument("--out-event", default="a1_exact25_controller_event.json")
    args = ap.parse_args()

    ledger, inventory, hardening = load(LEDGER_PATH), load(INVENTORY_PATH), load(HARDENING_PATH)
    receipt = load(Path(args.receipt))
    sid = str(ledger["active_strategy_id"])
    if receipt.get("strategy_id") != sid:
        raise RuntimeError(f"ACTIVE_RECEIPT_MISMATCH:{receipt.get('strategy_id')}!={sid}")
    entry = ledger["strategies"][sid]
    if entry.get("status") != "ACTIVE":
        raise RuntimeError("ACTIVE_LEDGER_STATUS_REQUIRED")

    metrics = receipt.get("metrics") or {}
    entry.update({
        "run_id": int(os.getenv("GITHUB_RUN_ID", "0")) or None,
        "job_id": None,
        "artifact_id": None,
        "artifact_digest": None,
        "receipt_sha": receipt.get("receipt_sha256"),
        "event_count": int(receipt.get("event_count") or receipt.get("intent_count") or 0),
        "intent_count": int(receipt.get("intent_count") or 0),
        "completed_trades": int(receipt.get("completed_trades") or 0),
        "gross_expectancy_bps": finite(metrics.get("gross_expectancy_bps")),
        "net_expectancy_bps": finite(metrics.get("net_expectancy_bps")),
        "net_pnl_bps": finite(metrics.get("net_pnl_bps")),
        "profit_factor": finite(metrics.get("net_profit_factor")),
        "payoff": finite(metrics.get("net_payoff")),
        "win_rate": finite(metrics.get("win_rate")),
        "drawdown_bps": finite(metrics.get("max_drawdown_bps")),
        "verified_pretrade_cost_bps": receipt_cost(receipt),
        "negative_control_state": controls_state(receipt),
        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
        "integrity_defects": receipt.get("integrity_defects") or [],
        "last_evaluated_utc": utc_now_iso(),
    })
    if receipt.get("policy_sha"):
        entry["policy_sha"] = receipt.get("policy_sha")
    if receipt.get("config_sha"):
        entry["config_sha"] = receipt.get("config_sha")
    if receipt.get("evidence_sha"):
        entry["evidence_sha"] = receipt.get("evidence_sha")

    disposition, reason = terminal_disposition(receipt, hardening)
    report_required = False
    next_sid: str | None = None
    report_line = evidence_line = None
    if disposition:
        entry["status"] = disposition
        entry["terminal_reason"] = reason
        entry["terminal_at_utc"] = utc_now_iso()
        ledger["done_count"] = sum(1 for x in ledger["strategies"].values() if isinstance(x, dict) and str(x.get("status", "")).startswith("A1_") and x.get("status") != "ACTIVE")
        if disposition == "A1_SURVIVOR" and sid not in ledger["survivors"]:
            ledger["survivors"].append(sid)
        ledger["survivor_count"] = len(ledger["survivors"])
        report_required = entry.get("reported_terminal_receipt_sha") != receipt.get("receipt_sha256")
        entry["reported_terminal_receipt_sha"] = receipt.get("receipt_sha256")

        for candidate in ledger["strategy_order"]:
            if ledger["strategies"][candidate].get("status") == "UNTESTED":
                next_sid = candidate
                break
        if next_sid:
            meta = policy_meta(next_sid, inventory)
            nxt = ledger["strategies"][next_sid]
            nxt.update({
                "status": "ACTIVE", "policy_config_source_sha": meta["policy_sha"],
                "policy_sha": meta["policy_sha"], "config_sha": None, "source_sha": None,
                "evidence_sha": meta["evidence_sha"], "prospective_boundary_utc": utc_now_iso(),
                "evaluator": "backend/research/rebuild/a1_exact25_generic_evaluator_v1.py",
                "workflow": ".github/workflows/a1-exact25-controller-v1.yml",
                "terminal_reason": None, "generation": int(nxt.get("generation") or 1),
            })
            ledger["active_strategy_id"] = next_sid
        else:
            ledger["active_strategy_id"] = None
            ledger["state"] = "A1_EXACT25_BASELINE_SWEEP_COMPLETE"

        wr = finite(metrics.get("win_rate"))
        progress = int(ledger["done_count"])
        short = "SURVIVOR" if disposition == "A1_SURVIVOR" else "BLOCKED" if disposition in {"A1_DATA_BLOCKED", "HOLD_USER_AUTHORITY"} else "FUTILITY" if "FUTILITY" in disposition else "FAIL"
        report_line = (
            f"A1:{sid}|{short}|trades={int(receipt.get('completed_trades') or 0)}|WR={'-' if wr is None else f'{100*wr:.2f}%'}|"
            f"Net={format_metric(metrics.get('net_pnl_bps'),'bps')}|Exp={format_metric(metrics.get('net_expectancy_bps'),'bps/trade')}|"
            f"PF={format_metric(metrics.get('net_profit_factor'))}|Payoff={format_metric(metrics.get('net_payoff'))}|"
            f"DD={format_metric(metrics.get('max_drawdown_bps'),'bps')}|cost={format_metric(receipt_cost(receipt),'bps/trade')}|action={'route_change' if next_sid else 'hold'}"
        )
        evidence_line = (
            f"근거:run={os.getenv('GITHUB_RUN_ID','-')}|artifact=-|receipt={receipt.get('receipt_sha256','-')}|"
            f"boundary={entry.get('prospective_boundary_utc','-')}|controls={controls_state(receipt)}|"
            f"integrity={len(entry.get('integrity_defects') or [])}|progress={progress}/25|survivors={ledger['survivor_count']}"
        )

    ledger["updated_at_utc"] = utc_now_iso()
    save(LEDGER_PATH, ledger)
    event = {
        "schema_version": "zel.a1_exact25_controller_event.v1", "strategy_id": sid,
        "disposition": disposition, "terminal_reason": reason, "report_required": report_required,
        "report_line": report_line, "evidence_line": evidence_line, "next_strategy_id": next_sid,
        "done_count": ledger["done_count"], "survivor_count": ledger["survivor_count"],
        "state": ledger["state"], "authority": ledger["authority"],
    }
    save(Path(args.out_event), event)
    write_output("report_required", "true" if report_required else "false")
    write_output("next_strategy_id", next_sid or "")
    write_output("sweep_complete", "true" if ledger["state"] == "A1_EXACT25_BASELINE_SWEEP_COMPLETE" else "false")
    write_output("report_line", report_line or "")
    write_output("evidence_line", evidence_line or "")
    print(json.dumps(event, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
