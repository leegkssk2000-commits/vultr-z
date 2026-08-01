from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

VERSION = "ZEL_ALPHA_COMBO_VALIDATION_CHAIN_V1"
VARIANTS = (
    "INCUMBENT_CONTROL",
    "TIME54",
    "TIME60",
    "TIME60_TRAIL100_ATR150",
    "TIME60_TRAIL100_ATR200",
    "TIME60_TRAIL125_ATR150",
)


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def load_alpha(alpha_root: Path) -> Any:
    path = alpha_root / "backend/tools/r7a4d_strategy11_alpha_primary_w1_multiobjective_v1.py"
    if not path.is_file():
        raise RuntimeError(f"ALPHA_RUNNER_MISSING:{path}")
    sys.path.insert(0, str(alpha_root))
    name = "zel_alpha_primary_for_validation_chain"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ALPHA_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def frame_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise RuntimeError(f"FRAME_COLUMNS:{path}")
    frame = frame.sort_values("timestamp_ms").drop_duplicates("timestamp_ms").reset_index(drop=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    frame["ts"] = frame["timestamp_ms"]
    return frame


def load_funding(root: Path, symbols: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        path = root / "funding" / f"{symbol}.json"
        payload = read_json(path)
        rows = [dict(row) for row in payload.get("rows", []) if isinstance(row, Mapping)]
        result[str(symbol)] = rows
    return result


def build_specs(alpha: Any, baseline: Mapping[str, Any], *, interval: str) -> dict[str, Any]:
    base_exit = alpha.multi.exact._exit_from(baseline["candidate"])
    factor = 15 if interval == "1m" else 1
    stop065 = replace(base_exit, exit_id=f"RR150_STOP065_{interval}", stop_mult=0.65)
    time54 = replace(stop065, exit_id=f"RR150_STOP065_TIME54_{interval}", time_stop_bars=54 * factor)
    time60 = replace(stop065, exit_id=f"RR150_STOP065_TIME60_{interval}", time_stop_bars=60 * factor)
    return {
        "INCUMBENT_CONTROL": base_exit,
        "TIME54": time54,
        "TIME60": time60,
        "TIME60_TRAIL100_ATR150": replace(
            time60,
            exit_id=f"RR150_STOP065_TIME60_TRAIL100_ATR150_{interval}",
            trail_activate_r=1.0,
            trail_atr_mult=1.5,
        ),
        "TIME60_TRAIL100_ATR200": replace(
            time60,
            exit_id=f"RR150_STOP065_TIME60_TRAIL100_ATR200_{interval}",
            trail_activate_r=1.0,
            trail_atr_mult=2.0,
        ),
        "TIME60_TRAIL125_ATR150": replace(
            time60,
            exit_id=f"RR150_STOP065_TIME60_TRAIL125_ATR150_{interval}",
            trail_activate_r=1.25,
            trail_atr_mult=1.5,
        ),
    }


def trade_hash(row: Mapping[str, Any], variant_id: str, interval: str, window_id: str) -> str:
    return stable_sha({
        "variant_id": variant_id,
        "interval": interval,
        "window_id": window_id,
        "symbol": row.get("symbol"),
        "entry_ts": row.get("entry_ts"),
        "exit_ts": row.get("exit_ts"),
        "side": row.get("side"),
    })


def replay_one(
    *,
    alpha: Any,
    strategy: Any,
    gate: Any,
    surgery: Any,
    exit_spec: Any,
    frame: pd.DataFrame,
    funding: Mapping[str, list[dict[str, Any]]],
    symbol: str,
    interval: str,
    window_id: str,
    variant_id: str,
    warmup_bars: int,
    stress: bool,
) -> list[dict[str, Any]]:
    features = alpha.multi.exact.compute_feature_frame(frame)
    raw = alpha.multi.p.replay_evidence(
        frame,
        features,
        strategy,
        gate,
        exit_spec,
        surgery,
        window_id=window_id,
        symbol=symbol,
        warmup_bars=warmup_bars,
        history_bars=220,
        cost_bps_per_side=12.0 if stress else 6.0,
        entry_delay_bars=2 if stress else 1,
    )["trades"]
    quantiles = alpha.multi.p.funding_rate_quantiles(funding)
    rows = alpha.multi.p.apply_funding(
        raw,
        funding,
        "ADVERSE_P95" if stress else "OBSERVED",
        quantiles,
    )
    output: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        row["data_interval"] = interval
        row["window_id"] = window_id
        row["variant_id"] = variant_id
        row["trade_id"] = trade_hash(row, variant_id, interval, window_id)
        output.append(row)
    return output


def ledger_sha(rows: Sequence[Mapping[str, Any]]) -> str:
    keep = [
        {
            "trade_id": row.get("trade_id"),
            "net_return_pct": row.get("net_return_pct"),
            "entry_ts": row.get("entry_ts"),
            "exit_ts": row.get("exit_ts"),
        }
        for row in sorted(rows, key=lambda item: str(item.get("trade_id")))
    ]
    return stable_sha(keep)


def variant_metrics(alpha: Any, rows: Sequence[Mapping[str, Any]], stress: Sequence[Mapping[str, Any]], stop_mult: float) -> dict[str, Any]:
    stats = alpha.multi.p.combine_stats(list(rows))
    stress_stats = alpha.multi.p.combine_stats(list(stress))
    loss = alpha.reference_loss_metrics(rows, stop_mult, -0.75)
    stress_loss = alpha.reference_loss_metrics(stress, stop_mult, -0.75)
    windows = sorted({f"{row.get('data_interval')}:{row.get('window_id')}" for row in rows})
    per_window: dict[str, Any] = {}
    positive = 0
    for window in windows:
        interval, window_id = window.split(":", 1)
        subset = [row for row in rows if str(row.get("data_interval")) == interval and str(row.get("window_id")) == window_id]
        stat = alpha.multi.p.combine_stats(subset)
        per_window[window] = stat
        positive += int(metric(stat.get("net_return_pct_sum")) > 0.0)
    return {
        **stats,
        "trade_count": len(rows),
        "loss_metrics": loss,
        "stress": {**stress_stats, "trade_count": len(stress), "loss_metrics": stress_loss},
        "window_count": len(windows),
        "positive_window_count": positive,
        "positive_windows_pct": positive / max(1, len(windows)) * 100.0,
        "window_stats": per_window,
    }


def gate_candidate(candidate: Mapping[str, Any], incumbent: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
    minimum = 100 if mode == "data-b" else 5
    retention = int(candidate.get("trade_count") or 0) / max(1, int(incumbent.get("trade_count") or 0)) * 100.0
    deltas = {
        "net": metric(candidate.get("net_return_pct_sum")) - metric(incumbent.get("net_return_pct_sum")),
        "pf": metric(candidate.get("net_profit_factor")) - metric(incumbent.get("net_profit_factor")),
        "payoff": metric(candidate.get("payoff_ratio")) - metric(incumbent.get("payoff_ratio")),
        "win_rate": metric(candidate.get("win_rate_pct")) - metric(incumbent.get("win_rate_pct")),
        "drawdown": metric(candidate.get("max_drawdown_pct"), math.inf) - metric(incumbent.get("max_drawdown_pct"), math.inf),
    }
    improved = sum(deltas[key] > 0.0 for key in ("net", "pf", "payoff", "win_rate"))
    loss = candidate.get("loss_metrics") or {}
    stress_loss = (candidate.get("stress") or {}).get("loss_metrics") or {}
    required_window_pct = 50.0 if mode == "forward" else 50.0
    checks = {
        "sample": int(candidate.get("trade_count") or 0) >= minimum,
        "retention": retention >= 70.0,
        "normal_loss_cap": metric(loss.get("normal_worst_net_loss_R"), -math.inf) >= -0.75 and int(loss.get("loss_cap_breach_count") or 0) == 0,
        "stress_loss_cap": metric(stress_loss.get("normal_worst_net_loss_R"), -math.inf) >= -0.75 and int(stress_loss.get("loss_cap_breach_count") or 0) == 0,
        "positive_windows": metric(candidate.get("positive_windows_pct")) >= required_window_pct,
        "net_improved": deltas["net"] > 0.0,
        "pf_improved": deltas["pf"] > 0.0,
        "drawdown_nonworse": deltas["drawdown"] <= 0.0,
        "multi_metric": improved >= 3,
    }
    return {"pass": all(checks.values()), "checks": checks, "deltas": deltas, "trade_retention_pct": retention}


def load_authorities(alpha: Any, alpha_root: Path, baseline_path: Path, authority_root: Path) -> tuple[dict[str, Any], Any, Any, Any, tuple[str, ...]]:
    baseline = read_json(baseline_path)
    authority = read_json(authority_root / "summary.json")
    if baseline.get("strategy_id") != "alpha_combo":
        raise RuntimeError("BASELINE_NOT_ALPHA")
    if authority.get("state") != "PASS_MULTIOBJECTIVE_RESEARCH_CANDIDATES":
        raise RuntimeError("ALPHA_AUTHORITY_NOT_PASS")
    if authority.get("promotion_authority") is not False or authority.get("sealed_holdback_read") is not False:
        raise RuntimeError("ALPHA_AUTHORITY_UNSAFE")
    candidate = baseline["candidate"]
    gate = alpha.multi.exact._gate_from(candidate)
    surgery = alpha.multi.p.surgery_from(baseline.get("surgery"))
    registry = alpha.multi.base._load_registry(alpha_root)
    strategy = alpha.multi.base._load_canonical_strategy(alpha_root, "alpha_combo", registry["alpha_combo"])
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    return baseline, strategy, gate, surgery, symbols


def run_data_b(args: argparse.Namespace, alpha: Any, baseline: Mapping[str, Any], strategy: Any, gate: Any, surgery: Any, symbols: Sequence[str]) -> dict[str, Any]:
    data_root = Path(args.data_root).resolve()
    manifest = read_json(data_root / "manifest.json")
    if manifest.get("state") != "PASS_HISTORICAL_OOS_DATA_READY" or manifest.get("forward_overlap_count") != 0:
        raise RuntimeError("DATA_B_AUTHORITY_INVALID")
    funding = load_funding(data_root, symbols)
    files = [row for row in manifest.get("files", []) if isinstance(row, Mapping) and row.get("kind") == "market"]
    if {str(row.get("interval")) for row in files} != {"15m", "1m"}:
        raise RuntimeError("DATA_B_INTERVAL_COVERAGE_INCOMPLETE")

    variants: dict[str, dict[str, Any]] = {}
    for variant_id in VARIANTS:
        normal_a: list[dict[str, Any]] = []
        normal_b: list[dict[str, Any]] = []
        stress: list[dict[str, Any]] = []
        stop_mult = 1.0
        for file_row in files:
            symbol = str(file_row["symbol"])
            if symbol not in symbols:
                continue
            interval = str(file_row["interval"])
            window_id = str(file_row["window_id"])
            frame = frame_csv(data_root / str(file_row["path"]))
            spec = build_specs(alpha, baseline, interval=interval)[variant_id]
            stop_mult = float(spec.stop_mult)
            kwargs = dict(
                alpha=alpha,
                strategy=strategy,
                gate=gate,
                surgery=surgery,
                exit_spec=spec,
                frame=frame,
                funding=funding,
                symbol=symbol,
                interval=interval,
                window_id=window_id,
                variant_id=variant_id,
                warmup_bars=240,
            )
            normal_a.extend(replay_one(**kwargs, stress=False))
            normal_b.extend(replay_one(**kwargs, stress=False))
            stress.extend(replay_one(**kwargs, stress=True))
        metrics = variant_metrics(alpha, normal_a, stress, stop_mult)
        parity = ledger_sha(normal_a) == ledger_sha(normal_b)
        duplicates = len(normal_a) - len({str(row.get("trade_id")) for row in normal_a})
        metrics["parity"] = {"state": "PASS" if parity and duplicates == 0 else "HOLD", "duplicate_trade_count": duplicates}
        metrics["variant_id"] = variant_id
        variants[variant_id] = metrics
        write_json(Path(args.out) / "variants" / f"{variant_id}.json", metrics)

    incumbent = variants["INCUMBENT_CONTROL"]
    for variant_id, row in variants.items():
        if variant_id == "INCUMBENT_CONTROL":
            continue
        row["gate"] = gate_candidate(row, incumbent, mode="data-b")
    eligible = [row for key, row in variants.items() if key != "INCUMBENT_CONTROL" and row.get("gate", {}).get("pass") and row.get("parity", {}).get("state") == "PASS"]
    eligible.sort(key=lambda row: (metric(row.get("net_return_pct_sum")), metric(row.get("net_profit_factor")), -metric(row.get("max_drawdown_pct"), math.inf)), reverse=True)
    active = [str(row["variant_id"]) for row in eligible[:2]]
    return {
        "schema_version": "zel.alpha_combo.validation.v1",
        "version": VERSION,
        "mode": "DATA_B_MULTI_TIMEFRAME",
        "state": "PASS_DATA_B_ALPHA_CANDIDATE" if active else "HOLD_NO_DATA_B_ALPHA_CANDIDATE",
        "strategy_id": "alpha_combo",
        "active_candidate_queue": active,
        "variants": list(variants.values()),
        "data_manifest_sha256": hashlib.sha256((data_root / "manifest.json").read_bytes()).hexdigest(),
        "canonical_strategy_files_mutated": False,
        "canonical_registry_mutated": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
        "next": "W2_NEW_FORWARD_COLLECTION" if active else "ALPHA_NEW_CAUSAL_AXIS_OR_RETAIN_CONTROLS",
    }


def run_forward(args: argparse.Namespace, alpha: Any, baseline: Mapping[str, Any], strategy: Any, gate: Any, surgery: Any, symbols: Sequence[str]) -> dict[str, Any]:
    source_root = Path(args.source_root).resolve()
    status = read_json(source_root / "status.json")
    manifest = read_json(source_root / "data" / "manifest.json")
    stage = str(args.stage)
    if status.get("state") != "PASS" or manifest.get("state") != "PASS" or manifest.get("window_id") != stage:
        raise RuntimeError("FORWARD_SOURCE_INVALID")
    funding = load_funding(source_root / "data", symbols)
    files = [row for row in manifest.get("files", []) if isinstance(row, Mapping)]
    variants: dict[str, dict[str, Any]] = {}
    for variant_id in VARIANTS:
        normal_a: list[dict[str, Any]] = []
        normal_b: list[dict[str, Any]] = []
        stress: list[dict[str, Any]] = []
        stop_mult = 1.0
        for file_row in files:
            symbol = str(file_row["symbol"])
            if symbol not in symbols:
                continue
            frame = frame_csv(source_root / str(file_row["path"]))
            spec = build_specs(alpha, baseline, interval="15m")[variant_id]
            stop_mult = float(spec.stop_mult)
            kwargs = dict(
                alpha=alpha,
                strategy=strategy,
                gate=gate,
                surgery=surgery,
                exit_spec=spec,
                frame=frame,
                funding=funding,
                symbol=symbol,
                interval="15m",
                window_id=stage,
                variant_id=variant_id,
                warmup_bars=int(manifest["warmup_bars"]),
            )
            normal_a.extend(replay_one(**kwargs, stress=False))
            normal_b.extend(replay_one(**kwargs, stress=False))
            stress.extend(replay_one(**kwargs, stress=True))
        metrics = variant_metrics(alpha, normal_a, stress, stop_mult)
        parity = ledger_sha(normal_a) == ledger_sha(normal_b)
        duplicates = len(normal_a) - len({str(row.get("trade_id")) for row in normal_a})
        metrics["parity"] = {"state": "PASS" if parity and duplicates == 0 else "HOLD", "duplicate_trade_count": duplicates}
        metrics["variant_id"] = variant_id
        variants[variant_id] = metrics
        write_json(Path(args.out) / "variants" / f"{variant_id}.json", metrics)

    incumbent = variants["INCUMBENT_CONTROL"]
    for variant_id, row in variants.items():
        if variant_id == "INCUMBENT_CONTROL":
            continue
        row["gate"] = gate_candidate(row, incumbent, mode="forward")
    eligible = [row for key, row in variants.items() if key != "INCUMBENT_CONTROL" and row.get("gate", {}).get("pass") and row.get("parity", {}).get("state") == "PASS"]
    eligible.sort(key=lambda row: (metric(row.get("net_return_pct_sum")), metric(row.get("net_profit_factor")), -metric(row.get("max_drawdown_pct"), math.inf)), reverse=True)
    active = [str(row["variant_id"]) for row in eligible[:2]]
    return {
        "schema_version": "zel.alpha_combo.validation.v1",
        "version": VERSION,
        "mode": f"{stage}_NEW_FORWARD",
        "state": f"PASS_{stage}_ALPHA_CONFIRMATION" if active else f"HOLD_{stage}_ALPHA_REJECT",
        "strategy_id": "alpha_combo",
        "stage": stage,
        "active_candidate_queue": active,
        "variants": list(variants.values()),
        "source_manifest_sha256": hashlib.sha256((source_root / "data" / "manifest.json").read_bytes()).hexdigest(),
        "canonical_strategy_files_mutated": False,
        "canonical_registry_mutated": False,
        "promotion_authority": False,
        "sealed_holdback_accessed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
        "next": "W3_TEMPORAL_DURABILITY" if stage == "W2" and active else "SEALED_FINAL_HOLDOUT_PREP" if stage == "W3" and active else "HOLD_RETAIN_CONTROLS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("data-b", "forward"), required=True)
    parser.add_argument("--stage", choices=("W2", "W3"))
    parser.add_argument("--alpha-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--multiobjective-root", required=True)
    parser.add_argument("--data-root")
    parser.add_argument("--source-root")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    alpha_root = Path(args.alpha_root).resolve()
    alpha = load_alpha(alpha_root)
    baseline, strategy, gate, surgery, symbols = load_authorities(
        alpha,
        alpha_root,
        Path(args.baseline_summary).resolve(),
        Path(args.multiobjective_root).resolve(),
    )
    if args.mode == "data-b":
        if not args.data_root:
            raise RuntimeError("DATA_ROOT_REQUIRED")
        result = run_data_b(args, alpha, baseline, strategy, gate, surgery, symbols)
    else:
        if not args.stage or not args.source_root:
            raise RuntimeError("FORWARD_STAGE_AND_SOURCE_REQUIRED")
        result = run_forward(args, alpha, baseline, strategy, gate, surgery, symbols)
    result["result_sha256"] = stable_sha(result)
    write_json(out / "latest.json", result)
    print(json.dumps({"state": result["state"], "active": result["active_candidate_queue"], "next": result["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
