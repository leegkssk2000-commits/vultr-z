from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRIOR_PATH = ROOT / "backend/tools/r7a4d_strategy11_gemini_22_prework_v1.py"
V31_PATH = ROOT / "backend/tools/r7a4d_strategy11_gemini_active_research_v3_1.py"
FEATURE_PATH = ROOT / "backend/strategy25/strategy11_feature_library_v1.py"

VERSION = "R7A4D_STRATEGY11_MULTIMODAL_RESCUE_L090_PLAN_V1"
CAPABILITY_MARKER = "MULTIMODAL_RESCUE_L090"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prior = load_module("s11_multimodal_prior", PRIOR_PATH)
v31 = load_module("s11_multimodal_v31", V31_PATH)
feature_lib = load_module("s11_multimodal_features", FEATURE_PATH)
v3 = v31.v3
p = prior.p

STRATEGIES = tuple(prior.STRATEGIES)

EXIT_CATALOG = {
    "STOP090": {"axis": "STOP", "changes": {"stop_mult": 0.90}},
    "STOP085": {"axis": "STOP", "changes": {"stop_mult": 0.85}},
    "TARGET125": {"axis": "TARGET", "changes": {"target_mult": 1.25}},
    "TARGET150": {"axis": "TARGET", "changes": {"target_mult": 1.50}},
    "BE050": {"axis": "BREAKEVEN", "changes": {"breakeven_r": 0.50}},
    "BE075": {"axis": "BREAKEVEN", "changes": {"breakeven_r": 0.75}},
    "PARTIAL30_R075": {"axis": "PARTIAL", "changes": {"partial_r": 0.75, "partial_fraction": 0.30}},
    "TRAIL_R075_ATR125": {"axis": "MFE_TRAILING", "changes": {"trail_activate_r": 0.75, "trail_atr_mult": 1.25}},
    "TRAIL_R100_ATR150": {"axis": "MFE_TRAILING", "changes": {"trail_activate_r": 1.0, "trail_atr_mult": 1.50}},
    "TIME12": {"axis": "TIME_STOP", "changes": {"time_stop_bars": 12}},
    "TIME24": {"axis": "TIME_STOP", "changes": {"time_stop_bars": 24}},
    "TIME48": {"axis": "TIME_STOP", "changes": {"time_stop_bars": 48}},
}


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


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def number(row: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        if finite(row.get(key)):
            return float(row[key])
    return None


def trade_net_r(row: Mapping[str, Any]) -> float | None:
    value = number(row, ("net_R", "net_reference_R", "pnl_r", "net_return_R"))
    if value is not None:
        return value
    net_pct = number(row, ("net_return_pct", "pnl_pct"))
    risk_pct = number(row, ("risk_pct", "reference_risk_pct"))
    return net_pct / risk_pct if net_pct is not None and risk_pct not in (None, 0.0) else None


def feature_contrast(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    wins = [row for row in trades if (trade_net_r(row) or 0.0) > 0.0]
    losses = [row for row in trades if (trade_net_r(row) or 0.0) < 0.0]
    keys = set()
    for row in trades:
        features = row.get("features")
        if isinstance(features, Mapping):
            keys.update(str(key) for key in features)
    rows = []
    for key in sorted(keys):
        w = [float(row["features"][key]) for row in wins if isinstance(row.get("features"), Mapping) and finite(row["features"].get(key))]
        l = [float(row["features"][key]) for row in losses if isinstance(row.get("features"), Mapping) and finite(row["features"].get(key))]
        if len(w) < 2 or len(l) < 2:
            continue
        wm, lm = sum(w) / len(w), sum(l) / len(l)
        scale = max(1e-9, abs(wm) + abs(lm))
        rows.append({"feature": key, "win_mean": wm, "loss_mean": lm, "normalized_delta": (wm - lm) / scale, "support": min(len(w), len(l))})
    rows.sort(key=lambda row: (abs(row["normalized_delta"]), row["support"]), reverse=True)
    return rows[:16]


def baseline_metrics(summary: Mapping[str, Any], trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cluster = v3.trade_cluster([dict(row) for row in trades])
    return {
        "state": summary.get("state"),
        "classification": summary.get("classification"),
        "trade_count": summary.get("trade_count", cluster.get("trade_count")),
        "win_rate_pct": summary.get("win_rate_pct", cluster.get("win_rate_pct")),
        "net_return_pct_sum": summary.get("net_return_pct_sum"),
        "net_profit_factor": summary.get("net_profit_factor"),
        "payoff_ratio": summary.get("payoff_ratio"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "positive_fresh_windows_pct": summary.get("positive_fresh_windows_pct"),
        "avg_win_R": cluster.get("avg_win_R"),
        "avg_loss_R": cluster.get("avg_loss_R"),
        "worst_loss_R": cluster.get("worst_loss_R"),
        "mfe_R_p50": cluster.get("mfe_R_p50"),
        "mfe_R_p75": cluster.get("mfe_R_p75"),
        "mae_R_p50": cluster.get("mae_R_p50"),
        "mae_R_p75": cluster.get("mae_R_p75"),
        "bars_held_p50": cluster.get("bars_held_p50"),
        "bars_held_p90": cluster.get("bars_held_p90"),
        "exit_reason_counts": cluster.get("exit_reason_counts"),
        "symbol_counts": cluster.get("symbol_counts"),
        "window_counts": cluster.get("window_counts"),
        "regime_counts": cluster.get("regime_counts"),
        "favorable_then_loss": cluster.get("favorable_then_loss"),
    }


def gate_catalog(strategy_id: str) -> dict[str, Any]:
    result = {}
    for spec in feature_lib.gate_specs_for(strategy_id):
        if spec.gate_id == "BASE":
            continue
        cid = f"GATE__{spec.gate_id}"
        result[cid] = {
            "kind": "GATE",
            "axis": "ENTRY_CONTEXT_GATE",
            "gate": {
                "gate_id": spec.gate_id,
                "family": spec.family,
                "required": list(spec.required),
                "forbidden": list(spec.forbidden),
                "description": spec.description,
            },
        }
    return result


def candidate_catalog(strategy_id: str, metrics: Mapping[str, Any]) -> dict[str, Any]:
    result = gate_catalog(strategy_id)
    for cid, spec in EXIT_CATALOG.items():
        result[cid] = {"kind": "EXIT", **spec}
    symbol_counts = metrics.get("symbol_counts") if isinstance(metrics.get("symbol_counts"), Mapping) else {}
    total = sum(int(value or 0) for value in symbol_counts.values())
    if total:
        worst_symbol = max(symbol_counts, key=lambda key: int(symbol_counts[key] or 0))
        if (total - int(symbol_counts[worst_symbol] or 0)) / total >= 0.70:
            result[f"EXCLUDE__{worst_symbol}"] = {
                "kind": "SYMBOL",
                "axis": "SYMBOL_EXCLUSION",
                "excluded_symbol": worst_symbol,
            }
    return result


def local_fallback(strategy_id: str, metrics: Mapping[str, Any], catalog: Mapping[str, Any]) -> list[str]:
    family = feature_lib.FAMILY_MAP[strategy_id]
    preferred = {
        "trend_following": ["GATE__TF_EMA_ADX20", "GATE__TF_EMA_HTF", "TRAIL_R100_ATR150", "STOP090"],
        "mean_reversion": ["GATE__MR_LOW_ADX", "GATE__MR_REJECTION", "BE050", "TIME24"],
        "breakout_momentum": ["GATE__BO_DONCHIAN_VOL", "GATE__BO_TREND_ADX", "TRAIL_R075_ATR125", "STOP090"],
        "market_structure": ["GATE__MS_SWEEP_REJECTION", "GATE__MS_REJECTION", "BE075", "TARGET125"],
        "session_volatility": ["GATE__SV_ACTIVE_VOL", "GATE__SV_VOL_ATR", "TIME12", "STOP090"],
        "hybrid": ["GATE__HY_TREND", "GATE__HY_RANGE_REJECT", "BE075", "TRAIL_R100_ATR150"],
    }.get(family, ["STOP090", "BE075"])
    favorable = metrics.get("favorable_then_loss") if isinstance(metrics.get("favorable_then_loss"), Mapping) else {}
    if sum(int(v or 0) for v in favorable.values()) > 0:
        preferred = ["BE050", "PARTIAL30_R075", *preferred]
    output = []
    seen_axes = set()
    for cid in preferred:
        spec = catalog.get(cid)
        if not spec:
            continue
        axis = spec["axis"]
        if axis in seen_axes:
            continue
        seen_axes.add(axis)
        output.append(cid)
        if len(output) == 2:
            return output
    return list(catalog)[:2]


def create_dashboard(out: Path, alias: str, metrics: Mapping[str, Any], contrasts: Sequence[Mapping[str, Any]], trades: Sequence[Mapping[str, Any]], frames: Mapping[tuple[str, str], pd.DataFrame]) -> Path:
    import matplotlib.pyplot as plt

    chart_dir = out / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    labels = ["WR", "Net", "PF", "Payoff", "DD"]
    values = [
        float(metrics.get("win_rate_pct") or 0.0),
        float(metrics.get("net_return_pct_sum") or 0.0),
        float(metrics.get("net_profit_factor") or 0.0),
        float(metrics.get("payoff_ratio") or 0.0),
        float(metrics.get("max_drawdown_pct") or 0.0),
    ]
    axes[0, 0].bar(labels, values)
    axes[0, 0].set_title("Baseline metric table")
    axes[0, 0].grid(axis="y", alpha=0.25)

    top = list(contrasts[:8])
    axes[0, 1].barh([row["feature"] for row in reversed(top)], [row["normalized_delta"] for row in reversed(top)])
    axes[0, 1].set_title("Winner vs loser feature contrast")
    axes[0, 1].grid(axis="x", alpha=0.25)

    points = []
    for row in trades:
        mfe = number(row, ("mfe_R", "mfe_r", "max_favorable_excursion_R"))
        mae = number(row, ("mae_R", "mae_r", "max_adverse_excursion_R"))
        net = trade_net_r(row)
        if mfe is not None and mae is not None and net is not None:
            points.append((mfe, mae, net))
    if points:
        axes[1, 0].scatter([x for x, _, _ in points], [y for _, y, _ in points], c=[1 if z > 0 else 0 for _, _, z in points], alpha=0.65)
    axes[1, 0].set_title("MFE / MAE trade map")
    axes[1, 0].set_xlabel("MFE (R)")
    axes[1, 0].set_ylabel("MAE (R)")
    axes[1, 0].grid(alpha=0.25)

    worst = sorted((row for row in trades if trade_net_r(row) is not None), key=lambda row: trade_net_r(row) or 0.0)[:1]
    plotted = False
    if worst:
        trade = worst[0]
        role, symbol = str(trade.get("window_id")), str(trade.get("symbol"))
        frame = frames.get((role, symbol))
        target = pd.to_datetime(trade.get("entry_ts"), utc=True, errors="coerce")
        if frame is not None and not frame.empty and not pd.isna(target):
            timestamps = pd.to_datetime(frame["timestamp"], utc=True)
            center = int((timestamps - target).abs().argmin())
            view = frame.iloc[max(0, center - 20):min(len(frame), center + 30)]
            axes[1, 1].plot(pd.to_datetime(view["timestamp"], utc=True), view["close"].astype(float))
            axes[1, 1].axvline(target, linestyle="--", linewidth=1)
            axes[1, 1].set_title(f"Worst-trade candle context: {symbol}/{role}")
            axes[1, 1].tick_params(axis="x", rotation=30)
            axes[1, 1].grid(alpha=0.25)
            plotted = True
    if not plotted:
        exits = metrics.get("exit_reason_counts") if isinstance(metrics.get("exit_reason_counts"), Mapping) else {}
        axes[1, 1].barh(list(exits)[:8], [int(exits[key] or 0) for key in list(exits)[:8]])
        axes[1, 1].set_title("Exit reason distribution")

    fig.suptitle(f"Strategy {alias}: multimodal rescue evidence")
    fig.tight_layout()
    path = chart_dir / f"{alias}_multimodal.png"
    fig.savefig(path, dpi=135)
    plt.close(fig)
    return path


def group_prompt(rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "strategies": [{
            "strategy_alias": "S01",
            "candidate_ids": ["EXACTLY_TWO_DISTINCT_IDS_FROM_CATALOG"],
            "evidence_lanes": ["METRIC_TABLE", "CANDLE_CONTEXT", "MFE_MAE_CHART", "FEATURE_CONTRAST", "PUBLIC_DIRECT_VIDEO"],
            "single_axis_reason": "...",
            "expected_metric_effect": {"Net": "...", "PF": "...", "payoff": "...", "DD": "...", "loss": "..."},
            "falsification_test": "...",
            "priority": 1,
        }]
    }
    return (
        "You are a skeptical quantitative strategy rescue planner. Directly inspect all attached public trading videos and each attached internal evidence dashboard. "
        "The dashboards contain anonymized metrics, candle context, feature contrast and MFE/MAE; no private code or account/order data is supplied. "
        "A prior exit-only search failing does not prove the strategy is dead. Select exactly two DISTINCT single-axis candidates per strategy from its candidate catalog. "
        "Use different causal axes when possible: entry context, candle structure, trend/regime, volatility, volume flow, momentum, session, symbol exclusion, or exit management. "
        "Do not invent IDs or combine axes. L090 is discovery only, then L085/L080/L075. Return strict JSON only.\n"
        f"POLICY={json.dumps(policy, ensure_ascii=False, sort_keys=True)}\n"
        f"PROFILES={json.dumps(v3.sanitize(list(rows)), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def red_prompt(rows: Sequence[Mapping[str, Any]]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "rows": [{
            "strategy_alias": "S01",
            "approved_candidate_ids": ["TWO_IDS"],
            "priority": 1,
            "reason": "...",
            "overfit_risk": "LOW|MEDIUM|HIGH",
        }]
    }
    return (
        "Independently red-team this 22-strategy multimodal rescue plan. Preserve every strategy; reject invalid hypotheses, not strategies. "
        "Each strategy must keep NO_CHANGE control plus exactly two distinct single-axis candidates. Prefer genuinely different axes and reject micro-parameter fishing. "
        "No more than three strategies may be active simultaneously. Return strict JSON only.\n"
        f"ROWS={json.dumps(v3.sanitize(list(rows)), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def analyze(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    policy = strict_json(Path(args.policy).resolve())
    registry = strict_json(Path(args.video_registry).resolve())
    videos = [row for row in registry.get("sources", []) if isinstance(row, Mapping)]
    channels = {str(row.get("channel") or "") for row in videos}
    if len(videos) < 4 or len(channels) < 4:
        raise RuntimeError("VIDEO_DIVERSITY_LT_4")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    models = v3.v2.list_models(key)
    if not models:
        raise RuntimeError("NO_FREE_FLASH_MODEL")

    evidence_root = Path(args.evidence_root).resolve()
    frames, _, _, manifest = p.load_fresh_data(Path(args.fresh_root).resolve())
    aliases = {sid: f"S{index:02d}" for index, sid in enumerate(STRATEGIES, start=1)}
    profiles = {}
    charts = {}
    for sid in STRATEGIES:
        summary_path = prior.find_summary(evidence_root, sid)
        summary = strict_json(summary_path)
        trades = v3.collect_trades([summary_path.parent], sid)
        metrics = baseline_metrics(summary, trades)
        contrasts = feature_contrast(trades)
        catalog = candidate_catalog(sid, metrics)
        fallback = local_fallback(sid, metrics, catalog)
        alias = aliases[sid]
        chart = create_dashboard(out, alias, metrics, contrasts, trades, frames)
        chart_sha = hashlib.sha256(chart.read_bytes()).hexdigest()
        table_path = out / "tables" / f"{alias}.csv"
        table_path.parent.mkdir(parents=True, exist_ok=True)
        with table_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["feature", "win_mean", "loss_mean", "normalized_delta", "support"])
            writer.writeheader()
            writer.writerows(contrasts)
        profile = {
            "strategy_alias": alias,
            "family": feature_lib.FAMILY_MAP[sid],
            "baseline_metrics": metrics,
            "feature_contrast": contrasts,
            "candidate_catalog": catalog,
            "local_fallback": fallback,
            "chart_sha256": chart_sha,
            "raw_code_sent": False,
        }
        profiles[sid] = profile
        charts[sid] = chart
        atomic_json(out / "profiles" / f"{alias}.json", profile)

    proposed = []
    calls = []
    groups = [STRATEGIES[0:6], STRATEGIES[6:12], STRATEGIES[12:17], STRATEGIES[17:22]]
    for index, ids in enumerate(groups, start=1):
        prompt = group_prompt([profiles[sid] for sid in ids], policy)
        parts = [{"text": prompt}]
        parts.extend({"file_data": {"file_uri": row["url"]}} for row in videos[:4])
        parts.extend(v3.image_part(charts[sid]) for sid in ids)
        model, text = v3.call_gemini(key, models, parts, max_tokens=16384)
        response = v31.strict_object_response(text)
        observed = {
            str(row.get("strategy_alias")): dict(row)
            for row in response.get("strategies", [])
            if isinstance(row, Mapping)
        }
        atomic_json(out / "gemini_batches" / f"batch-{index}.json", response)
        for sid in ids:
            alias = aliases[sid]
            catalog = profiles[sid]["candidate_catalog"]
            row = observed.get(alias, {})
            selected = [str(value) for value in row.get("candidate_ids", []) if str(value) in catalog]
            selected = list(dict.fromkeys(selected))[:2]
            fallback_used = False
            if len(selected) < 2:
                selected = profiles[sid]["local_fallback"]
                fallback_used = True
            proposed.append({
                "strategy_id": sid,
                "strategy_alias": alias,
                "candidate_ids": selected,
                "candidate_specs": {cid: catalog[cid] for cid in selected},
                "evidence_lanes": row.get("evidence_lanes", []),
                "single_axis_reason": row.get("single_axis_reason"),
                "expected_metric_effect": row.get("expected_metric_effect", {}),
                "falsification_test": row.get("falsification_test"),
                "priority": int(row.get("priority") or 999),
                "gemini_fallback_local": fallback_used,
            })
        calls.append({
            "stage": f"BATCH_{index}",
            "model": model,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "image_count": len(ids),
            "video_count": 4,
        })

    red_prompt_text = red_prompt(proposed)
    model, text = v3.call_gemini(key, models, [{"text": red_prompt_text}], max_tokens=16384)
    red = v31.strict_object_response(text)
    atomic_json(out / "red_team.json", red)
    red_rows = {
        str(row.get("strategy_alias")): dict(row)
        for row in red.get("rows", [])
        if isinstance(row, Mapping)
    }
    final_rows = []
    for row in proposed:
        catalog = profiles[row["strategy_id"]]["candidate_catalog"]
        adjudicated = red_rows.get(row["strategy_alias"], {})
        selected = [str(value) for value in adjudicated.get("approved_candidate_ids", []) if str(value) in catalog]
        selected = list(dict.fromkeys(selected))[:2]
        if len(selected) < 2:
            selected = row["candidate_ids"]
        final_rows.append({
            **row,
            "candidate_ids": selected,
            "candidate_specs": {cid: catalog[cid] for cid in selected},
            "priority": int(adjudicated.get("priority") or row["priority"]),
            "red_team_reason": adjudicated.get("reason"),
            "overfit_risk": adjudicated.get("overfit_risk", "HIGH"),
            "promotion_authority": False,
        })
    final_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    calls.append({
        "stage": "RED_TEAM",
        "model": model,
        "prompt_sha256": hashlib.sha256(red_prompt_text.encode()).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
    })
    plan = {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_marker": CAPABILITY_MARKER,
        "state": "PASS_MULTIMODAL_L090_PLAN",
        "strategy_count": len(final_rows),
        "candidate_count": sum(len(row["candidate_ids"]) for row in final_rows),
        "chart_count": len(charts),
        "table_count": len(charts),
        "loss_ladder": policy["loss_ladder"],
        "rows": final_rows,
        "call_audit": calls,
        "GEMINI_USED": True,
        "free_only": True,
        "direct_video_used": True,
        "public_video_count": 4,
        "independent_channel_count": len(channels),
        "internal_chart_images_used": True,
        "fresh_manifest_sha256": stable_sha(manifest),
        "private_code_sent": False,
        "account_data_sent": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "promotion_authority": False,
        "next": "ISOLATED_REPLAY_ALL_22_L090",
    }
    atomic_json(out / "plan.json", plan)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--video-registry", required=True)
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    return analyze(args)


if __name__ == "__main__":
    raise SystemExit(main())
