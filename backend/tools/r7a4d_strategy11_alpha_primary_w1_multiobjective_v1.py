from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.tools import r7a4d_strategy11_alpha_multiobjective_auto_v1 as multi
from backend.tools import r7a4d_strategy11_data_wait_pool_compute_v1 as w1


VERSION = "R7A4D_STRATEGY11_ALPHA_PRIMARY_W1_MULTIOBJECTIVE_V1"
CAPABILITY_MARKER = "PRIMARY_W1_MULTIOBJECTIVE_CONFIRMATION"
WINDOWS = ("F1", "F2", "F3", "W1")


def strict_json(path: Path) -> Any:
    return multi.strict_json(path)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def sorted_ledger(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(row) for row in trades),
        key=lambda row: (
            str(row.get("window_id")),
            str(row.get("symbol")),
            str(row.get("entry_ts")),
            str(row.get("exit_ts")),
            str(row.get("trade_id")),
        ),
    )


def ledger_sha(trades: Sequence[Mapping[str, Any]]) -> str:
    return stable_sha(sorted_ledger(trades))


def reference_loss_metrics(trades: Sequence[Mapping[str, Any]], stop_mult: float, cap_r: float) -> dict[str, Any]:
    wins: list[float] = []
    losses: list[float] = []
    normal_losses: list[float] = []
    unavoidable: list[float] = []
    for trade in trades:
        candidate_risk_pct = metric(trade.get("risk_pct"))
        reference_risk_pct = candidate_risk_pct / stop_mult if stop_mult > 0.0 else 0.0
        if reference_risk_pct <= 0.0:
            continue
        value = metric(trade.get("net_return_pct")) / reference_risk_pct
        if value > 0.0:
            wins.append(value)
        elif value < 0.0:
            losses.append(value)
            if bool(trade.get("path_ambiguous")):
                unavoidable.append(value)
            else:
                normal_losses.append(value)
    return {
        "r_definition": "NET_RETURN_PCT_DIVIDED_BY_INCUMBENT_RAW_RISK_PCT",
        "candidate_stop_mult": stop_mult,
        "avg_win_R": sum(wins) / len(wins) if wins else None,
        "avg_loss_R": sum(losses) / len(losses) if losses else None,
        "payoff_R": ((sum(wins) / len(wins)) / abs(sum(losses) / len(losses))) if wins and losses else 0.0,
        "worst_net_loss_R": min(losses) if losses else 0.0,
        "normal_worst_net_loss_R": min(normal_losses) if normal_losses else 0.0,
        "loss_cap_breach_count": sum(value < cap_r - 1e-12 for value in normal_losses),
        "unavoidable_execution_breach_count": sum(value < cap_r - 1e-12 for value in unavoidable),
        "loss_count": len(losses),
        "win_count": len(wins),
    }


def add_lineage(
    trades: Sequence[Mapping[str, Any]],
    *,
    variant_id: str,
    candidate_sha: str,
    stop_mult: float,
    manifest: Mapping[str, Any],
    source_run_id: str,
    source_head_sha: str,
    strategy_source_sha: str,
) -> list[dict[str, Any]]:
    market_shas = {str(row["symbol"]): str(row["sha256"]) for row in manifest.get("files", [])}
    output: list[dict[str, Any]] = []
    for ordinal, source in enumerate(trades):
        row = dict(source)
        symbol = str(row.get("symbol"))
        candidate_risk_pct = metric(row.get("risk_pct"))
        reference_risk_pct = candidate_risk_pct / stop_mult if stop_mult > 0.0 else 0.0
        row["window_id"] = "W1"
        row["strategy_id"] = "alpha_combo"
        row["variant_id"] = variant_id
        row["candidate_config_sha256"] = candidate_sha
        row["strategy_source_sha256"] = strategy_source_sha
        row["market_file_sha256"] = market_shas[symbol]
        row["source_w1_run_id"] = source_run_id
        row["source_w1_head_sha"] = source_head_sha
        row["candidate_risk_pct"] = candidate_risk_pct
        row["reference_risk_pct"] = reference_risk_pct
        row["net_reference_R"] = metric(row.get("net_return_pct")) / reference_risk_pct if reference_risk_pct > 0.0 else None
        row["reference_r_lock"] = "INCUMBENT_RAW_RISK_PCT"
        row["trade_id"] = stable_sha(
            {
                "strategy_id": "alpha_combo",
                "variant_id": variant_id,
                "window_id": "W1",
                "symbol": symbol,
                "entry_ts": row.get("entry_ts"),
                "exit_ts": row.get("exit_ts"),
                "candidate_config_sha256": candidate_sha,
                "market_file_sha256": market_shas[symbol],
                "ordinal": ordinal,
            }
        )
        output.append(row)
    return sorted_ledger(output)


def replay_once(
    *,
    variant_id: str,
    exit_spec: Any,
    strategy: Any,
    gate: Any,
    surgery: Any,
    symbols: tuple[str, ...],
    frames: Mapping[str, Any],
    features: Mapping[str, Any],
    funding: Mapping[str, list[dict[str, Any]]],
    manifest: Mapping[str, Any],
    combined_cost_bps: float,
    stress: bool,
    source_run_id: str,
    source_head_sha: str,
    strategy_source_sha: str,
) -> list[dict[str, Any]]:
    candidate_config = {"variant_id": variant_id, "exit": asdict(exit_spec)}
    candidate_sha = stable_sha(candidate_config)
    raw: list[dict[str, Any]] = []
    for symbol in symbols:
        replay = multi.p.replay_evidence(
            frames[symbol],
            features[symbol],
            strategy,
            gate,
            exit_spec,
            surgery,
            window_id="W1",
            symbol=symbol,
            warmup_bars=int(manifest["warmup_bars"]),
            history_bars=220,
            cost_bps_per_side=combined_cost_bps * (2.0 if stress else 1.0),
            entry_delay_bars=2 if stress else 1,
        )
        raw.extend(replay["trades"])
    quantiles = multi.p.funding_rate_quantiles(funding)
    adjusted = multi.p.apply_funding(raw, funding, "ADVERSE_P95" if stress else "OBSERVED", quantiles)
    return add_lineage(
        adjusted,
        variant_id=variant_id,
        candidate_sha=candidate_sha,
        stop_mult=float(exit_spec.stop_mult),
        manifest=manifest,
        source_run_id=source_run_id,
        source_head_sha=source_head_sha,
        strategy_source_sha=strategy_source_sha,
    )


def prior_trades(authority_root: Path, variant_id: str) -> list[dict[str, Any]]:
    path = authority_root / variant_id / "replay-A.json"
    payload = strict_json(path)
    return [dict(row) for row in payload.get("trades", []) if isinstance(row, Mapping)]


def evaluate_variant(
    *,
    variant_id: str,
    exit_spec: Any,
    authority_root: Path,
    strategy: Any,
    gate: Any,
    surgery: Any,
    symbols: tuple[str, ...],
    frames: Mapping[str, Any],
    features: Mapping[str, Any],
    funding: Mapping[str, list[dict[str, Any]]],
    manifest: Mapping[str, Any],
    combined_cost_bps: float,
    source_run_id: str,
    source_head_sha: str,
    strategy_source_sha: str,
    cap_r: float,
    out: Path,
) -> dict[str, Any]:
    replay_a = replay_once(
        variant_id=variant_id,
        exit_spec=exit_spec,
        strategy=strategy,
        gate=gate,
        surgery=surgery,
        symbols=symbols,
        frames=frames,
        features=features,
        funding=funding,
        manifest=manifest,
        combined_cost_bps=combined_cost_bps,
        stress=False,
        source_run_id=source_run_id,
        source_head_sha=source_head_sha,
        strategy_source_sha=strategy_source_sha,
    )
    replay_b = replay_once(
        variant_id=variant_id,
        exit_spec=exit_spec,
        strategy=strategy,
        gate=gate,
        surgery=surgery,
        symbols=symbols,
        frames=frames,
        features=features,
        funding=funding,
        manifest=manifest,
        combined_cost_bps=combined_cost_bps,
        stress=False,
        source_run_id=source_run_id,
        source_head_sha=source_head_sha,
        strategy_source_sha=strategy_source_sha,
    )
    stress = replay_once(
        variant_id=variant_id,
        exit_spec=exit_spec,
        strategy=strategy,
        gate=gate,
        surgery=surgery,
        symbols=symbols,
        frames=frames,
        features=features,
        funding=funding,
        manifest=manifest,
        combined_cost_bps=combined_cost_bps,
        stress=True,
        source_run_id=source_run_id,
        source_head_sha=source_head_sha,
        strategy_source_sha=strategy_source_sha,
    )

    sha_a, sha_b = ledger_sha(replay_a), ledger_sha(replay_b)
    duplicates = len(replay_a) - len({str(row.get("trade_id")) for row in replay_a})
    previous = prior_trades(authority_root, variant_id)
    cumulative = sorted_ledger(previous + replay_a)
    cumulative_stats = multi.p.combine_stats(cumulative)
    w1_stats = multi.p.combine_stats(replay_a)
    stress_stats = multi.p.combine_stats(stress)
    per_window = {
        role: multi.p.combine_stats([row for row in cumulative if str(row.get("window_id")) == role])
        for role in WINDOWS
    }
    positive_windows = sum(metric(row.get("net_return_pct_sum")) > 0.0 for row in per_window.values())
    stop_mult = float(exit_spec.stop_mult)
    normal_loss = reference_loss_metrics(replay_a, stop_mult, cap_r)
    stress_loss = reference_loss_metrics(stress, stop_mult, cap_r)
    cumulative_loss = {
        "avg_loss_R": metric(
            sum(metric(row.get("net_reference_R")) for row in cumulative if metric(row.get("net_reference_R")) < 0.0)
            / max(1, sum(metric(row.get("net_reference_R")) < 0.0 for row in cumulative))
        ),
        "worst_net_loss_R": min((metric(row.get("net_reference_R")) for row in cumulative), default=0.0),
    }
    candidate_sha = stable_sha({"variant_id": variant_id, "exit": asdict(exit_spec)})
    payload = {
        "variant_id": variant_id,
        "candidate_config_sha256": candidate_sha,
        "exit": asdict(exit_spec),
        "W1": {
            **w1_stats,
            "loss_metrics": normal_loss,
            "trade_count": len(replay_a),
        },
        "W1_stress_2x_p95_plus_one": {
            **stress_stats,
            "loss_metrics": stress_loss,
            "trade_count": len(stress),
        },
        "cumulative_F1_F2_F3_W1": {
            **cumulative_stats,
            **cumulative_loss,
            "positive_windows": positive_windows,
            "positive_windows_pct": positive_windows / len(WINDOWS) * 100.0,
            "window_stats": per_window,
        },
        "parity": {
            "state": "PASS" if sha_a == sha_b and duplicates == 0 else "HOLD",
            "replay_a_sha256": sha_a,
            "replay_b_sha256": sha_b,
            "duplicate_trade_count": duplicates,
            "trade_count_a": len(replay_a),
            "trade_count_b": len(replay_b),
        },
        "source_w1_run_id": source_run_id,
        "source_w1_head_sha": source_head_sha,
        "source_w1_manifest_sha256": sha256(Path(out).parent / "source-manifest.json") if (Path(out).parent / "source-manifest.json").exists() else None,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
    }
    atomic_json(out / variant_id / "replay-A.json", {"variant_id": variant_id, "trades": replay_a})
    atomic_json(out / variant_id / "replay-B.json", {"variant_id": variant_id, "trades": replay_b})
    atomic_json(out / variant_id / "W1-stress.json", {"variant_id": variant_id, "trades": stress})
    atomic_json(out / variant_id / "summary.json", payload)
    return payload


def candidate_gate(row: Mapping[str, Any], incumbent: Mapping[str, Any], prior_row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    gate = policy["w1_gate"]
    w1_row = row["W1"]
    w1_incumbent = incumbent["W1"]
    cumulative = row["cumulative_F1_F2_F3_W1"]
    normal_loss = w1_row["loss_metrics"]
    stress_loss = row["W1_stress_2x_p95_plus_one"]["loss_metrics"]
    incumbent_count = int(w1_incumbent.get("trade_count") or 0)
    candidate_count = int(w1_row.get("trade_count") or 0)
    retention = candidate_count / max(1, incumbent_count) * 100.0
    deltas = {
        "net_pct_points": metric(w1_row.get("net_return_pct_sum")) - metric(w1_incumbent.get("net_return_pct_sum")),
        "profit_factor": metric(w1_row.get("net_profit_factor")) - metric(w1_incumbent.get("net_profit_factor")),
        "payoff": metric(w1_row.get("payoff_ratio")) - metric(w1_incumbent.get("payoff_ratio")),
        "win_rate_pct_points": metric(w1_row.get("win_rate_pct")) - metric(w1_incumbent.get("win_rate_pct")),
        "drawdown_pct_points": metric(w1_row.get("max_drawdown_pct")) - metric(w1_incumbent.get("max_drawdown_pct")),
    }
    improved = sum(deltas[key] > 0.0 for key in ("net_pct_points", "profit_factor", "payoff"))
    checks = {
        "prior_research_strict_pass": bool(prior_row.get("multiobjective", {}).get("strict", {}).get("pass")),
        "incumbent_sample_qualified": incumbent_count >= int(gate["minimum_w1_trades"]),
        "candidate_sample_qualified": candidate_count >= int(gate["minimum_w1_trades"]),
        "parity_pass": row.get("parity", {}).get("state") == "PASS",
        "duplicate_free": int(row.get("parity", {}).get("duplicate_trade_count") or 0) == 0,
        "normal_loss_cap_pass": metric(normal_loss.get("normal_worst_net_loss_R"), -math.inf) >= float(gate["normal_worst_net_loss_R_min"]) and int(normal_loss.get("loss_cap_breach_count") or 0) <= int(gate["loss_cap_breach_count_max"]),
        "stress_loss_cap_pass": metric(stress_loss.get("normal_worst_net_loss_R"), -math.inf) >= float(gate["stress_worst_net_loss_R_min"]) and int(stress_loss.get("loss_cap_breach_count") or 0) <= int(gate["loss_cap_breach_count_max"]),
        "trade_retention_pass": retention >= float(gate["minimum_trade_retention_pct"]),
        "positive_windows_pass": metric(cumulative.get("positive_windows_pct")) >= float(gate["minimum_positive_windows_pct"]),
        "cumulative_net_pass": metric(cumulative.get("net_return_pct_sum")) > float(gate["minimum_cumulative_net_return_pct"]),
        "cumulative_profit_factor_pass": metric(cumulative.get("net_profit_factor")) > float(gate["minimum_cumulative_profit_factor"]),
        "drawdown_pass": deltas["drawdown_pct_points"] <= float(gate["max_drawdown_degradation_pct_points"]),
        "net_tolerance_pass": deltas["net_pct_points"] >= -float(gate["max_net_degradation_pct_points"]),
        "profit_factor_tolerance_pass": deltas["profit_factor"] >= -float(gate["max_profit_factor_degradation"]),
        "payoff_tolerance_pass": deltas["payoff"] >= -float(gate["max_payoff_degradation"]),
        "multiobjective_improvement_pass": improved >= int(gate["minimum_improved_primary_metrics"]),
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "trade_retention_pct": retention,
        "improved_primary_metrics": improved,
        "deltas_to_W1_incumbent": deltas,
    }


def wait_payload(source: Mapping[str, Any], *, source_run_id: str, source_head_sha: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_marker": CAPABILITY_MARKER,
        "state": "WAIT_DATA",
        "blockers": [],
        "strategy_id": "alpha_combo",
        "available_non_overlap_bars": int(source.get("available_non_overlap_bars") or 0),
        "missing_bars": int(source.get("missing_bars") or 0),
        "next_eligible_window_end": source.get("next_eligible_window_end"),
        "source_w1_run_id": source_run_id,
        "source_w1_head_sha": source_head_sha,
        "next": "RERUN_AFTER_DATA_WAIT_POOL_W1_PASS",
        "promotion_authority": False,
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--multiobjective-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--combined-cost-bps", type=float, default=4.0)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source_root = Path(args.source_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    authority_root = Path(args.multiobjective_root).resolve()
    policy_path = Path(args.policy).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    source_status = strict_json(source_root / "status.json")
    if source_status.get("state") == "WAIT_DATA":
        payload = wait_payload(source_status, source_run_id=args.source_run_id, source_head_sha=args.source_head_sha)
        atomic_json(out / "status.json", payload)
        atomic_json(out / "summary.json", payload)
        print(json.dumps({"state": payload["state"], "missing": payload["missing_bars"], "next": payload["next"]}, sort_keys=True))
        return 0
    if source_status.get("state") != "PASS" or source_status.get("blockers"):
        raise RuntimeError(f"W1_SOURCE_NOT_PASS:{source_status.get('state')}:{source_status.get('blockers')}")

    manifest_path = source_root / "data" / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("W1_MANIFEST_MISSING")
    manifest = strict_json(manifest_path)
    manifest_sha = sha256(manifest_path)
    if manifest_sha != source_status.get("W1_manifest_sha256"):
        raise RuntimeError("W1_MANIFEST_SHA_MISMATCH")
    if manifest.get("state") != "PASS" or manifest.get("blockers"):
        raise RuntimeError("W1_MANIFEST_NOT_PASS")
    if manifest.get("window_id") != "W1" or int(manifest.get("evaluation_bars") or 0) != 480 or int(manifest.get("warmup_bars") or 0) != 220:
        raise RuntimeError("W1_BOUNDARY_CONTRACT_FAIL")
    if len(manifest.get("files") or []) != 5:
        raise RuntimeError("W1_SYMBOL_FILE_COUNT_FAIL")

    baseline = strict_json(baseline_path)
    authority_summary = strict_json(authority_root / "summary.json")
    policy = strict_json(policy_path)
    if authority_summary.get("state") != "PASS_MULTIOBJECTIVE_RESEARCH_CANDIDATES":
        raise RuntimeError("MULTIOBJECTIVE_AUTHORITY_NOT_PASS")
    if authority_summary.get("promotion_authority") is not False or authority_summary.get("sealed_holdback_read") is not False:
        raise RuntimeError("MULTIOBJECTIVE_SAFETY_CONTRACT_FAIL")
    required_ids = list(policy["source_candidate_ids"])
    authority_rows = {str(row["variant_id"]): row for row in authority_summary.get("variants", [])}
    if any(candidate_id not in authority_rows for candidate_id in required_ids):
        raise RuntimeError("MULTIOBJECTIVE_VARIANT_MISSING")

    candidate = baseline["candidate"]
    gate = multi.exact._gate_from(candidate)
    base_exit = multi.exact._exit_from(candidate)
    surgery = multi.p.surgery_from(baseline.get("surgery"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    registry = multi.base._load_registry(root)
    registry_row = registry["alpha_combo"]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = multi.base._load_canonical_strategy(root, "alpha_combo", registry_row)
    frames, features, funding = w1.load_window(source_root, manifest)

    stop065 = replace(base_exit, exit_id="RR150_STOP065_W1", stop_mult=0.65)
    specs = {
        "INCUMBENT_CONTROL": base_exit,
        "STOP065_PROFIT_CONTROL": stop065,
        "TIME54": replace(stop065, exit_id="RR150_STOP065_TIME54_W1", time_stop_bars=54),
        "TIME60": replace(stop065, exit_id="RR150_STOP065_TIME60_W1", time_stop_bars=60),
    }
    rows: list[dict[str, Any]] = []
    for variant_id in required_ids:
        print(f"PRIMARY_W1_START variant={variant_id}", flush=True)
        row = evaluate_variant(
            variant_id=variant_id,
            exit_spec=specs[variant_id],
            authority_root=authority_root,
            strategy=strategy,
            gate=gate,
            surgery=surgery,
            symbols=symbols,
            frames=frames,
            features=features,
            funding=funding,
            manifest=manifest,
            combined_cost_bps=float(args.combined_cost_bps),
            source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            strategy_source_sha=strategy_source_sha,
            cap_r=float(policy["w1_gate"]["normal_worst_net_loss_R_min"]),
            out=out,
        )
        rows.append(row)
        print(f"PRIMARY_W1_END variant={variant_id}", flush=True)

    incumbent = rows[0]
    for row in rows[1:]:
        gate_result = candidate_gate(row, incumbent, authority_rows[str(row["variant_id"])], policy)
        row["W1_confirmation_gate"] = gate_result
        atomic_json(out / str(row["variant_id"]) / "summary.json", row)

    eligible = [row for row in rows[1:] if row.get("W1_confirmation_gate", {}).get("pass")]
    profit = max(eligible, key=lambda row: metric(row["W1"].get("net_return_pct_sum"))) if eligible else None
    balanced = max(eligible, key=lambda row: (metric(row["W1"].get("win_rate_pct")), metric(row["W1"].get("net_return_pct_sum")))) if eligible else None
    robust = min(eligible, key=lambda row: (metric(row["W1"].get("max_drawdown_pct"), math.inf), -metric(row["W1_stress_2x_p95_plus_one"].get("net_return_pct_sum")))) if eligible else None
    active: list[str] = []
    for row in (profit, balanced, robust):
        if row is not None and str(row["variant_id"]) not in active:
            active.append(str(row["variant_id"]))
        if len(active) >= int(policy["selection"]["max_active_candidates"]):
            break

    minimum = int(policy["w1_gate"]["minimum_w1_trades"])
    low_sample = int(incumbent["W1"].get("trade_count") or 0) < minimum
    state = "PASS_W1_PRIMARY_CONFIRMATION" if active else ("W1_LOW_SAMPLE_HOLD" if low_sample else "W1_REJECT_RETAIN_INCUMBENT")
    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_marker": CAPABILITY_MARKER,
        "state": state,
        "blockers": [],
        "strategy_id": "alpha_combo",
        "source_w1_run_id": args.source_run_id,
        "source_w1_head_sha": args.source_head_sha,
        "source_w1_manifest_sha256": manifest_sha,
        "source_multiobjective_run_id": authority_summary.get("source_run_id"),
        "source_multiobjective_head_sha": authority_summary.get("source_head_sha"),
        "baseline_summary_sha256": sha256(baseline_path),
        "multiobjective_summary_sha256": sha256(authority_root / "summary.json"),
        "policy_sha256": sha256(policy_path),
        "profit_control": profit["variant_id"] if profit else None,
        "balanced_control": balanced["variant_id"] if balanced else None,
        "robust_control": robust["variant_id"] if robust else None,
        "active_candidate_queue": active,
        "variants": rows,
        "requires_new_sealed_holdback": bool(active),
        "sealed_holdback_read": False,
        "promotion_authority": False,
        "next": "W1_NEW_SEALED_HOLDBACK_GENERATOR" if active else "ALPHA_NEXT_NON_OVERLAP_OR_RETAIN_INCUMBENT",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "paper_allowed": False,
        "live_allowed": False,
        "order_authority": "BLOCKED",
    }
    atomic_json(out / "status.json", final)
    atomic_json(out / "summary.json", final)
    print(json.dumps({"state": state, "active": active, "next": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
