#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import multiprocessing
import os
import statistics
import tempfile
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "backend/research/contracts/g5_clean_runner_contract_v1.json"
FREEZE_PATH = ROOT / "backend/research/rebuild/g5_clean_runner_strategy_freeze_v1.json"
STATE_MACHINE_PATH = ROOT / "backend/research/rebuild/g5_clean_runner_state_machine_v1.json"
DEFAULT_ARTIFACT_DIR = ROOT / "backend/research/rebuild"
DEFAULT_STATE_LOG = DEFAULT_ARTIFACT_DIR / "g5_clean_runner_state_events_v1.jsonl"
DEFAULT_ECONOMIC_LEDGER = DEFAULT_ARTIFACT_DIR / "g5_clean_runner_economic_ledger_v1.jsonl"
INTERVAL_MS = 14_400_000
STATUS_ORDER = ("NEW", "EVALUATED", "TRADE_OPENED", "TRADE_CLOSED", "LEDGER_WRITTEN", "FRESH_ACCEPTED")
REQUIRED_ECONOMIC_FIELDS = (
    "strategy_id", "child_id", "symbol", "side", "entry_ts", "entry_price", "qty", "notional",
    "exit_ts", "exit_price", "gross_bps", "fee_bps", "slippage_bps", "funding_bps", "net_bps",
    "MFE_bps", "MAE_bps",
)
TELEMETRY_FIELDS = (
    "source_event_ts", "source_received_ts", "bar_close_ts", "scheduler_fire_ts",
    "evaluation_start_ts", "evaluation_end_ts", "writer_ts",
)


class IntegrityError(RuntimeError):
    pass


class ConflictError(IntegrityError):
    pass


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def utc(ms: int | None = None) -> str:
    value = now_ms() if ms is None else int(ms)
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def sha_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IntegrityError(f"OBJECT_REQUIRED:{path}")
    return value


def receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["receipt_sha256"] = sha_json(result)
    return result


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def validate_receipt(value: Mapping[str, Any]) -> bool:
    supplied = str(value.get("receipt_sha256") or "")
    core = dict(value)
    core.pop("receipt_sha256", None)
    return bool(supplied) and supplied == sha_json(core)


def _append_fsync(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


class HashChainLog:
    """Small append-only, hash-chained JSONL log with process-safe appends."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def _locked(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        prior = "GENESIS"
        with self.path.open("r", encoding="utf-8") as handle:
            for number, raw in enumerate(handle, 1):
                if not raw.endswith("\n"):
                    raise IntegrityError(f"PARTIAL_JSONL_RECORD:{self.path}:{number}")
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise IntegrityError(f"INVALID_JSONL:{self.path}:{number}:{exc}") from exc
                if not isinstance(row, dict):
                    raise IntegrityError(f"JSONL_OBJECT_REQUIRED:{self.path}:{number}")
                if int(row.get("seq") or -1) != number:
                    raise IntegrityError(f"SEQUENCE_DRIFT:{self.path}:{number}")
                if row.get("previous_record_sha256") != prior:
                    raise IntegrityError(f"HASH_CHAIN_PREDECESSOR_DRIFT:{self.path}:{number}")
                supplied = str(row.get("record_sha256") or "")
                core = dict(row)
                core.pop("record_sha256", None)
                if supplied != sha_json(core):
                    raise IntegrityError(f"HASH_CHAIN_RECORD_DRIFT:{self.path}:{number}")
                prior = supplied
                records.append(row)
        return records

    def append(self, core: Mapping[str, Any]) -> dict[str, Any]:
        handle = self._locked()
        try:
            rows = self.records()
            body = {
                "seq": len(rows) + 1,
                "previous_record_sha256": rows[-1]["record_sha256"] if rows else "GENESIS",
                **dict(core),
            }
            body["record_sha256"] = sha_json(body)
            _append_fsync(self.path, body)
            return body
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


class StateStore(HashChainLog):
    def transition(self, key: str, status: str, payload: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        if status not in STATUS_ORDER:
            raise IntegrityError(f"UNKNOWN_STATUS:{status}")
        payload_sha = sha_json(dict(payload))
        handle = self._locked()
        try:
            rows = self.records()
            related = [row for row in rows if row.get("state_key") == key]
            prior_same = [row for row in related if row.get("status") == status]
            if prior_same:
                existing = prior_same[-1]
                if existing.get("payload_sha256") != payload_sha:
                    raise ConflictError(f"STATE_PAYLOAD_CONFLICT:{key}:{status}")
                return "IDEMPOTENT_NOOP", existing
            expected_index = 0 if not related else STATUS_ORDER.index(str(related[-1]["status"])) + 1
            if expected_index >= len(STATUS_ORDER) or STATUS_ORDER[expected_index] != status:
                current = related[-1]["status"] if related else "NONE"
                raise ConflictError(f"STATE_TRANSITION_OUT_OF_ORDER:{key}:{current}->{status}")
            core = {
                "seq": len(rows) + 1,
                "previous_record_sha256": rows[-1]["record_sha256"] if rows else "GENESIS",
                "record_type": "STATE_TRANSITION",
                "event_id": sha_json({"state_key": key, "status": status, "payload_sha256": payload_sha}),
                "event_ts": utc(),
                "state_key": key,
                "status": status,
                "payload": dict(payload),
                "payload_sha256": payload_sha,
            }
            core["record_sha256"] = sha_json(core)
            _append_fsync(self.path, core)
            outcome = "NEW_EVALUATION" if status == "NEW" else "NEW_APPEND"
            return outcome, core
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def state_rows(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self.records():
            grouped[str(row["state_key"])].append(row)
        return dict(grouped)


class EconomicLedger(HashChainLog):
    def append_trade(self, row: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        missing = [field for field in REQUIRED_ECONOMIC_FIELDS if field not in row]
        if missing:
            raise IntegrityError(f"ECONOMIC_FIELDS_MISSING:{','.join(missing)}")
        trade_id = str(row.get("trade_id") or "")
        if not trade_id:
            raise IntegrityError("TRADE_ID_REQUIRED")
        payload = dict(row)
        payload_sha = sha_json(payload)
        handle = self._locked()
        try:
            rows = self.records()
            existing = [x for x in rows if x.get("trade_id") == trade_id]
            if existing:
                prior = existing[-1]
                if prior.get("payload_sha256") != payload_sha:
                    raise ConflictError(f"DUPLICATE_CLOSE_CONFLICT:{trade_id}")
                return "IDEMPOTENT_NOOP", prior
            core = {
                "seq": len(rows) + 1,
                "previous_record_sha256": rows[-1]["record_sha256"] if rows else "GENESIS",
                "record_type": "FINAL_CLOSED_ECONOMIC_ROW",
                "trade_id": trade_id,
                "writer_ts": utc(),
                "payload": payload,
                "payload_sha256": payload_sha,
            }
            core["record_sha256"] = sha_json(core)
            _append_fsync(self.path, core)
            return "NEW_APPEND", core
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


class BingxSourceAdapter:
    def __init__(self, contract: Mapping[str, Any]):
        self.config = dict(contract["source"])

    def _request(self, params: Mapping[str, Any]) -> tuple[Any, int]:
        url = str(self.config["endpoint"]) + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read()
        received = now_ms()
        value = json.loads(raw.decode("utf-8"))
        if isinstance(value, dict) and value.get("code") not in (None, 0):
            raise IntegrityError(f"BINGX_SOURCE_ERROR:{value.get('code')}:{value.get('msg')}")
        return value, received

    @staticmethod
    def _decode(value: Any) -> list[dict[str, Any]]:
        raw_rows = value.get("data", value if isinstance(value, list) else []) if isinstance(value, (dict, list)) else []
        output: list[dict[str, Any]] = []
        for raw in raw_rows:
            try:
                if isinstance(raw, Mapping):
                    open_ts = int(raw.get("time") or raw.get("openTime") or raw.get("timestamp"))
                    row = {
                        "bar_open_ts": open_ts,
                        "bar_close_ts": open_ts + INTERVAL_MS,
                        "open": float(raw["open"]),
                        "high": float(raw["high"]),
                        "low": float(raw["low"]),
                        "close": float(raw["close"]),
                        "volume": float(raw.get("volume") or raw.get("vol") or 0.0),
                    }
                else:
                    open_ts = int(raw[0])
                    row = {
                        "bar_open_ts": open_ts,
                        "bar_close_ts": open_ts + INTERVAL_MS,
                        "open": float(raw[1]),
                        "high": float(raw[2]),
                        "low": float(raw[3]),
                        "close": float(raw[4]),
                        "volume": float(raw[5] if len(raw) > 5 else 0.0),
                    }
                validate_bar(row)
                output.append(row)
            except (KeyError, TypeError, ValueError, IntegrityError):
                continue
        return output

    def fetch(self, symbol: str, scheduler_fire_ts: int) -> dict[str, Any]:
        all_rows: dict[int, dict[str, Any]] = {}
        end_time = int(scheduler_fire_ts)
        received_times: list[int] = []
        for _ in range(int(self.config["max_pages"])):
            value, received = self._request({
                "symbol": symbol,
                "interval": "4h",
                "limit": int(self.config["page_limit"]),
                "endTime": end_time,
            })
            received_times.append(received)
            page = sorted(self._decode(value), key=lambda row: int(row["bar_open_ts"]))
            if not page:
                break
            for row in page:
                open_ts = int(row["bar_open_ts"])
                prior = all_rows.get(open_ts)
                if prior is not None and sha_json(prior) != sha_json(row):
                    raise ConflictError(f"SOURCE_BAR_CONFLICT:{symbol}:{open_ts}")
                all_rows[open_ts] = row
            oldest = int(page[0]["bar_open_ts"])
            if oldest >= end_time:
                raise IntegrityError(f"SOURCE_PAGINATION_STALLED:{symbol}:{oldest}")
            end_time = oldest - 1
            if len(page) < int(self.config["page_limit"]) * 0.9:
                break
        rows = [all_rows[key] for key in sorted(all_rows)]
        closed = [row for row in rows if int(row["bar_close_ts"]) <= scheduler_fire_ts]
        minimum = int(self.config["minimum_warmup_bars"])
        if len(closed) < minimum:
            raise IntegrityError(f"SOURCE_WARMUP_INCOMPLETE:{symbol}:{len(closed)}<{minimum}")
        verify_recent_continuity(symbol, closed[-minimum:])
        if not received_times:
            raise IntegrityError(f"SOURCE_NOT_RECEIVED:{symbol}")
        return {
            "symbol": symbol,
            "rows": rows,
            "closed_rows": closed,
            "source_received_ts": max(received_times),
            "source_id": self.config["source_id"],
            "stream_id": self.config["stream_id"],
        }


def validate_bar(row: Mapping[str, Any]) -> None:
    required = ("bar_open_ts", "bar_close_ts", "open", "high", "low", "close", "volume")
    if any(field not in row for field in required):
        raise IntegrityError("SOURCE_BAR_FIELD_MISSING")
    open_ts, close_ts = int(row["bar_open_ts"]), int(row["bar_close_ts"])
    if close_ts - open_ts != INTERVAL_MS:
        raise IntegrityError("BAR_INTERVAL_DRIFT")
    prices = [float(row[name]) for name in ("open", "high", "low", "close")]
    if any(not math.isfinite(value) or value <= 0 for value in prices):
        raise IntegrityError("BAR_PRICE_INVALID")
    if float(row["high"]) < max(float(row["open"]), float(row["close"])):
        raise IntegrityError("BAR_HIGH_INVALID")
    if float(row["low"]) > min(float(row["open"]), float(row["close"])):
        raise IntegrityError("BAR_LOW_INVALID")
    if not math.isfinite(float(row["volume"])) or float(row["volume"]) < 0:
        raise IntegrityError("BAR_VOLUME_INVALID")


def verify_recent_continuity(symbol: str, rows: Sequence[Mapping[str, Any]]) -> None:
    for left, right in zip(rows, rows[1:]):
        delta = int(right["bar_open_ts"]) - int(left["bar_open_ts"])
        if delta != INTERVAL_MS:
            raise IntegrityError(f"SOURCE_GAP:{symbol}:{left['bar_open_ts']}:{right['bar_open_ts']}:{delta}")


def _ema(values: Sequence[float], length: int) -> float:
    if not values:
        raise IntegrityError("EMA_EMPTY")
    alpha = 2.0 / (length + 1.0)
    result = float(values[0])
    for value in values[1:]:
        result = alpha * float(value) + (1.0 - alpha) * result
    return result


def windowed_ema(values: Sequence[float], length: int, index: int) -> float:
    start = max(0, index - max(length * 4, length) + 1)
    return _ema(values[start:index + 1], length)


def full_history_ema(values: Sequence[float], length: int, index: int) -> float:
    return _ema(values[:index + 1], length)


def atr14(rows: Sequence[Mapping[str, Any]], index: int) -> float:
    values: list[float] = []
    for j in range(max(1, index - 13), index + 1):
        high = float(rows[j]["high"])
        low = float(rows[j]["low"])
        prior_close = float(rows[j - 1]["close"])
        values.append(max(high - low, abs(high - prior_close), abs(low - prior_close)))
    if not values:
        raise IntegrityError("ATR14_EMPTY")
    return sum(values) / len(values)


def _population_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


class FrozenStrategyAdapter:
    EXPECTED_CHILDREN = {
        "keltner_trend": "keltner_range_owner_v1",
        "supertrend_pullback": "supertrend_replacement_highvol_mom_long_4h_h12_v2",
        "break_and_continue": "break_replacement_breakout50_long_4h_h6_v2",
    }

    def __init__(self, contract: Mapping[str, Any], freeze: Mapping[str, Any]):
        self.contract = dict(contract)
        self.freeze = dict(freeze)
        self.strategies = {str(row["strategy_id"]): dict(row) for row in contract["active_strategies"]}
        self.validate_identity()

    def validate_identity(self) -> None:
        if set(self.strategies) != set(self.EXPECTED_CHILDREN):
            raise IntegrityError("ACTIVE_STRATEGY_SET_DRIFT")
        frozen = self.freeze["active_runner_assets"]
        name_by_strategy = {str(row["strategy_id"]): name for name, row in frozen.items()}
        for strategy_id, expected_child in self.EXPECTED_CHILDREN.items():
            row = self.strategies[strategy_id]
            if row.get("child_id") != expected_child:
                raise IntegrityError(f"CHILD_IDENTITY_DRIFT:{strategy_id}")
            freeze_row = frozen[name_by_strategy[strategy_id]]
            for contract_key, freeze_key in (
                ("strategy_sha", "strategy_sha"), ("entry_sha", "entry_sha"),
                ("exit_sha", "exit_sha"), ("config_sha", "config_sha"),
                ("freeze_receipt_sha", "freeze_receipt_sha"),
            ):
                if row.get(contract_key) != freeze_row.get(freeze_key):
                    raise IntegrityError(f"STRATEGY_SHA_DRIFT:{strategy_id}:{contract_key}")
        if self.freeze.get("active3_sha_parity") is not True or self.freeze.get("strategy_mutation") is not False:
            raise IntegrityError("FREEZE_MANIFEST_NOT_SAFE")

    def evaluate(self, strategy_id: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if strategy_id not in self.strategies:
            raise IntegrityError(f"UNKNOWN_STRATEGY:{strategy_id}")
        if len(rows) < int(self.contract["source"]["minimum_warmup_bars"]):
            raise IntegrityError(f"STRATEGY_WARMUP_INCOMPLETE:{strategy_id}:{len(rows)}")
        i = len(rows) - 1
        closes = [float(row["close"]) for row in rows]
        ema20 = windowed_ema(closes, 20, i)
        ema50 = windowed_ema(closes, 50, i)
        features: dict[str, Any] = {"ema20": ema20, "ema50": ema50}
        if strategy_id == "keltner_trend":
            previous_ema20 = windowed_ema(closes, 20, i - 1)
            parent = ema20 > ema50 and closes[i - 1] <= previous_ema20 and closes[i] > ema20
            full20 = full_history_ema(closes, 20, i)
            full50 = full_history_ema(closes, 50, i)
            atr = atr14(rows, i)
            normalized = abs(full20 - full50) / max(atr, 1e-12)
            classifier = normalized < 0.5
            signal = bool(parent and classifier)
            features.update({
                "previous_ema20": previous_ema20,
                "full_history_ema20": full20,
                "full_history_ema50": full50,
                "atr14": atr,
                "normalized_ema_separation_atr": normalized,
                "parent_entry": parent,
                "range_owner": classifier,
            })
        elif strategy_id == "supertrend_pullback":
            ret1 = closes[i] / closes[i - 1] - 1.0
            returns = [closes[j] / closes[j - 1] - 1.0 for j in range(max(1, i - 19), i + 1)]
            retstd20 = _population_std(returns)
            signal = bool(abs(ret1) >= 1.5 * retstd20 and ret1 > 0 and ema20 > ema50)
            features.update({"ret1": ret1, "retstd20": retstd20})
        else:
            previous_highest50 = max(float(row["high"]) for row in rows[max(0, i - 50):i])
            recent_volume = [float(row["volume"]) for row in rows[max(0, i - 19):i + 1]]
            mean_volume = sum(recent_volume) / len(recent_volume)
            volume_ratio20 = float(rows[i]["volume"]) / mean_volume if mean_volume > 0 else None
            signal = bool(
                closes[i] > previous_highest50
                and ema20 > ema50
                and volume_ratio20 is not None
                and volume_ratio20 >= 1.1
            )
            features.update({"previous_highest50": previous_highest50, "volume_ratio20": volume_ratio20})
        config = self.strategies[strategy_id]
        return {
            "strategy_id": strategy_id,
            "child_id": config["child_id"],
            "strategy_sha": config["strategy_sha"],
            "entry_sha": config["entry_sha"],
            "exit_sha": config["exit_sha"],
            "config_sha": config["config_sha"],
            "signal": signal,
            "side": config["side"] if signal else None,
            "result": "SIGNAL_EMITTED" if signal else "BAR_EVALUATED_NO_SIGNAL",
            "features": features,
            "lookahead": 0,
        }


def state_key(strategy: Mapping[str, Any], symbol: str, bar_close_ts: int) -> str:
    return "|".join((str(strategy["strategy_id"]), str(strategy["child_id"]), symbol, str(int(bar_close_ts))))


def bar_key(symbol: str, bar_close_ts: int) -> str:
    return f"{symbol}|4h|{int(bar_close_ts)}"


def latest_status(rows: Sequence[Mapping[str, Any]]) -> str | None:
    return str(rows[-1]["status"]) if rows else None


def _status_at_least(status: str | None, target: str) -> bool:
    return status is not None and STATUS_ORDER.index(status) >= STATUS_ORDER.index(target)


def _open_trade_exists(store: StateStore, strategy_id: str, child_id: str, symbol: str) -> bool:
    prefix = f"{strategy_id}|{child_id}|{symbol}|"
    for key, rows in store.state_rows().items():
        if key.startswith(prefix):
            status = latest_status(rows)
            if status == "TRADE_OPENED":
                return True
    return False


class FreshAcceptor:
    def __init__(self, contract: Mapping[str, Any]):
        self.contract = dict(contract)

    def assess(self, row: Mapping[str, Any], *, ledger_parity: bool, duplicate: int, lookahead: int) -> dict[str, Any]:
        checks = {
            "source_provenance": bool(row.get("source_id") and row.get("bar_key")),
            "bar_provenance": int(row.get("signal_bar_close_ts") or 0) > 0,
            "child_identity": bool(row.get("strategy_sha") and row.get("entry_sha") and row.get("exit_sha") and row.get("config_sha")),
            "entry_provenance": int(row.get("entry_ts") or 0) > int(row.get("signal_bar_open_ts") or 0),
            "exit_provenance": int(row.get("exit_ts") or 0) > int(row.get("entry_ts") or 0),
            "cost_provenance": isinstance(row.get("cost_bps_per_trade"), (int, float)),
            "ledger_parity": bool(ledger_parity),
            "duplicate_zero": int(duplicate) == 0,
            "lookahead_zero": int(lookahead) == 0,
            "data_stale_authority": False,
        }
        shadow = self.contract.get("mode") == "SHADOW_NO_CREDIT"
        accepted = all(checks.values()) and not shadow
        return {
            "state": "ACCEPTED" if accepted else ("BLOCKED_SHADOW_MODE" if shadow else "BLOCKED_DATA_STALE_AUTHORITY"),
            "checks": checks,
            "accepted": accepted,
            "formal_credit": 1 if accepted else 0,
        }


def _telemetry(
    *, bar_close_ts: int, source_received_ts: int, scheduler_fire_ts: int,
    evaluation_start_ts: int, evaluation_end_ts: int, writer_ts: int,
) -> dict[str, int]:
    values = {
        "source_event_ts": int(bar_close_ts),
        "source_received_ts": int(source_received_ts),
        "bar_close_ts": int(bar_close_ts),
        "scheduler_fire_ts": int(scheduler_fire_ts),
        "evaluation_start_ts": int(evaluation_start_ts),
        "evaluation_end_ts": int(evaluation_end_ts),
        "writer_ts": int(writer_ts),
    }
    if any(values[name] <= 0 for name in TELEMETRY_FIELDS):
        raise IntegrityError("TELEMETRY_TIMESTAMP_MISSING")
    values.update({
        "evaluation_age_ms": values["evaluation_start_ts"] - values["bar_close_ts"],
        "source_lag_ms": values["source_received_ts"] - values["bar_close_ts"],
        "scheduler_lag_ms": values["scheduler_fire_ts"] - values["bar_close_ts"],
        "evaluation_duration_ms": values["evaluation_end_ts"] - values["evaluation_start_ts"],
    })
    if any(values[name] < 0 for name in ("evaluation_age_ms", "source_lag_ms", "scheduler_lag_ms", "evaluation_duration_ms")):
        raise IntegrityError("TELEMETRY_TIMESTAMP_INVERSION")
    return values


def _source_bar_payload(symbol: str, row: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "bar_key": bar_key(symbol, int(row["bar_close_ts"])),
        "source_id": source["source_id"],
        "stream_id": source["stream_id"],
        "symbol": symbol,
        "timeframe": "4h",
        "bar_open_ts": int(row["bar_open_ts"]),
        "bar_close_ts": int(row["bar_close_ts"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
        "source_bar_sha256": sha_json(dict(row)),
        "closed_confirmed": True,
    }


def evaluate_latest_bar(
    *, contract: Mapping[str, Any], adapter: FrozenStrategyAdapter, store: StateStore,
    source: Mapping[str, Any], scheduler_fire_ts: int,
) -> dict[str, int]:
    symbol = str(source["symbol"])
    closed = list(source["closed_rows"])
    latest = closed[-1]
    if int(latest["bar_close_ts"]) > scheduler_fire_ts:
        raise IntegrityError("FORMING_BAR_EVALUATION_ATTEMPT")
    counts = {"new": 0, "noop": 0, "signal": 0, "no_signal": 0}
    source_payload = _source_bar_payload(symbol, latest, source)
    for strategy in contract["active_strategies"]:
        key = state_key(strategy, symbol, int(latest["bar_close_ts"]))
        new_outcome, _ = store.transition(key, "NEW", {
            **source_payload,
            "strategy_id": strategy["strategy_id"],
            "child_id": strategy["child_id"],
        })
        if new_outcome == "IDEMPOTENT_NOOP":
            counts["noop"] += 1
        else:
            counts["new"] += 1
        states = store.state_rows()[key]
        if _status_at_least(latest_status(states), "EVALUATED"):
            continue
        start = now_ms()
        locked = _open_trade_exists(store, str(strategy["strategy_id"]), str(strategy["child_id"]), symbol)
        evaluation = adapter.evaluate(str(strategy["strategy_id"]), closed)
        if locked:
            evaluation["signal"] = False
            evaluation["side"] = None
            evaluation["result"] = "BAR_EVALUATED_NO_SIGNAL"
            evaluation["reason"] = "IN_POSITION_LOCK"
        end = max(now_ms(), start)
        writer = max(now_ms(), end)
        telemetry = _telemetry(
            bar_close_ts=int(latest["bar_close_ts"]),
            source_received_ts=int(source["source_received_ts"]),
            scheduler_fire_ts=scheduler_fire_ts,
            evaluation_start_ts=start,
            evaluation_end_ts=end,
            writer_ts=writer,
        )
        payload = {
            **evaluation,
            "evaluation_key": key,
            "bar_key": source_payload["bar_key"],
            "source_id": source["source_id"],
            "symbol": symbol,
            "timeframe": "4h",
            "source_bar_sha256": source_payload["source_bar_sha256"],
            "signal_bar_open_ts": int(latest["bar_open_ts"]),
            "signal_bar_close_ts": int(latest["bar_close_ts"]),
            "telemetry": telemetry,
            "source_seen": True,
            "closed_bar": True,
            "evaluated": True,
            "correct_child": evaluation["child_id"] == strategy["child_id"],
            "duplicate": 0,
            "formal_credit": 0,
        }
        store.transition(key, "EVALUATED", payload)
        if evaluation["signal"]:
            counts["signal"] += 1
        else:
            counts["no_signal"] += 1
    return counts


def _bar_index(rows: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    return {int(row["bar_open_ts"]): row for row in rows}


def process_trade_lifecycle(
    *, contract: Mapping[str, Any], store: StateStore, ledger: EconomicLedger,
    source_by_symbol: Mapping[str, Mapping[str, Any]], acceptor: FreshAcceptor,
) -> dict[str, int]:
    strategies = {str(row["strategy_id"]): dict(row) for row in contract["active_strategies"]}
    counts = {"opened": 0, "closed": 0, "ledger_written": 0, "fresh_accepted": 0}
    for key, transitions in sorted(store.state_rows().items()):
        evaluated = next((row for row in transitions if row["status"] == "EVALUATED"), None)
        if evaluated is None or not bool(evaluated["payload"].get("signal")):
            continue
        payload = evaluated["payload"]
        strategy_id = str(payload["strategy_id"])
        strategy = strategies[strategy_id]
        symbol = str(payload.get("symbol") or key.split("|")[2])
        source = source_by_symbol.get(symbol)
        if source is None:
            continue
        rows = list(source["rows"])
        index = _bar_index(rows)
        current_status = latest_status(transitions)
        entry_ts = int(payload["signal_bar_close_ts"])
        if current_status == "EVALUATED":
            entry_bar = index.get(entry_ts)
            if entry_bar is None:
                continue
            trade_id = sha_json({
                "strategy_id": strategy_id,
                "child_id": strategy["child_id"],
                "symbol": symbol,
                "side": payload["side"],
                "signal_bar_close_ts": payload["signal_bar_close_ts"],
                "entry_ts": entry_ts,
            })
            store.transition(key, "TRADE_OPENED", {
                "trade_id": trade_id,
                "strategy_id": strategy_id,
                "child_id": strategy["child_id"],
                "symbol": symbol,
                "side": payload["side"],
                "entry_ts": entry_ts,
                "entry_price": float(entry_bar["open"]),
                "qty": None,
                "notional": None,
                "size_authority": "UNAVAILABLE_SHADOW_NO_CREDIT",
                "exit_due_ts": entry_ts + int(strategy["max_hold_bars"]) * INTERVAL_MS,
                "formal_credit": 0,
            })
            counts["opened"] += 1
            transitions = store.state_rows()[key]
            current_status = latest_status(transitions)
        if current_status == "TRADE_OPENED":
            opened = next(row for row in transitions if row["status"] == "TRADE_OPENED")["payload"]
            exit_due_ts = int(opened["exit_due_ts"])
            closed_rows = list(source["closed_rows"])
            if not closed_rows or int(closed_rows[-1]["bar_close_ts"]) < exit_due_ts:
                continue
            path = [row for row in closed_rows if int(opened["entry_ts"]) <= int(row["bar_open_ts"]) < exit_due_ts]
            if len(path) != int(strategy["max_hold_bars"]):
                raise IntegrityError(f"TRADE_PATH_GAP:{opened['trade_id']}:{len(path)}")
            if int(path[-1]["bar_close_ts"]) != exit_due_ts:
                raise IntegrityError(f"TRADE_EXIT_BAR_MISMATCH:{opened['trade_id']}")
            entry_price = float(opened["entry_price"])
            exit_price = float(path[-1]["close"])
            side = str(opened["side"])
            direction = 1.0 if side == "long" else -1.0
            gross_bps = (exit_price / entry_price - 1.0) * 10_000.0 * direction
            cost_bps = float(strategy["cost_bps_per_trade"])
            if side == "long":
                mfe = (max(float(row["high"]) for row in path) / entry_price - 1.0) * 10_000.0
                mae = (1.0 - min(float(row["low"]) for row in path) / entry_price) * 10_000.0
            else:
                mfe = (1.0 - min(float(row["low"]) for row in path) / entry_price) * 10_000.0
                mae = (max(float(row["high"]) for row in path) / entry_price - 1.0) * 10_000.0
            economic = {
                "trade_id": opened["trade_id"],
                "strategy_id": strategy_id,
                "child_id": strategy["child_id"],
                "strategy_sha": strategy["strategy_sha"],
                "entry_sha": strategy["entry_sha"],
                "exit_sha": strategy["exit_sha"],
                "config_sha": strategy["config_sha"],
                "symbol": symbol,
                "side": side,
                "signal_bar_open_ts": int(payload["signal_bar_open_ts"]),
                "signal_bar_close_ts": int(payload["signal_bar_close_ts"]),
                "entry_ts": int(opened["entry_ts"]),
                "entry_price": entry_price,
                "qty": None,
                "notional": None,
                "size_authority": "UNAVAILABLE_SHADOW_NO_CREDIT",
                "exit_ts": exit_due_ts,
                "exit_price": exit_price,
                "gross_bps": gross_bps,
                "fee_bps": None,
                "slippage_bps": None,
                "funding_bps": None,
                "cost_component_state": "AGGREGATE_FROZEN_COST_ONLY",
                "cost_bps_per_trade": cost_bps,
                "net_bps": gross_bps - cost_bps,
                "MFE_bps": max(0.0, mfe),
                "MAE_bps": max(0.0, mae),
                "source_id": source["source_id"],
                "bar_key": payload["bar_key"],
                "source_bar_sha256": payload["source_bar_sha256"],
                "lookahead": 0,
                "duplicate": 0,
                "formal_credit": 0,
            }
            store.transition(key, "TRADE_CLOSED", {
                "trade_id": opened["trade_id"],
                "exit_ts": exit_due_ts,
                "exit_price": exit_price,
                "economic_row": economic,
                "economic_payload_sha256": sha_json(economic),
                "formal_credit": 0,
            })
            counts["closed"] += 1
            transitions = store.state_rows()[key]
            current_status = latest_status(transitions)
        if current_status != "TRADE_CLOSED":
            continue
        closed_payload = next(row for row in transitions if row["status"] == "TRADE_CLOSED")["payload"]
        economic = dict(closed_payload.get("economic_row") or {})
        if not economic or sha_json(economic) != closed_payload.get("economic_payload_sha256"):
            raise IntegrityError(f"TRADE_CLOSED_RECOVERY_PAYLOAD_INVALID:{key}")
        ledger_outcome, ledger_record = ledger.append_trade(economic)
        acceptance = acceptor.assess(economic, ledger_parity=True, duplicate=0, lookahead=0)
        store.transition(key, "LEDGER_WRITTEN", {
            "trade_id": economic["trade_id"],
            "ledger_outcome": ledger_outcome,
            "ledger_record_sha256": ledger_record["record_sha256"],
            "fresh_acceptance": acceptance,
            "formal_credit": 0,
        })
        counts["ledger_written"] += 1
        if acceptance["accepted"]:
            store.transition(key, "FRESH_ACCEPTED", {"trade_id": economic["trade_id"], "formal_credit": 1})
            counts["fresh_accepted"] += 1
    return counts


def _quantiles(values: Sequence[int]) -> dict[str, int | None]:
    if not values:
        return {"min": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(int(value) for value in values)
    def pick(p: float) -> int:
        return ordered[round((len(ordered) - 1) * p)]
    return {"min": ordered[0], "p50": pick(0.5), "p95": pick(0.95), "max": ordered[-1]}


def build_runtime_artifacts(
    *, contract: Mapping[str, Any], store: StateStore, ledger: EconomicLedger,
    artifact_dir: Path, run_observed_at_ms: int,
) -> dict[str, Any]:
    rows = store.records()
    evaluated = [row for row in rows if row.get("status") == "EVALUATED"]
    by_close: dict[int, list[dict[str, Any]]] = defaultdict(list)
    complete_tuples = 0
    missing_tuples = 0
    telemetry_values: dict[str, list[int]] = defaultdict(list)
    for row in evaluated:
        payload = row["payload"]
        close_ts = int(payload["signal_bar_close_ts"])
        by_close[close_ts].append(row)
        telemetry = payload.get("telemetry") if isinstance(payload.get("telemetry"), Mapping) else {}
        missing = [field for field in TELEMETRY_FIELDS if not isinstance(telemetry.get(field), int)]
        if missing:
            missing_tuples += 1
        else:
            complete_tuples += 1
            for field in ("evaluation_age_ms", "source_lag_ms", "scheduler_lag_ms", "evaluation_duration_ms"):
                telemetry_values[field].append(int(telemetry[field]))
    expected_per_close = len(contract["active_strategies"]) * len(contract["source"]["symbols"])
    complete_closes: list[int] = []
    for close_ts, close_rows in sorted(by_close.items()):
        keys = {(row["payload"]["strategy_id"], row["payload"].get("symbol") or row["state_key"].split("|")[2]) for row in close_rows}
        valid = all(
            row["payload"].get("source_seen") is True
            and row["payload"].get("closed_bar") is True
            and row["payload"].get("evaluated") is True
            and row["payload"].get("correct_child") is True
            and int(row["payload"].get("duplicate") or 0) == 0
            and int(row["payload"].get("lookahead") or 0) == 0
            and all(isinstance((row["payload"].get("telemetry") or {}).get(field), int) for field in TELEMETRY_FIELDS)
            for row in close_rows
        )
        if len(keys) == expected_per_close and valid:
            complete_closes.append(close_ts)
    consecutive: list[int] = []
    for close_ts in complete_closes:
        if not consecutive or close_ts - consecutive[-1] == INTERVAL_MS:
            consecutive.append(close_ts)
        else:
            consecutive = [close_ts]
    last_three = consecutive[-3:] if len(consecutive) >= 3 else consecutive
    shadow_pass = len(last_three) >= 3
    shadow = receipt({
        "schema_version": "zel.g5.clean_runner.shadow.v1",
        "generated_at_utc": utc(run_observed_at_ms),
        "state": "CLEAN_RUNNER_SHADOW_PASS" if shadow_pass else "CLEAN_RUNNER_SHADOW_ACTIVE",
        "mode": "SHADOW_NO_CREDIT",
        "owner_id": contract["owner_id"],
        "contract_sha256": sha_file(CONTRACT_PATH),
        "strategy_freeze_sha256": sha_file(FREEZE_PATH),
        "state_log_sha256": sha_file(store.path) if store.path.exists() else None,
        "economic_ledger_sha256": sha_file(ledger.path) if ledger.path.exists() else None,
        "evaluation_receipts": len(evaluated),
        "expected_evaluations_per_bar": expected_per_close,
        "complete_bar_count": len(complete_closes),
        "consecutive_complete_bar_count": len(consecutive),
        "bar1": utc(last_three[0]) if len(last_three) >= 1 else None,
        "bar2": utc(last_three[1]) if len(last_three) >= 2 else None,
        "bar3": utc(last_three[2]) if len(last_three) >= 3 else None,
        "source_parity": all(row["payload"].get("source_id") == contract["source"]["source_id"] for row in evaluated),
        "child_parity": all(row["payload"].get("correct_child") is True for row in evaluated),
        "duplicate": 0,
        "lookahead": 0,
        "formal_credit": 0,
        "shadow_3bar_pass": shadow_pass,
    })
    telemetry_receipt = receipt({
        "schema_version": "zel.g5.clean_runner.telemetry.v1",
        "generated_at_utc": utc(run_observed_at_ms),
        "state": "MEASURE_ALLOWED_FRESH_CREDIT_BLOCKED",
        "complete_tuples": complete_tuples,
        "missing_tuples": missing_tuples,
        "normal_N": 0,
        "failure_N": 0,
        "classification_state": "DATA_STALE_AUTHORITY_ABSENT",
        "distributions_ms": {name: _quantiles(values) for name, values in sorted(telemetry_values.items())},
        "DATA_STALE_MS": None,
        "formal_credit": 0,
    })
    cutover = receipt({
        "schema_version": "zel.g5.clean_runner.cutover_receipt.v1",
        "generated_at_utc": utc(run_observed_at_ms),
        "state": "CLEAN_RUNNER_CUTOVER_READY" if shadow_pass and missing_tuples == 0 else "WAIT_CLEAN_RUNNER_3BAR",
        "eligible": shadow_pass and missing_tuples == 0,
        "executed": False,
        "clean_runner_authority": False,
        "legacy_state": "READ_ONLY_DIAGNOSTIC",
        "automatic_cutover": False,
        "formal_credit": 0,
    })
    post = receipt({
        "schema_version": "zel.g5.clean_runner.post_cutover_3bar.v1",
        "generated_at_utc": utc(run_observed_at_ms),
        "state": "NOT_STARTED_CUTOVER_NOT_EXECUTED",
        "cutover_executed": False,
        "bar1": None,
        "bar2": None,
        "bar3": None,
        "post_cutover_bars": 0,
        "production_ready": False,
        "formal_credit": 0,
    })
    write_json(artifact_dir / "g5_clean_runner_shadow_v1.json", shadow)
    write_json(artifact_dir / "g5_clean_runner_telemetry_v1.json", telemetry_receipt)
    write_json(artifact_dir / "g5_clean_runner_cutover_receipt_v1.json", cutover)
    write_json(artifact_dir / "g5_clean_runner_post_cutover_3bar_v1.json", post)
    return {"shadow": shadow, "telemetry": telemetry_receipt, "cutover": cutover, "post_cutover": post}


def validate_contract_assets() -> dict[str, Any]:
    contract = read_json(CONTRACT_PATH)
    freeze = read_json(FREEZE_PATH)
    machine = read_json(STATE_MACHINE_PATH)
    checks = {
        "contract_schema": contract.get("schema_version") == "zel.g5.clean_runner.contract.v1",
        "shadow_no_credit": contract.get("mode") == "SHADOW_NO_CREDIT" and int(contract["authority"]["formal_credit"]) == 0,
        "seven_modules_or_less": len(contract.get("logical_modules") or []) <= 7,
        "single_owner": contract.get("owner_id") == "G5_CLEAN_RUNNER_OWNER_V1",
        "source_single": contract["source"]["source_duplication_forbidden"] is True,
        "forming_bar_forbidden": contract["source"]["forming_bar_evaluation_forbidden"] is True,
        "state_machine_match": tuple(machine.get("states") or []) == STATUS_ORDER,
        "append_only": contract["state_store"]["format"] == "append_only_hash_chained_jsonl",
        "fresh_fail_closed": contract["fresh_acceptor"]["fresh_credit_without_data_stale_authority"] is False,
        "primary_excluded": contract["external_preserved_lineages"]["Primary"]["active"] is False,
        "broad_not_reset": contract["external_preserved_lineages"]["Broad"]["reset_forbidden"] is True,
        "strategy_mutation_false": contract.get("strategy_mutation") is False and freeze.get("strategy_mutation") is False,
        "rr_blocked": contract.get("rr_research_allowed") is False,
        "live_blocked": contract["authority"]["execution"] == "NONE" and contract["authority"]["order"] == "BLOCKED" and contract["authority"]["live"] == "BLOCKED",
    }
    FrozenStrategyAdapter(contract, freeze)
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise IntegrityError(f"CLEAN_RUNNER_PREFLIGHT_FAILED:{','.join(failed)}")
    return receipt({
        "schema_version": "zel.g5.clean_runner.preflight.v1",
        "generated_at_utc": utc(),
        "state": "CLEAN_RUNNER_PREFLIGHT_PASS",
        "checks": checks,
        "contract_sha256": sha_file(CONTRACT_PATH),
        "strategy_freeze_sha256": sha_file(FREEZE_PATH),
        "state_machine_sha256": sha_file(STATE_MACHINE_PATH),
        "legacy_runtime_imports": 0,
        "formal_credit": 0,
    })


def _canary_worker(path: str, key: str, payload: dict[str, Any]) -> str:
    outcome, _ = StateStore(Path(path)).transition(key, "NEW", payload)
    return outcome


def _canary_economic_row() -> dict[str, Any]:
    return {
        "trade_id": "CANARY_TRADE_V1",
        "strategy_id": "canary",
        "child_id": "canary_child",
        "strategy_sha": "CANARY",
        "entry_sha": "CANARY",
        "exit_sha": "CANARY",
        "config_sha": "CANARY",
        "symbol": "BTC-USDT",
        "side": "long",
        "signal_bar_open_ts": 1_000_000,
        "signal_bar_close_ts": 1_000_000 + INTERVAL_MS,
        "entry_ts": 1_000_000 + INTERVAL_MS,
        "entry_price": 100.0,
        "qty": 1.0,
        "notional": 100.0,
        "exit_ts": 1_000_000 + 2 * INTERVAL_MS,
        "exit_price": 101.0,
        "gross_bps": 100.0,
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "funding_bps": 0.0,
        "cost_bps_per_trade": 15.0,
        "net_bps": 85.0,
        "MFE_bps": 120.0,
        "MAE_bps": 20.0,
        "source_id": "CANARY",
        "bar_key": "BTC-USDT|4h|15400000",
        "lookahead": 0,
        "duplicate": 0,
        "formal_credit": 0,
    }


def run_canary(artifact_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="g5-clean-runner-canary-") as raw:
        root = Path(raw)
        state_path = root / "state.jsonl"
        ledger_path = root / "ledger.jsonl"
        key = "canary|canary_child|BTC-USDT|15400000"
        new_payload = {"bar_key": "BTC-USDT|4h|15400000", "closed_confirmed": True, "formal_credit": 0}
        context = multiprocessing.get_context("fork")
        with context.Pool(processes=4) as pool:
            outcomes = pool.starmap(_canary_worker, [(str(state_path), key, new_payload)] * 4)
        store = StateStore(state_path)
        restart_outcome, _ = StateStore(state_path).transition(key, "NEW", new_payload)
        store.transition(key, "EVALUATED", {"result": "BAR_EVALUATED_NO_SIGNAL", "signal": False, "formal_credit": 0})
        late_retry, _ = store.transition(key, "NEW", new_payload)
        conflict_pass = False
        try:
            store.transition(key, "NEW", {**new_payload, "closed_confirmed": False})
        except ConflictError:
            conflict_pass = True
        out_of_order_pass = False
        try:
            store.transition("canary|bad|BTC-USDT|29800000", "EVALUATED", {"signal": False})
        except ConflictError:
            out_of_order_pass = True

        lifecycle_key = "canary|canary_child|ETH-USDT|15400000"
        lifecycle = StateStore(state_path)
        lifecycle.transition(lifecycle_key, "NEW", {"bar_key": "ETH-USDT|4h|15400000", "closed_confirmed": True})
        lifecycle.transition(lifecycle_key, "EVALUATED", {"result": "SIGNAL_EMITTED", "signal": True})
        lifecycle.transition(lifecycle_key, "TRADE_OPENED", {"trade_id": "CANARY_TRADE_V1", "entry_ts": 15_400_000})
        lifecycle.transition(lifecycle_key, "TRADE_CLOSED", {"trade_id": "CANARY_TRADE_V1", "exit_ts": 29_800_000})
        ledger = EconomicLedger(ledger_path)
        economic = _canary_economic_row()
        ledger_first, ledger_record = ledger.append_trade(economic)
        ledger_retry, _ = ledger.append_trade(economic)
        lifecycle.transition(lifecycle_key, "LEDGER_WRITTEN", {
            "trade_id": "CANARY_TRADE_V1",
            "ledger_record_sha256": ledger_record["record_sha256"],
            "fresh_acceptance": "BLOCKED_SHADOW_MODE",
            "formal_credit": 0,
        })
        contract = read_json(CONTRACT_PATH)
        accepted = FreshAcceptor(contract).assess(economic, ledger_parity=True, duplicate=0, lookahead=0)
        rows = store.records()
        ledger_rows = ledger.records()
        duplicate_evaluations = max(0, sum(1 for row in rows if row.get("state_key") == key and row.get("status") == "NEW") - 1)
        exactly_checks = {
            "same_bar_twice": outcomes.count("NEW_EVALUATION") == 1 and outcomes.count("IDEMPOTENT_NOOP") == 3,
            "process_restart": restart_outcome == "IDEMPOTENT_NOOP",
            "parallel_invocation": outcomes.count("NEW_EVALUATION") == 1,
            "late_retry": late_retry == "IDEMPOTENT_NOOP",
            "out_of_order_rejected": out_of_order_pass,
            "conflicting_retry_rejected": conflict_pass,
            "no_signal_receipt": any(row.get("status") == "EVALUATED" and row.get("payload", {}).get("result") == "BAR_EVALUATED_NO_SIGNAL" for row in rows),
            "ledger_exactly_once": ledger_first == "NEW_APPEND" and ledger_retry == "IDEMPOTENT_NOOP" and len(ledger_rows) == 1,
            "hash_chain_valid": len(rows) == 7 and len(ledger_rows) == 1,
        }
        exactly = receipt({
            "schema_version": "zel.g5.clean_runner.exactly_once_test.v1",
            "generated_at_utc": utc(),
            "state": "CLEAN_RUNNER_EXACTLY_ONCE_PASS" if all(exactly_checks.values()) else "CLEAN_RUNNER_EXACTLY_ONCE_FAIL",
            "state_store": "append_only_hash_chained_jsonl",
            "key": "strategy_id|child_id|symbol|bar_close_ts",
            "checks": exactly_checks,
            "parallel_outcomes": sorted(outcomes),
            "duplicate_evaluation": duplicate_evaluations,
            "duplicate_ledger_row": max(0, len(ledger_rows) - 1),
            "formal_credit": 0,
        })
        canary_checks = {
            "one_bar_one_evaluation": duplicate_evaluations == 0,
            "duplicate_retry_noop": outcomes.count("IDEMPOTENT_NOOP") == 3,
            "restart_safe": restart_outcome == "IDEMPOTENT_NOOP",
            "fake_signal": True,
            "fake_open": any(row.get("status") == "TRADE_OPENED" for row in rows),
            "fake_close": any(row.get("status") == "TRADE_CLOSED" for row in rows),
            "ledger_one_row": len(ledger_rows) == 1,
            "fresh_blocked": accepted["accepted"] is False and accepted["formal_credit"] == 0,
            "exactly_once_suite": all(exactly_checks.values()),
        }
        canary = receipt({
            "schema_version": "zel.g5.clean_runner.canary.v1",
            "generated_at_utc": utc(),
            "state": "CLEAN_RUNNER_CANARY_PASS" if all(canary_checks.values()) else "CLEAN_RUNNER_CANARY_FAIL",
            "namespace": "CANARY_G5_CLEAN_RUNNER_V1",
            "checks": canary_checks,
            "state_records": len(rows),
            "ledger_rows": len(ledger_rows),
            "fresh_acceptance": accepted,
            "formal_credit": 0,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        })
    if exactly["state"] != "CLEAN_RUNNER_EXACTLY_ONCE_PASS" or canary["state"] != "CLEAN_RUNNER_CANARY_PASS":
        raise IntegrityError("CLEAN_RUNNER_CANARY_FAILED")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    write_json(artifact_dir / "g5_clean_runner_exactly_once_test_v1.json", exactly)
    write_json(artifact_dir / "g5_clean_runner_canary_v1.json", canary)
    return exactly, canary


def synthetic_bars(count: int = 320) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 1_700_000_000_000 - (1_700_000_000_000 % INTERVAL_MS)
    close = 100.0
    for index in range(count):
        wave = math.sin(index / 8.0) * 0.35
        drift = 0.08 if index % 31 < 20 else -0.03
        open_price = close
        close = max(1.0, open_price + drift + wave)
        high = max(open_price, close) + 0.5 + (index % 3) * 0.03
        low = min(open_price, close) - 0.45 - (index % 5) * 0.02
        rows.append({
            "bar_open_ts": start + index * INTERVAL_MS,
            "bar_close_ts": start + (index + 1) * INTERVAL_MS,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0 + (index % 17) * 23.0,
        })
    return rows


def self_test() -> dict[str, Any]:
    preflight = validate_contract_assets()
    contract = read_json(CONTRACT_PATH)
    freeze = read_json(FREEZE_PATH)
    adapter = FrozenStrategyAdapter(contract, freeze)
    bars = synthetic_bars()
    for row in bars:
        validate_bar(row)
    verify_recent_continuity("SYNTH", bars[-240:])
    results = {strategy_id: adapter.evaluate(strategy_id, bars)["result"] for strategy_id in adapter.strategies}
    assert set(results) == set(FrozenStrategyAdapter.EXPECTED_CHILDREN)
    assert contract["external_preserved_lineages"]["Broad"]["W2_T_at_design"] == 10
    assert contract["external_preserved_lineages"]["Primary"]["state"] == "RETIRED_DIAGNOSTIC_ONLY"
    return receipt({
        "schema_version": "zel.g5.clean_runner.self_test.v1",
        "generated_at_utc": utc(),
        "state": "PASS",
        "preflight_receipt_sha256": preflight["receipt_sha256"],
        "synthetic_strategy_results": results,
        "formal_credit": 0,
    })


def run_shadow(
    *, state_log: Path, economic_ledger: Path, artifact_dir: Path, scheduler_fire_ts: int,
) -> dict[str, Any]:
    preflight = validate_contract_assets()
    contract = read_json(CONTRACT_PATH)
    freeze = read_json(FREEZE_PATH)
    exactly, canary = run_canary(artifact_dir)
    adapter = FrozenStrategyAdapter(contract, freeze)
    store = StateStore(state_log)
    ledger = EconomicLedger(economic_ledger)
    source_adapter = BingxSourceAdapter(contract)
    source_by_symbol: dict[str, dict[str, Any]] = {}
    evaluation_counts = {"new": 0, "noop": 0, "signal": 0, "no_signal": 0}
    for symbol in contract["source"]["symbols"]:
        source = source_adapter.fetch(str(symbol), scheduler_fire_ts)
        source_by_symbol[str(symbol)] = source
        counts = evaluate_latest_bar(
            contract=contract,
            adapter=adapter,
            store=store,
            source=source,
            scheduler_fire_ts=scheduler_fire_ts,
        )
        for name, value in counts.items():
            evaluation_counts[name] += value
    lifecycle = process_trade_lifecycle(
        contract=contract,
        store=store,
        ledger=ledger,
        source_by_symbol=source_by_symbol,
        acceptor=FreshAcceptor(contract),
    )
    artifacts = build_runtime_artifacts(
        contract=contract,
        store=store,
        ledger=ledger,
        artifact_dir=artifact_dir,
        run_observed_at_ms=scheduler_fire_ts,
    )
    run_receipt = receipt({
        "schema_version": "zel.g5.clean_runner.run.v1",
        "generated_at_utc": utc(scheduler_fire_ts),
        "state": artifacts["shadow"]["state"],
        "mode": "SHADOW_NO_CREDIT",
        "owner_id": contract["owner_id"],
        "preflight_sha256": preflight["receipt_sha256"],
        "exactly_once_sha256": exactly["receipt_sha256"],
        "canary_sha256": canary["receipt_sha256"],
        "evaluation_counts": evaluation_counts,
        "lifecycle_counts": lifecycle,
        "shadow_receipt_sha256": artifacts["shadow"]["receipt_sha256"],
        "telemetry_receipt_sha256": artifacts["telemetry"]["receipt_sha256"],
        "formal_credit": 0,
        "exchange_order_submitted": False,
    })
    write_json(artifact_dir / "g5_clean_runner_run_latest_v1.json", run_receipt)
    return run_receipt


def initialize_status_artifacts(artifact_dir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="g5-clean-runner-init-") as raw:
        store = StateStore(Path(raw) / "state.jsonl")
        ledger = EconomicLedger(Path(raw) / "ledger.jsonl")
        build_runtime_artifacts(
            contract=read_json(CONTRACT_PATH),
            store=store,
            ledger=ledger,
            artifact_dir=artifact_dir,
            run_observed_at_ms=now_ms(),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--initialize-status", action="store_true")
    parser.add_argument("--shadow", action="store_true")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--state-log", type=Path, default=DEFAULT_STATE_LOG)
    parser.add_argument("--economic-ledger", type=Path, default=DEFAULT_ECONOMIC_LEDGER)
    parser.add_argument("--scheduler-fire-ts", type=int)
    args = parser.parse_args()
    if not any((args.self_test, args.preflight, args.canary, args.initialize_status, args.shadow)):
        parser.error("one action is required")
    if args.self_test:
        result = self_test()
        print(f"PASS_G5_CLEAN_RUNNER_SELF_TEST:{result['receipt_sha256']}")
    if args.preflight:
        result = validate_contract_assets()
        write_json(args.artifact_dir / "g5_clean_runner_preflight_v1.json", result)
        print(f"CLEAN_RUNNER_PREFLIGHT_PASS:{result['receipt_sha256']}")
    if args.canary:
        exactly, canary = run_canary(args.artifact_dir)
        print(f"CLEAN_RUNNER_EXACTLY_ONCE_PASS:{exactly['receipt_sha256']}")
        print(f"CLEAN_RUNNER_CANARY_PASS:{canary['receipt_sha256']}")
    if args.initialize_status:
        initialize_status_artifacts(args.artifact_dir)
        print("CLEAN_RUNNER_STATUS_ARTIFACTS_INITIALIZED")
    if args.shadow:
        fire_ts = int(args.scheduler_fire_ts if args.scheduler_fire_ts is not None else now_ms())
        result = run_shadow(
            state_log=args.state_log,
            economic_ledger=args.economic_ledger,
            artifact_dir=args.artifact_dir,
            scheduler_fire_ts=fire_ts,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
