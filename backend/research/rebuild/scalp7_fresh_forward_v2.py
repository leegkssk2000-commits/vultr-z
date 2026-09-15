"""Durable fresh Scalp7 signal receipts; no executable quotes or trade fills.

The atomic STATE.json is the authoritative signal ledger and decision cursor.
Historical candles are fixed indicator context only. Observed 1m response hashes
and receipt times bind fresh closed-bar decisions. Orders are never available.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
import hashlib
import importlib
import json
import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd

from backend.research.rebuild.economic7_canonical_history_v1 import (
    atomic_json,
    immutable_bytes,
    json_bytes,
)
from backend.research.rebuild.scalp7_fresh_source_v2 import load_observed_minutes
from backend.research.rebuild.scalp7_source_data_v2 import (
    SYMBOLS,
    SourceDataError,
    aggregate_minutes,
    sha_file,
)
from backend.research.rebuild import scalp7_rolling_context_v2 as context

ROOT = Path(__file__).resolve().parents[3]
MINUTE_MS = 60_000
TF_MS = 900_000
MAX_LEDGER_BYTES = 64 * 1024 * 1024


class FreshForwardError(RuntimeError):
    pass


def _json_signal(signal: Mapping[str, Any]) -> dict[str, Any]:
    def scalar(value: Any) -> Any:
        if isinstance(value, np.generic):
            return value.item()
        raise TypeError("NON_JSON_SIGNAL_FIELD:" + type(value).__name__)

    return json.loads(json.dumps(signal, default=scalar, allow_nan=False))


def digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def _pinned(item: Mapping[str, Any]) -> Path:
    path = Path(str(item["path"]))
    if not path.is_absolute():
        path = ROOT / path
    if sha_file(path) != item["sha256"]:
        raise FreshForwardError("PINNED_FILE_CHANGED:" + str(path))
    return path


def source_entries(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    return (
        list(config["sources"])
        if "sources" in config
        else [
            {
                "path": config["source_dir"],
                "identity_sha256": config["source_identity_sha256"],
            }
        ]
    )


def project_signals(out: Path, state: Mapping[str, Any]) -> None:
    """Logical append-only immutable records; atomic replacement repairs crashes.

    Consumers may snapshot the complete file and deduplicate opportunity_key.
    A newly published file always retains the exact committed previous prefix.
    """
    rows = []
    previous = "0" * 64
    for stored in state["signals"]:
        actual = int(stored["strategy_observed_at_ms"])
        signal = dict(stored["signal"])
        signal["original_feature_signal_ts_ms"] = signal["signal_ts_ms"]
        signal["signal_ts_ms"] = max(
            actual, int(stored["observed_decision_available_ms"])
        )
        signal["available_ts_ms"] = signal["signal_ts_ms"]
        signal["earliest_entry_ts_ms"] = signal["signal_ts_ms"] + 1
        row = {
            "signal": signal,
            "observed_at_ms": actual,
            "opportunity_key": stored["opportunity_key"],
            "common_fresh_start_ms": stored["common_fresh_start_ms"],
            "decision_bar_close_ms": stored["decision_bar_close_ms"],
            "latest_common_decision_close_ms": stored[
                "latest_common_decision_close_ms"
            ],
            "execution_eligibility": stored["execution_eligibility"],
            "input_snapshot_cutoff_ms": stored["input_snapshot_cutoff_ms"],
            "source_cursor_sha256": stored["source_cursor_sha256"],
            "bar_witnesses": stored["bar_witnesses"],
            "previous_sha256": previous,
            "freeze_sha256": state["freeze_sha256"],
        }
        row["record_sha256"] = digest(row)
        previous = row["record_sha256"]
        rows.append(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
        )
    raw = "".join(rows).encode()
    destination = out / "fresh_signals.jsonl"
    if destination.exists():
        old = destination.read_bytes()
        if not raw.startswith(old):
            raise FreshForwardError("IMMUTABLE_SIGNAL_PREFIX_CHANGED")
        if old == raw:
            return
    temporary = out / "fresh_signals.jsonl.tmp"
    with temporary.open("wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    directory = os.open(out, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_config(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, float]]:
    config = json.loads(path.read_bytes())
    start = int(config["fresh_start_ms"])
    if (
        start % TF_MS
        or start <= int(config["frozen_at_ms"])
        or int(config["frozen_at_ms"]) < 0
    ):
        raise FreshForwardError("FUTURE_COMMON_UTC15_START_REQUIRED")
    contract_path = _pinned(config["campaign_contract"])
    contract = json.loads(contract_path.read_bytes())
    for name in set(contract["code_hashes"]) & set(config["code_hashes"]):
        if contract["code_hashes"][name] != config["code_hashes"][name]:
            raise FreshForwardError("CONFLICTING_FROZEN_CODE_PIN:" + name)
    for name, expected in {**contract["code_hashes"], **config["code_hashes"]}.items():
        code_path = Path(name) if Path(name).is_absolute() else ROOT / name
        if sha_file(code_path) != expected:
            raise FreshForwardError("FROZEN_CODE_CHANGED:" + name)
    for required in (
        Path(__file__).name,
        "scalp7_fresh_source_v2.py",
        "scalp7_source_data_v2.py",
    ):
        if not any(Path(name).name == required for name in config["code_hashes"]):
            raise FreshForwardError("FRESH_CODE_PIN_MISSING:" + required)
    cost_path = _pinned(config["cost_snapshot"])
    costs = json.loads(cost_path.read_bytes())["costs_bps"]
    if set(costs) != set(SYMBOLS) or any(
        not np.isfinite(v) or v <= 0 for v in costs.values()
    ):
        raise FreshForwardError("EXACT_SIX_FROZEN_COSTS_REQUIRED")
    for item in source_entries(config):
        source = Path(item["path"])
        if sha_file(source / "IDENTITY.json") != item["identity_sha256"]:
            raise FreshForwardError("OBSERVED_SOURCE_IDENTITY_CHANGED")
    fit = config["regime_fit"]
    body = {k: v for k, v in fit.items() if k != "sha256"}
    calculated = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if calculated != fit["sha256"] or int(fit["last_fit_observation_ms"]) >= start:
        raise FreshForwardError("FROZEN_PAST_REGIME_FIT_REQUIRED")
    if (
        int(fit["train_end_ms"]) > start
        or int(fit["last_fit_observation_ms"]) >= int(fit["train_end_ms"])
        or int(fit["train_start_ms"]) != int(fit["train_end_ms"]) - 90 * context.DAY
        or int(fit["train_rows"]) < 72
        or any(
            not np.isfinite(float(fit[key]))
            for key in ("disp_q67", "meanabs_q85", "vol_q25", "vol_q67")
        )
    ):
        raise FreshForwardError("FROZEN_REGIME_TRAINING_BOUNDARY_OR_SAMPLE")
    if config.get("external_micro"):
        micro = config["external_micro"]
        micro_freeze = json.loads(_pinned(micro["freeze"]).read_bytes())
        if micro_freeze["identity"] != micro["identity"]:
            raise FreshForwardError("EXTERNAL_MICRO_IDENTITY_MISMATCH")
    catalog = contract["candidates"]
    if len({row["identity"] for row in catalog}) != len(catalog):
        raise FreshForwardError("DUPLICATE_CANDIDATE_IDENTITY")
    if config.get("producer_role") != "SIGNALS_ONLY_NO_EXECUTABLE_FRESH_TRADES":
        raise FreshForwardError("EXECUTION_AUTHORITY_NOT_AVAILABLE")
    return config, contract, costs


def initialize(
    out: Path, config_path: Path, *, now_ms: int | None = None
) -> dict[str, Any]:
    now = int(time.time() * 1000) if now_ms is None else now_ms
    config, contract, _ = read_config(config_path)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "FREEZE.json"
    if path.exists():
        freeze = json.loads(path.read_bytes())
        if freeze["config_sha256"] != sha_file(config_path):
            raise FreshForwardError("FORWARD_CONFIG_CHANGED")
        return freeze
    if now > int(config["fresh_start_ms"]):
        raise FreshForwardError("INITIALIZE_BEFORE_FRESH_START_REQUIRED")
    primary = list(contract["primary_identities"])
    if config.get("external_micro"):
        primary = [
            config["external_micro"]["identity"] if "micro" in name else name
            for name in primary
        ]
    freeze = {
        "schema": "scalp7.fresh_forward.freeze.v2",
        "config_sha256": sha_file(config_path),
        "fresh_start_ms": config["fresh_start_ms"],
        "initialized_at_ms": now,
        "identities": [row["identity"] for row in contract["candidates"]],
        "primary_identities": primary,
        "producer_role": "SIGNALS_ONLY_NO_EXECUTABLE_FRESH_TRADES",
        "historical_context_trade_credit": False,
        "fresh_closed_trades": 0,
        "micro": "SEPARATE_REAL_RAW15M_PRODUCER",
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    immutable_bytes(path, json_bytes(freeze))
    return freeze


def _state(out: Path, freeze_sha: str) -> dict[str, Any]:
    path = out / "STATE.json"
    if not path.exists():
        return {
            "schema": "scalp7.fresh_forward.state.v2",
            "freeze_sha256": freeze_sha,
            "cursors": {"15": -1, "30": -1},
            "signals": [],
            "poll_count": 0,
            "seen_signal_keys": [],
            "evaluations": {},
            "fresh_closed_trades": 0,
        }
    state = json.loads(path.read_bytes())
    saved = state.pop("state_sha256")
    if digest(state) != saved or state["freeze_sha256"] != freeze_sha:
        raise FreshForwardError("STATE_HASH_OR_FREEZE_CHANGED")
    keys = [row["opportunity_key"] for row in state["signals"]]
    if len(keys) != len(set(keys)) or set(keys) != set(state["seen_signal_keys"]):
        raise FreshForwardError("SIGNAL_LEDGER_DUPLICATE_OR_CURSOR_MISMATCH")
    return state


def _history(config: Mapping[str, Any], tf: int) -> dict[str, pd.DataFrame]:
    result = {}
    entries = config["historical_context"][str(tf)]
    if set(entries) != set(SYMBOLS):
        raise FreshForwardError("EXACT_SIX_CONTEXT_FRAMES_REQUIRED")
    for symbol, item in entries.items():
        frame = pd.read_csv(_pinned(item), float_precision="round_trip")
        if frame.empty or (frame["close_ts_ms"] > int(config["fresh_start_ms"])).any():
            raise FreshForwardError("HISTORICAL_CONTEXT_AFTER_FRESH_START")
        result[symbol] = frame
    return result


def combine_context(
    historical: pd.DataFrame, observed: pd.DataFrame, tf: int
) -> pd.DataFrame:
    """Observed data wins overlaps only when raw OHLCV agrees exactly."""
    columns = [
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "segment_id",
    ]
    old = historical[columns].copy()
    fresh = observed[columns].copy()
    duplicate = set(old.open_ts_ms).intersection(fresh.open_ts_ms)
    if duplicate:
        left = old.set_index("open_ts_ms").loc[sorted(duplicate)]
        right = fresh.set_index("open_ts_ms").loc[sorted(duplicate)]
        pricecols = ["open", "high", "low", "close", "volume"]
        if not np.array_equal(
            left[pricecols].to_numpy(float), right[pricecols].to_numpy(float)
        ):
            raise FreshForwardError("HISTORICAL_OBSERVED_OVERLAP_MISMATCH")
        old = old[~old.open_ts_ms.isin(duplicate)]
    old["fresh_observed"] = False
    fresh["fresh_observed"] = True
    merged = (
        pd.concat([old, fresh], ignore_index=True)
        .sort_values("open_ts_ms")
        .reset_index(drop=True)
    )
    if merged.open_ts_ms.duplicated().any():
        raise FreshForwardError("DUPLICATE_COMBINED_CANDLE")
    merged["segment_id"] = merged.open_ts_ms.diff().ne(tf * MINUTE_MS).cumsum() - 1
    return merged


def bind_frozen_context(
    frames: dict[int, dict[str, pd.DataFrame]], fit: dict[str, Any]
) -> dict[int, dict[str, pd.DataFrame]]:
    features = context.cross_features(frames[30])
    result: dict[int, dict[str, pd.DataFrame]] = {}
    for tf, by in frames.items():
        result[tf] = {}
        for symbol, frame in by.items():
            # Preserve the frozen positive adapter's requirement that regime
            # context was already available by the decision candle close.
            x = pd.merge_asof(
                frame.sort_values("close_ts_ms"),
                features.sort_values("regime_available_ts_ms"),
                left_on="close_ts_ms",
                right_on="regime_available_ts_ms",
                direction="backward",
                tolerance=context.HOUR,
            )
            records = []
            for row in x.to_dict("records"):
                row.update(
                    regime="NO_CONTEXT", regime_fit_end_ts_ms=-1, regime_spec_sha256=""
                )
                if (
                    np.isfinite(row.get("dispersion24", np.nan))
                    and int(fit["last_fit_observation_ms"]) < int(row["close_ts_ms"])
                    and int(row["context_open_ts_ms"]) + context.HOUR
                    <= int(row["close_ts_ms"])
                ):
                    row.update(
                        regime=context.classify(row, fit),
                        regime_fit_end_ts_ms=fit["last_fit_observation_ms"],
                        regime_spec_sha256=fit["sha256"],
                    )
                records.append(row)
            result[tf][symbol] = pd.DataFrame(records)
    return result


def strategy_signals(
    spec: dict[str, Any], frames: dict[str, pd.DataFrame], costs: dict[str, float]
) -> list[dict[str, Any]]:
    mod = importlib.import_module("backend.research.rebuild." + spec["module"])
    if spec["module"] == "scalp7_positive_lanes_v2":
        return mod.generate_signals(frames, costs=costs, identities=(spec["identity"],))
    if spec["module"] == "scalp7_materials_program_v2":
        frames = mod.prepare_frames(frames)
    if spec["module"] in (
        "scalp7_parent_controls_v2",
        "scalp7_mr_formation_v2",
        "scalp7_materials_program_v2",
    ):
        return mod.generate_signals(frames, identity=spec["identity"])
    return mod.generate_signals(frames)


def build_current_frames(
    config: Mapping[str, Any], now_ms: int, *, bind: bool = True
) -> tuple[
    dict[int, dict[str, pd.DataFrame]],
    dict[int, dict[str, pd.DataFrame]],
    dict[str, Any],
]:
    """Verified observed bars plus fixed seed; never produces signals or fills."""
    pieces: dict[str, list[pd.DataFrame]] = {symbol: [] for symbol in SYMBOLS}
    cursor_receipts = []
    for item in source_entries(config):
        source = Path(item["path"])
        if sha_file(source / "IDENTITY.json") != item["identity_sha256"]:
            raise FreshForwardError("OBSERVED_SOURCE_IDENTITY_CHANGED")
        before = (source / "CURSOR.json").read_bytes()
        loaded = load_observed_minutes(source)
        if before != (source / "CURSOR.json").read_bytes():
            raise FreshForwardError("SOURCE_SNAPSHOT_CHANGED_RETRY_WITHOUT_ADVANCING")
        if set(loaded) != set(SYMBOLS):
            raise FreshForwardError("INCOMPLETE_OBSERVED_SIX_SYMBOLS")
        for symbol in SYMBOLS:
            pieces[symbol].append(loaded[symbol])
        cursor_receipts.append(
            {
                "path": str(source),
                "identity_sha256": item["identity_sha256"],
                "cursor_sha256": hashlib.sha256(before).hexdigest(),
            }
        )
    observed = {}
    for symbol, values in pieces.items():
        minutes = (
            pd.concat(values, ignore_index=True)
            .sort_values("timestamp_ms")
            .reset_index(drop=True)
        )
        if minutes.timestamp_ms.duplicated().any():
            raise FreshForwardError("OVERLAPPING_OBSERVED_SOURCE_MINUTES")
        observed[symbol] = minutes[minutes.received_at_ms <= now_ms]
    frames: dict[int, dict[str, pd.DataFrame]] = {}
    observed_bars: dict[int, dict[str, pd.DataFrame]] = {}
    ends: dict[int, int] = {}
    for tf in (15, 30):
        history = _history(config, tf)
        observed_bars[tf], frames[tf] = {}, {}
        for symbol in SYMBOLS:
            fresh = aggregate_minutes(observed[symbol], tf, observed=True)
            if fresh.empty:
                raise FreshForwardError("NO_COMPLETE_OBSERVED_BUCKET")
            observed_bars[tf][symbol] = fresh
            frames[tf][symbol] = combine_context(history[symbol], fresh, tf)
        ends[tf] = min(int(x.close_ts_ms.max()) for x in observed_bars[tf].values())
    if bind:
        frames = bind_frozen_context(frames, config["regime_fit"])
    return (
        frames,
        observed_bars,
        {
            "common_ends": ends,
            "sources": cursor_receipts,
            "source_cursor_sha256": digest(cursor_receipts),
        },
    )


def poll(
    out: Path,
    config_path: Path,
    *,
    now_ms: int | None = None,
    provider: Callable[
        [dict[str, Any], dict[str, pd.DataFrame], dict[str, float]],
        list[dict[str, Any]],
    ] = strategy_signals,
) -> dict[str, Any]:
    """Caller holds the writer lock. No partial cursor update on provider failure."""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    config, contract, costs = read_config(config_path)
    freeze = initialize(out, config_path, now_ms=now)
    state = _state(out, sha_file(out / "FREEZE.json"))
    project_signals(out, state)
    start = int(freeze["fresh_start_ms"])
    if now < start:
        return {
            "state": "WAIT_COMMON_FRESH_START",
            "fresh_start_ms": start,
            "fresh_closed_trades": 0,
        }
    frames, observed_bars, source_receipt = build_current_frames(
        config, now, bind=False
    )
    ends = source_receipt["common_ends"]
    active = [
        tf for tf in (15, 30) if ends[tf] > max(int(state["cursors"][str(tf)]), start)
    ]
    if not active:
        return {
            "state": "WAIT_NEW_COMPLETE_DECISION_BAR",
            "cursors": state["cursors"],
            "fresh_signals": len(state["signals"]),
            "fresh_closed_trades": 0,
        }
    bound = bind_frozen_context(frames, config["regime_fit"])
    seen = set(state["seen_signal_keys"])
    appended = 0
    previous_signal_count = len(state["signals"])
    for spec in contract["candidates"]:
        tf = int(spec["tf"])
        if tf not in active:
            continue
        identity = spec["identity"]
        raw_signals = provider(spec, bound[tf], costs)
        rows_by_symbol = {
            s: x.set_index("open_ts_ms") for s, x in observed_bars[tf].items()
        }
        count = 0
        for raw_signal in raw_signals:
            signal = _json_signal(raw_signal)
            if signal["identity"] != identity or int(signal["timeframe_min"]) != tf:
                raise FreshForwardError("PROVIDER_IDENTITY_OR_TIMEFRAME_CHANGED")
            opened = int(signal["signal_open_ts_ms"])
            closed = opened + tf * MINUTE_MS
            if (
                opened < start
                or not int(state["cursors"][str(tf)]) < closed <= ends[tf]
            ):
                continue
            names = [str(x["symbol"]) for x in signal.get("legs", [])] or [
                str(signal["symbol"])
            ]
            witnesses: list[dict[str, Any]] = []
            for symbol in names:
                if (
                    symbol not in rows_by_symbol
                    or opened not in rows_by_symbol[symbol].index
                ):
                    raise FreshForwardError("FRESH_SIGNAL_WITHOUT_ACTUAL_OBSERVED_BAR")
                row = rows_by_symbol[symbol].loc[opened].to_dict()
                witnesses.append(
                    {
                        "symbol": symbol,
                        "open_ts_ms": opened,
                        "close_ts_ms": int(row["close_ts_ms"]),
                        "available_ts_ms": int(row["available_ts_ms"]),
                        "bar_sha256": digest(row),
                    }
                )
            available = max(
                [int(signal["signal_ts_ms"])]
                + [x["available_ts_ms"] for x in witnesses]
            )
            if available > now:
                raise FreshForwardError("FUTURE_OBSERVATION_SIGNAL")
            key = digest(
                {
                    "identity": identity,
                    "symbol": signal["symbol"],
                    "opened": opened,
                    "side": signal.get("side"),
                    "legs": signal.get("legs"),
                }
            )
            if key in seen:
                continue
            record = {
                "opportunity_key": key,
                "identity": identity,
                "signal": signal,
                "observed_decision_available_ms": available,
                "decision_bar_close_ms": closed,
                "latest_common_decision_close_ms": ends[tf],
                "execution_eligibility": (
                    "CURRENT_DECISION_BAR_REQUIRES_NEW_QUOTE"
                    if closed == ends[tf]
                    else "MISSED_SUPERSEDED_DECISION_OBSERVATION_ONLY"
                ),
                "strategy_observed_at_ms": now,
                "earliest_executable_quote_ms": now + 1,
                "source_cursor_sha256": source_receipt["source_cursor_sha256"],
                "bar_witnesses": witnesses,
                "common_fresh_start_ms": start,
                "freeze_sha256": state["freeze_sha256"],
                "execution_state": "NO_EXECUTABLE_FRESH_TRADES_QUOTE_ADAPTER_UNBOUND",
                "historical_trade_credit": False,
                "fresh_closed_trade_credit": 0,
                "order_authority": "BLOCKED",
            }
            record["record_sha256"] = digest(record)
            state["signals"].append(record)
            seen.add(key)
            count += 1
            appended += 1
        state["evaluations"][identity] = {
            "last_complete_decision_close_ms": ends[tf],
            "evaluated_at_ms": now,
            "new_signals": count,
            "state": "FROZEN_FRESH_SIGNAL_OBSERVER",
        }
    emission_now = now if now_ms is not None else int(time.time() * 1000)
    if emission_now < now:
        raise FreshForwardError("CLOCK_REVERSED_DURING_DECISION")
    for record in state["signals"][previous_signal_count:]:
        record["strategy_observed_at_ms"] = emission_now
        record["earliest_executable_quote_ms"] = emission_now + 1
        record["input_snapshot_cutoff_ms"] = now
        record.pop("record_sha256", None)
        record["record_sha256"] = digest(record)
    for identity in state["evaluations"]:
        if state["evaluations"][identity]["evaluated_at_ms"] == now:
            state["evaluations"][identity]["evaluated_at_ms"] = emission_now
            state["evaluations"][identity]["input_snapshot_cutoff_ms"] = now
    for tf in active:
        state["cursors"][str(tf)] = ends[tf]
    state["seen_signal_keys"] = sorted(seen)
    state["poll_count"] += 1
    state["last_poll_ms"] = emission_now
    state["source_cursor_sha256"] = source_receipt["source_cursor_sha256"]
    state["state_sha256"] = digest(state)
    if len(json_bytes(state)) > MAX_LEDGER_BYTES:
        raise FreshForwardError("SIGNAL_LEDGER_BUDGET_HOLD_NO_DELETION")
    atomic_json(out / "STATE.json", state)
    project_signals(out, state)
    counts = Counter(row["identity"] for row in state["signals"])
    result = {
        "state": "SIMULTANEOUS_FROZEN_SIGNAL_COLLECTION_ACTIVE",
        "new_signals": appended,
        "total_signals": len(state["signals"]),
        "counts_by_identity": dict(counts),
        "configured_identities": len(contract["candidates"]),
        "cursors": state["cursors"],
        "fresh_closed_trades": 0,
        "execution_state": "NO_EXECUTABLE_FRESH_TRADES_QUOTE_ADAPTER_UNBOUND",
        "source_cursor_sha256": state["source_cursor_sha256"],
        "freeze_sha256": state["freeze_sha256"],
        "observed_at_ms": emission_now,
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    atomic_json(out / "STATUS.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "producer.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                result = poll(args.out, args.config)
            except (
                FreshForwardError,
                SourceDataError,
                ValueError,
                KeyError,
                OSError,
            ) as exc:
                result = {
                    "state": "HOLD_FRESH_SOURCE_OR_IDENTITY",
                    "reason": str(exc),
                    "fresh_closed_trades": 0,
                    "order_authority": "BLOCKED",
                }
                atomic_json(args.out / "STATUS.json", result)
                if "SNAPSHOT_CHANGED_RETRY" not in str(exc):
                    print(json.dumps(result), flush=True)
                    return 2
            print(json.dumps(result), flush=True)
            if args.once:
                return 0
            time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
