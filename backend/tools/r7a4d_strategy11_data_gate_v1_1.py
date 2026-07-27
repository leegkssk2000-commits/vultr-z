from __future__ import annotations

import argparse, csv, importlib.util, json, os, sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "backend/tools/r7a4d_strategy11_evidence_pipeline_v1.py"

spec = importlib.util.spec_from_file_location("s11_evidence_v1", V1)
if spec is None or spec.loader is None:
    raise RuntimeError("EVIDENCE_IMPORT_FAILED")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--evidence-root", required=True)
    p.add_argument("--fresh-manifest", required=True)
    p.add_argument("--sealed-manifest", required=True)
    p.add_argument("--ssot", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    er, fp, zp, sp, out = map(lambda x: Path(x).resolve(), [a.evidence_root, a.fresh_manifest, a.sealed_manifest, a.ssot, a.out])
    fresh, sealed, ssot = mod.strict_json(fp), mod.strict_json(zp), mod.strict_json(sp)
    summaries = {x.parent.name: mod.strict_json(x) for x in sorted(er.glob("*/summary.json"))}
    blockers: list[str] = []
    if len(summaries) != 25: blockers.append(f"EVIDENCE_STRATEGY_COUNT:{len(summaries)}")
    if fresh.get("state") != "PASS" or fresh.get("blockers"): blockers.append("FRESH_DATA_NOT_PASS")
    if sealed.get("state") != "PASS" or sealed.get("blockers"): blockers.append("SEALED_DATA_NOT_PASS")
    if int(fresh.get("window_count") or 0) < int(ssot["data_adequacy"]["min_distinct_fresh_windows"]): blockers.append("FRESH_WINDOW_COUNT_LOW")
    if int(sealed.get("window_count") or 0) < int(ssot["data_adequacy"]["min_sealed_final_holdback_windows"]): blockers.append("SEALED_WINDOW_COUNT_LOW")
    if sealed.get("repair_read_allowed") is not False or sealed.get("one_shot_only") is not True: blockers.append("SEALED_CONTRACT_INVALID")

    minimum = int(ssot["data_adequacy"]["min_fresh_trades_per_promoted_candidate"])
    total = 0
    eligible: list[str] = []
    mfe_ok = True
    stress_ok = True
    for sid, s in summaries.items():
        b = s.get("baseline") if isinstance(s.get("baseline"), Mapping) else {}
        n = int(b.get("trade_count") or 0)
        total += n
        if n >= minimum: eligible.append(sid)
        if float(b.get("mfe_mae_completeness_pct") or 0) != 100.0: mfe_ok = False
        if s.get("stress_grid_complete") is not True: stress_ok = False
    if not eligible: blockers.append("NO_CANDIDATE_WITH_MIN_FRESH_TRADES")
    if not mfe_ok: blockers.append("MFE_MAE_COMPLETENESS_NOT_100")
    if not stress_ok: blockers.append("COST_FUNDING_LATENCY_STRESS_INCOMPLETE")

    eligible_summaries = {sid: summaries[sid] for sid in eligible}
    stat_fail: dict[str, list[str]] = {}
    pvalues: dict[str, float] = {}
    for sid, s in eligible_summaries.items():
        boot = s.get("bootstrap") if isinstance(s.get("bootstrap"), Mapping) else {}
        dsr = s.get("deflated_sharpe") if isinstance(s.get("deflated_sharpe"), Mapping) else {}
        fail: list[str] = []
        if boot.get("state") != "PASS": fail.append(str(boot.get("blocker") or "BOOTSTRAP_NOT_PASS"))
        if dsr.get("state") != "PASS": fail.append(str(dsr.get("blocker") or "DSR_NOT_PASS"))
        if mod.finite(boot.get("p_mean_le_zero")): pvalues[sid] = float(boot["p_mean_le_zero"])
        else: fail.append("BOOTSTRAP_PVALUE_MISSING")
        if fail: stat_fail[sid] = fail
    stats_ok = bool(eligible) and not stat_fail
    if not stats_ok: blockers.append("STATISTICAL_EVIDENCE_INCOMPLETE_ELIGIBLE_ONLY")

    fdr = mod.bh_fdr(pvalues, float(ssot["statistical_validation"]["fdr_q"])) if pvalues else {"q": 0.1, "passed": [], "adjusted_pvalues": {}}
    pbo = mod.pbo_estimate(eligible_summaries)
    if pbo.get("state") != "PASS": blockers.append(str(pbo.get("blocker") or "PBO_NOT_PASS"))
    elif not mod.finite(pbo.get("pbo")): blockers.append("PBO_VALUE_MISSING")
    elif float(pbo["pbo"]) > float(ssot["statistical_validation"]["probability_of_backtest_overfitting_max"]): blockers.append(f"PBO_ABOVE_LIMIT:{pbo['pbo']}")

    rows = []
    passed = set(fdr.get("passed", []))
    for sid, s in summaries.items():
        b = s.get("baseline") if isinstance(s.get("baseline"), Mapping) else {}
        boot, dsr = s.get("bootstrap") or {}, s.get("deflated_sharpe") or {}
        rows.append({"strategy_id": sid, "trade_count": b.get("trade_count"), "win_rate_pct": b.get("win_rate_pct"), "net_return_pct_sum": b.get("net_return_pct_sum"), "net_profit_factor_adjusted": b.get("net_profit_factor_adjusted"), "payoff_ratio_adjusted": b.get("payoff_ratio_adjusted"), "max_drawdown_pct": b.get("max_drawdown_pct"), "positive_fresh_windows_pct": b.get("positive_fresh_windows_pct"), "bootstrap_p": boot.get("p_mean_le_zero"), "bh_adjusted_p": fdr.get("adjusted_pvalues", {}).get(sid), "fdr_pass": sid in passed, "deflated_sharpe_probability": dsr.get("deflated_sharpe_probability"), "eligible_for_improvement": sid in eligible, "statistics_pass": sid in eligible and sid not in stat_fail})
    rows.sort(key=lambda r: (bool(r["eligible_for_improvement"]), bool(r["statistics_pass"]), mod.metric(r["positive_fresh_windows_pct"]), -mod.metric(r["max_drawdown_pct"]), mod.metric(r["net_profit_factor_adjusted"]), mod.metric(r["payoff_ratio_adjusted"]), mod.metric(r["net_return_pct_sum"])), reverse=True)

    state = "PASS" if not blockers else "HOLD"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "global_ranking.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]) if rows else ["strategy_id"]); w.writeheader(); w.writerows(rows)
    queue = [r for r in rows if r["eligible_for_improvement"] and r["statistics_pass"]][:int(ssot["repair_budget"]["max_active_candidates"])]
    mod.atomic_json(out / "bh_fdr.json", fdr)
    mod.atomic_json(out / "pbo.json", pbo)
    mod.atomic_json(out / "candidate_queue.json", {"schema_version": "1.1", "state": state, "rows": queue, "gemini_allowed": state == "PASS", "auto_improvement_allowed": state == "PASS", "source_run_id": 30252022416})
    result = {"schema_version": "1.1", "pipeline_version": "R7A4D_STRATEGY11_DATA_GATE_V1_1", "authority": "READ_ONLY_AGGREGATE_ONLY_NO_EXECUTION", "state": state, "data_adequacy_pass": state == "PASS", "strategy_count": len(summaries), "fresh_window_count": fresh.get("window_count"), "sealed_window_count": sealed.get("window_count"), "total_fresh_trades": total, "eligible_candidate_count": len(eligible), "eligible_candidates": eligible, "mfe_mae_completeness_100": mfe_ok, "stress_grid_complete": stress_ok, "statistics_complete": stats_ok, "statistics_scope": "ELIGIBLE_CANDIDATES_ONLY", "statistics_failures": stat_fail, "bh_fdr": fdr, "pbo": pbo, "recomputed_batches": 0, "reused_evidence_batches": 5, "source_run_id": 30252022416, "gemini_allowed": state == "PASS", "auto_improvement_allowed": state == "PASS", "shadow_allowed": False, "execution_allowed": False, "blockers": blockers, "next": "GEMINI_MULTI_SOURCE_RESEARCH" if state == "PASS" else "WAIT_NEW_DATA_OR_EVIDENCE_REPAIR"}
    mod.atomic_json(out / "summary.json", result)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as h: h.write(f"data_adequacy={state}\n")
    print(json.dumps({"STATE": state, "ELIGIBLE": eligible, "BLOCKERS": blockers}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
