from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from backend.tools import r7a4d_strategy11_evidence_pipeline_v1 as evidence
from backend.tools import r7a4d_strategy11_exact as exact
from backend.tools import r7a4d_strategy11_session_bias_prior_range_repair_v1 as session_repair

base = evidence.base
STRATEGY_ID = "session_bias"
VERSION = "R7A4D_STRATEGY11_SESSION_BIAS_W1_REPAIR_ECONOMICS_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "canonical_mutated": False,
    "registry_mutated": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "native_w1_chain_modified": False,
}


def strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def stats(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        [dict(row) for row in trades],
        key=lambda row: (
            str(row.get("entry_ts") or ""),
            str(row.get("symbol") or ""),
            str(row.get("side") or ""),
            str(row.get("exit_ts") or ""),
        ),
    )
    values = [metric(row.get("net_return_pct")) for row in ordered]
    wins = [value for value in values if value > 0.0]
    losses = [value for value in values if value < 0.0]
    cumulative = peak = drawdown = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    gross_loss = abs(sum(losses))
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss_abs = abs(sum(losses) / len(losses)) if losses else 0.0
    r_values: list[float] = []
    for row in ordered:
        risk_pct = metric(row.get("risk_pct"))
        if risk_pct > 1e-12:
            r_values.append(metric(row.get("net_return_pct")) / risk_pct)
    r_losses = [value for value in r_values if value < 0.0]
    r_wins = [value for value in r_values if value > 0.0]
    symbol_net: dict[str, float] = {}
    for row in ordered:
        symbol = str(row.get("symbol") or "UNKNOWN")
        symbol_net[symbol] = symbol_net.get(symbol, 0.0) + metric(row.get("net_return_pct"))
    return {
        "trade_count": len(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0,
        "net_return_pct_sum": sum(values),
        "net_profit_factor": sum(wins) / gross_loss if gross_loss > 1e-12 else (999.0 if wins else 0.0),
        "payoff_ratio": avg_win / avg_loss_abs if avg_loss_abs > 1e-12 else (999.0 if wins else 0.0),
        "max_drawdown_pct": drawdown,
        "average_win_pct": avg_win,
        "average_loss_pct": -avg_loss_abs if losses else 0.0,
        "worst_trade_pct": min(values) if values else 0.0,
        "r_trade_count": len(r_values),
        "avg_win_R": sum(r_wins) / len(r_wins) if r_wins else 0.0,
        "avg_loss_R": sum(r_losses) / len(r_losses) if r_losses else 0.0,
        "worst_net_loss_R": min(r_values) if r_values else 0.0,
        "symbol_trade_breadth": len({str(row.get('symbol') or '') for row in ordered}),
        "positive_symbol_count": sum(1 for value in symbol_net.values() if value > 0.0),
        "symbol_net_return_pct": dict(sorted(symbol_net.items())),
    }


def verify_native(native_root: Path, expected_end: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
    native_status = strict_json(native_root / "native-out" / "status.json")
    shared_status = strict_json(native_root / "shared-w1" / "status.json")
    manifest_path = native_root / "shared-w1" / "data" / "manifest.json"
    manifest = strict_json(manifest_path)
    if native_status.get("state") != "PASS_W1_NATIVE_PRIMARY_CHAIN":
        raise RuntimeError(f"NATIVE_STATE:{native_status.get('state')}")
    if native_status.get("one_shot_completed") is not True:
        raise RuntimeError("NATIVE_ONE_SHOT_INCOMPLETE")
    manifest_sha = file_sha(manifest_path)
    if manifest_sha != native_status.get("source_w1_manifest_sha256"):
        raise RuntimeError("NATIVE_MANIFEST_SHA_STATUS")
    if manifest_sha != shared_status.get("W1_manifest_sha256"):
        raise RuntimeError("SHARED_MANIFEST_SHA_STATUS")
    if manifest.get("state") != "PASS" or manifest.get("blockers") != []:
        raise RuntimeError("W1_MANIFEST_INVALID")
    if manifest.get("window_id") != "W1" or int(manifest.get("evaluation_bars") or 0) != 480:
        raise RuntimeError("W1_WINDOW_CONTRACT")
    if str(manifest.get("evaluation_end")) != expected_end.replace("Z", "+00:00"):
        raise RuntimeError(f"W1_END:{manifest.get('evaluation_end')}")
    if len(manifest.get("files") or []) != 5:
        raise RuntimeError("W1_SYMBOL_PARITY")
    return native_status, manifest, manifest_path


def verify_non_overlap(baseline_manifest_path: Path, w1_manifest: Mapping[str, Any]) -> dict[str, Any]:
    baseline = strict_json(baseline_manifest_path)
    windows = [row for row in baseline.get("windows", []) if isinstance(row, Mapping)]
    if not windows:
        raise RuntimeError("BASELINE_WINDOWS_MISSING")
    baseline_end_ms = max(int(row.get("evaluation_end_ms") or 0) for row in windows)
    w1_start_ms = int(w1_manifest.get("evaluation_start_ms") or 0)
    if baseline_end_ms <= 0 or w1_start_ms <= 0:
        raise RuntimeError("NON_OVERLAP_BOUNDARY_MISSING")
    if w1_start_ms <= baseline_end_ms:
        raise RuntimeError(f"W1_OVERLAP:{w1_start_ms}:{baseline_end_ms}")
    return {
        "baseline_last_evaluation_end_ms": baseline_end_ms,
        "baseline_last_evaluation_end": pd.Timestamp(baseline_end_ms, unit="ms", tz="UTC").isoformat(),
        "w1_evaluation_start_ms": w1_start_ms,
        "w1_evaluation_start": pd.Timestamp(w1_start_ms, unit="ms", tz="UTC").isoformat(),
        "evaluation_non_overlapping": True,
        "gap_bars": (w1_start_ms - baseline_end_ms) // 900_000 - 1,
    }


def load_w1(native_root: Path, manifest: Mapping[str, Any]) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, list[dict[str, Any]]]]:
    source_root = native_root / "shared-w1"
    frames: dict[str, pd.DataFrame] = {}
    features: dict[str, pd.DataFrame] = {}
    for item in manifest["files"]:
        path = source_root / str(item["path"])
        if file_sha(path) != str(item["sha256"]):
            raise RuntimeError(f"MARKET_SHA:{item['symbol']}")
        frame = pd.read_csv(path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
        frame["ts"] = frame["timestamp_ms"]
        symbol = str(item["symbol"])
        frames[symbol] = frame
        features[symbol] = exact.compute_feature_frame(frame)
    funding: dict[str, list[dict[str, Any]]] = {}
    for symbol in frames:
        path = source_root / "data" / "funding" / f"{symbol}.json"
        row = strict_json(path)
        funding[symbol] = [dict(item) for item in row.get("rows", []) if isinstance(item, Mapping)]
    return frames, features, funding


def lineage(trades: Sequence[Mapping[str, Any]], *, variant_id: str, strategy_source_sha: str, manifest_sha: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for ordinal, source in enumerate(trades):
        row = dict(source)
        row["strategy_id"] = STRATEGY_ID
        row["variant_id"] = variant_id
        row["strategy_source_sha"] = strategy_source_sha
        row["source_w1_manifest_sha256"] = manifest_sha
        row["trade_id"] = stable_sha({
            "strategy_id": STRATEGY_ID,
            "variant_id": variant_id,
            "strategy_source_sha": strategy_source_sha,
            "symbol": row.get("symbol"),
            "entry_ts": row.get("entry_ts"),
            "exit_ts": row.get("exit_ts"),
            "side": row.get("side"),
            "ordinal": ordinal,
            "manifest_sha": manifest_sha,
        })
        output.append(row)
    return output


def replay_variant(
    strategy: Callable[..., dict[str, Any]],
    *,
    variant_id: str,
    strategy_source_sha: str,
    frames: Mapping[str, pd.DataFrame],
    features: Mapping[str, pd.DataFrame],
    funding: Mapping[str, list[dict[str, Any]]],
    symbols: Sequence[str],
    gate: Any,
    exit_spec: Any,
    surgery: Any,
    manifest_sha: str,
    cost_bps: float,
    entry_delay_bars: int,
    funding_mode: str,
) -> dict[str, Any]:
    raw: list[dict[str, Any]] = []
    for symbol in symbols:
        result = evidence.replay_evidence(
            frames[symbol],
            features[symbol],
            strategy,
            gate,
            exit_spec,
            surgery,
            window_id="W1",
            symbol=symbol,
            warmup_bars=220,
            history_bars=220,
            cost_bps_per_side=cost_bps,
            entry_delay_bars=entry_delay_bars,
        )
        raw.extend(result["trades"])
    quantiles = evidence.funding_rate_quantiles(funding)
    adjusted = evidence.apply_funding(raw, funding, funding_mode, quantiles)
    trades = lineage(
        adjusted,
        variant_id=variant_id,
        strategy_source_sha=strategy_source_sha,
        manifest_sha=manifest_sha,
    )
    keys = [(row.get("symbol"), row.get("side"), row.get("entry_ts"), row.get("exit_ts")) for row in trades]
    duplicate_count = len(keys) - len(set(keys))
    if duplicate_count:
        raise RuntimeError(f"DUPLICATE_TRADES:{variant_id}:{duplicate_count}")
    return {
        "variant_id": variant_id,
        "strategy_source_sha": strategy_source_sha,
        "metrics": stats(trades),
        "trade_count": len(trades),
        "duplicate_trade_count": duplicate_count,
        "trade_sha256": stable_sha(trades),
        "trades": trades,
    }


def classify(control: Mapping[str, Any], candidate: Mapping[str, Any], stress: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    c = control["metrics"]
    v = candidate["metrics"]
    s = stress["metrics"]
    blockers: list[str] = []
    minimum = 5
    if int(v["trade_count"]) < minimum:
        blockers.append(f"CANDIDATE_TRADES_LT_{minimum}:{v['trade_count']}")
    if int(v["trade_count"]) <= int(c["trade_count"]):
        blockers.append(f"TRADES_NOT_RECOVERED:{v['trade_count']}<={c['trade_count']}")
    if metric(v["net_return_pct_sum"]) <= 0.0:
        blockers.append("CANDIDATE_NET_NOT_POSITIVE")
    if metric(v["net_profit_factor"]) <= 1.0:
        blockers.append("CANDIDATE_PF_NOT_GT_ONE")
    if metric(s["net_return_pct_sum"]) <= 0.0:
        blockers.append("STRESS_NET_NOT_POSITIVE")
    if metric(s["net_profit_factor"]) <= 1.0:
        blockers.append("STRESS_PF_NOT_GT_ONE")
    if metric(v["worst_net_loss_R"], -math.inf) < -0.90:
        blockers.append(f"NORMAL_WORST_R_LT_-0.90:{v['worst_net_loss_R']:.6f}")
    if metric(s["worst_net_loss_R"], -math.inf) < -0.95:
        blockers.append(f"STRESS_WORST_R_LT_-0.95:{s['worst_net_loss_R']:.6f}")
    if int(v["trade_count"]) < minimum:
        state = "HOLD_W1_LOW_SAMPLE"
    elif blockers:
        state = "REJECT_W1_SESSION_BIAS_REPAIR"
    else:
        state = "PASS_W1_SESSION_BIAS_REPAIR_CONFIRMATION"
    return state, blockers, {
        "trade_delta": int(v["trade_count"]) - int(c["trade_count"]),
        "net_delta_pct_points": metric(v["net_return_pct_sum"]) - metric(c["net_return_pct_sum"]),
        "profit_factor_delta": metric(v["net_profit_factor"]) - metric(c["net_profit_factor"]),
        "drawdown_delta_pct_points": metric(v["max_drawdown_pct"]) - metric(c["max_drawdown_pct"]),
        "minimum_fresh_trades": minimum,
        "normal_worst_R_min": -0.90,
        "stress_worst_R_min": -0.95,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compute-root", type=Path, required=True)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--baseline-fresh-manifest", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-w1-end", default="2026-08-01T08:30:00Z")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    compute_root = args.compute_root.resolve()
    native_root = args.native_root.resolve()
    out = args.out.resolve()
    native_status, manifest, manifest_path = verify_native(native_root, args.expected_w1_end)
    manifest_sha = file_sha(manifest_path)
    non_overlap = verify_non_overlap(args.baseline_fresh_manifest.resolve(), manifest)

    summaries = [path for path in args.evidence_root.resolve().rglob("summary.json") if path.parent.name == STRATEGY_ID]
    if len(summaries) != 1:
        raise RuntimeError(f"EVIDENCE_SUMMARY_CARDINALITY:{len(summaries)}:{summaries}")
    baseline = strict_json(summaries[0])
    if baseline.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("EVIDENCE_STRATEGY_ID")
    source_config = dict(baseline["candidate"])
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    if symbols != ("XRPUSDT", "SOLUSDT"):
        raise RuntimeError(f"SOURCE_SYMBOLS:{symbols}")
    gate = exact._gate_from(source_config)
    if gate.required or gate.forbidden:
        raise RuntimeError("EXPECTED_BASE_GATE")
    exit_spec = exact._exit_from(source_config)
    surgery = evidence.surgery_from(baseline.get("surgery"))

    registry = base._load_registry(compute_root)
    registry_row = registry[STRATEGY_ID]
    canonical_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    control_strategy = base._load_canonical_strategy(compute_root, STRATEGY_ID, registry_row)
    candidate_strategy, patch_manifest = session_repair.load_patched_strategy(compute_root, canonical_source_sha)
    patched_source_sha = str(patch_manifest["patched_source_sha"])
    if patch_manifest.get("semantic_change") != "CURRENT_INCLUDED_SESSION_RANGE_TO_PRIOR_SESSION_RANGE":
        raise RuntimeError("PATCH_SEMANTIC_CHANGE")

    frames, features, funding = load_w1(native_root, manifest)
    for symbol in symbols:
        if symbol not in frames or symbol not in features or symbol not in funding:
            raise RuntimeError(f"W1_SYMBOL_MISSING:{symbol}")

    common = {
        "frames": frames,
        "features": features,
        "funding": funding,
        "symbols": symbols,
        "gate": gate,
        "exit_spec": exit_spec,
        "surgery": surgery,
        "manifest_sha": manifest_sha,
    }
    control_a = replay_variant(
        control_strategy,
        variant_id="CONTROL_CURRENT_INCLUDED_SESSION_RANGE",
        strategy_source_sha=canonical_source_sha,
        cost_bps=4.0,
        entry_delay_bars=1,
        funding_mode="OBSERVED",
        **common,
    )
    control_b = replay_variant(
        control_strategy,
        variant_id="CONTROL_CURRENT_INCLUDED_SESSION_RANGE",
        strategy_source_sha=canonical_source_sha,
        cost_bps=4.0,
        entry_delay_bars=1,
        funding_mode="OBSERVED",
        **common,
    )
    candidate_a = replay_variant(
        candidate_strategy,
        variant_id="PRIOR_SESSION_RANGE_REPAIR",
        strategy_source_sha=patched_source_sha,
        cost_bps=4.0,
        entry_delay_bars=1,
        funding_mode="OBSERVED",
        **common,
    )
    candidate_b = replay_variant(
        candidate_strategy,
        variant_id="PRIOR_SESSION_RANGE_REPAIR",
        strategy_source_sha=patched_source_sha,
        cost_bps=4.0,
        entry_delay_bars=1,
        funding_mode="OBSERVED",
        **common,
    )
    control_parity = stable_sha(control_a) == stable_sha(control_b)
    candidate_parity = stable_sha(candidate_a) == stable_sha(candidate_b)
    if not control_parity:
        raise RuntimeError("CONTROL_AB_PARITY")
    if not candidate_parity:
        raise RuntimeError("CANDIDATE_AB_PARITY")
    stress = replay_variant(
        candidate_strategy,
        variant_id="PRIOR_SESSION_RANGE_REPAIR__STRESS",
        strategy_source_sha=patched_source_sha,
        cost_bps=8.0,
        entry_delay_bars=2,
        funding_mode="ADVERSE_P95",
        **common,
    )

    state, blockers, relation = classify(control_a, candidate_a, stress)
    result = {
        "schema_version": "strategy11.session_bias_w1_repair_economics.v1",
        "version": VERSION,
        "state": state,
        "blockers": blockers,
        "strategy_id": STRATEGY_ID,
        "source_w1_run_id": native_status.get("source_w1_run_id"),
        "source_w1_manifest_sha256": manifest_sha,
        "source_w1_evaluation_start": manifest.get("evaluation_start"),
        "source_w1_evaluation_end": manifest.get("evaluation_end"),
        "baseline_fresh_manifest_sha256": file_sha(args.baseline_fresh_manifest.resolve()),
        "non_overlap": non_overlap,
        "symbols": list(symbols),
        "gate_id": str(getattr(gate, "gate_id", "BASE")),
        "exit_id": str(getattr(exit_spec, "exit_id", "ORIG")),
        "canonical_source_sha": canonical_source_sha,
        "patched_source_sha": patched_source_sha,
        "repair": patch_manifest,
        "control": {
            "metrics": control_a["metrics"],
            "trade_sha256": control_a["trade_sha256"],
            "duplicate_trade_count": control_a["duplicate_trade_count"],
        },
        "candidate": {
            "metrics": candidate_a["metrics"],
            "trade_sha256": candidate_a["trade_sha256"],
            "duplicate_trade_count": candidate_a["duplicate_trade_count"],
        },
        "stress": {
            "metrics": stress["metrics"],
            "trade_sha256": stress["trade_sha256"],
            "duplicate_trade_count": stress["duplicate_trade_count"],
            "cost_bps_per_side": 8.0,
            "entry_delay_bars": 2,
            "funding_mode": "ADVERSE_P95",
        },
        "normal_contract": {
            "cost_bps_per_side": 4.0,
            "entry_delay_bars": 1,
            "funding_mode": "OBSERVED",
        },
        "a_b_parity": "PASS" if control_parity and candidate_parity else "FAIL",
        "relation": relation,
        "canonical_source_modified": False,
        "registry_modified": False,
        "new_sealed_required": True,
        "next": (
            "NEW_SEALED_CONFIRMATION_REQUIRED" if state == "PASS_W1_SESSION_BIAS_REPAIR_CONFIRMATION"
            else "RETAIN_RESEARCH_HOLD"
        ),
        **SAFETY,
    }
    result["result_sha256"] = stable_sha(result)
    write_json(out / "status.json", result)
    write_json(out / "control-trades.json", {"strategy_id": STRATEGY_ID, "trades": control_a["trades"]})
    write_json(out / "candidate-trades.json", {"strategy_id": STRATEGY_ID, "trades": candidate_a["trades"]})
    write_json(out / "stress-trades.json", {"strategy_id": STRATEGY_ID, "trades": stress["trades"]})
    print(json.dumps({
        "state": state,
        "control_trades": control_a["trade_count"],
        "candidate_trades": candidate_a["trade_count"],
        "candidate_net": candidate_a["metrics"]["net_return_pct_sum"],
        "candidate_pf": candidate_a["metrics"]["net_profit_factor"],
        "stress_net": stress["metrics"]["net_return_pct_sum"],
        "stress_pf": stress["metrics"]["net_profit_factor"],
        "blockers": blockers,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
