#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import strategy_material_grade_v1 as material
from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7 as evo
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as swarm
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v3 as econ
from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import call_openai_generator

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
SSOT = ROOT / "backend/research/prep/strategy_synthesis_material_ssot_v1.json"
EVIDENCE = ROOT / "backend/research/architecture_factory/a1_free_evidence_sweep_v1.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_c_grade_pair_nursery_latest.json"
SCHEMA = "zel.a1.c_grade_pair_nursery.v1"
MAX_PAIRS_PER_RUN = 3
MAX_PAID_REQUESTS_PER_RUN = 1


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def current_main_strategy_ids() -> set[str]:
    raw = read(TOP5)
    out: set[str] = set()
    for row in raw.get("top5") or []:
        if isinstance(row, Mapping) and row.get("strategy_id"):
            out.add(str(row["strategy_id"]))
    return out


def material_state() -> dict[str, Any]:
    return material.evaluate(read(LEDGER), read(INVENTORY), read(SSOT))


def c_rows(mat: Mapping[str, Any]) -> list[dict[str, Any]]:
    blocked = current_main_strategy_ids()
    out: list[dict[str, Any]] = []
    for raw in mat.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("strategy_id") or "")
        if not sid or sid in blocked or str(raw.get("material_grade") or "") != "C" or sid not in evo.GENES:
            continue
        q = raw.get("quality") if isinstance(raw.get("quality"), Mapping) else {}
        gene = evo.GENES[sid]
        out.append({
            "strategy_id": sid,
            "family": str(raw.get("family") or "unknown"),
            "material_grade": "C",
            "material_disposition": raw.get("material_disposition"),
            "upgrade_axis": raw.get("upgrade_axis"),
            "structural_diversity_prior": float(raw.get("structural_diversity_prior") or 0.0),
            "completed_trades": int(q.get("completed_trades") or 0),
            "positive_gross": bool(q.get("positive_gross")),
            "positive_net": bool(q.get("positive_net")),
            "gene": gene["gene"],
            "gene_type": gene["type"],
            "required_sources": list(gene["required_sources"]),
        })
    out.sort(key=lambda x: (0 if x["positive_gross"] else 1, -x["structural_diversity_prior"], -x["completed_trades"], x["strategy_id"]))
    return out


def attempted_pair_ids() -> set[str]:
    prior = read(LATEST)
    out = set(str(x) for x in prior.get("attempted_pair_ids") or [] if str(x))
    for row in prior.get("pair_results") or []:
        if isinstance(row, Mapping) and row.get("pair_id"):
            out.add(str(row["pair_id"]))
    return out


def pair_id(host: Mapping[str, Any], donor: Mapping[str, Any]) -> str:
    return f"CPAIR__{host['strategy_id']}__X__{donor['strategy_id']}__{donor['gene']}"


def build_pairs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attempted = attempted_pair_ids()
    pairs: list[dict[str, Any]] = []
    for a, b in combinations(rows, 2):
        if a["family"] == b["family"]:
            continue
        # Test both causal directions: A host + B gene, and B host + A gene.
        for host, donor in ((a, b), (b, a)):
            pid = pair_id(host, donor)
            if pid in attempted:
                continue
            required = sorted(set(host["required_sources"]) | set(donor["required_sources"]))
            pairs.append({
                "pair_id": pid,
                "host_strategy_id": host["strategy_id"],
                "host_family": host["family"],
                "donor_strategy_id": donor["strategy_id"],
                "donor_family": donor["family"],
                "donor_gene": donor["gene"],
                "donor_gene_type": donor["gene_type"],
                "required_sources_hint": required,
                "changed_axis": f"C_PAIR__{donor['strategy_id'].upper()}__{str(donor['gene']).upper()}__ONLY",
                "rule": "PRESERVE_C_HOST_IDENTITY;IMPORT_ONE_QUALITATIVE_C_DONOR_MECHANISM;NO_NUMERIC_THRESHOLD_COPY",
                "priority": (
                    (2.0 if host["positive_gross"] else 0.0)
                    + (2.0 if donor["positive_gross"] else 0.0)
                    + host["structural_diversity_prior"] + donor["structural_diversity_prior"]
                    + min(host["completed_trades"], 25) / 100.0
                    + min(donor["completed_trades"], 25) / 100.0
                ),
            })
    pairs.sort(key=lambda x: (-float(x["priority"]), str(x["pair_id"])))
    return pairs[:MAX_PAIRS_PER_RUN]


def evidence_compact() -> tuple[list[dict[str, Any]], set[str]]:
    raw = read(EVIDENCE)
    rows: list[dict[str, Any]] = []
    ids: set[str] = set()
    for r in raw.get("sources") or []:
        if not isinstance(r, Mapping) or not r.get("id"):
            continue
        sid = str(r["id"]); ids.add(sid)
        rows.append({"id": sid, "tier": r.get("tier"), "claim": r.get("claim"), "limitations": r.get("limitations")})
    return rows[:30], ids


def prompt(pairs: list[dict[str, Any]], evidence: list[dict[str, Any]], readiness: Mapping[str, Any]) -> str:
    expected = [p["pair_id"] for p in pairs]
    return (
        "You are an executable strategy material nursery. This is NOT Top5 repair and NOT parameter optimization. "
        "For EACH supplied CxC pair emit at most ONE REPAIR candidate and zero if a causal executable child is not defensible. "
        "candidate_id MUST exactly equal pair_id; strategy_id MUST equal host_strategy_id. Preserve the host identity and change exactly ONE causal axis: use only the donor_gene qualitative mechanism. "
        "Never copy donor numeric thresholds, never add a second donor mechanism, never delete historical losers, never select a best horizon from outcomes, never lower the 14bps cost. "
        "Every emitted candidate MUST include deterministic executable_spec with keys bar_interval, features, entry_rule, side_rule, exit_rule, max_hold_bars, entry_timing, cost_model, development_data_rule, parameter_provenance. "
        "Only use replay-ready sources. The child will be killed unless >=12 trades, Net expectancy>0, PF>1, payoff>=1 and positive net/calendar-day under 14bps. "
        "Return JSON object {candidates:[...]}. EXPECTED_IDS=" + json.dumps(expected, separators=(",", ":")) +
        "\nSOURCE_READINESS=" + json.dumps(readiness, sort_keys=True, separators=(",", ":")) +
        "\nPAIRS=" + json.dumps(pairs, sort_keys=True, separators=(",", ":")) +
        "\nEVIDENCE=" + json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    )


def run(output: Path, *, no_ai: bool = False) -> dict[str, Any]:
    mat = material_state()
    cs = c_rows(mat)
    pairs = build_pairs(cs)
    prior = read(LATEST)
    prior_attempted = set(str(x) for x in prior.get("attempted_pair_ids") or [] if str(x))
    readiness = swarm._history_readiness()
    allowed = swarm._allowed_sources(readiness)
    evidence, evidence_ids = evidence_compact()
    queue: list[dict[str, Any]] = []
    provider: dict[str, Any] = {"request_count": 0, "successful": False, "reason": "NO_ELIGIBLE_C_PAIR" if not pairs else "NO_AI_MODE"}

    if pairs and not no_ai:
        model, raw, lineage = call_openai_generator(prompt(pairs, evidence, readiness))
        validated = swarm.validate_candidates(raw, "openai", evidence_ids, {p["host_strategy_id"] for p in pairs})
        pair_by_id = {p["pair_id"]: p for p in pairs}
        strict_rows = []
        for row in validated:
            cid = str(row.get("candidate_id") or "")
            p = pair_by_id.get(cid)
            if not p or str(row.get("strategy_id") or "") != str(p["host_strategy_id"]):
                continue
            if str(row.get("changed_axis") or "") != str(p["changed_axis"]):
                continue
            strict_rows.append(row)
        queue = swarm._attach(raw, strict_rows, allowed)
        provider = {"request_count": 1, "successful": bool(queue), "model": model, **lineage, "generated": len(validated), "accepted_executable": len(queue)}

    dev = econ.evaluate_queue(queue) if queue else {"rows": [], "passes": [], "economic_pass_count": 0}
    dev_by_id = {str(x.get("candidate_id") or ""): x for x in dev.get("rows") or [] if isinstance(x, Mapping)}
    pair_results = []
    upgrades = []
    for p in pairs:
        row = dev_by_id.get(p["pair_id"]) or {}
        m = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
        dd = m.get("drawdown_bps")
        payoff = m.get("payoff")
        absolute_b = bool(
            row.get("economic_pass") is True
            and int(m.get("trades") or 0) >= 12
            and float(m.get("net_pnl_bps") or 0.0) > 0.0
            and float(m.get("net_expectancy_bps") or 0.0) > 0.0
            and float(m.get("profit_factor") or 0.0) > 1.0
            and payoff is not None and float(payoff) >= 1.0
            and dd is not None and math.isfinite(float(dd))
        )
        pr = {**p, "development_state": row.get("state") or "NOT_GENERATED_OR_NOT_EXECUTABLE", "metrics": m, "c_to_b_upgrade_pass": absolute_b}
        pair_results.append(pr)
        if absolute_b:
            upgrades.append({"pair_id": p["pair_id"], "host_strategy_id": p["host_strategy_id"], "donor_strategy_id": p["donor_strategy_id"], "from_grade": "C", "to_grade": "B", "reason": "ABSOLUTE_AFTER_COST_ECONOMIC_PASS", "metrics": m})

    attempted_now = {p["pair_id"] for p in pairs}
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_C_TO_B_MATERIAL_UPGRADE" if upgrades else ("HOLD_NO_NEW_C_PAIR" if not pairs else "HOLD_C_PAIR_NO_ABSOLUTE_ECONOMIC_PASS"),
        "material_strategy_count": int(mat.get("strategy_count") or 0),
        "eligible_c_material_count": len(cs),
        "eligible_c_material_ids": [x["strategy_id"] for x in cs],
        "pair_count_this_run": len(pairs),
        "pairs": pairs,
        "pair_results": pair_results,
        "c_to_b_upgrade_count": len(upgrades),
        "c_to_b_upgrades": upgrades,
        "attempted_pair_ids": sorted(prior_attempted | attempted_now),
        "failed_pair_retest_same_identity_allowed": False,
        "max_pairs_per_run": MAX_PAIRS_PER_RUN,
        "max_paid_requests_per_run": MAX_PAID_REQUESTS_PER_RUN,
        "provider": provider,
        "grade_upgrade_gate": {"minimum_trades": 12, "net_pnl_positive": True, "net_expectancy_positive": True, "profit_factor_gt_1": True, "payoff_ge_1": True, "finite_drawdown": True, "verified_cost_bps": 14.0},
        "pair_policy": {"distinct_family_required": True, "host_identity_preserved": True, "one_donor_gene_only": True, "donor_numeric_threshold_copy": False, "outcome_selected_thresholds": False, "dedup_cosine_threshold": 0.85},
        "next": "REENTER_B_AS_VALIDATED_DONOR" if upgrades else "NEXT_UNTRIED_C_PAIR_ON_MATERIAL_CHANGE_OR_MANUAL_RUN",
        "production_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert MAX_PAIRS_PER_RUN == 3 and MAX_PAID_REQUESTS_PER_RUN == 1
    fixture = [
        {"strategy_id":"a","family":"f1","positive_gross":True,"structural_diversity_prior":1.0,"completed_trades":12,"gene":"g1","gene_type":"trend","required_sources":["ohlcv"]},
        {"strategy_id":"b","family":"f2","positive_gross":False,"structural_diversity_prior":0.5,"completed_trades":8,"gene":"g2","gene_type":"volume","required_sources":["ohlcv","volume"]},
    ]
    old = globals()["attempted_pair_ids"]
    globals()["attempted_pair_ids"] = lambda: set()
    try:
        ps = build_pairs(fixture)
        assert len(ps) == 2
        assert all(x["host_family"] != x["donor_family"] for x in ps)
    finally:
        globals()["attempted_pair_ids"] = old
    print("PASS_A1_C_GRADE_PAIR_NURSERY_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_c_grade_pair_nursery_v1.json"))
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    r = run(a.out, no_ai=a.no_ai)
    print(json.dumps({"state":r["state"],"c":r["eligible_c_material_count"],"pairs":r["pair_count_this_run"],"upgrades":r["c_to_b_upgrade_count"],"next":r["next"],"receipt":r["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
