from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

VERSION = "ZEL_BINGX_PLUS_ONE_BAR_STRESS_V1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def finite(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise RuntimeError(f"FINITE_REQUIRED:{field}")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RuntimeError(f"FINITE_REQUIRED:{field}")
    return parsed


def verify_receipt(value: Mapping[str, Any], field: str) -> None:
    expected = str(value.get("receipt_sha256") or "")
    material = dict(value)
    material.pop("receipt_sha256", None)
    if not expected or stable_sha(material) != expected:
        raise RuntimeError(f"RECEIPT_SHA_MISMATCH:{field}")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_trades(path: Path, strategy_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("strategy_id") or "") == strategy_id:
                rows.append(row)
    if not rows:
        raise RuntimeError(f"NO_TRADES_FOR_STRATEGY:{strategy_id}")
    return rows


def resolve_source_path(raw: Any, roots: list[Path]) -> Path:
    text = str(raw or "").strip()
    candidates: list[Path] = []
    if text:
        source = Path(text)
        candidates.append(source)
        for root in roots:
            candidates.append(root / text.lstrip("/"))
            candidates.append(root / source.name)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise RuntimeError(f"DATA_SOURCE_NOT_FOUND:{text}")


def timestamp_column(frame: pd.DataFrame) -> str:
    for name in ("timestamp", "datetime", "time", "ts", "open_time"):
        if name in frame.columns:
            return name
    raise RuntimeError("TIMESTAMP_COLUMN_NOT_FOUND")


def open_column(frame: pd.DataFrame) -> str:
    for name in ("open", "open_price", "price_open", "close"):
        if name in frame.columns:
            return name
    raise RuntimeError("OPEN_PRICE_COLUMN_NOT_FOUND")


def load_timeline(paths: list[Path]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_csv(path)
        ts_col = timestamp_column(frame)
        px_col = open_column(frame)
        part = frame[[ts_col, px_col]].copy()
        part.columns = ["timestamp", "next_open"]
        part["timestamp"] = pd.to_datetime(part["timestamp"], utc=True, errors="coerce")
        part["next_open"] = pd.to_numeric(part["next_open"], errors="coerce")
        part = part.dropna(subset=["timestamp", "next_open"])
        parts.append(part)
    if not parts:
        raise RuntimeError("EMPTY_TIMELINE")
    timeline = pd.concat(parts, ignore_index=True)
    timeline = timeline.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return timeline.reset_index(drop=True)


def next_open(timeline: pd.DataFrame, ts: Any) -> float | None:
    target = pd.Timestamp(ts)
    if target.tzinfo is None:
        target = target.tz_localize("UTC")
    else:
        target = target.tz_convert("UTC")
    pos = int(timeline["timestamp"].searchsorted(target, side="right"))
    if pos >= len(timeline):
        return None
    return finite(timeline.iloc[pos]["next_open"], "next_open")


def slippage_bps(observation: Mapping[str, Any], notional: float) -> float:
    floors = [
        row
        for row in observation.get("slippage_floor_bps_by_notional", [])
        if isinstance(row, Mapping)
    ]
    if not floors:
        raise RuntimeError("SLIPPAGE_FLOORS_MISSING")
    normalized = sorted(
        (
            finite(row.get("max_notional_usdt"), "max_notional_usdt"),
            finite(row.get("slippage_bps_one_way"), "slippage_bps_one_way"),
        )
        for row in floors
    )
    for max_notional, bps in normalized:
        if notional <= max_notional:
            return bps
    return normalized[-1][1]


def build_stress(
    observation: Mapping[str, Any],
    trades: list[dict[str, Any]],
    *,
    roots: list[Path],
    minimum_coverage_pct: float,
) -> dict[str, Any]:
    verify_receipt(observation, "observation")
    if observation.get("state") != "PASS_BINGX_REAL_OBSERVATION_COLLECTED_STRESS_PENDING":
        raise RuntimeError("REAL_OBSERVATION_NOT_PASS")
    taker_pct = finite(observation.get("taker_fee_pct"), "taker_fee_pct")
    funding_p95_pct = finite(
        observation.get("funding_p95_abs_pct_8h"), "funding_p95_abs_pct_8h"
    )

    grouped_paths: dict[tuple[str, str], set[Path]] = {}
    for row in trades:
        group = (str(row.get("symbol") or ""), str(row.get("data_interval") or row.get("interval") or "1m"))
        grouped_paths.setdefault(group, set()).add(resolve_source_path(row.get("data_source_path"), roots))
    timelines = {group: load_timeline(sorted(paths)) for group, paths in grouped_paths.items()}

    baseline_values: list[float] = []
    stressed_values: list[float] = []
    result_rows: list[dict[str, Any]] = []
    boundary_excluded = 0
    for row in trades:
        group = (str(row.get("symbol") or ""), str(row.get("data_interval") or row.get("interval") or "1m"))
        timeline = timelines[group]
        delayed_entry = next_open(timeline, row.get("entry_ts"))
        delayed_exit = next_open(timeline, row.get("exit_ts"))
        if delayed_entry is None or delayed_exit is None:
            boundary_excluded += 1
            continue
        side = str(row.get("side") or "").lower()
        qty = abs(finite(row.get("qty"), "qty"))
        risk = finite(row.get("initial_risk_usdt"), "initial_risk_usdt")
        if qty <= 0.0 or risk <= 0.0 or side not in {"long", "short", "buy", "sell"}:
            raise RuntimeError("TRADE_GEOMETRY_INVALID")
        entry_notional = qty * delayed_entry
        exit_notional = qty * delayed_exit
        gross = (
            (delayed_exit - delayed_entry) * qty
            if side in {"long", "buy"}
            else (delayed_entry - delayed_exit) * qty
        )
        fee = (entry_notional + exit_notional) * taker_pct / 100.0
        slip_bps = slippage_bps(observation, max(entry_notional, exit_notional))
        slippage = (entry_notional + exit_notional) * slip_bps / 10000.0
        exposure_min = max(0.0, finite(row.get("time_exposure_min", 0.0), "time_exposure_min") + 1.0)
        conservative_funding = -entry_notional * funding_p95_pct / 100.0 * (exposure_min / 480.0)
        stressed_r = (gross - fee - slippage + conservative_funding) / risk
        baseline_r = finite(
            row.get("realized_R_including_funding_estimate", row.get("realized_R")),
            "baseline_R",
        )
        baseline_values.append(baseline_r)
        stressed_values.append(stressed_r)
        result_rows.append(
            {
                "event_id": str(row.get("event_id") or row.get("position_id") or ""),
                "window_id": str(row.get("window_id") or ""),
                "side": side,
                "baseline_R": round(baseline_r, 12),
                "stressed_R": round(stressed_r, 12),
                "slippage_bps_one_way": round(slip_bps, 8),
            }
        )

    source_count = len(trades)
    trade_count = len(stressed_values)
    coverage_pct = trade_count / source_count * 100.0 if source_count else 0.0
    if trade_count <= 0 or coverage_pct < minimum_coverage_pct:
        raise RuntimeError(
            f"PLUS_ONE_BAR_COVERAGE_BELOW_MIN:{coverage_pct:.6f}<{minimum_coverage_pct:.6f}"
        )
    baseline_expectancy = sum(baseline_values) / trade_count
    stressed_expectancy = sum(stressed_values) / trade_count
    window_material = sorted(
        {
            (
                str(row.get("window_id") or ""),
                str(row.get("data_source_sha256") or ""),
                str(row.get("symbol") or ""),
            )
            for row in trades
        }
    )
    cost_material = {
        "maker_fee_pct": observation.get("maker_fee_pct"),
        "taker_fee_pct": observation.get("taker_fee_pct"),
        "funding_p95_abs_pct_8h": observation.get("funding_p95_abs_pct_8h"),
        "slippage_floor_bps_by_notional": observation.get("slippage_floor_bps_by_notional"),
        "latency_ms_p50": observation.get("latency_ms_p50"),
        "latency_ms_p95": observation.get("latency_ms_p95"),
    }
    receipt = {
        "schema_version": "zel.plus_one_bar_stress.receipt.v1",
        "version": VERSION,
        "state": "PASS_PLUS_ONE_BAR_STRESS",
        "fixture_only": False,
        "strategy_id": str(trades[0].get("strategy_id") or ""),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "trade_count": trade_count,
        "source_trade_count": source_count,
        "coverage_pct": coverage_pct,
        "terminal_boundary_excluded_count": boundary_excluded,
        "baseline_expectancy_R": baseline_expectancy,
        "stressed_expectancy_R": stressed_expectancy,
        "delta_expectancy_R": stressed_expectancy - baseline_expectancy,
        "window_sha256": stable_sha(window_material),
        "cost_model_sha256": stable_sha(cost_material),
        "result_sha256": stable_sha(result_rows),
        "execution_model": "ENTRY_AND_EXIT_AT_NEXT_OBSERVED_BAR_OPEN",
        "future_data_scope": "EXACTLY_ONE_OBSERVED_BAR_ONLY",
        "real_bingx_costs_applied": True,
        "protected_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def bind_h3(
    gate_path: Path,
    policy_path: Path,
    observation: Mapping[str, Any],
    stress: Mapping[str, Any],
) -> dict[str, Any]:
    gate = load_module(gate_path, "zel_economic_hardening_gate_runtime")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    row = dict(observation)
    row.pop("receipt_sha256", None)
    row["plus_one_bar_stress_receipt"] = dict(stress)
    return gate.h3_bingx_light_calibration(
        row,
        policy["h3_bingx_light_calibration"],
        datetime.now(timezone.utc),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--terminal-trades", type=Path, required=True)
    parser.add_argument("--strategy-id", default="ema_ribbon_scalp")
    parser.add_argument("--data-root", action="append", default=[])
    parser.add_argument("--minimum-coverage-pct", type=float, default=95.0)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--stress-out", type=Path, required=True)
    parser.add_argument("--h3-out", type=Path, required=True)
    args = parser.parse_args()
    observation = json.loads(args.observation.read_text(encoding="utf-8"))
    trades = read_trades(args.terminal_trades, args.strategy_id)
    roots = [Path(value) for value in args.data_root] or [
        Path("/"),
        Path("/opt/zel/historical-oos-v1"),
        Path("/var/lib/zel-research"),
    ]
    stress = build_stress(
        observation,
        trades,
        roots=roots,
        minimum_coverage_pct=args.minimum_coverage_pct,
    )
    h3 = bind_h3(args.gate, args.policy, observation, stress)
    args.stress_out.parent.mkdir(parents=True, exist_ok=True)
    args.h3_out.parent.mkdir(parents=True, exist_ok=True)
    args.stress_out.write_text(json.dumps(stress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.h3_out.write_text(json.dumps(h3, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "stress_state": stress["state"],
                "h3_state": h3["state"],
                "trade_count": stress["trade_count"],
                "coverage_pct": stress["coverage_pct"],
                "baseline_expectancy_R": stress["baseline_expectancy_R"],
                "stressed_expectancy_R": stress["stressed_expectancy_R"],
                "stress_receipt_sha256": stress["receipt_sha256"],
                "h3_receipt_sha256": h3["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if h3["state"] == "PASS_BINGX_LIGHT_CALIBRATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
