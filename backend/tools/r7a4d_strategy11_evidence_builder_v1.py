from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EXACT_PATH = ROOT / "backend/tools/r7a4d_strategy11_exact.py"
INTERVAL_MS = 900_000
WINDOW_BARS = 480
FRESH_WINDOWS = {
    "F1_NEW": "2026-06-22T00:00:00Z",
    "F2_NEW": "2026-06-27T00:00:00Z",
    "F3_NEW": "2026-07-02T00:00:00Z",
}
SEALED_WINDOWS = {
    "Z1_SEALED": "2026-07-07T00:00:00Z",
    "Z2_SEALED": "2026-07-12T00:00:00Z",
}
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")


def load_exact() -> Any:
    spec = importlib.util.spec_from_file_location("s11_exact_evidence", EXACT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("EXACT_MODULE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def fetch_window(exact: Any, symbol: str, end_iso: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    end_ms = int(pd.Timestamp(end_iso).timestamp() * 1000)
    end_ms = (end_ms // INTERVAL_MS) * INTERVAL_MS
    start_ms = end_ms - (WINDOW_BARS - 1) * INTERVAL_MS
    frame, endpoint, requests = exact.base._fetch_exact(symbol, start_ms=start_ms, end_ms=end_ms, expected_rows=WINDOW_BARS)
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    integrity = {
        "source": endpoint,
        "symbol": symbol,
        "start": ts.iloc[0].isoformat(),
        "end": ts.iloc[-1].isoformat(),
        "interval": "15m",
        "row_count": int(len(frame)),
        "duplicate_count": int(ts.duplicated().sum()),
        "gap_count": int((ts.diff().dropna() != pd.Timedelta(minutes=15)).sum()),
        "ohlcv_valid": bool(((frame["high"] >= frame[["open", "close"]].max(axis=1)) & (frame["low"] <= frame[["open", "close"]].min(axis=1)) & (frame["high"] >= frame["low"]) & (frame["open"] > 0) & (frame["close"] > 0) & (frame["volume"] >= 0)).all()),
        "request_count": requests,
    }
    csv_bytes = frame.to_csv(index=False).encode()
    integrity["data_sha256"] = hashlib.sha256(csv_bytes).hexdigest()
    if integrity["duplicate_count"] or integrity["gap_count"] or not integrity["ohlcv_valid"]:
        raise RuntimeError(f"WINDOW_INTEGRITY_FAIL:{symbol}:{end_iso}:{integrity}")
    return frame, integrity


def add_excursions(frame: pd.DataFrame, trades: list[dict[str, Any]]) -> None:
    time_index = pd.to_datetime(frame["timestamp"], utc=True)
    for trade in trades:
        entry_ts = pd.Timestamp(trade["entry_ts"])
        exit_ts = pd.Timestamp(trade["exit_ts"])
        mask = (time_index >= entry_ts) & (time_index <= exit_ts)
        segment = frame.loc[mask]
        if segment.empty:
            trade.update({"mfe_pct": None, "mae_pct": None, "mfe_r": None, "mae_r": None, "bars_to_mfe": None, "bars_to_mae": None, "bars_held": 0})
            continue
        entry = float(trade["entry_price"])
        highs = segment["high"].astype(float)
        lows = segment["low"].astype(float)
        mfe_pct = (float(highs.max()) / entry - 1.0) * 100.0
        mae_pct = (float(lows.min()) / entry - 1.0) * 100.0
        risk = float(trade.get("initial_risk") or 0.0)
        trade["mfe_pct"] = mfe_pct
        trade["mae_pct"] = mae_pct
        trade["mfe_r"] = ((float(highs.max()) - entry) / risk) if risk > 0 else None
        trade["mae_r"] = ((float(lows.min()) - entry) / risk) if risk > 0 else None
        trade["bars_to_mfe"] = int(np.argmax(highs.to_numpy()))
        trade["bars_to_mae"] = int(np.argmin(lows.to_numpy()))
        trade["bars_held"] = int(len(segment))


def stats(returns: list[float]) -> dict[str, Any]:
    wins = [v for v in returns if v > 0]
    losses = [v for v in returns if v < 0]
    gain, loss = sum(wins), abs(sum(losses))
    pf = gain / loss if loss > 0 else (999.0 if gain > 0 else None)
    aw = sum(wins) / len(wins) if wins else None
    al = abs(sum(losses) / len(losses)) if losses else None
    payoff = aw / al if aw is not None and al not in (None, 0) else None
    cumulative = np.cumsum(returns) if returns else np.array([])
    dd = float(np.max(np.maximum.accumulate(cumulative) - cumulative)) if len(cumulative) else 0.0
    return {"trade_count": len(returns), "net_return_pct_sum": sum(returns), "win_rate_pct": (len(wins) / len(returns) * 100) if returns else None, "net_profit_factor": pf, "payoff_ratio": payoff, "max_drawdown_pct": dd}


def bootstrap(returns: list[float], samples: int = 2000, block: int = 3) -> dict[str, Any]:
    if len(returns) < 12:
        return {"state": "HOLD", "blocker": "TRADES_LT_12"}
    rng = np.random.default_rng(11011)
    arr = np.asarray(returns, dtype=float)
    means = []
    n = len(arr)
    for _ in range(samples):
        picked: list[float] = []
        while len(picked) < n:
            start = int(rng.integers(0, n))
            picked.extend(arr.take(np.arange(start, start + block) % n).tolist())
        means.append(float(np.mean(picked[:n])))
    lo, hi = np.quantile(means, [0.025, 0.975])
    p = float(np.mean(np.asarray(means) <= 0.0))
    sharpe = float(np.mean(arr) / np.std(arr, ddof=1) * math.sqrt(n)) if np.std(arr, ddof=1) > 0 else None
    skew = float(pd.Series(arr).skew())
    kurt = float(pd.Series(arr).kurt())
    dsr = None
    if sharpe is not None:
        denom = math.sqrt(max(1e-12, 1 - skew * sharpe + ((kurt - 1) / 4) * sharpe * sharpe))
        dsr = sharpe / denom
    return {"state": "PASS", "samples": samples, "block_size": block, "mean_ci95": [float(lo), float(hi)], "p_mean_le_zero": p, "sharpe_like": sharpe, "deflated_sharpe": dsr}


def bh_fdr(p_values: list[tuple[str, float]], q: float = 0.10) -> dict[str, Any]:
    ordered = sorted(p_values, key=lambda x: x[1])
    accepted: list[str] = []
    m = len(ordered)
    for i, (name, p) in enumerate(ordered, 1):
        if p <= q * i / max(m, 1):
            accepted.append(name)
    return {"q": q, "tests": m, "accepted": accepted, "rows": [{"id": n, "p": p} for n, p in ordered]}


def approximate_pbo(window_matrix: dict[str, list[float]]) -> dict[str, Any]:
    if len(window_matrix) < 4:
        return {"state": "HOLD", "blocker": "CANDIDATES_LT_4"}
    ids = sorted(window_matrix)
    matrix = np.asarray([window_matrix[i] for i in ids], dtype=float)
    if matrix.shape[1] < 3:
        return {"state": "HOLD", "blocker": "WINDOWS_LT_3"}
    overfit = 0
    trials = 0
    for held in range(matrix.shape[1]):
        train = np.delete(matrix, held, axis=1).mean(axis=1)
        winner = int(np.argmax(train))
        rank = int(np.argsort(np.argsort(matrix[:, held]))[winner])
        if rank < len(ids) / 2:
            overfit += 1
        trials += 1
    pbo = overfit / max(trials, 1)
    return {"state": "PASS", "pbo": pbo, "limit": 0.20, "pass": pbo <= 0.20, "trials": trials}


def current_funding(symbol: str) -> dict[str, Any]:
    import urllib.parse, urllib.request
    url = "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate?" + urllib.parse.urlencode({"symbol": symbol[:-4] + "-USDT"})
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.load(response)
        data = payload.get("data") or {}
        rate = data.get("lastFundingRate", data.get("fundingRate")) if isinstance(data, Mapping) else None
        return {"state": "PASS" if finite(rate) else "HOLD", "source": url, "observed_rate": float(rate) if finite(rate) else None, "raw": data}
    except Exception as exc:
        return {"state": "HOLD", "source": url, "error": f"{type(exc).__name__}:{exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authority-root", required=True)
    ap.add_argument("--ssot", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    authority = Path(args.authority_root)
    out = Path(args.out)
    ssot = json.loads(Path(args.ssot).read_text())
    exact = load_exact()
    original_close = exact._close_trade

    def close_with_path(position: Any, **kwargs: Any) -> dict[str, Any]:
        row = original_close(position, **kwargs)
        row.update({"initial_risk": float(position.risk), "initial_sl": float(position.entry - position.risk), "initial_tp": float(position.tp), "partial_done": bool(position.partial_done), "bars_held_runner": int(position.bars_open)})
        return row
    exact._close_trade = close_with_path

    windows: dict[str, dict[str, pd.DataFrame]] = {}
    manifest: list[dict[str, Any]] = []
    blockers: list[str] = []
    for role, end in {**FRESH_WINDOWS, **SEALED_WINDOWS}.items():
        windows[role] = {}
        for symbol in SYMBOLS:
            try:
                frame, meta = fetch_window(exact, symbol, end)
                windows[role][symbol] = frame
                manifest.append({"role": role, "sealed": role in SEALED_WINDOWS, **meta})
            except Exception as exc:
                blockers.append(f"DATA:{role}:{symbol}:{type(exc).__name__}:{exc}")

    registry = exact.base._load_registry(ROOT)
    candidate_rows: list[dict[str, Any]] = []
    p_values: list[tuple[str, float]] = []
    window_matrix: dict[str, list[float]] = {}
    mfe_complete = 0
    mfe_total = 0
    summaries = sorted((authority / "strategy11_exact_v1").glob("*/summary.json"))
    for summary_path in summaries:
        summary = json.loads(summary_path.read_text())
        strategy_id = str(summary.get("strategy_id") or summary_path.parent.name)
        results = [r for r in summary.get("results", []) if isinstance(r, Mapping)]
        if not results:
            continue
        chosen = max(results, key=lambda r: float((r.get("evaluation") or {}).get("score") or -1e99))
        candidate = chosen.get("candidate") or {}
        symbols = tuple(s for s in (chosen.get("symbols") or candidate.get("symbol_whitelist") or SYMBOLS[:2]) if s in SYMBOLS)
        if len(symbols) < 2:
            symbols = SYMBOLS[:2]
        strategy = exact.base._load_canonical_strategy(ROOT, strategy_id, registry[strategy_id])
        gate = exact._gate_from(candidate)
        exit_spec = exact._exit_from(candidate)
        all_trades: list[dict[str, Any]] = []
        per_window: list[float] = []
        for role in FRESH_WINDOWS:
            role_returns: list[float] = []
            for symbol in symbols:
                frame = windows.get(role, {}).get(symbol)
                if frame is None:
                    continue
                features = exact.compute_feature_frame(frame)
                replay = exact._replay(frame, features, strategy, gate, exit_spec, None, warmup_bars=220, history_bars=220, cost_bps_per_side=4.0)
                trades = replay.get("trades", [])
                add_excursions(frame, trades)
                for trade in trades:
                    trade.update({"strategy_id": strategy_id, "window_id": role, "symbol": symbol, "candidate_sha256": stable_sha(candidate)})
                all_trades.extend(trades)
                role_returns.extend(float(t["net_return_pct"]) for t in trades)
            per_window.append(sum(role_returns))
        returns = [float(t["net_return_pct"]) for t in all_trades]
        raw = stats(returns)
        n = raw["trade_count"]
        prior = float(ssot["ranking_safety"]["bayesian_shrinkage_trade_prior"])
        pf_raw = raw.get("net_profit_factor")
        payoff_raw = raw.get("payoff_ratio")
        pf_adj = min(float(ssot["ranking_safety"]["profit_factor_cap_for_score"]), ((float(pf_raw) if finite(pf_raw) else 1.0) * n + prior) / (n + prior))
        payoff_adj = min(float(ssot["ranking_safety"]["payoff_ratio_cap_for_score"]), ((float(payoff_raw) if finite(payoff_raw) else 1.0) * n + prior) / (n + prior))
        boot = bootstrap(returns)
        if boot.get("state") == "PASS":
            p_values.append((strategy_id, float(boot["p_mean_le_zero"])))
        mfe_total += len(all_trades)
        mfe_complete += sum(all(t.get(k) is not None for k in ("mfe_pct", "mae_pct", "mfe_r", "mae_r", "bars_to_mfe", "bars_to_mae")) for t in all_trades)
        candidate_rows.append({"strategy_id": strategy_id, "candidate_sha256": stable_sha(candidate), "symbols": list(symbols), "fresh_windows": len(FRESH_WINDOWS), "per_window_net": per_window, "raw_metrics": raw, "adjusted_metrics": {"profit_factor": pf_adj, "payoff_ratio": payoff_adj, "prior_trades": prior}, "bootstrap": boot, "trades": all_trades})
        window_matrix[strategy_id] = per_window

    funding = {s: current_funding(s) for s in SYMBOLS}
    funding_ok = all(v.get("state") == "PASS" for v in funding.values())
    stress = []
    for row in candidate_rows:
        base_returns = [float(t["net_return_pct"]) for t in row["trades"]]
        for fee_mult in (1.0, 1.5, 2.0):
            for slip_mult in (1.0, 1.5, 2.0):
                for funding_scenario in ("OBSERVED", "ADVERSE_P75", "ADVERSE_P95"):
                    for latency in ("NEXT_BAR_OPEN", "PLUS_ONE_BAR"):
                        extra_cost = (fee_mult - 1.0) * 0.04 * 2 + (slip_mult - 1.0) * 0.04 * 2
                        if latency == "PLUS_ONE_BAR":
                            extra_cost += 0.03
                        stressed = [v - extra_cost for v in base_returns]
                        stress.append({"strategy_id": row["strategy_id"], "fee_mult": fee_mult, "slippage_mult": slip_mult, "funding_scenario": funding_scenario, "latency_scenario": latency, "metrics": stats(stressed), "model_note": "PLUS_ONE_BAR uses conservative 3bp penalty; funding rate artifact is observed public snapshot and not yet historical per-trade accrual"})

    fdr = bh_fdr(p_values)
    pbo = approximate_pbo(window_matrix)
    min_trades = int(ssot["data_adequacy"]["min_fresh_trades_per_promoted_candidate"])
    enough_candidates = [r for r in candidate_rows if r["raw_metrics"]["trade_count"] >= min_trades]
    if len(FRESH_WINDOWS) < int(ssot["data_adequacy"]["min_distinct_fresh_windows"]): blockers.append("FRESH_WINDOWS_LT_MIN")
    if len(SEALED_WINDOWS) < 2: blockers.append("SEALED_WINDOWS_LT_2")
    if not enough_candidates: blockers.append("NO_CANDIDATE_WITH_MIN_FRESH_TRADES")
    if mfe_total == 0 or mfe_complete != mfe_total: blockers.append(f"MFE_MAE_INCOMPLETE:{mfe_complete}/{mfe_total}")
    if not funding_ok: blockers.append("FUNDING_OBSERVED_SNAPSHOT_INCOMPLETE")
    if any(r["bootstrap"].get("state") != "PASS" for r in candidate_rows): blockers.append("STATISTICAL_BOOTSTRAP_INCOMPLETE")
    if pbo.get("state") != "PASS" or not pbo.get("pass", False): blockers.append("PBO_NOT_PASS")
    blockers.append("FUNDING_HISTORY_AND_TRUE_PLUS_ONE_BAR_REPLAY_NOT_IMPLEMENTED")

    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "window_manifest.json", {"windows": manifest, "fresh_roles": list(FRESH_WINDOWS), "sealed_roles": list(SEALED_WINDOWS), "sealed_usage": "HASH_AND_INTEGRITY_ONLY_NOT_REPLAYED"})
    atomic_json(out / "candidate_evidence.json", {"candidates": candidate_rows})
    atomic_json(out / "cost_stress_grid.json", {"rows": stress, "funding": funding})
    atomic_json(out / "statistics.json", {"bh_fdr": fdr, "pbo": pbo})
    summary = {"schema_version": "1.0", "authority": "READ_ONLY_BASELINE_EVIDENCE_NO_REPAIR", "state": "PASS" if not blockers else "HOLD", "fresh_window_count": len(FRESH_WINDOWS), "sealed_holdback_count": len(SEALED_WINDOWS), "candidate_count": len(candidate_rows), "candidates_with_min_fresh_trades": len(enough_candidates), "trade_count_total": mfe_total, "mfe_mae_complete": mfe_complete == mfe_total and mfe_total > 0, "cost_grid_rows": len(stress), "funding_snapshot_complete": funding_ok, "statistics": {"bootstrap_complete": all(r["bootstrap"].get("state") == "PASS" for r in candidate_rows), "bh_fdr_tests": fdr["tests"], "pbo": pbo}, "gemini_allowed": False if blockers else True, "auto_improvement_allowed": False if blockers else True, "blockers": sorted(set(blockers)), "next": "DATA_ADEQUACY_PASS_THEN_GEMINI" if not blockers else "HOLD_BUILD_MISSING_EVIDENCE"}
    atomic_json(out / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
