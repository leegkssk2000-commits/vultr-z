from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from backend.tools import r7a4d_strategy11_evidence_pipeline_v1 as evidence
from backend.tools import r7a4d_strategy11_exact as exact

base = evidence.base
VERSION = "R7A4D_STRATEGY11_V3_SURVIVOR_W1_OVERLAY_V1"
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
            str(row.get("window_id") or ""),
            str(row.get("entry_ts") or ""),
            str(row.get("symbol") or ""),
            str(row.get("side") or ""),
        ),
    )
    values = [metric(row.get("net_return_pct")) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    cumulative = peak = drawdown = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    gross_loss = abs(sum(losses))
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    return {
        "trade_count": len(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0,
        "net_return_pct_sum": sum(values),
        "net_profit_factor": sum(wins) / gross_loss if gross_loss > 1e-12 else (999.0 if wins else 0.0),
        "payoff_ratio": avg_win / avg_loss if avg_loss > 1e-12 else 0.0,
        "max_drawdown_pct": drawdown,
        "average_win_pct": avg_win,
        "average_loss_pct": -avg_loss if losses else 0.0,
        "worst_trade_pct": min(values) if values else 0.0,
    }


def locate_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.rglob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"FILE_CARDINALITY:{pattern}:{len(matches)}")
    return matches[0]


def load_strategy_module(compute_root: Path, strategy_id: str) -> tuple[Any, dict[str, Any], str]:
    registry = base._load_registry(compute_root)
    entry = dict(registry[strategy_id])
    engine = dict(entry["canonical_engine"])
    source_path = compute_root / str(engine["implementation_path"])
    source_sha = file_sha(source_path)
    if source_sha != str(engine["source_sha256"]):
        raise RuntimeError(f"CANONICAL_SOURCE_SHA:{source_sha}:{engine['source_sha256']}")
    name = f"s11_w1_overlay_{strategy_id}_{source_sha[:12]}"
    spec = importlib.util.spec_from_file_location(name, source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("STRATEGY_MODULE_SPEC")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "strategy", None)):
        raise RuntimeError("STRATEGY_CALLABLE_MISSING")
    return module, entry, source_sha


def verify_native(native_root: Path, contract: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], Path]:
    native_status = strict_json(native_root / "native-out" / "status.json")
    shared_status = strict_json(native_root / "shared-w1" / "status.json")
    manifest_path = native_root / "shared-w1" / "data" / "manifest.json"
    manifest = strict_json(manifest_path)
    expected = contract["upstream"]
    if native_status.get("state") != expected["native_required_state"]:
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
    if str(manifest.get("evaluation_end")) != expected["w1_exact_end_utc"].replace("Z", "+00:00"):
        raise RuntimeError(f"W1_END:{manifest.get('evaluation_end')}")
    if len(manifest.get("files") or []) != 5:
        raise RuntimeError("W1_SYMBOL_PARITY")
    return native_status, manifest, manifest_path


def verify_discovery(discovery_root: Path, contract: Mapping[str, Any], source_sha: str) -> dict[str, Any]:
    result_path = locate_one(discovery_root, "result.json")
    result = strict_json(result_path)
    candidate_contract = contract["candidate"]
    if result.get("strategy_id") != candidate_contract["strategy_id"]:
        raise RuntimeError("DISCOVERY_STRATEGY")
    if result.get("source_sha256") != source_sha:
        raise RuntimeError(f"DISCOVERY_SOURCE_SHA:{result.get('source_sha256')}:{source_sha}")
    variants = [row for row in result.get("variants", []) if isinstance(row, Mapping)]
    matches = [row for row in variants if row.get("variant_id") == candidate_contract["variant_id"]]
    if len(matches) != 1:
        raise RuntimeError("DISCOVERY_VARIANT_CARDINALITY")
    survivor = dict(matches[0])
    spec = dict(survivor.get("candidate_spec") or {})
    for key in ("candidate_spec_sha256", "field", "base_value", "mutation_value"):
        expected = candidate_contract[key]
        actual = spec.get(key) if key != "candidate_spec_sha256" else survivor.get(key)
        if actual != expected:
            raise RuntimeError(f"DISCOVERY_SPEC:{key}:{actual}:{expected}")
    if survivor.get("research_state") != "DISCOVERY_PASS_INTERNAL_OR_REGIME":
        raise RuntimeError("DISCOVERY_NOT_PASS")
    return survivor


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


def trade_lineage(trades: Sequence[Mapping[str, Any]], *, variant_id: str, manifest_sha: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for ordinal, source in enumerate(trades):
        row = dict(source)
        row["strategy_id"] = "trend_ma_macd"
        row["variant_id"] = variant_id
        row["source_w1_manifest_sha256"] = manifest_sha
        row["trade_id"] = stable_sha({
            "variant_id": variant_id,
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
    trades = trade_lineage(adjusted, variant_id=variant_id, manifest_sha=manifest_sha)
    keys = [(row.get("symbol"), row.get("side"), row.get("entry_ts"), row.get("exit_ts")) for row in trades]
    duplicate_count = len(keys) - len(set(keys))
    if duplicate_count:
        raise RuntimeError(f"DUPLICATE_TRADES:{variant_id}:{duplicate_count}")
    return {
        "variant_id": variant_id,
        "metrics": stats(trades),
        "trade_count": len(trades),
        "duplicate_trade_count": duplicate_count,
        "trade_sha256": stable_sha(trades),
        "trades": trades,
    }


def classify(control: Mapping[str, Any], candidate: Mapping[str, Any], stress: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    c = control["metrics"]
    v = candidate["metrics"]
    s = stress["metrics"]
    evaluation = policy["evaluation"]
    blockers: list[str] = []
    minimum = int(evaluation["minimum_fresh_trades"])
    if int(v["trade_count"]) < minimum:
        blockers.append(f"CANDIDATE_TRADES_LT_{minimum}:{v['trade_count']}")
    if int(c["trade_count"]) > 0:
        retention = int(v["trade_count"]) / int(c["trade_count"])
    else:
        retention = 1.0 if int(v["trade_count"]) > 0 else 0.0
    if retention < float(evaluation["retention_min"]):
        blockers.append(f"RETENTION:{retention:.6f}")
    deltas = {
        "net_return_pct_sum": metric(v["net_return_pct_sum"]) - metric(c["net_return_pct_sum"]),
        "net_profit_factor": metric(v["net_profit_factor"]) - metric(c["net_profit_factor"]),
        "payoff_ratio": metric(v["payoff_ratio"]) - metric(c["payoff_ratio"]),
        "max_drawdown_pct_reduction": metric(c["max_drawdown_pct"]) - metric(v["max_drawdown_pct"]),
        "worst_trade_pct_improvement": metric(v["worst_trade_pct"]) - metric(c["worst_trade_pct"]),
    }
    flags = {
        "net": deltas["net_return_pct_sum"] >= float(evaluation["net_delta_pct_points_min"]),
        "pf": deltas["net_profit_factor"] >= float(evaluation["profit_factor_delta_min"]),
        "payoff": deltas["payoff_ratio"] >= float(evaluation["payoff_delta_min"]),
        "dd": deltas["max_drawdown_pct_reduction"] >= 0.1,
    }
    improved_count = sum(flags.values())
    if improved_count < int(evaluation["material_metrics_min"]):
        blockers.append(f"MATERIAL_METRICS:{improved_count}")
    if metric(v["max_drawdown_pct"]) - metric(c["max_drawdown_pct"]) > float(evaluation["drawdown_worsening_max_pct_points"]):
        blockers.append("DD_WORSENING")
    if metric(v["net_return_pct_sum"]) <= 0:
        blockers.append("CANDIDATE_NET_NOT_POSITIVE")
    if metric(v["net_profit_factor"]) <= 1:
        blockers.append("CANDIDATE_PF_NOT_GT_ONE")
    if metric(s["net_return_pct_sum"]) <= 0:
        blockers.append("STRESS_NET_NOT_POSITIVE")
    if metric(s["net_profit_factor"]) <= 1:
        blockers.append("STRESS_PF_NOT_GT_ONE")
    if int(v["trade_count"]) < minimum:
        state = "HOLD_W1_LOW_SAMPLE"
    elif blockers:
        state = "REJECT_W1_V3_SURVIVOR"
    else:
        state = "PASS_W1_V3_SURVIVOR_CONFIRMATION"
    return state, blockers, {
        "retention": retention,
        "deltas": deltas,
        "flags": flags,
        "improved_count": improved_count,
    }


def run(args: argparse.Namespace) -> int:
    contract = strict_json(Path(args.contract).resolve())
    native_root = Path(args.native_root).resolve()
    compute_root = Path(args.compute_root).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    discovery_root = Path(args.discovery_root).resolve()
    out = Path(args.out).resolve()
    native_status, manifest, manifest_path = verify_native(native_root, contract)
    manifest_sha = file_sha(manifest_path)
    strategy_id = str(contract["candidate"]["strategy_id"])
    module, registry_entry, source_sha = load_strategy_module(compute_root, strategy_id)
    survivor = verify_discovery(discovery_root, contract, source_sha)
    summary_path = locate_one(evidence_root, "summary.json")
    summary = strict_json(summary_path)
    if summary.get("strategy_id") != strategy_id:
        raise RuntimeError("EVIDENCE_STRATEGY")
    symbols = tuple(str(value) for value in summary.get("symbols", []))
    frames, features, funding = load_w1(native_root, manifest)
    if not symbols or any(symbol not in frames for symbol in symbols):
        raise RuntimeError(f"EVIDENCE_SYMBOLS:{symbols}")
    candidate_cfg = module.TrendMaMacdConfig()
    if metric(candidate_cfg.max_chase_dist_atr) != metric(contract["candidate"]["base_value"]):
        raise RuntimeError("CANDIDATE_BASE_CONFIG")
    candidate_cfg = dataclasses.replace(candidate_cfg, max_chase_dist_atr=float(contract["candidate"]["mutation_value"]))
    control_strategy = module.strategy

    def candidate_strategy(frame: pd.DataFrame, *, state: Mapping[str, Any] | None = None, risk_action: str = "hold") -> dict[str, Any]:
        return module.strategy(frame, state=dict(state or {}), risk_action=risk_action, config=candidate_cfg)

    candidate = summary.get("candidate") if isinstance(summary.get("candidate"), Mapping) else {}
    gate = exact._gate_from(candidate)
    exit_spec = exact._exit_from(candidate)
    surgery = evidence.surgery_from(summary.get("surgery") if isinstance(summary.get("surgery"), Mapping) else None)
    cost = float(contract["evaluation"]["normal_cost_bps_per_side"])
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
    control_a = replay_variant(control_strategy, variant_id="NO_CHANGE_CONTROL", cost_bps=cost, entry_delay_bars=1, funding_mode="OBSERVED", **common)
    control_b = replay_variant(control_strategy, variant_id="NO_CHANGE_CONTROL", cost_bps=cost, entry_delay_bars=1, funding_mode="OBSERVED", **common)
    candidate_a = replay_variant(candidate_strategy, variant_id=contract["candidate"]["variant_id"], cost_bps=cost, entry_delay_bars=1, funding_mode="OBSERVED", **common)
    candidate_b = replay_variant(candidate_strategy, variant_id=contract["candidate"]["variant_id"], cost_bps=cost, entry_delay_bars=1, funding_mode="OBSERVED", **common)
    if stable_sha(control_a) != stable_sha(control_b):
        raise RuntimeError("CONTROL_AB_PARITY")
    if stable_sha(candidate_a) != stable_sha(candidate_b):
        raise RuntimeError("CANDIDATE_AB_PARITY")
    stress = replay_variant(
        candidate_strategy,
        variant_id=f"{contract['candidate']['variant_id']}__STRESS",
        cost_bps=cost * float(contract["evaluation"]["stress_cost_multiplier"]),
        entry_delay_bars=int(contract["evaluation"]["stress_entry_delay_bars"]),
        funding_mode=str(contract["evaluation"]["stress_funding_mode"]),
        **common,
    )
    state, blockers, comparison = classify(control_a, candidate_a, stress, contract)
    result = {
        "schema_version": "strategy11.v3_survivor_w1_overlay.v1",
        "version": VERSION,
        "state": state,
        "blockers": blockers,
        "strategy_id": strategy_id,
        "variant_id": contract["candidate"]["variant_id"],
        "source_w1_run_id": native_status["source_w1_run_id"],
        "source_w1_head_sha": native_status["source_w1_head_sha"],
        "source_w1_manifest_sha256": manifest_sha,
        "w1_evaluation_start": manifest["evaluation_start"],
        "w1_evaluation_end": manifest["evaluation_end"],
        "canonical_source_path": registry_entry["canonical_engine"]["implementation_path"],
        "canonical_source_sha256": source_sha,
        "candidate_spec": contract["candidate"],
        "discovery_evidence": {
            "research_state": survivor["research_state"],
            "trade_count": survivor["trade_count"],
            "net_return_pct_sum": survivor["net_return_pct_sum"],
            "net_profit_factor": survivor["net_profit_factor"],
            "max_drawdown_pct": survivor["max_drawdown_pct"],
            "candidate_spec_sha256": survivor["candidate_spec_sha256"],
        },
        "control": {key: value for key, value in control_a.items() if key != "trades"},
        "candidate": {key: value for key, value in candidate_a.items() if key != "trades"},
        "stress": {key: value for key, value in stress.items() if key != "trades"},
        "comparison": comparison,
        "a_b_parity": "PASS",
        "duplicate_trade_count": 0,
        "fresh_confirmation_only": True,
        "next": "W2_SURVIVOR_CONFIRMATION" if state == "PASS_W1_V3_SURVIVOR_CONFIRMATION" else "ARCHIVE_OR_WAIT_NEW_FINGERPRINT",
        **SAFETY,
    }
    result["result_sha256"] = stable_sha(result)
    write_json(out / "status.json", result)
    write_json(out / "lineage.json", {
        "source_w1_manifest_sha256": manifest_sha,
        "source_w1_status_sha256": file_sha(native_root / "shared-w1" / "status.json"),
        "native_status_sha256": file_sha(native_root / "native-out" / "status.json"),
        "canonical_source_sha256": source_sha,
        "candidate_spec_sha256": contract["candidate"]["candidate_spec_sha256"],
        "control_trade_sha256": control_a["trade_sha256"],
        "candidate_trade_sha256": candidate_a["trade_sha256"],
        "stress_trade_sha256": stress["trade_sha256"],
        "result_sha256": result["result_sha256"],
    })
    write_json(out / "control_trades.json", {"trades": control_a["trades"]})
    write_json(out / "candidate_trades.json", {"trades": candidate_a["trades"]})
    write_json(out / "stress_trades.json", {"trades": stress["trades"]})
    print(json.dumps({
        "state": state,
        "blockers": blockers,
        "control": control_a["metrics"],
        "candidate": candidate_a["metrics"],
        "stress": stress["metrics"],
        "sha": result["result_sha256"],
    }, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--native-root", required=True)
    parser.add_argument("--compute-root", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--discovery-root", required=True)
    parser.add_argument("--out", required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
