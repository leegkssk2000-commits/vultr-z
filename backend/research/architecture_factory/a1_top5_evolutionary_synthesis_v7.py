#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_a5_economic_improvement_v3 as v3
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

ROOT = Path(__file__).resolve().parents[3]
LEAGUE = ROOT / "backend/research/rebuild/a1_strategy25_improvement_league_latest.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_top5_evolutionary_synthesis_latest.json"
SCHEMA = "zel.a1_top5_evolutionary_synthesis.v7"

# Mechanism genes are qualitative priors only. Numeric thresholds from donor strategies are never copied.
GENES: dict[str, dict[str, Any]] = {
    "alpha_combo": {"gene": "multi_factor_confirmation", "type": "confirmation", "required_sources": ["ohlcv", "volume"]},
    "anchor_vwap_trend": {"gene": "anchored_vwap_trend_ownership", "type": "trend", "required_sources": ["ohlcv", "volume"]},
    "bb_revert": {"gene": "band_mean_reversion", "type": "mean_reversion", "required_sources": ["ohlcv"]},
    "break_and_continue": {"gene": "breakout_persistence", "type": "breakout", "required_sources": ["ohlcv", "volume"]},
    "ema_ribbon_scalp": {"gene": "multi_speed_trend_alignment", "type": "trend", "required_sources": ["ohlcv"]},
    "fvg_revert": {"gene": "imbalance_reversion", "type": "mean_reversion", "required_sources": ["ohlcv"]},
    "grid_rebalance": {"gene": "range_inventory_regime", "type": "range", "required_sources": ["ohlcv"]},
    "keltner_trend": {"gene": "band_expansion_transition", "type": "trend", "required_sources": ["ohlcv"]},
    "liquidity_sweep": {"gene": "liquidity_sweep_rejection", "type": "liquidity", "required_sources": ["ohlcv", "volume"]},
    "mfi_rsi_div": {"gene": "flow_momentum_divergence", "type": "momentum", "required_sources": ["ohlcv", "volume"]},
    "obv_trend": {"gene": "volume_trend_confirmation", "type": "volume", "required_sources": ["ohlcv", "volume"]},
    "pivot_reversal": {"gene": "pivot_rejection", "type": "structure", "required_sources": ["ohlcv"]},
    "range_fade": {"gene": "range_mean_reversion", "type": "range", "required_sources": ["ohlcv"]},
    "rbreaker_like": {"gene": "breakout_reversal_regime_switch", "type": "breakout", "required_sources": ["ohlcv"]},
    "rsi_swing_fail": {"gene": "momentum_failure_reversal", "type": "momentum", "required_sources": ["ohlcv"]},
    "scalp_snap": {"gene": "short_horizon_impulse_reversal", "type": "momentum", "required_sources": ["ohlcv", "volume"]},
    "session_bias": {"gene": "session_ownership", "type": "session", "required_sources": ["ohlcv"]},
    "squeeze_break": {"gene": "compression_expansion", "type": "volatility", "required_sources": ["ohlcv"]},
    "sr_levels": {"gene": "support_resistance_context", "type": "structure", "required_sources": ["ohlcv"]},
    "supertrend_pullback": {"gene": "trend_persistence_after_pullback", "type": "trend", "required_sources": ["ohlcv"]},
    "trend_ma_macd": {"gene": "multi_speed_trend_confirmation", "type": "trend", "required_sources": ["ohlcv"]},
    "trend_rider": {"gene": "multi_horizon_trend_ownership", "type": "trend", "required_sources": ["ohlcv"]},
    "turtle_trend": {"gene": "channel_breakout_persistence", "type": "breakout", "required_sources": ["ohlcv"]},
    "vol_spike_fade": {"gene": "volatility_exhaustion", "type": "volatility", "required_sources": ["ohlcv", "volume"]},
    "vwap_revert": {"gene": "vwap_deviation_reversion", "type": "mean_reversion", "required_sources": ["ohlcv", "volume"]},
}

HOST_TYPES: dict[str, set[str]] = {
    "trend_rider": {"trend", "breakout", "volatility", "volume", "liquidity", "session", "confirmation"},
    "keltner_trend": {"trend", "breakout", "volatility", "volume", "liquidity", "session", "confirmation"},
    "break_and_continue": {"breakout", "volatility", "volume", "liquidity", "session", "structure", "confirmation"},
    "supertrend_pullback": {"trend", "mean_reversion", "range", "momentum", "structure", "volume", "session", "confirmation"},
    "trend_ma_macd": {"trend", "breakout", "volatility", "volume", "session", "confirmation", "structure"},
}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("display_metrics", "metrics", "formal_metrics"):
        value = row.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _positive_edge(metrics: Mapping[str, Any]) -> bool:
    try:
        trades = int(metrics.get("completed_trades") or 0)
        pnl = float(metrics.get("net_pnl_bps") or 0.0)
        exp = float(metrics.get("net_expectancy_bps") or 0.0)
        pf_raw = metrics.get("profit_factor")
        pf = float(pf_raw) if pf_raw is not None else 1.0
        return trades >= 8 and pnl > 0.0 and exp > 0.0 and pf >= 1.0
    except (TypeError, ValueError):
        return False


def _rank(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("performance_rank") or row.get("rank") or 999)
    except (TypeError, ValueError):
        return 999


def _host_order(league: Mapping[str, Any]) -> list[str]:
    active = [str(x) for x in league.get("active_top5") or [] if str(x)]
    if len(active) != 5 or len(set(active)) != 5:
        raise RuntimeError(f"PERFORMANCE_TOP5_REQUIRED:{active}")
    supported = set((v3.v1.contract().get("strategies") or {}).keys())
    return [sid for sid in active if sid in supported]


def _donor_pool(league: Mapping[str, Any], hosts: list[str]) -> list[dict[str, Any]]:
    host_set = set(hosts)
    out: list[dict[str, Any]] = []
    for raw in league.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("strategy_id") or "")
        if not sid or sid in host_set or sid not in GENES:
            continue
        m = _metrics(raw)
        positive = _positive_edge(m)
        out.append({
            "strategy_id": sid,
            "performance_rank": _rank(raw),
            "role": raw.get("role"),
            "metrics": m,
            "gene": GENES[sid]["gene"],
            "gene_type": GENES[sid]["type"],
            "required_sources": list(GENES[sid]["required_sources"]),
            "donor_tier": "VALIDATED_EDGE_DONOR" if positive else "MECHANISM_HYPOTHESIS_ONLY",
            "whole_strategy_merge_allowed": False,
            "numeric_threshold_import_allowed": False,
        })
    out.sort(key=lambda x: (0 if x["donor_tier"] == "VALIDATED_EDGE_DONOR" else 1, int(x["performance_rank"]), str(x["strategy_id"])))
    return out


def _axis_name(donor: Mapping[str, Any]) -> str:
    sid = str(donor["strategy_id"]).upper().replace("-", "_")
    gene = str(donor["gene"]).upper().replace("-", "_")
    return f"DONOR__{sid}__{gene}__ONLY"


def _prior_attempted() -> dict[str, set[str]]:
    prior = _read(LATEST)
    raw = prior.get("economic_attempted_axes") or {}
    out: dict[str, set[str]] = {}
    if isinstance(raw, Mapping):
        for sid, rows in raw.items():
            if isinstance(rows, list):
                out[str(sid)] = {str(x) for x in rows if str(x)}
    return out


def _host_plans(hosts: list[str], donors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    attempted = _prior_attempted()
    plans: dict[str, dict[str, Any]] = {}
    for host in hosts:
        compatible_types = HOST_TYPES.get(host, set())
        eligible = [d for d in donors if str(d.get("gene_type")) in compatible_types]
        next_donor = next((d for d in eligible if _axis_name(d) not in attempted.get(host, set())), None)
        plans[host] = {
            "host_strategy_id": host,
            "next_donor": dict(next_donor) if next_donor else None,
            "next_axis": _axis_name(next_donor) if next_donor else None,
            "compatible_donor_count": len(eligible),
            "attempted_donor_gene_count": sum(1 for d in eligible if _axis_name(d) in attempted.get(host, set())),
            "policy": "ONE_GENE_PER_HOST_PER_CYCLE_EXACT_PARENT_ABLATION",
        }
    return plans


def _donor_axes(plans: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for host, plan in plans.items():
        donor = plan.get("next_donor")
        axis = str(plan.get("next_axis") or "")
        if not isinstance(donor, Mapping) or not axis:
            continue
        out[str(host)] = [{
            "axis": axis,
            "priority": 500.0 if donor.get("donor_tier") == "VALIDATED_EDGE_DONOR" else 300.0,
            "required_sources": list(donor.get("required_sources") or ["ohlcv"]),
            "source_lane": "READY_COMMON",
            "origin": "DEMOTED_STRATEGY_DONOR_GENE",
            "donor_strategy_id": donor.get("strategy_id"),
            "donor_gene": donor.get("gene"),
            "donor_gene_type": donor.get("gene_type"),
            "donor_tier": donor.get("donor_tier"),
            "mechanism": (
                f"Change only one causal host component using the qualitative donor mechanism '{donor.get('gene')}' "
                f"from {donor.get('strategy_id')}; preserve all other host geometry. Do not copy donor numeric thresholds."
            ),
        }]
    return out


def _wrap_prompt(original, plans: Mapping[str, Mapping[str, Any]]):
    def wrapped(kind, fps, axes, evidence, readiness, prior, selected=None):
        text = original(kind, fps, axes, evidence, readiness, prior, selected)
        marker = "\nCONTEXT="
        if marker not in text:
            return text
        head, raw = text.split(marker, 1)
        context = json.loads(raw)
        context["evolutionary_synthesis_v7"] = {
            "host_plans": plans,
            "loop": "TOP5_HOST -> DONOR_GENE -> ONE_AXIS_MUTATION -> DEVELOPMENT_CHALLENGER -> FRESH_OOS -> RERANK",
            "acceptance": {
                "net_pnl_must_improve": True,
                "expectancy_must_improve": True,
                "profit_factor_must_not_worsen": True,
                "drawdown_must_not_worsen": True,
                "trade_retention_gate_required": True,
                "same_baseline_ab_required_before_claiming_upgrade": True,
                "fresh_oos_required_before_promotion": True,
            },
        }
        constraints = context.setdefault("constraints", {})
        constraints["evolutionary_synthesis_mode"] = True
        constraints["one_donor_gene_per_host_per_attempt"] = True
        constraints["whole_strategy_merge_forbidden"] = True
        constraints["donor_numeric_threshold_copy_forbidden"] = True
        constraints["donor_outcome_claim_copy_forbidden"] = True
        constraints["exact_parent_ablation_required"] = True
        constraints["changed_axis_must_equal_supplied_donor_axis"] = True
        constraints["failed_donor_host_pair_retry_forbidden"] = True
        constraints["dd_nonworsening_required_for_synthesis_acceptance"] = True
        return head + marker + json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return wrapped


def _candidate_attribution(result: Mapping[str, Any], plans: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("initial_candidates", "second_step_candidates"):
        for raw in result.get(key) or []:
            if not isinstance(raw, Mapping):
                continue
            sid = str(raw.get("strategy_id") or "")
            plan = plans.get(sid) or {}
            if str(raw.get("changed_axis") or "") != str(plan.get("next_axis") or ""):
                continue
            donor = plan.get("next_donor") if isinstance(plan.get("next_donor"), Mapping) else {}
            out.append({
                "candidate_id": raw.get("candidate_id"),
                "host_strategy_id": sid,
                "changed_axis": raw.get("changed_axis"),
                "donor_strategy_id": donor.get("strategy_id"),
                "donor_gene": donor.get("gene"),
                "donor_tier": donor.get("donor_tier"),
                "development_only": True,
                "promotion_ready": False,
            })
    return out


def run(output: Path) -> dict[str, Any]:
    league = _read(LEAGUE)
    hosts = _host_order(league)
    if not hosts:
        raise RuntimeError("NO_SUPPORTED_PERFORMANCE_TOP5_HOST")
    donors = _donor_pool(league, hosts)
    plans = _host_plans(hosts, donors)
    axes = _donor_axes(plans)

    old_order = v3.v1.a5_order
    old_allowed = v3.v1.allowed_axes
    old_prompt = v3._prompt
    old_latest = v3.LATEST

    def focused_order(_contract: Mapping[str, Any]) -> list[str]:
        return list(hosts)

    def donor_only_axes(_contract: Mapping[str, Any], _readiness: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
        return {sid: [dict(x) for x in rows] for sid, rows in axes.items()}

    try:
        v3.v1.a5_order = focused_order
        v3.v1.allowed_axes = donor_only_axes
        v3._prompt = _wrap_prompt(old_prompt, plans)
        v3.LATEST = LATEST
        result = dict(v3.run(output))
    finally:
        v3.v1.a5_order = old_order
        v3.v1.allowed_axes = old_allowed
        v3._prompt = old_prompt
        v3.LATEST = old_latest

    attributions = _candidate_attribution(result, plans)
    result["schema_version"] = SCHEMA
    result["performance_top5_hosts"] = list(hosts)
    result["performance_top5_source"] = str(LEAGUE.relative_to(ROOT))
    result["donor_pool"] = donors
    result["donor_pool_count"] = len(donors)
    result["validated_edge_donor_count"] = sum(1 for x in donors if x.get("donor_tier") == "VALIDATED_EDGE_DONOR")
    result["mechanism_hypothesis_donor_count"] = sum(1 for x in donors if x.get("donor_tier") == "MECHANISM_HYPOTHESIS_ONLY")
    result["host_plans"] = plans
    result["candidate_donor_attribution"] = attributions
    result["evolutionary_candidate_count"] = len(attributions)
    result["direct_improvement_scope"] = "CURRENT_PERFORMANCE_TOP5_HOSTS_ONLY"
    result["demoted_strategy_direct_repair_enabled"] = False
    result["demoted_top5_becomes_donor"] = True
    result["full_strategy_merge_allowed"] = False
    result["one_gene_per_host_per_attempt"] = True
    result["donor_numeric_threshold_copy_allowed"] = False
    result["failed_gene_pair_archive_via_stable_axis_history"] = True
    result["synthesis_acceptance_gate"] = {
        "net_pnl_improves": True,
        "expectancy_improves": True,
        "profit_factor_nonworse": True,
        "drawdown_nonworse": True,
        "trade_retention_gate": True,
        "same_baseline_ab": True,
        "fresh_oos_before_promotion": True,
    }
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    league = {
        "active_top5": ["trend_rider", "break_and_continue", "supertrend_pullback", "keltner_trend", "trend_ma_macd"],
        "rows": [
            {"strategy_id": "trend_rider", "rank": 1, "display_metrics": {"completed_trades": 16, "net_pnl_bps": 20, "net_expectancy_bps": 1, "profit_factor": 2}},
            {"strategy_id": "squeeze_break", "rank": 6, "display_metrics": {"completed_trades": 12, "net_pnl_bps": 9, "net_expectancy_bps": 1, "profit_factor": 2}},
            {"strategy_id": "liquidity_sweep", "rank": 20, "display_metrics": {"completed_trades": 90, "net_pnl_bps": -3, "net_expectancy_bps": -1, "profit_factor": 0.4}},
        ],
    }
    hosts = _host_order(league)
    donors = _donor_pool(league, hosts)
    assert hosts == ["trend_rider", "break_and_continue", "supertrend_pullback", "keltner_trend", "trend_ma_macd"]
    assert [x["strategy_id"] for x in donors] == ["squeeze_break", "liquidity_sweep"]
    assert donors[0]["donor_tier"] == "VALIDATED_EDGE_DONOR"
    assert donors[1]["donor_tier"] == "MECHANISM_HYPOTHESIS_ONLY"
    axis = _axis_name(donors[0])
    assert axis.startswith("DONOR__SQUEEZE_BREAK__") and axis.endswith("__ONLY")
    assert v3.AUTH["execution_authority"] == "NONE" and v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_EVOLUTIONARY_SYNTHESIS_V7_SELF_TEST")
    print("PASS_TOP5_HOST_DONOR_GENE_ONE_AXIS_ARCHIVE_POLICY")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_top5_evolutionary_synthesis_v7.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r.get("state"),
        "hosts": r.get("performance_top5_hosts"),
        "donors": r.get("donor_pool_count"),
        "validated_donors": r.get("validated_edge_donor_count"),
        "candidates": r.get("evolutionary_candidate_count"),
        "development_pass": r.get("development_economic_pass_count"),
        "paid": r.get("paid_request_count"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
