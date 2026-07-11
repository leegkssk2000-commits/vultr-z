from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
OVERLAY_ROOT = Path(
    os.environ.get("Q4R3_ROUTE_A_OVERLAY_ROOT", "/tmp/q4r3-route-a-video-fidelity")
)
CURRENT_HOLDOUT_DIR = ROOT / "data" / "oos_a2" / "frozen_pre30d"
SECOND_HOLDOUT_DIR = ROOT / "data" / "oos_a3" / "raschke_second_holdout"
FORENSIC_RESULT = ROOT / "runtime" / "q4r3_route_a_raschke_forensic_rescue_latest.json"
FORENSIC_TRADES = ROOT / "runtime" / "q4r3_route_a_raschke_forensic_trades_latest.json"
OUT = ROOT / "runtime" / "q4r3_route_a_raschke_second_holdout_latest.json"
TRADES_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_second_holdout_trades_latest.json"

SYMBOLS: Dict[str, str] = {
    "BTCUSDT": "BTC-USDT",
    "ETHUSDT": "ETH-USDT",
    "SOLUSDT": "SOL-USDT",
    "XRPUSDT": "XRP-USDT",
    "LINKUSDT": "LINK-USDT",
}
API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
MINUTE_MS = 60_000
HOLDOUT_DAYS = 90
ROWS_REQUIRED = HOLDOUT_DAYS * 24 * 60
REQUEST_LIMIT = 200
REQUEST_SLEEP = 0.70
COST_LEVELS = (0.10, 0.15, 0.20)
FROZEN_MODES = ("source_core", "candle_direction")
FROZEN_CONTRACT = {
    "target_R": 2.0,
    "loss_cap_R": -0.50,
    "timeout_min": 480,
    "cooldown_min": 60,
}

sys.path.insert(0, str(OVERLAY_ROOT))
sys.path.insert(1, str(ROOT))


def _load_forensic_module() -> Any:
    path = OVERLAY_ROOT / "tools" / "q4r3_route_a_raschke_forensic_rescue.py"
    spec = importlib.util.spec_from_file_location("q4r3_raschke_forensic_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"FORENSIC_IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FORENSIC = _load_forensic_module()


def _timestamp_ms(value: Any) -> int:
    stamp = int(float(value))
    return stamp * 1000 if abs(stamp) < 100_000_000_000 else stamp


def _rows(payload: Dict[str, Any]) -> List[List[Any]]:
    rows = payload.get("rows", [])
    return rows if isinstance(rows, list) else []


def second_window_from_current_start(
    current_start_ms: int,
    rows_required: int = ROWS_REQUIRED,
) -> Tuple[int, int, int]:
    end_ms = int(current_start_ms) - MINUTE_MS
    start_ms = end_ms - (int(rows_required) - 1) * MINUTE_MS
    return start_ms, end_ms, int(rows_required)


def derive_second_window() -> Tuple[int, int, int, int]:
    reference = CURRENT_HOLDOUT_DIR / "BTCUSDT_1m_90d_pre30d.json"
    if not reference.exists():
        raise FileNotFoundError(str(reference))
    payload = json.loads(reference.read_text(errors="ignore"))
    stamps = sorted(
        _timestamp_ms(row[0])
        for row in _rows(payload)
        if isinstance(row, list) and len(row) >= 6
    )
    if len(stamps) != ROWS_REQUIRED:
        raise RuntimeError(f"CURRENT_HOLDOUT_COUNT_MISMATCH:{len(stamps)}")
    if any(stamps[index] - stamps[index - 1] != MINUTE_MS for index in range(1, len(stamps))):
        raise RuntimeError("CURRENT_HOLDOUT_GAP")
    current_start_ms = int(stamps[0])
    start_ms, end_ms, rows_required = second_window_from_current_start(current_start_ms)
    if end_ms >= current_start_ms:
        raise RuntimeError("SECOND_HOLDOUT_OVERLAP")
    return start_ms, end_ms, rows_required, current_start_ms


def _normalize_api_rows(payload: Dict[str, Any]) -> List[Dict[str, float]]:
    data = payload.get("data", [])
    if isinstance(data, dict):
        for key in ("data", "rows", "items", "klines", "candles"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []

    output: List[Dict[str, float]] = []
    for row in data:
        if isinstance(row, list) and len(row) >= 6:
            raw_ts, raw_open, raw_high, raw_low, raw_close, raw_volume = row[:6]
        elif isinstance(row, dict):
            raw_ts = row.get("time", row.get("openTime", row.get("timestamp", row.get("ts", row.get("t")))))
            raw_open = row.get("open", row.get("o"))
            raw_high = row.get("high", row.get("h"))
            raw_low = row.get("low", row.get("l"))
            raw_close = row.get("close", row.get("c"))
            raw_volume = row.get("volume", row.get("vol", row.get("v", 0.0)))
        else:
            continue
        try:
            stamp = _timestamp_ms(raw_ts)
            open_ = float(raw_open)
            high = float(raw_high)
            low = float(raw_low)
            close = float(raw_close)
            volume = float(raw_volume or 0.0)
        except (TypeError, ValueError, OverflowError):
            continue
        if min(open_, high, low, close) <= 0 or high < low or volume < 0:
            continue
        output.append(
            {
                "ts": stamp,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    return output


def _fetch_page(api_symbol: str, end_ms: int) -> List[Dict[str, float]]:
    query = urllib.parse.urlencode(
        {
            "symbol": api_symbol,
            "interval": "1m",
            "limit": REQUEST_LIMIT,
            "endTime": int(end_ms),
        }
    )
    request = urllib.request.Request(
        API + "?" + query,
        headers={
            "Accept": "application/json",
            "User-Agent": "ZEL-Q4R3-RASCHKE-SECOND-HOLDOUT/1.0",
        },
    )
    last_error = "UNKNOWN"
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if payload.get("code") not in (None, 0, "0"):
                raise RuntimeError(
                    f"BINGX_CODE={payload.get('code')}:"
                    f"{payload.get('msg', payload.get('message'))}"
                )
            rows = _normalize_api_rows(payload)
            if not rows:
                raise RuntimeError("EMPTY_PAGE")
            return rows
        except Exception as exc:
            last_error = repr(exc)
            time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"FETCH_FAILED:{api_symbol}:{last_error}")


def validate_file(
    path: Path,
    start_ms: int,
    end_ms: int,
    rows_required: int,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    if not path.exists():
        return False, None, "MISSING"
    try:
        payload = json.loads(path.read_text(errors="ignore"))
    except Exception as exc:
        return False, None, f"JSON_ERROR:{exc!r}"
    stamps = sorted(
        {
            _timestamp_ms(row[0])
            for row in _rows(payload)
            if isinstance(row, list) and len(row) >= 6
        }
    )
    if len(stamps) != rows_required:
        return False, payload, f"COUNT={len(stamps)}"
    if stamps[0] != start_ms:
        return False, payload, "START_MISMATCH"
    if stamps[-1] != end_ms:
        return False, payload, "END_MISMATCH"
    if any(stamps[index] - stamps[index - 1] != MINUTE_MS for index in range(1, len(stamps))):
        return False, payload, "GAP"
    return True, payload, "PASS"


def collect_symbol(
    symbol: str,
    api_symbol: str,
    start_ms: int,
    end_ms: int,
    rows_required: int,
    current_holdout_start_ms: int,
) -> Tuple[Path, int, str]:
    path = SECOND_HOLDOUT_DIR / f"{symbol}_1m_{HOLDOUT_DAYS}d_pre90d.json"
    valid, _, reason = validate_file(path, start_ms, end_ms, rows_required)
    if valid:
        print(f"REUSE {symbol} rows={rows_required}", flush=True)
        return path, 0, "REUSE"

    SECOND_HOLDOUT_DIR.mkdir(parents=True, exist_ok=True)
    candles: Dict[int, Dict[str, float]] = {}
    cursor = end_ms
    pages = 0
    max_pages = math.ceil(rows_required / REQUEST_LIMIT) + 25

    for page in range(1, max_pages + 1):
        api_rows = _fetch_page(api_symbol, cursor)
        pages = page
        for row in api_rows:
            stamp = int(row["ts"])
            if start_ms <= stamp <= end_ms:
                candles[stamp] = row
        oldest = min(int(row["ts"]) for row in api_rows)
        if page % 100 == 0:
            print(f"COLLECT {symbol} page={page} unique={len(candles)}", flush=True)
        if oldest <= start_ms:
            break
        cursor = oldest - MINUTE_MS
        time.sleep(REQUEST_SLEEP)

    ordered = [candles[stamp] for stamp in sorted(candles)]
    stamps = [int(row["ts"]) for row in ordered]
    failures: List[str] = []
    if len(ordered) != rows_required:
        failures.append(f"COUNT={len(ordered)}")
    if not stamps or stamps[0] != start_ms:
        failures.append("START_MISMATCH")
    if not stamps or stamps[-1] != end_ms:
        failures.append("END_MISMATCH")
    gap_count = sum(
        stamps[index] - stamps[index - 1] != MINUTE_MS
        for index in range(1, len(stamps))
    )
    if gap_count:
        failures.append(f"GAPS={gap_count}")
    if end_ms >= current_holdout_start_ms:
        failures.append("OVERLAP")
    if failures:
        raise RuntimeError(f"{symbol}:{','.join(failures)}:existing={reason}")

    payload = {
        "symbol": symbol,
        "source": "bingx_public",
        "timeframe": "1m",
        "window_relation": "strictly_before_existing_90d_holdout",
        "start_ms": start_ms,
        "end_ms": end_ms,
        "current_holdout_start_ms": current_holdout_start_ms,
        "rows_count": len(ordered),
        "rows": [
            [
                int(row["ts"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            ]
            for row in ordered
        ],
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
    print(f"PASS COLLECT {symbol} rows={len(ordered)} pages={pages}", flush=True)
    return path, pages, "COLLECTED"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(errors="ignore"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"INVALID_JSON_OBJECT:{path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_frozen_inputs() -> Dict[str, Any]:
    forensic_result = _load_json(FORENSIC_RESULT)
    queue = tuple(forensic_result.get("second_holdout_queue_frozen", []))
    if queue != FROZEN_MODES:
        raise RuntimeError(f"FROZEN_QUEUE_MISMATCH:{queue!r}")
    prior_contract = forensic_result.get("contract", {})
    expected = {
        "target_R": 2.0,
        "loss_cap_R": -0.50,
        "timeout_min": 480,
        "cooldown_min": 60,
    }
    for key, value in expected.items():
        if float(prior_contract.get(key, float("nan"))) != float(value):
            raise RuntimeError(f"FROZEN_CONTRACT_MISMATCH:{key}:{prior_contract.get(key)}")
    strategy_path = OVERLAY_ROOT / "backend" / "strategies" / "raschke_macd_ema200.py"
    if not strategy_path.exists():
        raise FileNotFoundError(str(strategy_path))
    frozen_spec = {
        "modes": list(FROZEN_MODES),
        "contract": FROZEN_CONTRACT,
        "cost_levels_pct_round_trip": list(COST_LEVELS),
        "strategy_sha256": _sha256(strategy_path),
        "selection_source": str(FORENSIC_RESULT),
    }
    canonical = json.dumps(frozen_spec, sort_keys=True, separators=(",", ":"))
    frozen_spec["frozen_spec_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return frozen_spec


def cost_survival(report: Dict[str, Any]) -> bool:
    return bool(
        float(report.get("avg_net_R", 0.0)) > 0.0
        and float(report.get("profit_factor_R", 0.0)) > 1.0
        and int(report.get("positive_symbols", 0)) >= 3
    )


def mode_verdict(costs: Dict[str, Any]) -> str:
    cost_015 = costs["cost_0.15"]["second_holdout_90d"]
    cost_020 = costs["cost_0.20"]["second_holdout_90d"]
    if FORENSIC.passes_gate(cost_015, FORENSIC.HARD_GATE) and cost_survival(cost_020):
        return "SECOND_HOLDOUT_ROBUST_PASS"
    if FORENSIC.passes_gate(cost_015, FORENSIC.HARD_GATE):
        return "SECOND_HOLDOUT_HARD_GATE_COST_FRAGILE"
    if FORENSIC.passes_gate(cost_015, FORENSIC.NEAR_GATE):
        return "SECOND_HOLDOUT_NEAR_GATE"
    return "SECOND_HOLDOUT_FAIL"


def main() -> None:
    frozen = verify_frozen_inputs()
    prior_trades_payload = _load_json(FORENSIC_TRADES)
    start_ms, end_ms, rows_required, current_start_ms = derive_second_window()

    raw_cache: Dict[str, pd.DataFrame] = {}
    integrity: Dict[str, Any] = {}
    collection: Dict[str, Any] = {}
    for symbol, api_symbol in SYMBOLS.items():
        path, pages, action = collect_symbol(
            symbol,
            api_symbol,
            start_ms,
            end_ms,
            rows_required,
            current_start_ms,
        )
        frame, report = FORENSIC.BASE.load_frame(path)
        raw_cache[symbol] = frame
        integrity[symbol] = report
        collection[symbol] = {
            "path": str(path),
            "pages": pages,
            "action": action,
        }

    second_trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    reason_counts: Dict[str, Any] = {}
    for mode in FROZEN_MODES:
        reason_counts[mode] = {}
        for symbol in SYMBOLS:
            rows, reasons = FORENSIC.run_mode_symbol(
                mode=mode,
                sample="second_holdout_90d",
                symbol=symbol,
                raw=raw_cache[symbol],
            )
            second_trades[mode].extend(rows)
            reason_counts[mode][symbol] = reasons

    evaluations: Dict[str, Any] = {}
    robust_modes: List[str] = []
    for mode in FROZEN_MODES:
        prior_mode = prior_trades_payload.get("trades", {}).get(mode, {})
        prior_holdout = prior_mode.get("holdout_90d", [])
        if not isinstance(prior_holdout, list):
            raise RuntimeError(f"PRIOR_TRADES_INVALID:{mode}")
        combined = list(prior_holdout) + list(second_trades[mode])
        costs: Dict[str, Any] = {}
        for cost in COST_LEVELS:
            key = f"cost_{cost:.2f}"
            second_report = FORENSIC.metrics(second_trades[mode], cost)
            combined_report = FORENSIC.metrics(combined, cost)
            costs[key] = {
                "second_holdout_90d": second_report,
                "combined_independent_180d": combined_report,
                "second_hard_gate": FORENSIC.passes_gate(second_report, FORENSIC.HARD_GATE),
                "second_near_gate": FORENSIC.passes_gate(second_report, FORENSIC.NEAR_GATE),
                "second_cost_survival": cost_survival(second_report),
            }
        verdict = mode_verdict(costs)
        if verdict == "SECOND_HOLDOUT_ROBUST_PASS":
            robust_modes.append(mode)
        evaluations[mode] = {
            "mechanism": FORENSIC.MODES[mode]["mechanism"],
            "config": FORENSIC.asdict(FORENSIC._mode_config(mode)),
            "costs": costs,
            "verdict": verdict,
            "second_decomposition_cost_0.15": FORENSIC.decomposition(second_trades[mode], 0.15),
        }

    if robust_modes:
        verdict = "RASCHKE_SECOND_HOLDOUT_PASS_4TH_SHADOW_CANDIDATE"
    elif any(
        evaluations[mode]["verdict"] in {
            "SECOND_HOLDOUT_HARD_GATE_COST_FRAGILE",
            "SECOND_HOLDOUT_NEAR_GATE",
        }
        for mode in FROZEN_MODES
    ):
        verdict = "RASCHKE_SECOND_HOLDOUT_RESERVE_REBUILD"
    else:
        verdict = "RASCHKE_SECOND_HOLDOUT_FAIL_NO_CORE_PROMOTION"

    trades_payload = {
        "status": "PASS_Q4R3_RASCHKE_SECOND_HOLDOUT_TRADES",
        "frozen_spec": frozen,
        "window": {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "current_holdout_start_ms": current_start_ms,
            "rows_per_symbol": rows_required,
        },
        "trades": {mode: second_trades[mode] for mode in FROZEN_MODES},
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
        },
    }
    TRADES_OUT.parent.mkdir(parents=True, exist_ok=True)
    trades_tmp = TRADES_OUT.with_suffix(".json.tmp")
    trades_tmp.write_text(json.dumps(trades_payload, ensure_ascii=False), encoding="utf-8")
    trades_tmp.replace(TRADES_OUT)

    output = {
        "status": "PASS_Q4R3_ROUTE_A_RASCHKE_SECOND_HOLDOUT",
        "verdict": verdict,
        "purpose": "untouched earlier 90d validation of pre-frozen Raschke modes",
        "frozen_spec": frozen,
        "window": {
            "relation": "strictly_before_existing_90d_holdout",
            "start_ms": start_ms,
            "end_ms": end_ms,
            "start_utc": str(pd.to_datetime(start_ms, unit="ms", utc=True)),
            "end_utc": str(pd.to_datetime(end_ms, unit="ms", utc=True)),
            "current_holdout_start_ms": current_start_ms,
            "current_holdout_start_utc": str(pd.to_datetime(current_start_ms, unit="ms", utc=True)),
            "rows_per_symbol": rows_required,
            "overlap_minutes": 0,
        },
        "collection": collection,
        "integrity": integrity,
        "reason_counts": reason_counts,
        "evaluations": evaluations,
        "robust_pass_modes": robust_modes,
        "promotion_rule": {
            "cost_0.15": FORENSIC.HARD_GATE,
            "cost_0.20_survival": {
                "avg_net_R_min_exclusive": 0.0,
                "profit_factor_R_min_exclusive": 1.0,
                "positive_symbols_min": 3,
            },
            "no_retuning": True,
        },
        "trades_out": str(TRADES_OUT),
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
        },
        "out": str(OUT),
    }
    temporary = OUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(OUT)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
