from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from backend.tools.strategy11_long_short_observer_v3 import replay as observer_replay
from backend.tools.strategy11_regime_edge_router_v3 import classify_regime
from backend.tools.strategy11_supertrend_authentic_child_v1 import authentic_supertrend

VERSION = "STRATEGY11_SUPERTREND_PARENT_BASIS_V1"
PARENTS = ("supertrend_pullback", "trend_rider")
EXPECTED_SYMBOLS = ("XRPUSDT", "SOLUSDT")
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{name}:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_registry(root: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(root / "backend/strategy25/canonical_strategy_registry_v1.json")
    entries = [row for row in payload.get("entries", []) if isinstance(row, dict)]
    output = {str(row.get("strategy_id")): row for row in entries}
    if payload.get("fail_closed") is not True or len(output) != 25:
        raise RuntimeError("CANONICAL_REGISTRY_INVALID")
    return output


def find_strategy_json(root: Path, strategy_id: str, filename: str) -> Path:
    matches = [path for path in root.rglob(filename) if path.parent.name == strategy_id]
    if len(matches) != 1:
        raise RuntimeError(f"STRATEGY_FILE_CARDINALITY:{strategy_id}:{filename}:{len(matches)}")
    return matches[0]


def stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        trades,
        key=lambda row: (
            str(row.get("window_id") or ""),
            str(row.get("entry_ts") or ""),
            str(row.get("symbol") or ""),
            str(row.get("side") or ""),
        ),
    )
    values = [float(row["net_return_pct"]) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    cumulative = peak = drawdown = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    gross_loss = abs(sum(losses))
    average_win = sum(wins) / len(wins) if wins else None
    average_loss = abs(sum(losses) / len(losses)) if losses else None
    return {
        "trade_count": len(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0,
        "net_return_pct_sum": sum(values),
        "net_profit_factor": sum(wins) / gross_loss if gross_loss > 1e-12 else (999.0 if wins else 0.0),
        "payoff_ratio": average_win / average_loss if average_win is not None and average_loss not in (None, 0.0) else 0.0,
        "max_drawdown_pct": drawdown,
    }


class CachedParentChild:
    def __init__(self, module: Any, strategy: Any) -> None:
        self.module = module
        self.strategy = strategy
        self.original_supertrend = getattr(module, "_supertrend", None)
        self.original_ema = getattr(module, "_ema", None)
        if not callable(self.original_supertrend):
            raise RuntimeError("PARENT_SUPERTREND_MISSING")
        self.context = ("", "")
        self.supertrend_cache: dict[tuple[Any, ...], pd.DataFrame] = {}
        self.ema_cache: dict[tuple[Any, ...], pd.Series] = {}
        self.regime_cache: dict[tuple[Any, ...], str] = {}
        self.decision_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self.counts: Counter[str] = Counter()
        self.hold_reasons: Counter[str] = Counter()
        setattr(module, "_supertrend", self._supertrend)
        if callable(self.original_ema):
            setattr(module, "_ema", self._ema)

    def prepare(self, window_id: str, symbol: str) -> None:
        self.context = (window_id, symbol)

    def _key(self, value: pd.DataFrame | pd.Series) -> tuple[Any, ...]:
        if len(value) == 0:
            return (*self.context, 0, None, None)
        index = value.index
        return (*self.context, len(value), repr(index[0]), repr(index[-1]))

    def _supertrend(self, frame: pd.DataFrame, length: int, multiplier: float) -> pd.DataFrame:
        key = (*self._key(frame), int(length), float(multiplier))
        cached = self.supertrend_cache.get(key)
        if cached is None:
            raw = authentic_supertrend(frame, length=int(length), multiplier=float(multiplier))
            cached = raw[["supertrend", "direction", "atr"]].copy(deep=True)
            self.supertrend_cache[key] = cached
        else:
            self.counts["cache_hit:supertrend"] += 1
        output = cached.copy(deep=True)
        output.index = frame.index
        return output

    def _ema(self, series: pd.Series, length: int) -> pd.Series:
        key = (*self._key(series), int(length))
        cached = self.ema_cache.get(key)
        if cached is None:
            cached = self.original_ema(series, int(length)).copy(deep=True)
            self.ema_cache[key] = cached
        else:
            self.counts["cache_hit:ema"] += 1
        output = cached.copy(deep=True)
        output.index = series.index
        return output

    @staticmethod
    def _state_key(state: Mapping[str, Any] | None) -> str:
        return json.dumps(dict(state or {}), sort_keys=True, separators=(",", ":"), default=str)

    def __call__(self, history: pd.DataFrame, state: Mapping[str, Any] | None = None, risk_action: str = "hold") -> dict[str, Any]:
        base_key = self._key(history)
        state_key = self._state_key(state)
        decision_key = (*base_key, state_key, str(risk_action))
        cached = self.decision_cache.get(decision_key)
        if cached is not None:
            self.counts["cache_hit:decision"] += 1
            return copy.deepcopy(cached)
        regime = self.regime_cache.get(base_key)
        if regime is None:
            regime = classify_regime(history)
            self.regime_cache[base_key] = regime
        else:
            self.counts["cache_hit:regime"] += 1
        result = self.strategy(history, state=dict(state or {}), risk_action=risk_action)
        if not isinstance(result, dict):
            raise RuntimeError("PARENT_RESULT_NOT_DICT")
        action = str(result.get("action") or "hold").lower()
        side = str(result.get("side") or "none").lower()
        self.counts["calls"] += 1
        self.counts[f"regime:{regime}"] += 1
        self.counts[f"action:{action}"] += 1
        self.counts[f"side:{side}"] += 1
        if action == "hold":
            self.hold_reasons[str(result.get("why") or "unknown")] += 1
        self.decision_cache[decision_key] = copy.deepcopy(result)
        return result

    def diagnostics(self) -> dict[str, Any]:
        return {
            "counts": dict(sorted(self.counts.items())),
            "hold_reasons": dict(self.hold_reasons.most_common()),
            "supertrend_cache_size": len(self.supertrend_cache),
            "ema_cache_size": len(self.ema_cache),
            "regime_cache_size": len(self.regime_cache),
            "decision_cache_size": len(self.decision_cache),
        }


def annotate(trades: list[dict[str, Any]], window_id: str, symbol: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for trade in trades:
        row = dict(trade)
        row["window_id"] = window_id
        row["symbol"] = symbol
        output.append(row)
    return output


def replay_phase(
    wrapper: CachedParentChild,
    frames: list[tuple[str, str, pd.DataFrame]],
    *,
    warmup_bars: int,
    cost_bps_per_side: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for window_id, symbol, frame in frames:
        wrapper.prepare(window_id, symbol)
        result = observer_replay(
            frame,
            wrapper,
            warmup_bars=warmup_bars,
            history_bars=220,
            cost_bps_per_side=cost_bps_per_side,
        )
        tagged = annotate(result["trades"], window_id, symbol)
        trades.extend(tagged)
        rows.append({
            "window_id": window_id,
            "symbol": symbol,
            "combined": stats(tagged),
            "long": stats([row for row in tagged if row["side"] == "long"]),
            "short": stats([row for row in tagged if row["side"] == "short"]),
            "ignored_add_reduce": int(result["ignored_add_reduce"]),
        })
    return {"rows": rows, "trades": trades, "combined": stats(trades)}


def parent_result(
    strategy_id: str,
    *,
    compute_root: Path,
    archive_root: Path,
    evidence_root: Path,
    control_root: Path,
) -> dict[str, Any]:
    registry = load_registry(compute_root)
    canonical = registry[strategy_id]["canonical_engine"]
    source_path = compute_root / str(canonical["implementation_path"])
    source_sha = file_sha(source_path)
    if source_sha != str(canonical["source_sha256"]):
        raise RuntimeError(f"PARENT_SOURCE_SHA_MISMATCH:{strategy_id}")
    module = load_module(f"s11_parent_basis_{strategy_id}", source_path)
    strategy = getattr(module, "strategy", None)
    if not callable(strategy):
        raise RuntimeError(f"PARENT_STRATEGY_MISSING:{strategy_id}")
    evidence = read_json(find_strategy_json(evidence_root, strategy_id, "summary.json"))
    symbols = tuple(map(str, evidence.get("symbols") or []))
    if symbols != EXPECTED_SYMBOLS:
        raise RuntimeError(f"PARENT_SYMBOL_AUTHORITY:{strategy_id}:{symbols}")
    control = read_json(find_strategy_json(control_root, strategy_id, "result.json"))
    if control.get("archive_sha256") != read_json(archive_root / "manifest.json")["archive_sha256"]:
        raise RuntimeError(f"CONTROL_ARCHIVE_MISMATCH:{strategy_id}")
    control_row = dict(control["control"])
    expected_reason = "st_pullback_indicator_nan" if strategy_id == "supertrend_pullback" else "trend_rider_indicator_nan"
    if control_row.get("opportunity_diagnostics", {}).get("hold_reasons", {}).get(expected_reason) != 16296:
        raise RuntimeError(f"CONTROL_NAN_AUTHORITY:{strategy_id}")
    manifest = read_json(archive_root / "manifest.json")
    frames: list[tuple[str, str, pd.DataFrame]] = []
    for item in manifest["rows"]:
        symbol = str(item["symbol"])
        if symbol not in symbols:
            continue
        frame = pd.read_csv(archive_root / str(item["path"]))
        frames.append((str(item["window_id"]), symbol, frame))
    if len(frames) != 24:
        raise RuntimeError(f"PARENT_FRAME_COUNT:{strategy_id}:{len(frames)}")
    wrapper = CachedParentChild(module, strategy)
    normal_a = replay_phase(wrapper, frames, warmup_bars=int(manifest["warmup_bars"]), cost_bps_per_side=4.0)
    first_diagnostics = wrapper.diagnostics()
    normal_b = replay_phase(wrapper, frames, warmup_bars=int(manifest["warmup_bars"]), cost_bps_per_side=4.0)
    if stable_sha(normal_a) != stable_sha(normal_b):
        raise RuntimeError(f"PARENT_AB_PARITY:{strategy_id}")
    stress = replay_phase(wrapper, frames, warmup_bars=int(manifest["warmup_bars"]), cost_bps_per_side=8.0)
    keys = [
        (row["window_id"], row["symbol"], row["side"], row["entry_ts"], row["exit_ts"])
        for row in normal_a["trades"]
    ]
    duplicate_count = len(keys) - len(set(keys))
    if duplicate_count:
        raise RuntimeError(f"PARENT_DUPLICATES:{strategy_id}:{duplicate_count}")
    windows = {
        window_id: stats([row for row in normal_a["trades"] if row["window_id"] == window_id])
        for window_id in sorted({row["window_id"] for row in normal_a["trades"]})
    }
    symbols_stats = {
        symbol: stats([row for row in normal_a["trades"] if row["symbol"] == symbol])
        for symbol in symbols
    }
    combined = normal_a["combined"]
    positive_windows = sum(float(row["net_return_pct_sum"]) > 0 for row in windows.values())
    positive_symbols = sum(float(row["net_return_pct_sum"]) > 0 for row in symbols_stats.values())
    if combined["trade_count"] == 0:
        economic_state = "BASIS_REPAIR_NO_TRADES"
    elif (
        combined["net_return_pct_sum"] > 0
        and combined["net_profit_factor"] > 1.0
        and positive_windows >= 6
        and positive_symbols >= 1
        and combined["max_drawdown_pct"] <= 10.0
        and stress["combined"]["net_return_pct_sum"] > 0
    ):
        economic_state = "HOLD_BASIS_EDGE_DISCOVERY"
    else:
        economic_state = "REJECT_BASIS_ECONOMICS"
    result = {
        "strategy_id": strategy_id,
        "parent_source_path": str(canonical["implementation_path"]),
        "parent_source_sha256": source_sha,
        "parent_symbols": list(symbols),
        "basis_change": "IN_MEMORY_ONLY_SUPERTREND_TO_TRUE_RANGE_WILDER_RMA_ATR10_HL2_MULT3_FIRST_VALID_SEED",
        "change_budget": 1,
        "legacy_parent_modified": False,
        "control": {
            "trade_count": int(control_row["trade_count"]),
            "indicator_nan_count": int(control_row["opportunity_diagnostics"]["hold_reasons"][expected_reason]),
            "result_sha256": str(control["result_sha256"]),
        },
        "repaired": {
            "combined": combined,
            "long": stats([row for row in normal_a["trades"] if row["side"] == "long"]),
            "short": stats([row for row in normal_a["trades"] if row["side"] == "short"]),
            "stress_2x_cost": stress["combined"],
            "positive_window_count": positive_windows,
            "positive_symbol_count": positive_symbols,
            "window_stats": windows,
            "symbol_stats": symbols_stats,
            "opportunity_diagnostics": first_diagnostics,
            "duplicate_trade_count": duplicate_count,
            "ab_parity": "PASS",
            "trade_sha256": stable_sha(normal_a["trades"]),
        },
        "economic_state": economic_state,
        "fresh_confirmation_required": True,
        "w1_w2_w3_new_sealed_required": True,
        **SAFETY,
    }
    result["result_sha256"] = stable_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compute-root", required=True)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--control-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    compute_root = Path(args.compute_root).resolve()
    archive_root = Path(args.archive_root).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    control_root = Path(args.control_root).resolve()
    rows = [
        parent_result(
            strategy_id,
            compute_root=compute_root,
            archive_root=archive_root,
            evidence_root=evidence_root,
            control_root=control_root,
        )
        for strategy_id in PARENTS
    ]
    output = {
        "schema_version": "strategy11.supertrend_parent_basis.v1",
        "version": VERSION,
        "state": "PASS_SUPERTREND_PARENT_BASIS_DECOMPOSITION",
        "archive_sha256": read_json(archive_root / "manifest.json")["archive_sha256"],
        "parent_count": len(rows),
        "rows": rows,
        "canonical_parent_mutation_count": 0,
        "next": "W1_FRESH_CONFIRMATION_OR_SINGLE_AXIS_ENTRY_QUALITY_ONLY_FOR_HOLD_ROWS",
        **SAFETY,
    }
    output["result_sha256"] = stable_sha(output)
    out = Path(args.out).resolve()
    write_json(out / "final.json", output)
    for row in rows:
        write_json(out / f"{row['strategy_id']}.json", row)
    print(json.dumps({
        "state": output["state"],
        "rows": [
            {
                "strategy": row["strategy_id"],
                "economic_state": row["economic_state"],
                **row["repaired"]["combined"],
                "positive_windows": row["repaired"]["positive_window_count"],
                "stress_net": row["repaired"]["stress_2x_cost"]["net_return_pct_sum"],
            }
            for row in rows
        ],
        "sha": output["result_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
