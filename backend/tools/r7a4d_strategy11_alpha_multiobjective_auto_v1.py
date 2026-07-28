from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
L085_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_adaptive_l085_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_MULTIOBJECTIVE_AUTO_V1"
WINDOWS = ("F1", "F2", "F3")


def load_l085() -> Any:
    name = "r7a4d_strategy11_alpha_l085_for_multiobjective"
    spec = importlib.util.spec_from_file_location(name, L085_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("L085_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


l085 = load_l085()
cost = l085.cost
p = l085.p
exact = l085.exact
base = l085.base
strict_json = l085.strict_json
metric = l085.metric
worst = l085.worst


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def loss_breaches(row: Mapping[str, Any], *, stress: bool = False) -> int:
    source = row.get("stress_2x_p95_plus_one", {}).get("loss_metrics", {}) if stress else row.get("loss_metrics", {})
    return int(source.get("loss_cap_breach_count") or 0)


def trade_metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [metric(row.get("net_reference_R")) for row in trades]
    wins = [value for value in returns if value > 0.0]
    losses = [value for value in returns if value < 0.0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(returns),
        "win_rate_pct": (len(wins) / len(returns) * 100.0) if returns else 0.0,
        "net_R": sum(returns),
        "profit_factor_R": (gross_win / gross_loss) if gross_loss > 0.0 else 0.0,
        "payoff_R": ((sum(wins) / len(wins)) / abs(sum(losses) / len(losses))) if wins and losses else 0.0,
        "avg_loss_R": (sum(losses) / len(losses)) if losses else 0.0,
        "worst_loss_R": min(losses) if losses else 0.0,
    }


def window_profile(out: Path, variant_id: str, incumbent_windows: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    payload = strict_json(out / variant_id / "replay-A.json")
    trades = [dict(row) for row in payload.get("trades", []) if isinstance(row, Mapping)]
    windows: dict[str, Any] = {}
    nonnegative = 0
    net_improved = 0
    wr_improved = 0
    for window_id in WINDOWS:
        row = trade_metrics([trade for trade in trades if str(trade.get("window_id")) == window_id])
        windows[window_id] = row
        if row["net_R"] >= 0.0:
            nonnegative += 1
        if incumbent_windows:
            incumbent = incumbent_windows.get(window_id, {})
            if row["net_R"] >= metric(incumbent.get("net_R")):
                net_improved += 1
            if row["win_rate_pct"] >= metric(incumbent.get("win_rate_pct")):
                wr_improved += 1
    return {
        "windows": windows,
        "nonnegative_window_count": nonnegative,
        "net_improved_window_count": net_improved,
        "win_rate_improved_window_count": wr_improved,
        "minimum_window_net_R": min((metric(row.get("net_R")) for row in windows.values()), default=0.0),
        "minimum_window_profit_factor_R": min((metric(row.get("profit_factor_R")) for row in windows.values()), default=0.0),
    }


def strict_gate(row: Mapping[str, Any], incumbent: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    strict = policy["strict_gate"]
    deltas = {
        "net_pct_points": metric(row.get("net_return_pct_sum")) - metric(incumbent.get("net_return_pct_sum")),
        "profit_factor": metric(row.get("net_profit_factor")) - metric(incumbent.get("net_profit_factor")),
        "payoff": metric(row.get("payoff_ratio")) - metric(incumbent.get("payoff_ratio")),
        "win_rate_pct_points": metric(row.get("win_rate_pct")) - metric(incumbent.get("win_rate_pct")),
        "drawdown_pct_points": metric(row.get("max_drawdown_pct")) - metric(incumbent.get("max_drawdown_pct")),
    }
    retention = metric(row.get("trade_count")) / max(1.0, metric(incumbent.get("trade_count"), 1.0)) * 100.0
    checks = {
        "parity_pass": row.get("parity", {}).get("state") == "PASS",
        "duplicate_free": int(row.get("parity", {}).get("duplicate_trade_count") or 0) == 0,
        "normal_cap_pass": worst(row) >= float(strict["normal_worst_net_loss_R_min"]) and loss_breaches(row) <= int(strict["loss_cap_breach_count_max"]),
        "stress_cap_pass": worst(row, stress=True) >= float(strict["stress_worst_net_loss_R_min"]) and loss_breaches(row, stress=True) <= int(strict["loss_cap_breach_count_max"]),
        "trade_retention_pass": retention >= float(strict["trade_retention_pct_min"]),
        "positive_windows_pass": metric(row.get("positive_fresh_windows_pct")) >= float(strict["positive_windows_pct_min"]),
        "dd_pass": deltas["drawdown_pct_points"] <= float(strict["dd_degradation_pct_points_max"]),
        "net_nonworse": deltas["net_pct_points"] >= 0.0,
        "profit_factor_nonworse": deltas["profit_factor"] >= 0.0,
        "payoff_nonworse": deltas["payoff"] >= 0.0,
    }
    return {"checks": checks, "pass": all(checks.values()), "trade_retention_pct": retention, "deltas_to_incumbent": deltas}


def scores(row: Mapping[str, Any], incumbent: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, float]:
    net_delta = metric(row.get("net_return_pct_sum")) - metric(incumbent.get("net_return_pct_sum"))
    pf_delta = metric(row.get("net_profit_factor")) - metric(incumbent.get("net_profit_factor"))
    payoff_delta = metric(row.get("payoff_ratio")) - metric(incumbent.get("payoff_ratio"))
    wr_delta = metric(row.get("win_rate_pct")) - metric(incumbent.get("win_rate_pct"))
    dd_delta = metric(row.get("max_drawdown_pct")) - metric(incumbent.get("max_drawdown_pct"))
    stress_net_delta = metric(row.get("stress_2x_p95_plus_one", {}).get("net_return_pct_sum")) - metric(incumbent.get("stress_2x_p95_plus_one", {}).get("net_return_pct_sum"))
    robustness = metric(profile.get("nonnegative_window_count")) * 2.0 + metric(profile.get("net_improved_window_count")) * 1.5 + metric(profile.get("win_rate_improved_window_count")) + metric(profile.get("minimum_window_net_R"))
    return {
        "profit_score": net_delta * 4.0 + pf_delta * 15.0 + payoff_delta * 4.0 + wr_delta * 0.10 - dd_delta * 6.0 + stress_net_delta * 2.0 + robustness,
        "balanced_score": net_delta * 3.0 + pf_delta * 12.0 + payoff_delta * 2.0 + wr_delta * 0.65 - dd_delta * 9.0 + stress_net_delta * 2.0 + robustness * 1.5,
        "robust_score": net_delta * 2.0 + pf_delta * 10.0 + payoff_delta * 2.0 + wr_delta * 0.35 - dd_delta * 12.0 + stress_net_delta * 3.0 + robustness * 2.0,
    }


def dominates(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    maximize = ("net_return_pct_sum", "net_profit_factor", "payoff_ratio", "win_rate_pct")
    minimize = ("max_drawdown_pct",)
    not_worse = all(metric(a.get(key)) >= metric(b.get(key)) for key in maximize) and all(metric(a.get(key), math.inf) <= metric(b.get(key), math.inf) for key in minimize)
    strictly_better = any(metric(a.get(key)) > metric(b.get(key)) for key in maximize) or any(metric(a.get(key), math.inf) < metric(b.get(key), math.inf) for key in minimize)
    return not_worse and strictly_better


def pareto_frontier(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    eligible = [row for row in rows if row.get("multiobjective", {}).get("strict", {}).get("pass")]
    return [str(row["variant_id"]) for row in eligible if not any(dominates(other, row) for other in eligible if other is not row)]


def parse_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    value = json.loads(text)
    if not isinstance(value, Mapping):
        raise RuntimeError("GEMINI_RESPONSE_NOT_OBJECT")
    return dict(value)


def call_gemini(key: str, model: str, registry: Mapping[str, Any], catalog: Sequence[Mapping[str, Any]], context: Mapping[str, Any]) -> dict[str, Any]:
    sources = [dict(row) for row in registry.get("sources", []) if isinstance(row, Mapping)]
    channels = {str(row.get("channel") or "") for row in sources if row.get("channel")}
    prompt = {
        "role": "Quantitative exit-research adjudicator",
        "task": "Select zero to two distinct single-cause candidates from the allowed catalog to improve alpha_combo win rate without damaging Net, PF, payoff, DD, normal/stress -0.75R caps, or window robustness. Return zero candidates when no allowed axis has sufficient causal support. Public videos are hypotheses only. Return strict JSON.",
        "current_context": context,
        "allowed_catalog": list(catalog),
        "constraints": {"allowed_candidate_ids_only": True, "max_selected": 2, "zero_selection_allowed": True, "prefer_distinct_axes": True, "no_performance_claim": True, "internal_replay_required": True, "same_window_overfit_warning_required": True},
        "output_schema": {"status": "PASS|HOLD", "selected_candidate_ids": ["candidate_id"], "reasons": [{"candidate_id": "...", "causal_reason": "...", "falsification": "..."}], "rejected_axes": ["..."]},
    }
    parts: list[dict[str, Any]] = [{"text": json.dumps(prompt, ensure_ascii=False, sort_keys=True)}]
    parts.extend({"file_data": {"file_uri": str(row["url"])}} for row in sources)
    payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192, "responseMimeType": "application/json", "thinkingConfig": {"thinkingLevel": "low"}}}
    request = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent", data=json.dumps(payload).encode("utf-8"), headers={"x-goog-api-key": key, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=900) as response:
        generated = json.load(response)
    texts = [str(part["text"]) for candidate in generated.get("candidates", []) for part in candidate.get("content", {}).get("parts", []) if isinstance(part.get("text"), str)]
    if not texts:
        raise RuntimeError("GEMINI_EMPTY_RESPONSE")
    parsed = parse_json_text("\n".join(texts))
    allowed = {str(row["candidate_id"]) for row in catalog}
    selected: list[str] = []
    for value in parsed.get("selected_candidate_ids", []):
        candidate_id = str(value)
        if candidate_id in allowed and candidate_id not in selected:
            selected.append(candidate_id)
        if len(selected) >= 2:
            break
    return {
        "GEMINI_USED": True,
        "free_only": True,
        "model": model,
        "public_urls": [str(row["url"]) for row in sources],
        "public_video_count": len(sources),
        "independent_channel_count": len(channels),
        "selected_candidate_ids": selected,
        "response": parsed,
        "input_sha256": hashlib.sha256(json.dumps(prompt, sort_keys=True).encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest(),
        "status": "PASS" if selected else "HOLD_NO_NEW_AXIS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--l085-summary", required=True)
    parser.add_argument("--l075-summary", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--video-registry", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    l085_path = Path(args.l085_summary).resolve()
    l075_path = Path(args.l075_summary).resolve()
    policy_path = Path(args.policy).resolve()
    registry_path = Path(args.video_registry).resolve()
    out = Path(args.out).resolve()

    baseline = strict_json(baseline_path)
    l085_summary = strict_json(l085_path)
    l075_summary = strict_json(l075_path)
    policy = strict_json(policy_path)
    video_registry = strict_json(registry_path)
    if l085_summary.get("state") != "PASS_L085_RESEARCH_CANDIDATE":
        raise RuntimeError("L085_AUTHORITY_INVALID")
    if l075_summary.get("state") != "PASS_L075_RESEARCH_CANDIDATE":
        raise RuntimeError("L075_AUTHORITY_INVALID")
    if l075_summary.get("winner") != "L075_STOP065_CONTROL":
        raise RuntimeError("L075_WINNER_INVALID")
    if l075_summary.get("sealed_holdback_read") is not False:
        raise RuntimeError("SEALED_REUSE_VIOLATION")

    candidate = baseline["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    surgery = p.surgery_from(baseline.get("surgery"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry["alpha_combo"]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, "alpha_combo", registry_row)
    frames, features, funding, manifest = p.load_fresh_data(fresh_root)
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = cost.v1.market_sha_map(manifest)

    stop065 = replace(base_exit, exit_id="RR150_STOP065_MULTIOBJ", stop_mult=0.65)
    gen1_specs = [("INCUMBENT_CONTROL", base_exit), ("STOP065_PROFIT_CONTROL", stop065)]
    for bars in policy["generation_1"]["values"]:
        gen1_specs.append((f"TIME{int(bars)}", replace(stop065, exit_id=f"RR150_STOP065_TIME{int(bars)}_MULTIOBJ", time_stop_bars=int(bars))))

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in gen1_specs:
        print(f"MULTIOBJ_GEN1_START variant={variant_id}", flush=True)
        row = cost.evaluate_with_reference_r(variant_id=variant_id, exit_spec=exit_spec, strategy=strategy, gate=gate, surgery=surgery, symbols=symbols, frames=frames, features=features, funding=funding, quantiles=quantiles, manifest=manifest, market_shas=market_shas, strategy_source_sha=strategy_source_sha, source_run_id=args.source_run_id, source_head_sha=args.source_head_sha, cap_r=-0.75, out=out)
        rows.append(row)
        print(f"MULTIOBJ_GEN1_END variant={variant_id}", flush=True)

    incumbent = rows[0]
    incumbent_profile = window_profile(out, "INCUMBENT_CONTROL")
    for row in rows:
        profile = window_profile(out, str(row["variant_id"]), incumbent_profile["windows"])
        row["multiobjective"] = {"generation": 1, "window_profile": profile, "strict": strict_gate(row, incumbent, policy), "scores": scores(row, incumbent, profile)}
        atomic_json(out / str(row["variant_id"]) / "summary.json", row)

    strict_gen1 = [row for row in rows[1:] if row["multiobjective"]["strict"]["pass"]]
    balanced_gen1 = [row for row in strict_gen1 if metric(row.get("win_rate_pct")) >= metric(incumbent.get("win_rate_pct")) and row["multiobjective"]["window_profile"]["nonnegative_window_count"] >= int(policy["balanced_gate"]["minimum_windows_nonnegative"])]
    base_for_gen2 = max(balanced_gen1 or strict_gen1, key=lambda row: row["multiobjective"]["scores"]["balanced_score"])
    base_exit_gen2 = exact._exit_from({"exit": base_for_gen2["exit"]})

    context = {
        "incumbent": {key: incumbent.get(key) for key in ("trade_count", "win_rate_pct", "net_return_pct_sum", "net_profit_factor", "payoff_ratio", "max_drawdown_pct")},
        "generation_1": [{"variant_id": row["variant_id"], "trade_count": row.get("trade_count"), "win_rate_pct": row.get("win_rate_pct"), "net_return_pct_sum": row.get("net_return_pct_sum"), "net_profit_factor": row.get("net_profit_factor"), "payoff_ratio": row.get("payoff_ratio"), "max_drawdown_pct": row.get("max_drawdown_pct"), "normal_worst_net_loss_R": worst(row), "stress_worst_net_loss_R": worst(row, stress=True), "window_profile": row["multiobjective"]["window_profile"]} for row in rows],
        "selected_generation_2_base": base_for_gen2["variant_id"],
    }

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    gemini_audit = call_gemini(gemini_key, str(policy["gemini"]["model"]), video_registry, policy["generation_2_catalog"], context)
    atomic_json(out / "gemini_audit.json", gemini_audit)
    catalog = {str(row["candidate_id"]): dict(row) for row in policy["generation_2_catalog"]}

    for candidate_id in gemini_audit["selected_candidate_ids"]:
        spec = catalog[candidate_id]
        exit_spec = base_exit_gen2
        if spec["axis"] == "breakeven_r":
            exit_spec = replace(exit_spec, exit_id=f"{base_exit_gen2.exit_id}_{candidate_id}", breakeven_r=float(spec["breakeven_r"]))
        elif spec["axis"] == "partial":
            exit_spec = replace(exit_spec, exit_id=f"{base_exit_gen2.exit_id}_{candidate_id}", partial_r=float(spec["partial_r"]), partial_fraction=float(spec["partial_fraction"]))
        else:
            raise RuntimeError(f"UNSUPPORTED_GEN2_AXIS:{spec['axis']}")
        variant_id = f"GEN2_{base_for_gen2['variant_id']}_{candidate_id}"
        print(f"MULTIOBJ_GEN2_START variant={variant_id}", flush=True)
        row = cost.evaluate_with_reference_r(variant_id=variant_id, exit_spec=exit_spec, strategy=strategy, gate=gate, surgery=surgery, symbols=symbols, frames=frames, features=features, funding=funding, quantiles=quantiles, manifest=manifest, market_shas=market_shas, strategy_source_sha=strategy_source_sha, source_run_id=args.source_run_id, source_head_sha=args.source_head_sha, cap_r=-0.75, out=out)
        profile = window_profile(out, variant_id, incumbent_profile["windows"])
        row["multiobjective"] = {"generation": 2, "gemini_candidate_id": candidate_id, "base_variant_id": base_for_gen2["variant_id"], "window_profile": profile, "strict": strict_gate(row, incumbent, policy), "scores": scores(row, incumbent, profile)}
        atomic_json(out / variant_id / "summary.json", row)
        rows.append(row)
        print(f"MULTIOBJ_GEN2_END variant={variant_id}", flush=True)

    strict_rows = [row for row in rows[1:] if row["multiobjective"]["strict"]["pass"]]
    balanced_rows = [row for row in strict_rows if metric(row.get("win_rate_pct")) >= metric(incumbent.get("win_rate_pct")) and row["multiobjective"]["window_profile"]["nonnegative_window_count"] >= int(policy["balanced_gate"]["minimum_windows_nonnegative"])]
    robust_rows = [row for row in strict_rows if row["multiobjective"]["window_profile"]["nonnegative_window_count"] == len(WINDOWS)]
    profit_max = max(strict_rows, key=lambda row: row["multiobjective"]["scores"]["profit_score"]) if strict_rows else None
    balanced = max(balanced_rows, key=lambda row: row["multiobjective"]["scores"]["balanced_score"]) if balanced_rows else None
    robust = max(robust_rows, key=lambda row: row["multiobjective"]["scores"]["robust_score"]) if robust_rows else None
    frontier = pareto_frontier(rows)
    selected = []
    for row in (profit_max, balanced, robust):
        if row is not None and row["variant_id"] not in selected:
            selected.append(row["variant_id"])
        if len(selected) >= int(policy["generation_policy"]["max_active_candidates"]):
            break

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_MULTIOBJECTIVE_RESEARCH_CANDIDATES" if selected else "HOLD_NO_STRICT_CANDIDATE",
        "strategy_id": "alpha_combo",
        "generation_count": 2,
        "same_dataset_generation_budget_exhausted": True,
        "same_window_infinite_search_forbidden": True,
        "generation_1_candidate_count": len(gen1_specs),
        "generation_2_candidate_count": len(gemini_audit["selected_candidate_ids"]),
        "gemini_audit": gemini_audit,
        "profit_max_control": profit_max["variant_id"] if profit_max else None,
        "balanced_wr_control": balanced["variant_id"] if balanced else None,
        "robust_control": robust["variant_id"] if robust else None,
        "pareto_frontier": frontier,
        "active_candidate_queue": selected,
        "requires_w1_fresh_non_overlap": True,
        "requires_new_sealed_holdback": True,
        "sealed_holdback_read": False,
        "promotion_authority": False,
        "next": "ALPHA_W1_MULTIOBJECTIVE_CONFIRMATION",
        "next_generation_triggers": ["W1_NEW_NON_OVERLAP", "NEW_CAUSAL_EVIDENCE"],
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "strategy_source_sha": strategy_source_sha,
        "fresh_manifest_sha256": sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": sha256(baseline_path),
        "l085_summary_sha256": sha256(l085_path),
        "l075_summary_sha256": sha256(l075_path),
        "policy_sha256": sha256(policy_path),
        "video_registry_sha256": sha256(registry_path),
        "variants": rows,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "order_authority": "BLOCKED",
        "blockers": [],
    }
    atomic_json(out / "summary.json", final)
    atomic_json(out / "next_generation_request.json", {"state": "WAIT_NEW_INDEPENDENT_EVIDENCE", "strategy_id": "alpha_combo", "active_candidate_queue": selected, "trigger": final["next_generation_triggers"], "action_on_trigger": "RERUN_MULTIOBJECTIVE_SELECTION_THEN_OPEN_AT_MOST_ONE_NEW_SINGLE_CAUSE_AXIS", "same_dataset_parameter_mining_forbidden": True, "execution_allowed": False})
    print(json.dumps({"state": final["state"], "profit_max": final["profit_max_control"], "balanced": final["balanced_wr_control"], "robust": final["robust_control"], "active": final["active_candidate_queue"], "next": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
