from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

sys.path.insert(0, "/home/z/z")

STRATEGY_DIR = Path("/home/z/z/backend/strategies")
DATA_DIR = Path("/home/z/z/data/oos_a1/bingx_public")
OUT = Path("/home/z/z/runtime/q4r3_route_c_semantic_audit_latest.json")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"]
WINDOW = 120
TUNING_START = pd.Timestamp("2026-06-29 19:30:00", tz="UTC")
TUNING_END = pd.Timestamp("2026-07-06 18:09:00", tz="UTC")

FAMILIES: Dict[str, Dict[str, List[str]]] = {
    "C1_SQUEEZE_EXPANSION_BREAKOUT": {
        "core": [
            "squeeze", "compression", "expansion", "bollinger", "keltner",
            "bandwidth", "volatility contraction", "volatility expansion",
            "breakout", "release",
        ],
        "confirm": [
            "atr", "volume", "momentum", "close_location", "range",
            "body", "retest", "continuation",
        ],
    },
    "C2_DONCHIAN_TURTLE_BREAKOUT": {
        "core": [
            "donchian", "turtle", "channel_high", "channel_low",
            "highest", "lowest", "rolling_high", "rolling_low",
            "range breakout", "breakout",
        ],
        "confirm": [
            "atr", "n_value", "trend", "pyramid", "retest", "volume",
            "lookback", "channel",
        ],
    },
    "C3_VOLUME_TREND_CONTINUATION": {
        "core": [
            "obv", "on_balance_volume", "volume trend", "volume impulse",
            "money flow", "mfi", "relative volume", "rvol",
            "momentum continuation", "trend continuation",
        ],
        "confirm": [
            "ema", "slope", "macd", "breakout", "atr", "reclaim",
            "higher_high", "lower_low",
        ],
    },
}

GENERIC_TOKENS = {
    "beam", "long_beam", "short_beam", "entry", "signal", "hold",
    "risk", "stop", "take_profit", "strategy", "side", "price",
}
MEAN_REVERSION_TOKENS = [
    "mean_revert", "mean reversion", "reversion", "oversold", "overbought",
    "fade", "vwap deviation", "zscore", "z_score", "liquidity sweep",
    "support", "resistance", "pivot reversal",
]


def read_strategy_scope(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    lines = source.splitlines()
    chunks: List[str] = []
    for node in tree.body:
        include = isinstance(node, (ast.ClassDef, ast.Assign, ast.AnnAssign))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            include = node.name == "strategy"
        if not include or not hasattr(node, "lineno"):
            continue
        start = max(0, int(node.lineno) - 1)
        end = int(getattr(node, "end_lineno", node.lineno))
        chunks.append("\n".join(lines[start:end]))
    return "\n\n".join(chunks) if chunks else source


def count_token(text: str, token: str) -> int:
    return text.lower().count(token.lower())


def family_score(scope: str, family: str) -> Dict[str, Any]:
    spec = FAMILIES[family]
    core_hits = {
        token: count_token(scope, token)
        for token in spec["core"]
        if token not in GENERIC_TOKENS and count_token(scope, token) > 0
    }
    confirm_hits = {
        token: count_token(scope, token)
        for token in spec["confirm"]
        if token not in GENERIC_TOKENS and count_token(scope, token) > 0
    }
    reversion_hits = {
        token: count_token(scope, token)
        for token in MEAN_REVERSION_TOKENS
        if count_token(scope, token) > 0
    }
    core_unique = len(core_hits)
    confirm_unique = len(confirm_hits)
    raw = core_unique * 4 + min(sum(core_hits.values()), 8)
    raw += confirm_unique * 2 + min(sum(confirm_hits.values()), 6)
    penalty = 6 if len(reversion_hits) >= 3 and core_unique < 3 else 0
    score = max(0, raw - penalty)
    identity = (
        "strong" if core_unique >= 3 and score >= 18
        else "medium" if core_unique >= 2 and score >= 10
        else "weak"
    )
    return {
        "family": family,
        "score": score,
        "identity": identity,
        "core_hits": core_hits,
        "confirm_hits": confirm_hits,
        "mean_reversion_hits": reversion_hits,
        "penalty": penalty,
    }


def load_1m(symbol: str) -> pd.DataFrame:
    obj = json.loads(
        (DATA_DIR / f"{symbol}_1m_30d_isolated.json").read_text(errors="ignore")
    )
    rows: List[Dict[str, Any]] = []
    for row in obj.get("rows", []):
        if not isinstance(row, list) or len(row) < 6:
            continue
        ts = int(float(row[0]))
        if abs(ts) < 100_000_000_000:
            ts *= 1000
        rows.append({
            "ts": ts,
            "ts_dt": pd.to_datetime(ts, unit="ms", utc=True),
            "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]),
            "volume": float(row[5]),
        })
    return (
        pd.DataFrame(rows).sort_values("ts_dt")
        .drop_duplicates("ts_dt", keep="last").reset_index(drop=True)
    )


def make_15m(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["bucket"] = data["ts_dt"].dt.floor("15min")
    bars = data.groupby("bucket").agg(
        ts=("ts", "last"), open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
        count=("ts", "count"), min_dt=("ts_dt", "min"), max_dt=("ts_dt", "max"),
    ).reset_index()
    bars["span_min"] = (bars["max_dt"] - bars["min_dt"]).dt.total_seconds() / 60.0
    bars["complete"] = (bars["count"] == 15) & bars["span_min"].between(13.5, 14.5)
    return bars.reset_index(drop=True)


def contiguous(window: pd.DataFrame) -> bool:
    if len(window) != WINDOW or not bool(window["complete"].all()):
        return False
    return bool((window["bucket"].diff().dt.total_seconds().dropna() == 900).all())


def strict_oos(window: pd.DataFrame) -> bool:
    return window["max_dt"].iloc[-1] < TUNING_START or window["min_dt"].iloc[0] > TUNING_END


def invoke(strategy_fn: Any, frame: pd.DataFrame) -> Any:
    signature = inspect.signature(strategy_fn)
    kwargs: Dict[str, Any] = {}
    if "state" in signature.parameters:
        kwargs["state"] = {}
    if "risk_action" in signature.parameters:
        kwargs["risk_action"] = "hold"
    return strategy_fn(frame, **kwargs)


def signal_contract(module_name: str, bars_by_symbol: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "module": module_name, "import_error": None,
        "strategy_signature": None, "by_symbol": {}, "aggregate": {},
    }
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        report["import_error"] = repr(exc)
        return report
    strategy_fn = getattr(module, "strategy", None)
    if not callable(strategy_fn):
        report["import_error"] = "STRATEGY_CALLABLE_MISSING"
        return report
    report["strategy_signature"] = str(inspect.signature(strategy_fn))
    aggregate = Counter()
    columns = ["ts", "open", "high", "low", "close", "volume"]
    for symbol, bars in bars_by_symbol.items():
        counts = Counter()
        reasons = Counter()
        errors: List[str] = []
        for end_i in range(WINDOW, len(bars) + 1):
            window = bars.iloc[end_i - WINDOW:end_i]
            if not contiguous(window) or not strict_oos(window):
                continue
            try:
                result = invoke(strategy_fn, window[columns].copy())
            except Exception as exc:
                counts["strategy_error"] += 1
                if len(errors) < 5:
                    errors.append(repr(exc))
                continue
            counts["windows"] += 1
            if not isinstance(result, dict):
                counts["invalid_result"] += 1
                continue
            action = str(result.get("action", "")).lower()
            side = str(result.get("side", "")).lower()
            reason = str(result.get("why", result.get("reason", "UNKNOWN")))
            reasons[reason] += 1
            if action in {"", "hold", "none"}:
                counts["hold"] += 1
                continue
            counts["enter"] += 1
            counts[f"side:{side}"] += 1
            try:
                entry, sl, tp = map(float, (result.get("entry"), result.get("sl"), result.get("tp")))
                valid = (side == "long" and sl < entry < tp) or (side == "short" and tp < entry < sl)
                if valid:
                    counts["native_exit_valid"] += 1
            except Exception:
                pass
        report["by_symbol"][symbol] = {
            **dict(counts), "reason_top15": reasons.most_common(15), "errors": errors,
        }
        aggregate.update(counts)
    enter = int(aggregate.get("enter", 0))
    valid = int(aggregate.get("native_exit_valid", 0))
    report["aggregate"] = {
        **dict(aggregate),
        "active_symbols": sum(1 for row in report["by_symbol"].values() if int(row.get("enter", 0)) > 0),
        "native_exit_valid_rate_pct": round(valid / enter * 100.0, 3) if enter else 0.0,
    }
    return report


def discover() -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for path in sorted(STRATEGY_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        source = path.read_text(errors="ignore")
        scope = read_strategy_scope(source)
        family_reports = [family_score(scope, family) for family in FAMILIES]
        best = max(family_reports, key=lambda row: int(row["score"]))
        if int(best["score"]) < 8:
            continue
        candidates.append({
            "path": str(path), "module": f"backend.strategies.{path.stem}",
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
            "best_family": best["family"], "best_score": best["score"],
            "best_identity": best["identity"], "family_reports": family_reports,
        })
    return candidates


def main() -> None:
    candidates = discover()
    bars_by_symbol = {symbol: make_15m(load_1m(symbol)) for symbol in SYMBOLS}
    reports = [{**candidate, "contract": signal_contract(candidate["module"], bars_by_symbol)} for candidate in candidates]
    ranked_by_family: Dict[str, List[Dict[str, Any]]] = {}
    selected: Dict[str, Any] = {}
    for family in FAMILIES:
        rows = [row for row in reports if row["best_family"] == family]
        rows.sort(key=lambda row: (
            int(row["best_score"]),
            int(row["contract"]["aggregate"].get("active_symbols", 0)),
            float(row["contract"]["aggregate"].get("native_exit_valid_rate_pct", 0.0)),
            -int(row["contract"]["aggregate"].get("strategy_error", 0)),
        ), reverse=True)
        ranked_by_family[family] = rows
        selected[family] = rows[0] if rows else None

    hard_fail: List[str] = []
    for family, row in selected.items():
        if row is None:
            hard_fail.append(f"{family}:NO_CANDIDATE")
            continue
        aggregate = row["contract"]["aggregate"]
        if int(aggregate.get("strategy_error", 0)) > 0:
            hard_fail.append(f"{family}:RUNTIME_ERROR")
        if int(aggregate.get("enter", 0)) == 0:
            hard_fail.append(f"{family}:NO_SIGNALS")
        if float(aggregate.get("native_exit_valid_rate_pct", 0.0)) < 95.0:
            hard_fail.append(f"{family}:NATIVE_EXIT_CONTRACT_WEAK")

    status = "PASS_Q4R3_ROUTE_C_SEMANTIC_AUDIT" if not hard_fail else "HOLD_Q4R3_ROUTE_C_SEMANTIC_AUDIT"
    payload = {
        "status": status,
        "scope": "Route C breakout/momentum identity and 5-symbol strict OOS signal-contract audit",
        "route_definition": {
            "C1": "squeeze/compression expansion breakout",
            "C2": "Donchian/Turtle channel breakout",
            "C3": "volume-confirmed trend continuation",
        },
        "candidate_files_found": len(candidates),
        "selected_by_family": selected,
        "ranked_by_family": ranked_by_family,
        "hard_fail": sorted(set(hard_fail)),
        "data_contract": {"symbols": SYMBOLS, "timeframe": "15m", "window_bars": WINDOW, "strict_oos": True},
        "order_authority": "blocked", "execution_authority": "none",
        "real_order_enabled": False, "paper_request_written": False,
        "live_execution_allowed": False,
        "next": "Verify one semantic candidate per family, then run independent native-exit PnL replay. Do not rank by signal count alone.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": status,
        "candidate_files_found": len(candidates),
        "selected_by_family": {
            family: ({
                "module": row["module"], "score": row["best_score"],
                "identity": row["best_identity"], "aggregate": row["contract"]["aggregate"],
            } if row else None)
            for family, row in selected.items()
        },
        "hard_fail": payload["hard_fail"], "out": str(OUT),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
