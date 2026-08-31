from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_EMA_CAUSAL_CONTEXT_HELPER_V1"
SCOPE = "EMA_ENTRY_CONTEXT_READ_ONLY"


def stable_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text(row: Mapping[str, Any], keys: Sequence[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def number(row: Mapping[str, Any], keys: Sequence[str]) -> float:
    for key in keys:
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    return 0.0


def event_id(row: Mapping[str, Any]) -> str:
    return text(row, ("event_id", "trade_id", "position_id"))


def window_id(row: Mapping[str, Any]) -> str:
    return text(row, ("window_id", "window"), "unknown")


def symbol(row: Mapping[str, Any]) -> str:
    return text(row, ("symbol", "market")).upper()


def timestamp_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return text(row, ("exit_ts", "exit_time", "captured_at")), event_id(row)


def max_drawdown(values: Sequence[float]) -> float:
    equity = peak = worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def profit_factor(gross_profit: float, gross_loss: float) -> float | None:
    if gross_loss > 0:
        return gross_profit / gross_loss
    if gross_profit > 0:
        return 999.0
    return None


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=timestamp_key)
    values = [number(row, ("realized_R", "net_R", "pnl_r", "net_reference_R")) for row in ordered]
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    return {
        "trade_count": len(rows),
        "net_R": sum(values),
        "profit_factor": profit_factor(gross_profit, gross_loss),
        "max_drawdown_R": max_drawdown(values),
        "event_id_set_sha256": stable_sha(sorted(event_id(row) for row in rows)),
    }


def delta(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    base_pf = base.get("profit_factor")
    candidate_pf = candidate.get("profit_factor")
    return {
        "delta_net_R": float(candidate["net_R"]) - float(base["net_R"]),
        "delta_max_drawdown_R": float(candidate["max_drawdown_R"]) - float(base["max_drawdown_R"]),
        "delta_profit_factor": float(candidate_pf) - float(base_pf) if base_pf is not None and candidate_pf is not None else None,
        "retention_pct": int(candidate["trade_count"]) / max(int(base["trade_count"]), 1) * 100.0,
    }


def read_rows(path: Path, strategy_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise RuntimeError(f"ROW_NOT_OBJECT:{line_number}")
            if text(payload, ("strategy_id", "strategy", "strategy_name")) == strategy_id:
                rows.append(dict(payload))
    return rows


def epoch_ns(pd_module: Any, value: Any) -> int | None:
    try:
        stamp = pd_module.Timestamp(value)
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC").tz_localize(None)
        return int(stamp.value)
    except Exception:
        return None


def resolve_path(root: Path, row: Mapping[str, Any]) -> Path:
    for key in ("path", "file", "csv_path", "relative_path"):
        value = row.get(key)
        if isinstance(value, str) and value:
            path = Path(value)
            return path if path.is_absolute() else root / path
    raise RuntimeError("DATA_FILE_PATH_MISSING")
