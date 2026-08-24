#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_strategy25_improvement_league_v1.json"
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
BASELINE = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
PREVIOUS = ROOT / "backend/research/rebuild/a1_strategy25_improvement_league_latest.json"
REBUILD = ROOT / "backend/research/rebuild"
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}

TIME_KEYS = (
    "checkpoint_at_utc", "evaluated_at_utc", "last_evaluated_utc", "generated_at_utc",
    "observed_at_utc", "created_at_utc", "asof_utc", "terminal_at_utc", "boundary_utc",
)
RETROSPECTIVE_WORDS = ("retrospective", "discovery", "counterfactual", "attribution", "historical")


def read(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def finite(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def metrics_from(row: Mapping[str, Any]) -> dict[str, Any] | None:
    candidates: list[Mapping[str, Any]] = []
    if isinstance(row.get("profit_lane"), Mapping) and isinstance(row["profit_lane"].get("metrics"), Mapping):
        candidates.append(row["profit_lane"]["metrics"])
    if isinstance(row.get("metrics"), Mapping):
        candidates.append(row["metrics"])
    candidates.append(row)
    for m in candidates:
        completed = m.get("completed_trades", row.get("completed_trades"))
        if completed is None:
            continue
        n = int(completed or 0)
        pnl = finite(m.get("net_pnl_bps", m.get("net_pnl")))
        exp = finite(m.get("net_expectancy_bps", m.get("expectancy_bps", m.get("expectancy"))))
        pf = finite(m.get("profit_factor", m.get("net_profit_factor")))
        wr = finite(m.get("win_rate", m.get("wr")))
        dd = finite(m.get("drawdown_bps", m.get("max_drawdown_bps", row.get("drawdown_bps"))))
        if all(x is None for x in (pnl, exp, pf, wr, dd)) and n == 0:
            continue
        if wr is not None and wr > 1.0:
            wr /= 100.0
        return {
            "completed_trades": n,
            "win_rate": wr,
            "net_pnl_bps": pnl,
            "net_expectancy_bps": exp,
            "profit_factor": pf,
            "drawdown_bps": dd,
            "pnl_dd": (pnl / dd) if pnl is not None and dd not in (None, 0.0) else None,
        }
    return None


def stage_rank(row: Mapping[str, Any]) -> int:
    if row.get("pilot_survivor") is True:
        return 6
    a3 = row.get("a3_pilot") if isinstance(row.get("a3_pilot"), Mapping) else {}
    if a3.get("pass") is True or str(a3.get("state", "")).startswith("PASS_A3"):
        return 6
    if str(a3.get("state", "")).startswith("WAIT_A3"):
        return 5
    a2p = row.get("a2_pilot") if isinstance(row.get("a2_pilot"), Mapping) else {}
    if a2p.get("pass") is True or str(row.get("a2_pilot_state", "")).startswith("PASS_A2"):
        return 4
    if str(row.get("strict_a2_state", "")).startswith("PASS_A2"):
        return 4
    cert = row.get("certification_pilot") if isinstance(row.get("certification_pilot"), Mapping) else {}
    if cert.get("pass") is True:
        return 3
    profit = row.get("profit_lane") if isinstance(row.get("profit_lane"), Mapping) else {}
    if profit.get("pass") is True:
        return 2
    status = str(row.get("status") or row.get("state") or "")
    if status in ("A1_SURVIVOR", "A1_FINALIST_PARKED"):
        return 1
    m = metrics_from(row)
    if m and positive_economics(m):
        return 1
    return 0


def positive_economics(m: Mapping[str, Any]) -> bool:
    pnl = finite(m.get("net_pnl_bps")); exp = finite(m.get("net_expectancy_bps")); pf = finite(m.get("profit_factor"))
    if pnl is None or exp is None:
        return False
    if pnl <= 0 or exp <= 0:
        return False
    return pf is None or pf >= 1.0


def path_priority(path: Path) -> int:
    n = path.name.lower()
    if n == "a1_strategy25_active_deep_replay_latest.json":
        return 600
    if n == "a1_top3_profitability_survivor_latest.json":
        return 550
    if "fresh" in n or "forward" in n or "prospective" in n:
        return 500
    if "latest" in n:
        return 400
    return 100


def inherited_time(row: Mapping[str, Any], inherited: datetime | None) -> datetime | None:
    for key in TIME_KEYS:
        dt = iso(row.get(key))
        if dt:
            return dt
    return inherited


def walk_rows(value: Any, canonical: set[str], source_path: Path, inherited: datetime | None = None) -> Iterable[dict[str, Any]]:
    if isinstance(value, Mapping):
        current_time = inherited_time(value, inherited)
        sid = value.get("strategy_id")
        if sid in canonical:
            m = metrics_from(value)
            if m is not None:
                yield {
                    "strategy_id": str(sid),
                    "identity": value.get("identity") or value.get("label") or str(sid),
                    "metrics": m,
                    "stage_rank": stage_rank(value),
                    "source_path": str(source_path.relative_to(ROOT)),
                    "source_priority": path_priority(source_path),
                    "observed_at_utc": iso_z(current_time) if current_time else None,
                    "status": value.get("status") or value.get("state"),
                    "operational_evidence": not any(x in source_path.name.lower() for x in RETROSPECTIVE_WORDS),
                    "integrity_defects": list(value.get("integrity_defects") or []),
                    "leakage_lookahead": int(value.get("leakage_lookahead") or 0),
                }
        for child in value.values():
            yield from walk_rows(child, canonical, source_path, current_time)
    elif isinstance(value, list):
        for child in value:
            yield from walk_rows(child, canonical, source_path, inherited)


def baseline_evidence(ledger: Mapping[str, Any], canonical: list[str]) -> list[dict[str, Any]]:
    rows = []
    for sid in canonical:
        row = (ledger.get("strategies") or {}).get(sid) or {}
        m = metrics_from(row) or {
            "completed_trades": int(row.get("completed_trades") or 0), "win_rate": None,
            "net_pnl_bps": finite(row.get("net_pnl_bps")), "net_expectancy_bps": finite(row.get("net_expectancy_bps")),
            "profit_factor": finite(row.get("profit_factor")), "drawdown_bps": finite(row.get("drawdown_bps")), "pnl_dd": None,
        }
        if m["net_pnl_bps"] is not None and m["drawdown_bps"] not in (None, 0):
            m["pnl_dd"] = m["net_pnl_bps"] / m["drawdown_bps"]
        rows.append({
            "strategy_id": sid, "identity": sid, "metrics": m, "stage_rank": stage_rank(row),
            "source_path": str(BASELINE.relative_to(ROOT)), "source_priority": 100,
            "observed_at_utc": row.get("last_evaluated_utc") or row.get("terminal_at_utc"),
            "status": row.get("status"), "operational_evidence": True,
            "integrity_defects": list(row.get("integrity_defects") or []), "leakage_lookahead": int(row.get("leakage_lookahead") or 0),
        })
    return rows


def evidence_key(e: Mapping[str, Any]) -> tuple[Any, ...]:
    m = e["metrics"]
    return (
        int(e.get("source_priority") or 0), int(e.get("stage_rank") or 0), int(positive_economics(m)),
        int(m.get("completed_trades") or 0), finite(m.get("net_expectancy_bps")) or -1e30,
        finite(m.get("net_pnl_bps")) or -1e30,
    )


def select_evidence(all_evidence: list[dict[str, Any]], sid: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = [x for x in all_evidence if x["strategy_id"] == sid]
    operational = [x for x in rows if x["operational_evidence"] and not x["integrity_defects"] and int(x["leakage_lookahead"]) == 0]
    nonzero = [x for x in operational if int(x["metrics"].get("completed_trades") or 0) > 0 or positive_economics(x["metrics"])]
    pool = nonzero or operational or rows
    if not pool:
        raise RuntimeError(f"NO_EVIDENCE:{sid}")
    return max(pool, key=evidence_key), rows


def hours_between(a: datetime, b: datetime) -> float:
    return max(0.0, (b - a).total_seconds() / 3600.0)


def delta_metrics(cur: Mapping[str, Any], prev: Mapping[str, Any] | None) -> dict[str, Any]:
    keys = ("completed_trades", "win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps", "pnl_dd")
    out: dict[str, Any] = {}
    for k in keys:
        a = finite(cur.get(k)); b = finite((prev or {}).get(k))
        out[k] = (a - b) if a is not None and b is not None else None
    return out


def pareto_state(cur: Mapping[str, Any], prev: Mapping[str, Any] | None) -> str:
    if not prev:
        return "BASELINE_ESTABLISHED"
    d = delta_metrics(cur, prev)
    critical_nonworse = True
    for k in ("net_pnl_bps", "net_expectancy_bps", "profit_factor", "pnl_dd"):
        if d[k] is not None and d[k] < 0:
            critical_nonworse = False
    if d["drawdown_bps"] is not None and d["drawdown_bps"] > 0:
        critical_nonworse = False
    gains = [
        d["completed_trades"] is not None and d["completed_trades"] > 0,
        d["win_rate"] is not None and d["win_rate"] > 0,
        d["net_pnl_bps"] is not None and d["net_pnl_bps"] > 0,
        d["net_expectancy_bps"] is not None and d["net_expectancy_bps"] > 0,
        d["profit_factor"] is not None and d["profit_factor"] > 0,
        d["drawdown_bps"] is not None and d["drawdown_bps"] < 0,
        d["pnl_dd"] is not None and d["pnl_dd"] > 0,
    ]
    if critical_nonworse and any(gains):
        return "IMPROVED"
    if not critical_nonworse:
        return "REGRESSED_OR_TRADEOFF"
    return "UNCHANGED"


def rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    m = row["metrics"]
    dd = finite(m.get("drawdown_bps"))
    return (
        0 if row.get("failover_due") else 1,
        int(row.get("stage_rank") or 0), int(positive_economics(m)), int(m.get("completed_trades") or 0),
        finite(m.get("net_expectancy_bps")) or -1e30, finite(m.get("net_pnl_bps")) or -1e30,
        finite(m.get("profit_factor")) or -1e30, -(dd if dd is not None else 1e30),
    )


def remainder_disposition(row: Mapping[str, Any], baseline_status: str) -> str:
    if positive_economics(row["metrics"]):
        return "SYNTHESIS_MATERIAL_CANDIDATE"
    if baseline_status in ("A1_ECONOMIC_FAIL", "A1_COST_FUTILITY", "A1_CAUSAL_CONTROL_FAIL"):
        return "REJECT"
    if baseline_status in ("A1_SPARSE_EVENT_FUTILITY", "A1_DATA_BLOCKED"):
        return "DORMANT"
    return "HOLD"


def build(extra_json: list[Path] | None = None) -> dict[str, Any]:
    contract = read(CONTRACT); inventory = read(INVENTORY); baseline = read(BASELINE); previous = read(PREVIOUS, {}) or {}
    canonical = list((inventory.get("strategies") or {}).keys())
    if len(canonical) != 25 or len(set(canonical)) != 25:
        raise RuntimeError(f"CANONICAL_25_REQUIRED:{len(canonical)}")
    canonical_set = set(canonical)
    evidence = baseline_evidence(baseline, canonical)
    scanned: list[str] = []
    for path in sorted(REBUILD.rglob("*latest*.json")):
        if path == PREVIOUS or "strategy25_improvement_league" in path.name:
            continue
        payload = read(path, None)
        if payload is None:
            continue
        scanned.append(str(path.relative_to(ROOT)))
        evidence.extend(walk_rows(payload, canonical_set, path))
    for path in extra_json or []:
        if not path.exists():
            continue
        scanned.append(str(path))
        evidence.extend(walk_rows(read(path), canonical_set, path if path.is_absolute() and ROOT in path.parents else ROOT / path))

    now = now_utc(); previous_rows = {x["strategy_id"]: x for x in previous.get("rows", []) if isinstance(x, Mapping) and x.get("strategy_id")}
    previous_at = iso(previous.get("generated_at_utc"))
    rows: list[dict[str, Any]] = []
    for sid in canonical:
        chosen, all_rows = select_evidence(evidence, sid)
        prev = previous_rows.get(sid)
        curm = dict(chosen["metrics"]); prevm = (prev or {}).get("metrics") if isinstance((prev or {}).get("metrics"), Mapping) else None
        deltas = delta_metrics(curm, prevm)
        prev_growth = iso((prev or {}).get("last_completed_trade_growth_at_utc"))
        grew = deltas.get("completed_trades") is not None and deltas["completed_trades"] > 0
        last_growth = now if grew or not prev_growth else prev_growth
        no_growth_h = hours_between(last_growth, now)
        eta_h: float | None = None
        if previous_at and prevm and deltas.get("completed_trades") is not None and deltas["completed_trades"] > 0:
            elapsed = max(1e-9, hours_between(previous_at, now))
            rate = float(deltas["completed_trades"]) / elapsed
            target = int(contract["no_idle"]["target_completed_trades_for_profit_cert_progress"])
            remaining = max(0, target - int(curm.get("completed_trades") or 0))
            eta_h = remaining / rate if rate > 0 else None
        prev_role = str((prev or {}).get("role") or "")
        failover = bool(prev and prev_role == "ACTIVE_TOP5" and int(chosen["stage_rank"]) < 6 and (
            no_growth_h >= float(contract["no_idle"]["no_completed_trade_growth_hours"]) or
            (eta_h is not None and eta_h > float(contract["no_idle"]["estimated_hours_to_12_trades_failover"]))
        ))
        baseline_status = str(((baseline.get("strategies") or {}).get(sid) or {}).get("status") or "")
        rows.append({
            "strategy_id": sid, "evidence_identity": chosen.get("identity"), "stage_rank": int(chosen["stage_rank"]),
            "positive_economics": positive_economics(curm), "metrics": curm,
            "source": {"path": chosen["source_path"], "priority": chosen["source_priority"], "observed_at_utc": chosen.get("observed_at_utc")},
            "evidence_count": len(all_rows), "baseline_status": baseline_status,
            "pareto_state": pareto_state(curm, prevm), "deltas": deltas,
            "last_completed_trade_growth_at_utc": iso_z(last_growth), "no_completed_trade_growth_hours": no_growth_h,
            "estimated_hours_to_12_trades": eta_h, "failover_due": failover,
            "role": None, "remainder_disposition": None,
        })
    ranked = sorted(rows, key=lambda x: (rank_key(x), x["strategy_id"]), reverse=True)
    active_n = int(contract["roles"]["active_top5"]); challenger_n = int(contract["roles"]["challenger_next5"])
    for i, row in enumerate(ranked):
        row["rank"] = i + 1
        if i < active_n:
            row["role"] = "ACTIVE_TOP5"
        elif i < active_n + challenger_n:
            row["role"] = "CHALLENGER_NEXT5"
        else:
            row["role"] = "MATERIAL_HOLD"
            row["remainder_disposition"] = remainder_disposition(row, row["baseline_status"])
    result = {
        "schema_version": "zel.a1.strategy25_improvement_league.v1",
        "state": "ACTIVE_25WIDE_IMPROVEMENT_LEAGUE",
        "generated_at_utc": iso_z(now), "research_only": True, "receipt_first": True,
        "canonical_strategy_count": len(canonical), "evidence_record_count": len(evidence), "scanned_latest_json_count": len(set(scanned)),
        "role_counts": {
            "ACTIVE_TOP5": sum(x["role"] == "ACTIVE_TOP5" for x in ranked),
            "CHALLENGER_NEXT5": sum(x["role"] == "CHALLENGER_NEXT5" for x in ranked),
            "MATERIAL_HOLD": sum(x["role"] == "MATERIAL_HOLD" for x in ranked),
        },
        "active_top5": [x["strategy_id"] for x in ranked if x["role"] == "ACTIVE_TOP5"],
        "challenger_next5": [x["strategy_id"] for x in ranked if x["role"] == "CHALLENGER_NEXT5"],
        "failover_due": [x["strategy_id"] for x in ranked if x["failover_due"]],
        "improved_count": sum(x["pareto_state"] == "IMPROVED" for x in ranked),
        "regressed_or_tradeoff_count": sum(x["pareto_state"] == "REGRESSED_OR_TRADEOFF" for x in ranked),
        "deep_replay_manifest": {
            "strategy_ids": [x["strategy_id"] for x in ranked if x["role"] == "ACTIVE_TOP5"],
            "source_mode": "SHARED_CACHE_ACTIVE5_DEEP_REPLAY",
            "symbols": list(contract["shared_deep_replay"]["symbols"]),
            "canonical_ledger_mutation_allowed": False,
        },
        "rows": ranked,
        "strict_reference_preserved": True, "strict_global_gate_mutation": False,
        "new_strategy_generation_enabled": False, "numeric_threshold_sweep": False,
        **AUTH,
    }
    if result["role_counts"] != {"ACTIVE_TOP5": 5, "CHALLENGER_NEXT5": 5, "MATERIAL_HOLD": 15}:
        raise RuntimeError(f"ROLE_PARTITION_INVALID:{result['role_counts']}")
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    c = read(CONTRACT); inv = read(INVENTORY); base = read(BASELINE)
    assert c["roles"] == {"active_top5": 5, "challenger_next5": 5, "remainder": 15}
    assert len((inv.get("strategies") or {})) == 25
    assert int(base.get("done_count") or 0) == 25
    assert c["authority"]["execution_authority"] == "NONE"
    assert c["authority"]["order_authority"] == "BLOCKED" and c["authority"]["live_trade_authority"] == "BLOCKED"
    assert c["improvement"]["strict_h4_h5_a2_a3_threshold_mutation"] is False
    print("PASS_A1_STRATEGY25_IMPROVEMENT_LEAGUE_V1_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--self-test", action="store_true")
    p.add_argument("--out", type=Path, default=Path("out/a1_strategy25_improvement_league_latest.json"))
    p.add_argument("--extra-json", action="append", default=[])
    args = p.parse_args()
    if args.self_test:
        return self_test()
    result = build([Path(x) for x in args.extra_json])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("STRATEGY25_LEAGUE=" + json.dumps({
        "active": result["active_top5"], "challenger": result["challenger_next5"],
        "roles": result["role_counts"], "improved": result["improved_count"], "failover": result["failover_due"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
