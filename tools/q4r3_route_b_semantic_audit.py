from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

sys.path.insert(0, "/home/z/z")

STRATEGY_DIR = Path("/home/z/z/backend/strategies")
DATA_DIR = Path("/home/z/z/data/oos_a1/bingx_public")
OUT = Path("/home/z/z/runtime/q4r3_route_b_semantic_audit_latest.json")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"]
WINDOW = 120

TUNING_START = pd.Timestamp("2026-06-29 19:30:00", tz="UTC")
TUNING_END = pd.Timestamp("2026-07-06 18:09:00", tz="UTC")

FAMILIES: Dict[str, Dict[str, List[str]]] = {
    "B1_VWAP_DEVIATION_REVERSION": {
        "core": [
            "vwap", "anchored_vwap", "avwap", "zscore", "z_score",
            "standard deviation", "std", "deviation", "band",
            "mean_revert", "mean reversion", "reversion",
        ],
        "confirm": [
            "overbought", "oversold", "rsi", "mfi", "distance",
            "extension", "reclaim", "cross", "volume",
        ],
    },
    "B2_STRUCTURE_RECLAIM": {
        "core": [
            "support", "resistance", "pivot", "swing_high", "swing_low",
            "zone", "reclaim", "rejection", "retest",
        ],
        "confirm": [
            "wick", "touch", "close_location", "atr", "volume",
            "range", "neutral", "chop",
        ],
    },
    "B3_LIQUIDITY_SWEEP_REVERSAL": {
        "core": [
            "liquidity", "sweep", "stop_hunt", "stop hunt",
            "previous_high", "previous_low", "equal_high", "equal_low",
        ],
        "confirm": [
            "wick", "reclaim", "rejection", "volume", "atr",
            "false_break", "failed_break", "close_back",
        ],
    },
}

GENERIC_TOKENS = {
    "beam", "long_beam", "short_beam", "trend", "entry", "signal",
    "hold", "risk", "stop", "take_profit", "strategy",
}

TREND_BREAKOUT_TOKENS = [
    "donchian", "breakout", "trend_follow", "momentum_continuation",
    "ema_stack", "ribbon_expansion",
]


def read_strategy_scope(source: str) -> str:
    """Return Config/classes plus strategy() body, excluding unrelated helpers."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    lines = source.splitlines()
    chunks: List[str] = []

    for node in tree.body:
        include = False
        if isinstance(node, (ast.ClassDef, ast.Assign, ast.AnnAssign)):
            include = True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            include = node.name == "strategy"

        if not include or not hasattr(node, "lineno"):
            continue

        start = max(0, int(node.lineno) - 1)
        end = int(getattr(node, "end_lineno", node.lineno))
        chunks.append("\n".join(lines[start:end]))

    return "\n\n".join(chunks) if chunks else source


def count_token(text: str, token: str) -> int:
    lowered = text.lower()
    return lowered.count(token.lower())


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
    trend_hits = {
        token: count_token(scope, token)
        for token in TREND_BREAKOUT_TOKENS
        if count_token(scope, token) > 0
    }

    core_unique = len(core_hits)
    confirm_unique = len(confirm_hits)
    raw = core_unique * 4 + min(sum(core_hits.values()), 8)
    raw += confirm_unique * 2 + min(sum(confirm_hits.values()), 6)

    # A mean-reversion module may contain breakout vetoes. Penalize only when
    # trend/breakout language materially dominates its core identity.
    penalty = 0
    if len(trend_hits) >= 3 and core_unique < 3:
        penalty = 5

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
        "trend_breakout_hits": trend_hits,
        "penalty": penalty,
    }


def load_1m(symbol: str) -> pd.DataFrame:
    path = DATA_DIR / f"{symbol}_1m_30d_isolated.json"
    obj = json.loads(path.read_text(errors="ignore"))
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
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })

    frame = pd.DataFrame(rows)
    return (
        frame.sort_values("ts_dt")
        .drop_duplicates("ts_dt", keep="last")
        .reset_index(drop=True)
    )


def make_15m(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["bucket"] = data["ts_dt"].dt.floor("15min")
    bars = data.groupby("bucket").agg(
        ts=("ts", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        count=("ts", "count"),
        min_dt=("ts_dt", "min"),
        max_dt=("ts_dt", "max"),
    ).reset_index()
    bars["span_min"] = (
        bars["max_dt"] - bars["min_dt"]
    ).dt.total_seconds() / 60.0
    bars["complete"] = (
        (bars["count"] == 15)
        & bars["span_min"].between(13.5, 14.5)
    )
    return bars.reset_index(drop=True)


def contiguous(window: pd.DataFrame) -> bool:
    if len(window) != WINDOW or not bool(window["complete"].all()):
        return False
    diffs = window["bucket"].diff().dt.total_seconds().dropna()
    return bool((diffs == 900).all())


def strict_oos(window: pd.DataFrame) -> bool:
    start = window["min_dt"].iloc[0]
    end = window["max_dt"].iloc[-1]
    return end < TUNING_START or start > TUNING_END


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
        "module": module_name,
        "import_error": None,
        "strategy_signature": None,
        "by_symbol": {},
        "aggregate": {},
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
                entry = float(result.get("entry"))
                sl = float(result.get("sl"))
                tp = float(result.get("tp"))
                valid = (
                    side == "long" and sl < entry < tp
                ) or (
                    side == "short" and tp < entry < sl
                )
                if valid:
                    counts["native_exit_valid"] += 1
            except Exception:
                pass

        report["by_symbol"][symbol] = {
            **dict(counts),
            "reason_top15": reasons.most_common(15),
            "errors": errors,
        }
        aggregate.update(counts)

    enter = int(aggregate.get("enter", 0))
    valid = int(aggregate.get("native_exit_valid", 0))
    report["aggregate"] = {
        **dict(aggregate),
        "active_symbols": sum(
            1 for row in report["by_symbol"].values()
            if int(row.get("enter", 0)) > 0
        ),
        "native_exit_valid_rate_pct": (
            round(valid / enter * 100.0, 3) if enter else 0.0
        ),
    }
    return report


def discover() -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    for path in sorted(STRATEGY_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue

        source = path.read_text(errors="ignore")
        scope = read_strategy_scope(source)
        family_reports = [
            family_score(scope, family)
            for family in FAMILIES
        ]
        best = max(family_reports, key=lambda row: int(row["score"]))

        if int(best["score"]) < 8:
            continue

        candidates.append({
            "path": str(path),
            "module": f"backend.strategies.{path.stem}",
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
            "best_family": best["family"],
            "best_score": best["score"],
            "best_identity": best["identity"],
            "family_reports": family_reports,
        })

    return candidates


def main() -> None:
    candidates = discover()
    bars_by_symbol = {
        symbol: make_15m(load_1m(symbol))
        for symbol in SYMBOLS
    }

    reports: List[Dict[str, Any]] = []
    for candidate in candidates:
        contract = signal_contract(candidate["module"], bars_by_symbol)
        reports.append({**candidate, "contract": contract})

    ranked_by_family: Dict[str, List[Dict[str, Any]]] = {}
    for family in FAMILIES:
        rows = [row for row in reports if row["best_family"] == family]
        rows.sort(
            key=lambda row: (
                int(row["best_score"]),
                int(row["contract"].get("aggregate", {}).get("active_symbols", 0)),
                float(row["contract"].get("aggregate", {}).get("native_exit_valid_rate_pct", 0.0)),
            ),
            reverse=True,
        )
        ranked_by_family[family] = rows

    best_existing = {
        family: (rows[0] if rows else None)
        for family, rows in ranked_by_family.items()
    }

    runnable = [
        row for row in reports
        if row["contract"].get("import_error") is None
        and int(row["contract"].get("aggregate", {}).get("strategy_error", 0)) == 0
        and int(row["contract"].get("aggregate", {}).get("enter", 0)) > 0
    ]

    payload = {
        "status": (
            "PASS_Q4R3_ROUTE_B_SEMANTIC_AUDIT"
            if runnable else "HOLD_Q4R3_ROUTE_B_NO_RUNNABLE_CANDIDATE"
        ),
        "scope": (
            "Route B research identity audit: VWAP deviation reversion, "
            "structure reclaim, liquidity sweep reversal"
        ),
        "route_b_definition": {
            "B1": "VWAP/AVWAP deviation mean reversion",
            "B2": "support-resistance/pivot reclaim",
            "B3": "liquidity sweep failed-break reversal",
            "not_historical_policy_B": True,
        },
        "candidate_count": len(candidates),
        "runnable_count": len(runnable),
        "best_existing_by_family": best_existing,
        "ranked_by_family": ranked_by_family,
        "all_reports": reports,
        "data_contract": {
            "symbols": SYMBOLS,
            "timeframe": "15m",
            "window_bars": WINDOW,
            "strict_oos": True,
            "source": str(DATA_DIR),
        },
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "paper_request_written": False,
        "live_execution_allowed": False,
        "next": (
            "Freeze one candidate per family by semantic identity first; "
            "then replay B1/B2/B3 independently with native exits and costs."
        ),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    compact = {
        "status": payload["status"],
        "candidate_count": payload["candidate_count"],
        "runnable_count": payload["runnable_count"],
        "best_existing_by_family": {
            family: (
                None if row is None else {
                    "module": row["module"],
                    "score": row["best_score"],
                    "identity": row["best_identity"],
                    "aggregate": row["contract"].get("aggregate", {}),
                }
            )
            for family, row in best_existing.items()
        },
        "out": str(OUT),
    }
    print(json.dumps(compact, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
