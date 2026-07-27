from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tools import r7a4d_strategy11_evidence_pipeline_v1 as evidence
from backend.tools import r7a4d_strategy11_exact as exact

base = evidence.base

INTERVAL_MS = 900_000
EVALUATION_BARS = 480
WARMUP_BARS = 220
WINDOW_ID = "W1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
PRIMARY_REVIEW_QUEUE = {"alpha_combo", "turtle_trend", "ema_ribbon_scalp"}
PIPELINE_VERSION = "R7A4D_STRATEGY11_DATA_WAIT_POOL_COMPUTE_V1"


def strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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


def atomic_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({str(key) for row in rows for key in row})
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def aligned_closed_end(now_ms: int) -> int:
    return ((now_ms // INTERVAL_MS) - 1) * INTERVAL_MS


def iso(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="UTC").isoformat()


def read_ranking(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if len(rows) != 25:
        raise RuntimeError(f"RANKING_STRATEGY_COUNT:{len(rows)}")
    return rows


def locate_strategy(evidence_root: Path, strategy_id: str) -> Path:
    matches = sorted(evidence_root.glob(f"batch-*/{strategy_id}/summary.json"))
    if len(matches) != 1:
        raise RuntimeError(f"STRATEGY_AUTHORITY_MATCHES:{strategy_id}:{len(matches)}")
    return matches[0].parent


def loss_metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    wins: list[float] = []
    losses: list[float] = []
    all_r: list[float] = []
    ambiguous = 0
    for row in trades:
        risk_pct = metric(row.get("risk_pct"))
        if risk_pct <= 0.0:
            continue
        net_r = metric(row.get("net_return_pct")) / risk_pct
        all_r.append(net_r)
        if net_r > 0:
            wins.append(net_r)
        elif net_r < 0:
            losses.append(net_r)
        ambiguous += int(bool(row.get("path_ambiguous")))
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    payoff = avg_win / abs(avg_loss) if wins and losses and avg_loss < 0 else 0.0
    return {
        "avg_win_R": avg_win,
        "avg_loss_R": avg_loss,
        "payoff_R": payoff,
        "worst_net_loss_R": min(losses) if losses else 0.0,
        "loss_cap_breach_count": sum(value < -0.75 - 1e-12 for value in losses),
        "path_ambiguous_count": ambiguous,
        "r_trade_count": len(all_r),
    }


def add_lineage(
    trades: Sequence[dict[str, Any]],
    *,
    strategy_id: str,
    candidate_sha: str,
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    file_sha = {str(row["symbol"]): str(row["sha256"]) for row in manifest["files"]}
    output: list[dict[str, Any]] = []
    for index, source in enumerate(trades):
        row = dict(source)
        row["strategy_id"] = strategy_id
        row["candidate_config_sha256"] = candidate_sha
        row["market_file_sha256"] = file_sha[str(row["symbol"])]
        row["window_id"] = WINDOW_ID
        row["trade_id"] = stable_sha({
            "strategy_id": strategy_id,
            "window_id": WINDOW_ID,
            "symbol": row.get("symbol"),
            "entry_ts": row.get("entry_ts"),
            "exit_ts": row.get("exit_ts"),
            "candidate_config_sha256": candidate_sha,
            "ordinal": index,
        })
        output.append(row)
    return output


def collect_window(
    *,
    out: Path,
    authority_end_ms: int,
    now_ms: int,
) -> tuple[str, dict[str, Any] | None]:
    latest_closed_ms = aligned_closed_end(now_ms)
    evaluation_start_ms = authority_end_ms + INTERVAL_MS
    evaluation_end_ms = authority_end_ms + EVALUATION_BARS * INTERVAL_MS
    available = max(0, (latest_closed_ms - authority_end_ms) // INTERVAL_MS)
    if latest_closed_ms < evaluation_end_ms:
        return "WAIT_DATA", {
            "available_non_overlap_bars": int(available),
            "missing_bars": max(0, EVALUATION_BARS - int(available)),
            "next_eligible_window_end_ms": evaluation_end_ms,
            "next_eligible_window_end": iso(evaluation_end_ms),
        }

    fetch_start_ms = evaluation_start_ms - WARMUP_BARS * INTERVAL_MS
    expected_rows = EVALUATION_BARS + WARMUP_BARS
    files: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        frame, endpoint, requests = base._fetch_exact(
            symbol,
            start_ms=fetch_start_ms,
            end_ms=evaluation_end_ms,
            expected_rows=expected_rows,
        )
        errors = evidence.validate_frame(
            frame,
            start_ms=fetch_start_ms,
            end_ms=evaluation_end_ms,
            expected_rows=expected_rows,
        )
        if errors:
            raise RuntimeError(f"W1_MARKET_INVALID:{symbol}:{'|'.join(errors)}")
        path = out / "data" / "market" / f"{WINDOW_ID}-{symbol}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
        files.append({
            "window_id": WINDOW_ID,
            "symbol": symbol,
            "path": str(path.relative_to(out)),
            "sha256": sha256(path),
            "source": endpoint,
            "request_count": requests,
            "rows": len(frame),
            "fetch_start_ms": fetch_start_ms,
            "evaluation_start_ms": evaluation_start_ms,
            "evaluation_end_ms": evaluation_end_ms,
        })

    funding_sources: dict[str, str] = {}
    funding_counts: dict[str, int] = {}
    for symbol in SYMBOLS:
        rows, endpoint = evidence.fetch_funding(symbol, evaluation_start_ms, evaluation_end_ms)
        path = out / "data" / "funding" / f"{symbol}.json"
        evidence.atomic_json(path, {"symbol": symbol, "source": endpoint, "rows": rows})
        funding_sources[symbol] = endpoint
        funding_counts[symbol] = len(rows)

    manifest = {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "state": "PASS",
        "blockers": [],
        "window_id": WINDOW_ID,
        "interval_ms": INTERVAL_MS,
        "warmup_bars": WARMUP_BARS,
        "evaluation_bars": EVALUATION_BARS,
        "evaluation_start_ms": evaluation_start_ms,
        "evaluation_start": iso(evaluation_start_ms),
        "evaluation_end_ms": evaluation_end_ms,
        "evaluation_end": iso(evaluation_end_ms),
        "latest_closed_end_ms": latest_closed_ms,
        "latest_closed_end": iso(latest_closed_ms),
        "files": files,
        "funding_sources": funding_sources,
        "funding_event_counts": funding_counts,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
    }
    atomic_json(out / "data" / "manifest.json", manifest)
    return "READY", manifest


def load_window(out: Path, manifest: Mapping[str, Any]) -> tuple[
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
    dict[str, list[dict[str, Any]]],
]:
    frames: dict[str, pd.DataFrame] = {}
    features: dict[str, pd.DataFrame] = {}
    for row in manifest["files"]:
        path = out / str(row["path"])
        if sha256(path) != row["sha256"]:
            raise RuntimeError(f"W1_SHA_MISMATCH:{row['symbol']}")
        frame = pd.read_csv(path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
        frame["ts"] = frame["timestamp_ms"]
        symbol = str(row["symbol"])
        frames[symbol] = frame
        features[symbol] = exact.compute_feature_frame(frame)
    funding = {
        symbol: [
            dict(row)
            for row in strict_json(out / "data" / "funding" / f"{symbol}.json").get("rows", [])
            if isinstance(row, Mapping)
        ]
        for symbol in SYMBOLS
    }
    return frames, features, funding


def evaluate_one(
    *,
    root: Path,
    out: Path,
    evidence_root: Path,
    strategy_id: str,
    frames: Mapping[str, pd.DataFrame],
    features: Mapping[str, pd.DataFrame],
    funding: Mapping[str, list[dict[str, Any]]],
    manifest: Mapping[str, Any],
    combined_cost_bps: float,
) -> dict[str, Any]:
    authority = locate_strategy(evidence_root, strategy_id)
    summary_path = authority / "summary.json"
    trades_path = authority / "baseline_trades.json"
    stress_path = authority / "stress_grid.json"
    summary = strict_json(summary_path)
    prior_trades = [
        dict(row)
        for row in strict_json(trades_path).get("trades", [])
        if isinstance(row, Mapping)
    ]
    prior_stress = strict_json(stress_path)
    candidate = summary.get("candidate") if isinstance(summary.get("candidate"), Mapping) else {}
    surgery = evidence.surgery_from(summary.get("surgery") if isinstance(summary.get("surgery"), Mapping) else None)
    symbols = tuple(str(value) for value in summary.get("symbols", []) if str(value) in SYMBOLS)
    if not candidate or not symbols:
        raise RuntimeError(f"AUTHORITY_CONFIG_MISSING:{strategy_id}")

    registry = base._load_registry(root)
    strategy = base._load_canonical_strategy(root, strategy_id, registry[strategy_id])
    gate = exact._gate_from(candidate)
    exit_spec = exact._exit_from(candidate)
    candidate_sha = stable_sha({
        "candidate": candidate,
        "surgery": summary.get("surgery"),
        "symbols": symbols,
    })
    quantiles = evidence.funding_rate_quantiles(funding)

    raw_normal: list[dict[str, Any]] = []
    raw_stress: list[dict[str, Any]] = []
    for symbol in symbols:
        normal = evidence.replay_evidence(
            frames[symbol],
            features[symbol],
            strategy,
            gate,
            exit_spec,
            surgery,
            window_id=WINDOW_ID,
            symbol=symbol,
            warmup_bars=WARMUP_BARS,
            history_bars=220,
            cost_bps_per_side=combined_cost_bps,
            entry_delay_bars=1,
        )
        stress = evidence.replay_evidence(
            frames[symbol],
            features[symbol],
            strategy,
            gate,
            exit_spec,
            surgery,
            window_id=WINDOW_ID,
            symbol=symbol,
            warmup_bars=WARMUP_BARS,
            history_bars=220,
            cost_bps_per_side=combined_cost_bps * 2.0,
            entry_delay_bars=2,
        )
        raw_normal.extend(normal["trades"])
        raw_stress.extend(stress["trades"])

    normal = evidence.apply_funding(raw_normal, funding, "OBSERVED", quantiles)
    stress = evidence.apply_funding(raw_stress, funding, "ADVERSE_P95", quantiles)
    normal = add_lineage(normal, strategy_id=strategy_id, candidate_sha=candidate_sha, manifest=manifest)
    stress = add_lineage(stress, strategy_id=strategy_id, candidate_sha=candidate_sha, manifest=manifest)

    cumulative = prior_trades + normal
    stats = evidence.combine_stats(cumulative)
    window_stats = {
        role: evidence.combine_stats([row for row in cumulative if str(row.get("window_id")) == role])
        for role in ("F1", "F2", "F3", WINDOW_ID)
    }
    positive_windows = sum(metric(row.get("net_return_pct_sum")) > 0.0 for row in window_stats.values())
    positive_pct = positive_windows / 4.0 * 100.0
    normal_loss = loss_metrics(cumulative)
    stress_loss = loss_metrics(stress)
    returns = [metric(row.get("net_return_pct")) for row in cumulative]
    bootstrap = evidence.block_bootstrap(returns, 2000, 0.95, seed=int(stable_sha(strategy_id)[:8], 16))
    dsr = evidence.deflated_sharpe(returns, trials=25)
    prior_stress_rows = prior_stress.get("rows") if isinstance(prior_stress.get("rows"), list) else []
    prior_stress_complete = bool(summary.get("stress_grid_complete")) and len(prior_stress_rows) > 0
    n = int(stats.get("trade_count") or 0)
    blockers: list[str] = []
    if n < 12:
        blockers.append(f"CUMULATIVE_TRADES_LT_12:{n}")
    if positive_pct < 70.0:
        blockers.append(f"POSITIVE_WINDOWS_LT_70:{positive_pct:.2f}")
    if metric(stats.get("net_return_pct_sum")) <= 0.0:
        blockers.append("CUMULATIVE_NET_NOT_POSITIVE")
    if metric(stats.get("net_profit_factor")) <= 1.0:
        blockers.append("CUMULATIVE_PF_NOT_ABOVE_1")
    if normal_loss["loss_cap_breach_count"] != 0 or normal_loss["worst_net_loss_R"] < -0.75 - 1e-12:
        blockers.append("NORMAL_LOSS_CAP_FAIL")
    if stress_loss["loss_cap_breach_count"] != 0 or stress_loss["worst_net_loss_R"] < -0.75 - 1e-12:
        blockers.append("W1_STRESS_LOSS_CAP_FAIL")
    if not prior_stress_complete:
        blockers.append("PRIOR_STRESS_GRID_INCOMPLETE")
    if bootstrap.get("state") != "PASS":
        blockers.append(str(bootstrap.get("blocker") or "BOOTSTRAP_HOLD"))
    if dsr.get("state") != "PASS":
        blockers.append(str(dsr.get("blocker") or "DSR_HOLD"))

    strategy_out = out / "strategies" / strategy_id
    atomic_json(strategy_out / "W1-trades.json", {"strategy_id": strategy_id, "trades": normal})
    atomic_json(strategy_out / "W1-stress-trades.json", {"strategy_id": strategy_id, "trades": stress})
    payload = {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "strategy_id": strategy_id,
        "state": "PASS_PRE_FDR" if not blockers else "HOLD",
        "blockers": blockers,
        "candidate_config_sha256": candidate_sha,
        "source_summary_sha256": sha256(summary_path),
        "source_baseline_trades_sha256": sha256(trades_path),
        "source_stress_grid_sha256": sha256(stress_path),
        "symbols": list(symbols),
        "prior_trade_count": len(prior_trades),
        "W1_trade_count": len(normal),
        "cumulative": {
            **stats,
            **normal_loss,
            "positive_windows": positive_windows,
            "positive_windows_pct": positive_pct,
        },
        "window_stats": window_stats,
        "W1_stress": {
            **evidence.combine_stats(stress),
            **stress_loss,
        },
        "bootstrap": bootstrap,
        "deflated_sharpe": dsr,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
    }
    atomic_json(strategy_out / "summary.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-manifest", required=True)
    parser.add_argument("--ranking", required=True)
    parser.add_argument("--ema-terminal", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--as-of-ms", type=int)
    parser.add_argument("--combined-cost-bps", type=float, default=4.0)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_manifest_path = Path(args.fresh_manifest).resolve()
    ranking_path = Path(args.ranking).resolve()
    ema_terminal_path = Path(args.ema_terminal).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    out = Path(args.out).resolve()

    authority_manifest = strict_json(fresh_manifest_path)
    ranking = read_ranking(ranking_path)
    terminal = strict_json(ema_terminal_path)
    blockers: list[str] = []
    if authority_manifest.get("state") != "PASS" or authority_manifest.get("blockers"):
        blockers.append("FRESH_AUTHORITY_NOT_PASS")
    if terminal.get("state") != "STRUCTURAL_REJECT" or terminal.get("next") != "START_DATA_WAIT_POOL_REFRESH":
        blockers.append("EMA_TERMINAL_AUTHORITY_MISMATCH")
    pool = [str(row.get("strategy_id") or "") for row in ranking if str(row.get("strategy_id") or "") not in PRIMARY_REVIEW_QUEUE]
    if len(pool) != 22 or len(set(pool)) != 22:
        blockers.append(f"DATA_WAIT_POOL_INVALID:{len(pool)}")
    authority_end_ms = int(authority_manifest.get("latest_closed_end_ms") or 0)
    if authority_end_ms <= 0:
        blockers.append("AUTHORITY_END_MISSING")
    if blockers:
        atomic_json(out / "status.json", {
            "state": "HOLD",
            "blockers": blockers,
            "next": "REPAIR_AUTHORITY",
            "canonical_mutated": False,
            "registry_mutated": False,
            "protected_mutations": 0,
            "execution_allowed": False,
        })
        return 0

    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000) if args.as_of_ms is None else int(args.as_of_ms)
    readiness, readiness_payload = collect_window(out=out, authority_end_ms=authority_end_ms, now_ms=now_ms)
    if readiness == "WAIT_DATA":
        payload = {
            "schema_version": "1.0",
            "pipeline_version": PIPELINE_VERSION,
            "authority": "READ_ONLY_DATA_WAIT_POOL_COMPUTE_NO_EXECUTION",
            "state": "WAIT_DATA",
            "blockers": [],
            "data_wait_pool_count": len(pool),
            "source_fresh_manifest_sha256": sha256(fresh_manifest_path),
            "source_ranking_sha256": sha256(ranking_path),
            "source_ema_terminal_sha256": sha256(ema_terminal_path),
            **dict(readiness_payload or {}),
            "next": "RERUN_WHEN_480_BARS_COMPLETE",
            "canonical_mutated": False,
            "registry_mutated": False,
            "protected_mutations": 0,
            "shadow_allowed": False,
            "execution_allowed": False,
        }
        atomic_json(out / "status.json", payload)
        print(json.dumps(payload, sort_keys=True))
        return 0

    manifest = readiness_payload
    if not isinstance(manifest, Mapping):
        raise RuntimeError("W1_MANIFEST_MISSING")
    frames, features, funding = load_window(out, manifest)
    results: list[dict[str, Any]] = []
    for strategy_id in pool:
        print(f"REFRESH_START strategy={strategy_id}", flush=True)
        try:
            row = evaluate_one(
                root=root,
                out=out,
                evidence_root=evidence_root,
                strategy_id=strategy_id,
                frames=frames,
                features=features,
                funding=funding,
                manifest=manifest,
                combined_cost_bps=float(args.combined_cost_bps),
            )
        except Exception as exc:
            row = {
                "strategy_id": strategy_id,
                "state": "HOLD",
                "blockers": [f"{type(exc).__name__}:{exc}"],
                "canonical_mutated": False,
                "registry_mutated": False,
                "protected_mutations": 0,
                "execution_allowed": False,
            }
            atomic_json(out / "strategies" / strategy_id / "summary.json", row)
        results.append(row)
        print(f"REFRESH_END strategy={strategy_id} state={row.get('state')}", flush=True)

    pvalues = {
        str(row["strategy_id"]): metric((row.get("bootstrap") or {}).get("p_mean_le_zero"), 1.0)
        for row in results
        if row.get("state") == "PASS_PRE_FDR"
    }
    fdr = evidence.bh_fdr(pvalues, 0.10)
    passed = set(fdr.get("passed") or [])
    queue: list[dict[str, Any]] = []
    ranking_rows: list[dict[str, Any]] = []
    for row in results:
        sid = str(row["strategy_id"])
        cumulative = row.get("cumulative") if isinstance(row.get("cumulative"), Mapping) else {}
        blockers_row = list(row.get("blockers") or [])
        if row.get("state") == "PASS_PRE_FDR" and sid not in passed:
            blockers_row.append("BH_FDR_Q10_FAIL")
        qualified = row.get("state") == "PASS_PRE_FDR" and sid in passed
        classification = "SECONDARY_REVIEW_QUEUE" if qualified else (
            "NO_SIGNAL_WAIT" if int(cumulative.get("trade_count") or 0) == 0 else "LOW_SAMPLE_OR_PERFORMANCE_WAIT"
        )
        item = {
            "strategy_id": sid,
            "classification": classification,
            "qualified": qualified,
            "trade_count": int(cumulative.get("trade_count") or 0),
            "win_rate_pct": cumulative.get("win_rate_pct"),
            "net_return_pct_sum": cumulative.get("net_return_pct_sum"),
            "net_profit_factor": cumulative.get("net_profit_factor"),
            "payoff_ratio": cumulative.get("payoff_ratio"),
            "max_drawdown_pct": cumulative.get("max_drawdown_pct"),
            "avg_win_R": cumulative.get("avg_win_R"),
            "avg_loss_R": cumulative.get("avg_loss_R"),
            "worst_net_loss_R": cumulative.get("worst_net_loss_R"),
            "positive_windows_pct": cumulative.get("positive_windows_pct"),
            "bh_adjusted_p": (fdr.get("adjusted_pvalues") or {}).get(sid),
            "blockers": "|".join(blockers_row),
        }
        ranking_rows.append(item)
        if qualified:
            queue.append(item)

    queue.sort(
        key=lambda row: (
            metric(row.get("net_return_pct_sum")),
            metric(row.get("net_profit_factor")),
            metric(row.get("payoff_ratio")),
            -metric(row.get("max_drawdown_pct")),
        ),
        reverse=True,
    )
    active = queue[:3]
    atomic_csv(out / "global_refresh_ranking.csv", ranking_rows)
    atomic_json(out / "bh_fdr.json", fdr)
    atomic_json(out / "secondary_review_queue.json", {
        "qualified_count": len(queue),
        "active_count": len(active),
        "active": active,
        "all_qualified": queue,
    })
    final = {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "authority": "READ_ONLY_DATA_WAIT_POOL_REFRESH_NO_EXECUTION",
        "state": "PASS",
        "blockers": [],
        "data_wait_pool_count": len(pool),
        "evaluated_strategy_count": len(results),
        "W1_manifest_sha256": sha256(out / "data" / "manifest.json"),
        "qualified_count": len(queue),
        "secondary_review_queue": [row["strategy_id"] for row in queue],
        "active_candidates": [row["strategy_id"] for row in active],
        "next": "CREATE_SECONDARY_REPAIR_CHILDREN" if active else "WAIT_NEXT_NON_OVERLAP_480_BAR_WINDOW",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "shadow_allowed": False,
        "execution_allowed": False,
    }
    atomic_json(out / "status.json", final)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("## Strategy11 DATA_WAIT_POOL_REFRESH compute\n\n")
            handle.write(f"- state: `{final['state']}`\n")
            handle.write(f"- evaluated: `{len(results)}/22`\n")
            handle.write(f"- qualified: `{len(queue)}`\n")
            handle.write(f"- active: `{', '.join(final['active_candidates']) or 'none'}`\n")
            handle.write(f"- next: `{final['next']}`\n")
    print(json.dumps(final, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
