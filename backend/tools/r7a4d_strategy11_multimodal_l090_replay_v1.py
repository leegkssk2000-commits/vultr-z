from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

from backend.strategy25.strategy11_feature_library_v1 import GateSpec
from backend.tools import r7a4d_strategy11_gemini_22_prework_v1_1 as normalized_prior

prior = normalized_prior.v1
repair = prior.repair
p = prior.p
exact = prior.exact
base = prior.base

VERSION = "R7A4D_STRATEGY11_MULTIMODAL_L090_REPLAY_V1"
CAPABILITY_MARKER = "MULTIMODAL_RESCUE_L090_REPLAY"
STRATEGIES = tuple(prior.STRATEGIES)


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return str(value)


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(json_safe(payload), handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def stable_sha(value: Any) -> str:
    raw = json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def resolve_candidate(
    strategy_id: str,
    candidate_id: str,
    spec: Mapping[str, Any],
    base_gate: Any,
    base_exit: Any,
    base_surgery: Any,
    symbols: tuple[str, ...],
) -> tuple[Any, Any, Any, tuple[str, ...], dict[str, Any]]:
    kind = str(spec["kind"])
    gate, exit_spec, surgery, selected_symbols = base_gate, base_exit, base_surgery, symbols
    if kind == "GATE":
        gate = GateSpec(**dict(spec["gate"]))
    elif kind == "EXIT":
        exit_spec = replace(base_exit, exit_id=f"{base_exit.exit_id}_{candidate_id}", **dict(spec["changes"]))
    elif kind == "SYMBOL":
        excluded = str(spec["excluded_symbol"])
        selected_symbols = tuple(symbol for symbol in symbols if symbol != excluded)
        if not selected_symbols:
            raise RuntimeError(f"SYMBOL_EXCLUSION_EMPTY:{strategy_id}:{excluded}")
    else:
        raise RuntimeError(f"UNKNOWN_CANDIDATE_KIND:{kind}")
    config = {
        "strategy_id": strategy_id,
        "candidate_id": candidate_id,
        "axis": spec["axis"],
        "kind": kind,
        "gate": asdict(gate),
        "exit": asdict(exit_spec),
        "surgery": asdict(surgery) if surgery is not None else None,
        "symbols": list(selected_symbols),
    }
    return gate, exit_spec, surgery, selected_symbols, config


def evaluate(
    *,
    variant_id: str,
    config: Mapping[str, Any],
    exit_spec: Any,
    strategy: Any,
    gate: Any,
    surgery: Any,
    symbols: tuple[str, ...],
    frames: Mapping[Any, Any],
    features: Mapping[Any, Any],
    funding: Mapping[str, list[dict[str, Any]]],
    quantiles: Mapping[str, Mapping[str, float]],
    manifest: Mapping[str, Any],
    market_shas: Mapping[Any, str],
    strategy_source_sha: str,
    source_run_id: str,
    source_head_sha: str,
    normal_cap_r: float,
    stress_cap_r: float,
    out: Path,
) -> dict[str, Any]:
    candidate_sha = stable_sha(config)
    ledgers = []
    for replay_name in ("A", "B"):
        trades = repair.replay_once(
            variant_id=variant_id,
            exit_spec=exit_spec,
            strategy=strategy,
            gate=gate,
            surgery=surgery,
            symbols=symbols,
            frames=frames,
            features=features,
            funding=funding,
            quantiles=quantiles,
            manifest=manifest,
            market_shas=market_shas,
            strategy_source_sha=strategy_source_sha,
            candidate_sha=candidate_sha,
            source_run_id=source_run_id,
            source_head_sha=source_head_sha,
            cost_multiplier=1.0,
            funding_scenario="OBSERVED",
            latency_scenario="NEXT_BAR_OPEN",
        )
        ledgers.append(trades)
        atomic_json(out / variant_id / f"replay-{replay_name}.json", {"variant_id": variant_id, "trades": trades})
    stress = repair.replay_once(
        variant_id=variant_id,
        exit_spec=exit_spec,
        strategy=strategy,
        gate=gate,
        surgery=surgery,
        symbols=symbols,
        frames=frames,
        features=features,
        funding=funding,
        quantiles=quantiles,
        manifest=manifest,
        market_shas=market_shas,
        strategy_source_sha=strategy_source_sha,
        candidate_sha=candidate_sha,
        source_run_id=source_run_id,
        source_head_sha=source_head_sha,
        cost_multiplier=2.0,
        funding_scenario="ADVERSE_P95",
        latency_scenario="PLUS_ONE_BAR",
    )
    sha_a, sha_b = repair.ledger_sha(ledgers[0]), repair.ledger_sha(ledgers[1])
    duplicate_count = len(ledgers[0]) - len({row["trade_id"] for row in ledgers[0]})
    stats = p.combine_stats(ledgers[0])
    per_window = {
        role: p.combine_stats([row for row in ledgers[0] if row.get("window_id") == role])
        for role in repair.FRESH_ROLES
    }
    positive_windows = sum(metric(row.get("net_return_pct_sum")) > 0.0 for row in per_window.values())
    payload = {
        "variant_id": variant_id,
        "candidate_config": config,
        "candidate_config_sha256": candidate_sha,
        "trade_count": int(stats.get("trade_count") or 0),
        "win_rate_pct": stats.get("win_rate_pct"),
        "net_return_pct_sum": stats.get("net_return_pct_sum"),
        "net_profit_factor": stats.get("net_profit_factor"),
        "payoff_ratio": stats.get("payoff_ratio"),
        "max_drawdown_pct": stats.get("max_drawdown_pct"),
        "positive_fresh_windows": positive_windows,
        "positive_fresh_windows_pct": positive_windows / len(repair.FRESH_ROLES) * 100.0,
        "window_stats": per_window,
        "loss_metrics": repair.loss_metrics(ledgers[0], normal_cap_r),
        "stress_2x_p95_plus_one": {
            "trade_count": len(stress),
            "stats": p.combine_stats(stress),
            "loss_metrics": repair.loss_metrics(stress, stress_cap_r),
        },
        "parity": {
            "state": "PASS" if sha_a == sha_b and duplicate_count == 0 else "HOLD",
            "replay_a_sha256": sha_a,
            "replay_b_sha256": sha_b,
            "duplicate_trade_count": duplicate_count,
            "trade_count_a": len(ledgers[0]),
            "trade_count_b": len(ledgers[1]),
        },
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
    }
    atomic_json(out / variant_id / "summary.json", payload)
    return payload


def ladder_check(row: Mapping[str, Any], incumbent: Mapping[str, Any], stage: Mapping[str, Any], floors: Mapping[str, Any]) -> dict[str, Any]:
    normal = row.get("loss_metrics", {})
    stress = row.get("stress_2x_p95_plus_one", {}).get("loss_metrics", {})
    incumbent_loss = incumbent.get("loss_metrics", {})
    deltas = {
        "net": metric(row.get("net_return_pct_sum")) - metric(incumbent.get("net_return_pct_sum")),
        "pf": metric(row.get("net_profit_factor")) - metric(incumbent.get("net_profit_factor")),
        "payoff": metric(row.get("payoff_ratio")) - metric(incumbent.get("payoff_ratio")),
        "dd": metric(row.get("max_drawdown_pct")) - metric(incumbent.get("max_drawdown_pct")),
    }
    retention = metric(row.get("trade_count")) / max(1.0, metric(incumbent.get("trade_count"), 1.0)) * 100.0
    improved = sum(deltas[key] > 0.0 for key in ("net", "pf", "payoff"))
    avg_loss_ok = metric(normal.get("avg_loss_R"), -math.inf) >= metric(incumbent_loss.get("avg_loss_R"), -math.inf)
    normal_worst = metric(normal.get("normal_worst_net_loss_R", normal.get("worst_net_loss_R")), -math.inf)
    stress_worst = metric(stress.get("normal_worst_net_loss_R", stress.get("worst_net_loss_R")), -math.inf)
    passed = (
        row.get("parity", {}).get("state") == "PASS"
        and int(row.get("parity", {}).get("duplicate_trade_count") or 0) == 0
        and normal_worst >= float(stage["normal_worst_net_loss_R_min"])
        and stress_worst >= float(stage["stress_worst_net_loss_R_min"])
        and int(normal.get("loss_cap_breach_count") or 0) == 0
        and int(stress.get("loss_cap_breach_count") or 0) == 0
        and retention >= float(stage["trade_retention_pct_min"])
        and metric(row.get("positive_fresh_windows_pct")) >= float(stage["positive_windows_pct_min"])
        and deltas["dd"] <= float(stage["max_dd_degradation_pct_points"])
        and improved >= int(floors["minimum_improved_primary_metrics"])
        and deltas["net"] >= -float(floors["max_net_degradation_pct_points"])
        and deltas["pf"] >= -float(floors["max_profit_factor_degradation"])
        and deltas["payoff"] >= -float(floors["max_payoff_degradation"])
        and avg_loss_ok
    )
    return {
        "stage": stage["stage"],
        "research_pass": passed,
        "normal_worst_net_loss_R": normal_worst,
        "stress_worst_net_loss_R": stress_worst,
        "trade_retention_pct": retention,
        "improved_primary_metrics": improved,
        "average_loss_nonworse": avg_loss_ok,
        "deltas": deltas,
        "promotion_authority": False,
    }


def replay(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    plan = strict_json(Path(args.plan).resolve())
    policy = strict_json(Path(args.policy).resolve())
    plan_rows = {str(row["strategy_id"]): row for row in plan["rows"]}
    requested = [value.strip() for value in args.strategy_ids.split(",") if value.strip()]
    if not requested or any(sid not in STRATEGIES for sid in requested):
        raise RuntimeError("STRATEGY_IDS_INVALID")
    evidence_root = Path(args.evidence_root).resolve()
    frames, features, funding, manifest = p.load_fresh_data(Path(args.fresh_root).resolve())
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = repair.market_sha_map(manifest)
    registry = base._load_registry(Path(args.root).resolve())
    stage = policy["loss_ladder"][0]
    floors = policy["economic_floors"]
    batch_rows = []
    for sid in requested:
        summary_path = prior.find_summary(evidence_root, sid)
        baseline_summary = strict_json(summary_path)
        candidate = baseline_summary["candidate"]
        base_gate = exact._gate_from(candidate)
        base_exit = exact._exit_from(candidate)
        base_surgery = p.surgery_from(baseline_summary.get("surgery"))
        symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))
        registry_row = registry[sid]
        strategy = base._load_canonical_strategy(Path(args.root).resolve(), sid, registry_row)
        source_sha = str(registry_row["canonical_engine"]["source_sha256"])
        control_config = {
            "strategy_id": sid,
            "candidate_id": "NO_CHANGE_CONTROL",
            "axis": "NO_CHANGE",
            "kind": "CONTROL",
            "gate": asdict(base_gate),
            "exit": asdict(base_exit),
            "surgery": asdict(base_surgery) if base_surgery is not None else None,
            "symbols": list(symbols),
        }
        strategy_out = out / sid
        incumbent = evaluate(
            variant_id="NO_CHANGE_CONTROL",
            config=control_config,
            exit_spec=base_exit,
            strategy=strategy,
            gate=base_gate,
            surgery=base_surgery,
            symbols=symbols,
            frames=frames,
            features=features,
            funding=funding,
            quantiles=quantiles,
            manifest=manifest,
            market_shas=market_shas,
            strategy_source_sha=source_sha,
            source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            normal_cap_r=float(stage["normal_worst_net_loss_R_min"]),
            stress_cap_r=float(stage["stress_worst_net_loss_R_min"]),
            out=strategy_out,
        )
        variants = [incumbent]
        for candidate_id in plan_rows[sid]["candidate_ids"]:
            spec = plan_rows[sid]["candidate_specs"][candidate_id]
            gate, exit_spec, surgery, selected_symbols, config = resolve_candidate(
                sid, candidate_id, spec, base_gate, base_exit, base_surgery, symbols
            )
            row = evaluate(
                variant_id=candidate_id,
                config=config,
                exit_spec=exit_spec,
                strategy=strategy,
                gate=gate,
                surgery=surgery,
                symbols=selected_symbols,
                frames=frames,
                features=features,
                funding=funding,
                quantiles=quantiles,
                manifest=manifest,
                market_shas=market_shas,
                strategy_source_sha=source_sha,
                source_run_id=args.source_run_id,
                source_head_sha=args.source_head_sha,
                normal_cap_r=float(stage["normal_worst_net_loss_R_min"]),
                stress_cap_r=float(stage["stress_worst_net_loss_R_min"]),
                out=strategy_out,
            )
            row["ladder_check"] = ladder_check(row, incumbent, stage, floors)
            atomic_json(strategy_out / candidate_id / "summary.json", row)
            variants.append(row)
        eligible = [row for row in variants[1:] if row["ladder_check"]["research_pass"]]
        winner = max(
            eligible,
            key=lambda row: (
                metric(row.get("net_return_pct_sum")),
                metric(row.get("net_profit_factor")),
                metric(row.get("payoff_ratio")),
                -metric(row.get("max_drawdown_pct"), math.inf),
            ),
        ) if eligible else None
        summary = {
            "schema_version": "1.0",
            "version": VERSION,
            "capability_marker": CAPABILITY_MARKER,
            "state": "PASS_L090_RESEARCH_CANDIDATE" if winner else "NO_L090_CANDIDATE",
            "strategy_id": sid,
            "tested_candidate_ids": plan_rows[sid]["candidate_ids"],
            "winner": winner["variant_id"] if winner else None,
            "variants": variants,
            "next": "L085_REFINEMENT" if winner else "NEXT_DISTINCT_CAUSAL_AXIS",
            "same_axis_generation_count": 1,
            "same_axis_generation_limit": 2,
            "distinct_axis_reopen_allowed": True,
            "promotion_authority": False,
            "w1_confirmation_required": True,
            "new_sealed_required": True,
            "canonical_mutated": False,
            "registry_mutated": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        }
        atomic_json(strategy_out / "summary.json", summary)
        batch_rows.append(summary)
    atomic_json(out / "batch.json", {"state": "PASS", "rows": batch_rows})
    return 0


def aggregate(args: argparse.Namespace) -> int:
    root = Path(args.replay_root).resolve()
    found = []
    for path in sorted(root.rglob("summary.json")):
        payload = strict_json(path)
        if payload.get("strategy_id") and payload.get("version") == VERSION:
            found.append(payload)
    by_strategy = {str(row["strategy_id"]): row for row in found}
    if set(by_strategy) != set(STRATEGIES):
        raise RuntimeError(f"AGGREGATE_STRATEGY_MISMATCH:{len(by_strategy)}")
    candidates = [row for row in by_strategy.values() if row["state"] == "PASS_L090_RESEARCH_CANDIDATE"]
    def winner_row(summary: Mapping[str, Any]) -> Mapping[str, Any]:
        return next(row for row in summary["variants"] if row["variant_id"] == summary["winner"])
    candidates.sort(
        key=lambda row: (
            metric(winner_row(row).get("net_return_pct_sum")),
            metric(winner_row(row).get("net_profit_factor")),
            metric(winner_row(row).get("payoff_ratio")),
        ),
        reverse=True,
    )
    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_marker": CAPABILITY_MARKER,
        "state": "PASS_MULTIMODAL_L090_REPLAY_COMPLETE",
        "strategy_count": len(by_strategy),
        "l090_candidate_count": len(candidates),
        "active_l085_queue": [
            {
                "strategy_id": row["strategy_id"],
                "winner": row["winner"],
                "metrics": winner_row(row),
                "next": "L085_REFINEMENT",
            }
            for row in candidates[:3]
        ],
        "pending_distinct_axis_queue": [
            {"strategy_id": row["strategy_id"], "next": "NEXT_DISTINCT_CAUSAL_AXIS"}
            for row in by_strategy.values()
            if row["state"] != "PASS_L090_RESEARCH_CANDIDATE"
        ],
        "rows": [by_strategy[sid] for sid in STRATEGIES],
        "continue_until_utc": "2026-08-01T08:30:00Z",
        "promotion_authority": False,
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "next": "RUN_L085_QUEUE_AND_REOPEN_DISTINCT_AXES",
    }
    atomic_json(Path(args.out).resolve() / "final.json", final)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("replay", "aggregate"), required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan")
    parser.add_argument("--policy")
    parser.add_argument("--fresh-root")
    parser.add_argument("--evidence-root")
    parser.add_argument("--strategy-ids")
    parser.add_argument("--source-run-id")
    parser.add_argument("--source-head-sha")
    parser.add_argument("--replay-root")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    return replay(args) if args.mode == "replay" else aggregate(args)


if __name__ == "__main__":
    raise SystemExit(main())
