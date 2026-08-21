from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ge

ROOT = Path(__file__).resolve().parents[3]
LEDGER_PATH = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY_PATH = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
CLOCK_PATH = ROOT / "backend/research/rebuild/a1_exact25_parallel_evidence_clock_v1.json"

TERMINAL = {
    "A1_SURVIVOR",
    "A1_FINALIST_PARKED",
    "A1_ECONOMIC_FAIL",
    "A1_COST_FUTILITY",
    "A1_CAUSAL_CONTROL_FAIL",
    "A1_SPARSE_EVENT_FUTILITY",
    "A1_DATA_BLOCKED",
    "HOLD_USER_AUTHORITY",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def save(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def write_output(name: str, value: str) -> None:
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def _config_sha(cfg: Any) -> str:
    raw = getattr(cfg, "sha", None)
    if isinstance(raw, str):
        return raw
    body = asdict(cfg) if is_dataclass(cfg) else vars(cfg)
    return ge.stable_sha(body)


def _policy_contract(strategy_id: str, inventory: dict[str, Any]) -> dict[str, Any]:
    module, policy_path, policy_sha = ge.load_policy(strategy_id, inventory)
    cfg = ge.config_instance(module)
    timeframe_ms = int(getattr(cfg, "timeframe_ms"))
    ge.interval_for_ms(timeframe_ms)
    # Readiness means the generic evaluator can actually consume this policy.
    # bb_revert has a dedicated evaluator, but also validates through the same policy adapter contract.
    ge.policy_functions(module, strategy_id)
    evidence_path = ROOT / str(inventory["strategies"][strategy_id]["evidence_packet"])
    return {
        "policy_path": str(policy_path.relative_to(ROOT)),
        "policy_sha": policy_sha,
        "config_sha": _config_sha(cfg),
        "evidence_sha": ge.git_blob_sha(evidence_path),
        "timeframe_ms": timeframe_ms,
        "interval": ge.interval_for_ms(timeframe_ms),
        "source_contract": "BINGX_PUBLIC_KLINES_DEPTH_FUNDING_BACKFILL_BY_FROZEN_BOUNDARY",
    }


def _new_clock(ledger: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "zel.a1_exact25_parallel_evidence_clock.v1",
        "state": "ACTIVE",
        "scheduling_policy": {
            "old_or_pre_rebuild_pnl_used": False,
            "win_rate_used": False,
            "profit_factor_used": False,
            "payoff_used": False,
            "ordering": ["never_probed_first", "shorter_timeframe_first", "exact25_order_tiebreak"],
            "one_heavy_evaluator_at_a_time": True,
            "passive_parallel_evidence_allowed": True,
        },
        "authority": dict(ledger["authority"]),
        "strategies": {},
        "clocks_started_count": 0,
        "source_blocked_count": 0,
        "heavy_active_count": 0,
        "waiting_count": 0,
        "ready_count": 0,
        "updated_at_utc": None,
    }


def bootstrap(ledger: dict[str, Any], inventory: dict[str, Any], clock: dict[str, Any], *, now: datetime) -> None:
    order = list(ledger["strategy_order"])
    if len(order) != 25 or len(set(order)) != 25:
        raise RuntimeError("EXACT25_IDENTITY_CONTRACT_BROKEN")
    for sid in order:
        drow = ledger["strategies"][sid]
        crow = clock["strategies"].setdefault(sid, {})
        status = str(drow.get("status") or "UNTESTED")
        if status in TERMINAL:
            crow.update({"state": "TERMINAL", "terminal_disposition": status})
            continue
        try:
            contract = _policy_contract(sid, inventory)
        except Exception as exc:
            # Preserve any already-frozen clock for audit, but exclude this identity from heavy scheduling.
            boundary = crow.get("boundary_utc") or drow.get("prospective_boundary_utc")
            crow.update({
                "state": "CLOCK_STARTED",
                "source_ready": False,
                "source_blocker": f"POLICY_EVALUATOR_READINESS:{type(exc).__name__}:{exc}",
                "boundary_utc": boundary,
                "clock_frozen": bool(boundary),
            })
            if str(drow.get("status")) == "ACTIVE":
                drow["status"] = "UNTESTED"
                if ledger.get("active_strategy_id") == sid:
                    ledger["active_strategy_id"] = None
            continue
        # Once a clock exists it is immutable; never let later serial routing replace it.
        boundary = str(crow.get("boundary_utc") or drow.get("prospective_boundary_utc") or iso(now))
        drow["prospective_boundary_utc"] = boundary
        if not drow.get("policy_sha"):
            drow["policy_sha"] = contract["policy_sha"]
        if not drow.get("config_sha"):
            drow["config_sha"] = contract["config_sha"]
        if not drow.get("evidence_sha"):
            drow["evidence_sha"] = contract["evidence_sha"]
        crow.update(contract)
        crow.update({
            "boundary_utc": boundary,
            "clock_frozen": True,
            "source_ready": True,
            "source_blocker": None,
            "evidence_accumulation": "PASSIVE_PARALLEL_BOUNDARY_BACKFILL",
            "probe_count": int(crow.get("probe_count") or 0),
            "last_probe_utc": crow.get("last_probe_utc"),
        })
        if crow.get("state") not in {"WAITING_EVIDENCE", "HEAVY_ACTIVE", "TERMINAL"}:
            crow["state"] = "READY_FOR_HEAVY"


def _rank(order: list[str], clock: dict[str, Any], *, now: datetime, exclude: set[str]) -> list[str]:
    index = {sid: i for i, sid in enumerate(order)}
    candidates: list[str] = []
    for sid in order:
        if sid in exclude:
            continue
        row = clock["strategies"][sid]
        if row.get("state") == "TERMINAL" or row.get("source_ready") is not True:
            continue
        if row.get("state") == "WAITING_EVIDENCE":
            next_raw = row.get("next_probe_utc")
            if next_raw:
                next_dt = datetime.fromisoformat(str(next_raw).replace("Z", "+00:00"))
                if now < next_dt:
                    continue
        candidates.append(sid)
    return sorted(candidates, key=lambda sid: (
        int(clock["strategies"][sid].get("probe_count") or 0),
        int(clock["strategies"][sid].get("timeframe_ms") or 10**15),
        index[sid],
    ))


def _mark_waiting(sid: str, clock: dict[str, Any], *, now: datetime) -> None:
    row = clock["strategies"][sid]
    row["awaiting_heavy_evaluation"] = False
    tf_ms = int(row.get("timeframe_ms") or 3_600_000)
    row.update({
        "state": "WAITING_EVIDENCE",
        "last_probe_utc": iso(now),
        "probe_count": int(row.get("probe_count") or 0) + 1,
        "next_probe_utc": iso(now + timedelta(milliseconds=max(tf_ms, 60_000))),
    })


def _activate(sid: str, ledger: dict[str, Any], clock: dict[str, Any]) -> None:
    if clock["strategies"][sid].get("source_ready") is not True:
        raise RuntimeError(f"ACTIVATE_NON_READY:{sid}")
    previous = ledger.get("active_strategy_id")
    if previous and previous != sid:
        prow = ledger["strategies"][previous]
        if str(prow.get("status")) == "ACTIVE":
            prow["status"] = "UNTESTED"
    for other, row in clock["strategies"].items():
        if other != sid and row.get("state") == "HEAVY_ACTIVE":
            row["state"] = "READY_FOR_HEAVY" if row.get("source_ready") is True else "CLOCK_STARTED"
            row["awaiting_heavy_evaluation"] = False
    ledger["active_strategy_id"] = sid
    ledger["strategies"][sid]["status"] = "ACTIVE"
    clock["strategies"][sid]["state"] = "HEAVY_ACTIVE"
    clock["strategies"][sid]["awaiting_heavy_evaluation"] = True


def route_prepare(ledger: dict[str, Any], clock: dict[str, Any], *, now: datetime) -> tuple[str | None, bool]:
    current = ledger.get("active_strategy_id")
    routed = False
    if current:
        drow = ledger["strategies"][current]
        crow = clock["strategies"][current]
        if crow.get("source_ready") is not True:
            if str(drow.get("status")) == "ACTIVE":
                drow["status"] = "UNTESTED"
            ledger["active_strategy_id"] = None
            current = None
            routed = True
        elif str(drow.get("status")) in TERMINAL:
            crow["state"] = "TERMINAL"
            ledger["active_strategy_id"] = None
            current = None
        elif crow.get("state") == "HEAVY_ACTIVE" and crow.get("awaiting_heavy_evaluation") is True:
            # A strategy activated by the previous routing step must consume one
            # real evaluator receipt before stale ledger metrics can route it away.
            return current, False
        elif int(drow.get("intent_count") or 0) == 0 and int(drow.get("completed_trades") or 0) == 0 and drow.get("last_evaluated_utc"):
            _mark_waiting(current, clock, now=now)
            drow["status"] = "UNTESTED"
            ledger["active_strategy_id"] = None
            current = None
            routed = True
        else:
            crow["state"] = "HEAVY_ACTIVE"
            return current, False
    ranked = _rank(list(ledger["strategy_order"]), clock, now=now, exclude=set())
    if ranked:
        _activate(ranked[0], ledger, clock)
        return ranked[0], routed
    return None, routed


def route_after_receipt(ledger: dict[str, Any], clock: dict[str, Any], receipt: dict[str, Any], *, now: datetime) -> tuple[str | None, bool]:
    sid = str(receipt["strategy_id"])
    crow = clock["strategies"][sid]
    drow = ledger["strategies"][sid]
    status = str(drow.get("status") or "")
    crow["awaiting_heavy_evaluation"] = False
    crow["last_receipt_sha"] = receipt.get("receipt_sha256")
    crow["last_observed_bars_per_symbol"] = [int(x.get("bars_post_boundary") or 0) for x in ((receipt.get("source") or {}).get("symbols") or [])]
    if status in TERMINAL:
        crow["state"] = "TERMINAL"
        crow["terminal_disposition"] = status
        return ledger.get("active_strategy_id"), False
    waiting = receipt.get("state") == "WAIT_FRESH_PROSPECTIVE_DATA" or int(receipt.get("completed_trades") or 0) == 0
    if not waiting:
        crow.update({"state": "HEAVY_ACTIVE", "last_probe_utc": iso(now), "probe_count": int(crow.get("probe_count") or 0) + 1})
        return sid, False
    _mark_waiting(sid, clock, now=now)
    if ledger.get("active_strategy_id") == sid and str(drow.get("status")) == "ACTIVE":
        drow["status"] = "UNTESTED"
        ledger["active_strategy_id"] = None
    ranked = _rank(list(ledger["strategy_order"]), clock, now=now, exclude={sid})
    if ranked:
        _activate(ranked[0], ledger, clock)
        return ranked[0], True
    return None, False


def refresh_counts(clock: dict[str, Any]) -> None:
    rows = list(clock["strategies"].values())
    # A blocked identity may preserve an audit boundary; count it only once, as blocked.
    clock["clocks_started_count"] = sum(1 for x in rows if x.get("boundary_utc") and x.get("source_ready") is True)
    clock["source_blocked_count"] = sum(1 for x in rows if x.get("source_ready") is False)
    clock["heavy_active_count"] = sum(1 for x in rows if x.get("state") == "HEAVY_ACTIVE")
    clock["waiting_count"] = sum(1 for x in rows if x.get("state") == "WAITING_EVIDENCE")
    clock["ready_count"] = sum(1 for x in rows if x.get("state") == "READY_FOR_HEAVY")
    if clock["heavy_active_count"] > 1:
        raise RuntimeError("ONE_HEAVY_CONTRACT_BROKEN")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["prepare", "after-receipt"], default="prepare")
    ap.add_argument("--receipt")
    args = ap.parse_args()
    ledger = load(LEDGER_PATH)
    inventory = load(INVENTORY_PATH)
    clock = load(CLOCK_PATH) if CLOCK_PATH.exists() else _new_clock(ledger)
    now = utc_now()
    bootstrap(ledger, inventory, clock, now=now)
    if args.mode == "prepare":
        next_sid, route_changed = route_prepare(ledger, clock, now=now)
    else:
        if not args.receipt:
            raise RuntimeError("RECEIPT_REQUIRED")
        next_sid, route_changed = route_after_receipt(ledger, clock, load(Path(args.receipt)), now=now)
    refresh_counts(clock)
    if clock["clocks_started_count"] + clock["source_blocked_count"] != 25:
        raise RuntimeError("EXACT25_CLOCK_OR_BLOCKER_COVERAGE_REQUIRED")
    clock["updated_at_utc"] = iso(now)
    save(LEDGER_PATH, ledger)
    save(CLOCK_PATH, clock)
    write_output("next_strategy_id", next_sid or "")
    write_output("route_changed", "true" if route_changed else "false")
    write_output("clocks_started_count", str(clock["clocks_started_count"]))
    write_output("source_blocked_count", str(clock["source_blocked_count"]))
    write_output("waiting_count", str(clock["waiting_count"]))
    write_output("ready_count", str(clock["ready_count"]))
    write_output("heavy_active_count", str(clock["heavy_active_count"]))
    print(json.dumps({
        "state": "PASS_PARALLEL_EVIDENCE_SCHEDULER",
        "next_strategy_id": next_sid,
        "route_changed": route_changed,
        "clocks_started_count": clock["clocks_started_count"],
        "source_blocked_count": clock["source_blocked_count"],
        "waiting_count": clock["waiting_count"],
        "ready_count": clock["ready_count"],
        "heavy_active_count": clock["heavy_active_count"],
        "authority": clock["authority"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
