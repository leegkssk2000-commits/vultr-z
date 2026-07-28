from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MULTI_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_multiobjective_auto_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_PRIMARY_W1_CONFIRMATION_V1"
CAPABILITY = "PRIMARY_W1_MULTIOBJECTIVE_CONFIRMATION"
REQUIRED_VARIANTS = ("INCUMBENT_CONTROL", "STOP065_PROFIT_CONTROL", "TIME54", "TIME60")


def load_multi() -> Any:
    name = "r7a4d_strategy11_alpha_multiobjective_for_w1"
    spec = importlib.util.spec_from_file_location(name, MULTI_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("ALPHA_MULTIOBJECTIVE_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


multi = load_multi()
l085 = multi.l085
cost = multi.cost
p = multi.p
exact = multi.exact
base = multi.base
strict_json = multi.strict_json
metric = multi.metric
worst = multi.worst


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


def candidate_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    stress = row.get("stress_2x_p95_plus_one", {})
    stress_stats = stress.get("stats", {}) if isinstance(stress, Mapping) else {}
    stress_loss = stress.get("loss_metrics", {}) if isinstance(stress, Mapping) else {}
    loss = row.get("loss_metrics", {}) if isinstance(row.get("loss_metrics"), Mapping) else {}
    parity = row.get("parity", {}) if isinstance(row.get("parity"), Mapping) else {}
    return {
        "variant_id": str(row.get("variant_id")),
        "trade_count": int(row.get("trade_count") or 0),
        "win_rate_pct": metric(row.get("win_rate_pct")),
        "net_return_pct_sum": metric(row.get("net_return_pct_sum")),
        "net_profit_factor": metric(row.get("net_profit_factor")),
        "payoff_ratio": metric(row.get("payoff_ratio")),
        "max_drawdown_pct": metric(row.get("max_drawdown_pct")),
        "avg_loss_R": metric(loss.get("avg_loss_R")),
        "normal_worst_net_loss_R": metric(loss.get("normal_worst_net_loss_R")),
        "normal_breach_count": int(loss.get("loss_cap_breach_count") or 0),
        "stress_net_return_pct_sum": metric(stress_stats.get("net_return_pct_sum")),
        "stress_profit_factor": metric(stress_stats.get("net_profit_factor")),
        "stress_payoff_ratio": metric(stress_stats.get("payoff_ratio")),
        "stress_max_drawdown_pct": metric(stress_stats.get("max_drawdown_pct")),
        "stress_worst_net_loss_R": metric(stress_loss.get("normal_worst_net_loss_R")),
        "stress_breach_count": int(stress_loss.get("loss_cap_breach_count") or 0),
        "parity_state": parity.get("state"),
        "duplicate_trade_count": int(parity.get("duplicate_trade_count") or 0),
    }


def dominates(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    maximize = ("net_return_pct_sum", "net_profit_factor", "payoff_ratio", "win_rate_pct")
    minimize = ("max_drawdown_pct",)
    not_worse = all(metric(a.get(k)) >= metric(b.get(k)) for k in maximize) and all(metric(a.get(k)) <= metric(b.get(k)) for k in minimize)
    strictly = any(metric(a.get(k)) > metric(b.get(k)) for k in maximize) or any(metric(a.get(k)) < metric(b.get(k)) for k in minimize)
    return not_worse and strictly


def pareto(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(row["variant_id"]) for row in rows if not any(dominates(other, row) for other in rows if other is not row)]


def wait_payload(manifest: Mapping[str, Any], manifest_path: Path) -> dict[str, Any]:
    available = int(manifest.get("available_non_overlap_bars") or 0)
    return {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_id": CAPABILITY,
        "state": "WAIT_DATA",
        "available_non_overlap_bars": available,
        "missing_to_w1_480": max(0, 480 - available),
        "w1_ready": False,
        "stream_manifest_sha256": sha256(manifest_path),
        "required_variants": list(REQUIRED_VARIANTS),
        "same_w1_source_sha_required": True,
        "promotion_authority": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "next": "RETRY_WHEN_STREAM_MANIFEST_REACHES_480",
        "blockers": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--stream-manifest", required=True)
    parser.add_argument("--fresh-root")
    parser.add_argument("--baseline-summary")
    parser.add_argument("--alpha-authority-summary")
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", default="WAIT_DATA_FIXTURE")
    parser.add_argument("--source-head-sha", default="WAIT_DATA_FIXTURE")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    manifest_path = Path(args.stream_manifest).resolve()
    out = Path(args.out).resolve()
    stream_manifest = strict_json(manifest_path)
    available = int(stream_manifest.get("available_non_overlap_bars") or 0)
    if stream_manifest.get("state") != "PASS" or stream_manifest.get("blockers"):
        raise RuntimeError("STREAM_MANIFEST_INTEGRITY_FAIL")
    if int(stream_manifest.get("protected_mutations") or 0) != 0 or stream_manifest.get("order_authority") != "BLOCKED":
        raise RuntimeError("STREAM_SAFETY_INVARIANT_FAIL")
    if available < 480:
        payload = wait_payload(stream_manifest, manifest_path)
        atomic_json(out / "status.json", payload)
        atomic_json(out / "summary.json", payload)
        print(json.dumps(payload, sort_keys=True))
        return 0

    required_args = {
        "fresh_root": args.fresh_root,
        "baseline_summary": args.baseline_summary,
        "alpha_authority_summary": args.alpha_authority_summary,
    }
    missing = [key for key, value in required_args.items() if not value]
    if missing:
        raise RuntimeError("W1_READY_REQUIRED_ARGUMENTS_MISSING:" + ",".join(missing))

    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    authority_path = Path(args.alpha_authority_summary).resolve()
    baseline = strict_json(baseline_path)
    authority = strict_json(authority_path)
    if authority.get("state") != "PASS_MULTIOBJECTIVE_RESEARCH_CANDIDATES":
        raise RuntimeError("ALPHA_AUTHORITY_STATE_INVALID")
    authority_ids = {str(row.get("variant_id")) for row in authority.get("variants", []) if isinstance(row, Mapping)}
    if not set(REQUIRED_VARIANTS).issubset(authority_ids):
        raise RuntimeError("ALPHA_AUTHORITY_VARIANTS_MISSING")
    if authority.get("sealed_holdback_read") is not False or authority.get("promotion_authority") is not False:
        raise RuntimeError("ALPHA_AUTHORITY_SAFETY_INVALID")

    candidate = baseline["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    surgery = p.surgery_from(baseline.get("surgery"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry["alpha_combo"]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, "alpha_combo", registry_row)
    frames, features, funding, fresh_manifest = p.load_fresh_data(fresh_root)
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = cost.v1.market_sha_map(fresh_manifest)

    stop065 = replace(base_exit, exit_id="RR150_STOP065_W1", stop_mult=0.65)
    specs = [
        ("INCUMBENT_CONTROL", base_exit),
        ("STOP065_PROFIT_CONTROL", stop065),
        ("TIME54", replace(stop065, exit_id="RR150_STOP065_TIME54_W1", time_stop_bars=54)),
        ("TIME60", replace(stop065, exit_id="RR150_STOP065_TIME60_W1", time_stop_bars=60)),
    ]
    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in specs:
        print(f"PRIMARY_W1_START variant={variant_id}", flush=True)
        row = cost.evaluate_with_reference_r(
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
            manifest=fresh_manifest,
            market_shas=market_shas,
            strategy_source_sha=strategy_source_sha,
            source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            cap_r=-0.75,
            out=out,
        )
        rows.append(row)
        print(f"PRIMARY_W1_END variant={variant_id}", flush=True)

    metrics = [candidate_metrics(row) for row in rows]
    parity_pass = all(row["parity_state"] == "PASS" and row["duplicate_trade_count"] == 0 for row in metrics)
    loss_pass = all(row["normal_worst_net_loss_R"] >= -0.75 and row["stress_worst_net_loss_R"] >= -0.75 and row["normal_breach_count"] == 0 and row["stress_breach_count"] == 0 for row in metrics[1:])
    frontier = pareto(metrics)
    payload = {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_id": CAPABILITY,
        "state": "PASS_W1_MULTIOBJECTIVE_CONFIRMATION" if parity_pass else "HOLD_PARITY_FAIL",
        "strategy_id": "alpha_combo",
        "required_variants": list(REQUIRED_VARIANTS),
        "pareto_frontier": frontier,
        "variants": metrics,
        "parity_pass": parity_pass,
        "strict_loss_cap_pass_for_research_candidates": loss_pass,
        "same_w1_source_sha_required": True,
        "stream_manifest_sha256": sha256(manifest_path),
        "fresh_manifest_sha256": sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": sha256(baseline_path),
        "alpha_authority_summary_sha256": sha256(authority_path),
        "strategy_source_sha": strategy_source_sha,
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "requires_new_sealed_holdback": True,
        "sealed_holdback_read": False,
        "promotion_authority": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "order_authority": "BLOCKED",
        "next": "W1_NEW_SEALED_HOLDBACK_GENERATOR" if parity_pass else "HOLD",
        "blockers": [] if parity_pass else ["PARITY_FAIL"],
    }
    atomic_json(out / "status.json", payload)
    atomic_json(out / "summary.json", payload)
    print(json.dumps({"state": payload["state"], "pareto_frontier": frontier, "next": payload["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
