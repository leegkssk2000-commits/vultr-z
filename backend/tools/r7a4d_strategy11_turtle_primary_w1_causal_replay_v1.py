from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.tools import r7a4d_strategy11_data_wait_pool_compute_v1 as w1
from backend.tools import r7a4d_strategy11_turtle_gemini_trailing_v1 as gemini_turtle


VERSION = "R7A4D_STRATEGY11_TURTLE_PRIMARY_W1_CAUSAL_REPLAY_V1"
CAPABILITY_MARKER = "PRIMARY_W1_CAUSAL_REPLAY"
STRATEGY_ID = "turtle_trend"
WINDOWS = ("F1", "F2", "F3", "W1")

turtle = gemini_turtle.turtle
sealed = turtle.sealed
p = turtle.p
exact = turtle.exact
base = turtle.base


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def sorted_ledger(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sealed.v1.sorted_ledger([dict(row) for row in trades])


def prior_trades(authority_root: Path, variant_id: str) -> list[dict[str, Any]]:
    payload = strict_json(authority_root / variant_id / "replay-A.json")
    return [dict(row) for row in payload.get("trades", []) if isinstance(row, Mapping)]


def cumulative_loss_metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    wins = [metric(row.get("net_reference_R")) for row in trades if metric(row.get("net_reference_R")) > 0.0]
    losses = [metric(row.get("net_reference_R")) for row in trades if metric(row.get("net_reference_R")) < 0.0]
    return {
        "avg_win_R": sum(wins) / len(wins) if wins else None,
        "avg_loss_R": sum(losses) / len(losses) if losses else None,
        "payoff_R": ((sum(wins) / len(wins)) / abs(sum(losses) / len(losses))) if wins and losses else 0.0,
        "worst_net_loss_R": min(losses) if losses else 0.0,
        "loss_count": len(losses),
        "win_count": len(wins),
    }


def wait_payload(source: Mapping[str, Any], *, source_run_id: str, source_head_sha: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_marker": CAPABILITY_MARKER,
        "state": "WAIT_DATA",
        "blockers": [],
        "strategy_id": STRATEGY_ID,
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
        "paper_allowed": False,
        "live_allowed": False,
        "order_authority": "BLOCKED",
    }


def evaluate_w1_variant(
    *,
    variant_id: str,
    exit_spec: Any,
    surgery: Any,
    strategy: Any,
    gate: Any,
    symbols: tuple[str, ...],
    frames: Mapping[str, Any],
    features: Mapping[str, Any],
    funding: Mapping[str, list[dict[str, Any]]],
    manifest: Mapping[str, Any],
    strategy_source_sha: str,
    source_run_id: str,
    source_head_sha: str,
    cap_r: float,
    authority_root: Path,
    out: Path,
) -> dict[str, Any]:
    tuple_frames = {("W1", symbol): frames[symbol] for symbol in symbols}
    tuple_features = {("W1", symbol): features[symbol] for symbol in symbols}
    market_shas = {
        ("W1", str(row["symbol"])): str(row["sha256"])
        for row in manifest.get("files", [])
        if str(row.get("symbol")) in symbols
    }
    quantiles = p.funding_rate_quantiles(funding)
    original_roles = turtle.FRESH_ROLES
    original_surgery_allows = p.surgery_allows
    turtle.FRESH_ROLES = ("W1",)
    try:
        row = turtle.evaluate_variant_with_surgery(
            variant_id=variant_id,
            exit_spec=exit_spec,
            surgery=surgery,
            original_surgery_allows=original_surgery_allows,
            strategy=strategy,
            gate=gate,
            symbols=symbols,
            frames=tuple_frames,
            features=tuple_features,
            funding=funding,
            quantiles=quantiles,
            manifest=manifest,
            market_shas=market_shas,
            strategy_source_sha=strategy_source_sha,
            source_run_id=source_run_id,
            source_head_sha=source_head_sha,
            cap_r=cap_r,
            out=out,
        )
    finally:
        turtle.FRESH_ROLES = original_roles

    current = strict_json(out / variant_id / "replay-A.json")
    current_trades = [dict(item) for item in current.get("trades", []) if isinstance(item, Mapping)]
    for item in current_trades:
        item["strategy_id"] = STRATEGY_ID
        item["variant_id"] = variant_id
        item["source_w1_run_id"] = source_run_id
        item["source_w1_head_sha"] = source_head_sha
    current_trades = sorted_ledger(current_trades)
    current_b = strict_json(out / variant_id / "replay-B.json")
    current_b_trades = [dict(item) for item in current_b.get("trades", []) if isinstance(item, Mapping)]
    for item in current_b_trades:
        item["strategy_id"] = STRATEGY_ID
        item["variant_id"] = variant_id
        item["source_w1_run_id"] = source_run_id
        item["source_w1_head_sha"] = source_head_sha
    current_b_trades = sorted_ledger(current_b_trades)
    atomic_json(out / variant_id / "replay-A.json", {"variant_id": variant_id, "roles": ["W1"], "trades": current_trades})
    atomic_json(out / variant_id / "replay-B.json", {"variant_id": variant_id, "roles": ["W1"], "trades": current_b_trades})

    sha_a = sealed.v1.ledger_sha(current_trades)
    sha_b = sealed.v1.ledger_sha(current_b_trades)
    duplicates = len(current_trades) - len({str(item.get("trade_id")) for item in current_trades})
    row["parity"] = {
        **dict(row.get("parity") or {}),
        "state": "PASS" if sha_a == sha_b and duplicates == 0 else "HOLD",
        "replay_a_sha256": sha_a,
        "replay_b_sha256": sha_b,
        "duplicate_trade_count": duplicates,
        "trade_count_a": len(current_trades),
        "trade_count_b": len(current_b_trades),
    }

    previous = prior_trades(authority_root, variant_id)
    cumulative = sorted_ledger(previous + current_trades)
    cumulative_stats = p.combine_stats(cumulative)
    per_window = {
        role: p.combine_stats([item for item in cumulative if str(item.get("window_id")) == role])
        for role in WINDOWS
    }
    positive_windows = sum(metric(stats.get("net_return_pct_sum")) > 0.0 for stats in per_window.values())
    w1_stats = {
        "trade_count": int(row.get("trade_count") or 0),
        "win_rate_pct": row.get("win_rate_pct"),
        "net_return_pct_sum": row.get("net_return_pct_sum"),
        "net_profit_factor": row.get("net_profit_factor"),
        "payoff_ratio": row.get("payoff_ratio"),
        "max_drawdown_pct": row.get("max_drawdown_pct"),
        "loss_metrics": row.get("loss_metrics"),
        "bootstrap": row.get("bootstrap"),
        "deflated_sharpe": row.get("deflated_sharpe"),
    }
    stress_source = dict(row.get("stress_2x_p95_plus_one") or {})
    stress_stats = dict(stress_source.get("stats") or {})
    stress_payload = {
        **stress_stats,
        "trade_count": int(stress_source.get("trade_count") or 0),
        "loss_metrics": stress_source.get("loss_metrics"),
    }
    row["strategy_id"] = STRATEGY_ID
    row["W1"] = w1_stats
    row["W1_stress_2x_p95_plus_one"] = stress_payload
    row["cumulative_F1_F2_F3_W1"] = {
        **cumulative_stats,
        **cumulative_loss_metrics(cumulative),
        "positive_windows": positive_windows,
        "positive_windows_pct": positive_windows / len(WINDOWS) * 100.0,
        "window_stats": per_window,
    }
    row["source_w1_run_id"] = source_run_id
    row["source_w1_head_sha"] = source_head_sha
    row["canonical_mutated"] = False
    row["registry_mutated"] = False
    row["protected_mutations"] = 0
    row["execution_allowed"] = False
    atomic_json(out / variant_id / "summary.json", row)
    return row


def confirmation_gate(
    row: Mapping[str, Any],
    incumbent: Mapping[str, Any],
    prior_row: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    gate = policy["w1_gate"]
    w1_row = row["W1"]
    w1_incumbent = incumbent["W1"]
    cumulative = row["cumulative_F1_F2_F3_W1"]
    incumbent_cumulative = incumbent["cumulative_F1_F2_F3_W1"]
    normal_loss = dict(w1_row.get("loss_metrics") or {})
    stress_loss = dict(row["W1_stress_2x_p95_plus_one"].get("loss_metrics") or {})
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
    candidate_avg_loss = metric(cumulative.get("avg_loss_R"), -math.inf)
    incumbent_avg_loss = metric(incumbent_cumulative.get("avg_loss_R"), -math.inf)
    checks = {
        "prior_causal_axis_present": str(prior_row.get("variant_id")) == str(row.get("variant_id")),
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
        "average_loss_nonworse": candidate_avg_loss >= incumbent_avg_loss,
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
        "prior_F1_F2_F3_comparison": prior_row.get("comparison_to_incumbent"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--turtle-authority-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source_root = Path(args.source_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    authority_root = Path(args.turtle_authority_root).resolve()
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
    authority = strict_json(authority_root / "summary.json")
    policy = strict_json(policy_path)
    if baseline.get("state") != "PASS" or baseline.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("TURTLE_BASELINE_AUTHORITY_INVALID")
    if authority.get("state") != "RESEARCH_DERIVED_REPAIR_HOLD" or authority.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("TURTLE_CAUSAL_AUTHORITY_INVALID")
    if authority.get("winner") is not None or authority.get("sealed_holdback_read") is not False or authority.get("existing_sealed_reused") is not False:
        raise RuntimeError("TURTLE_CAUSAL_SAFETY_CONTRACT_FAIL")
    required_ids = list(policy["source_candidate_ids"])
    authority_rows = {str(item["variant_id"]): item for item in authority.get("variants", [])}
    if any(candidate_id not in authority_rows for candidate_id in required_ids):
        raise RuntimeError("TURTLE_CAUSAL_VARIANT_MISSING")

    candidate = baseline["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    surgery = p.surgery_from(baseline.get("surgery"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry[STRATEGY_ID]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, STRATEGY_ID, registry_row)
    frames, features, funding = w1.load_window(source_root, manifest)

    specs = {
        "INCUMBENT_CONTROL": base_exit,
        "TRAIL_ACT100_ATR200": replace(base_exit, exit_id="TIGHT085_TRAIL_ACT100_ATR200_W1", trail_activate_r=1.0, trail_atr_mult=2.0),
        "TRAIL_ACT100_ATR250": replace(base_exit, exit_id="TIGHT085_TRAIL_ACT100_ATR250_W1", trail_activate_r=1.0, trail_atr_mult=2.5),
    }
    rows: list[dict[str, Any]] = []
    for variant_id in required_ids:
        print(f"TURTLE_PRIMARY_W1_START variant={variant_id}", flush=True)
        row = evaluate_w1_variant(
            variant_id=variant_id,
            exit_spec=specs[variant_id],
            surgery=surgery,
            strategy=strategy,
            gate=gate,
            symbols=symbols,
            frames=frames,
            features=features,
            funding=funding,
            manifest=manifest,
            strategy_source_sha=strategy_source_sha,
            source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            cap_r=float(policy["w1_gate"]["normal_worst_net_loss_R_min"]),
            authority_root=authority_root,
            out=out,
        )
        rows.append(row)
        print(f"TURTLE_PRIMARY_W1_END variant={variant_id}", flush=True)

    incumbent = rows[0]
    for row in rows[1:]:
        gate_result = confirmation_gate(row, incumbent, authority_rows[str(row["variant_id"])], policy)
        row["W1_confirmation_gate"] = gate_result
        atomic_json(out / str(row["variant_id"]) / "summary.json", row)

    eligible = [row for row in rows[1:] if row.get("W1_confirmation_gate", {}).get("pass")]
    eligible.sort(
        key=lambda row: (
            metric(row["W1"].get("net_return_pct_sum")),
            metric(row["W1"].get("net_profit_factor")),
            metric(row["W1"].get("payoff_ratio")),
            -metric(row["W1"].get("max_drawdown_pct"), math.inf),
        ),
        reverse=True,
    )
    active = [str(row["variant_id"]) for row in eligible[: int(policy["selection"]["max_active_candidates"])]]
    minimum = int(policy["w1_gate"]["minimum_w1_trades"])
    low_sample = int(incumbent["W1"].get("trade_count") or 0) < minimum
    state = "PASS_W1_PRIMARY_CAUSAL_REPLAY" if active else ("W1_LOW_SAMPLE_HOLD" if low_sample else "W1_REJECT_RETAIN_INCUMBENT")
    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_marker": CAPABILITY_MARKER,
        "state": state,
        "blockers": [],
        "strategy_id": STRATEGY_ID,
        "source_w1_run_id": args.source_run_id,
        "source_w1_head_sha": args.source_head_sha,
        "source_w1_manifest_sha256": manifest_sha,
        "source_turtle_authority_run_id": authority.get("source_run_id"),
        "source_turtle_authority_head_sha": authority.get("source_head_sha"),
        "baseline_summary_sha256": sha256(baseline_path),
        "turtle_authority_summary_sha256": sha256(authority_root / "summary.json"),
        "policy_sha256": sha256(policy_path),
        "active_candidate_queue": active,
        "variants": rows,
        "requires_new_sealed_holdback": bool(active),
        "sealed_holdback_read": False,
        "promotion_authority": False,
        "next": "W1_NEW_SEALED_HOLDBACK_GENERATOR" if active else "TURTLE_RETAIN_INCUMBENT_OR_GEMINI_W1_DELTA",
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
