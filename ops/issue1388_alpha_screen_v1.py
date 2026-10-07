"""One-shot, costed cheap screen for Issue 1388 Internet Alpha intake.

This is research-only.  It cannot place orders or promote a strategy.  The
external signal rules are pinned by URL/commit/blob in INTAKE.json.  Historical
delivery is modeled at bar close and every fill is a conservative next-open
taker fill; this explicit adapter is not represented as the donor's live fill.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE_ROOT = Path("/home/z/z/runtime/economic7_campaign_20260915")
INTAKE_PATH = ROOT / "research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/INTAKE.json"
COST_PATH = ROOT / "research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
SOURCE_INVENTORY_SHA256 = "53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2"
COST_SHA256 = "cb9c337d95aa9eb65c32776ca68c63390350c501de4df8024b5416ed778dbe73"
START_MS = 1_768_262_400_000
END_MS = 1_781_654_400_000
WARMUP_MS = 90 * 86_400_000
CANDIDATE_ID = "E_FT_SWING_HIGH_TO_SKY_15M_V1"
SOURCE_COMMIT = "f3340ce11f5bdf62f598522e64d1f5638eaa13f5"
SOURCE_BLOB = "4289cde249a7065a83401e85cf0cf37a5f6b0627"
GLOBAL_HEAVY_GROUP = "a1-global-heavy-economic-evaluator-v1"
ACTIVATION_TOKEN = "[issue1388-alpha-screen-1-20261007T1420Z-8d31b7a]"
EXECUTION_REF = "refs/heads/research-execution-consumptions/issue1388-cheap-swinghigh-v1"
RESULT_REF = "refs/heads/research-results/issue1388-cheap-swinghigh-v1"
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT", "LINK-USDT")


class ScreenError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ScreenError("JSON_OBJECT_REQUIRED:" + path.name)
    return value


def write_once(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _commit(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def _git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False).hexdigest()


def github_create(route: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if route not in ("/git/blobs", "/git/trees", "/git/commits", "/git/refs"):
        raise ScreenError("FIXED_GIT_CREATE_ROUTE_REQUIRED")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise ScreenError("GITHUB_TOKEN_REQUIRED")
    base = "https://api.github.com/repos/leegkssk2000-commits/vultr-z"
    request = Request(base + route, method="POST", data=json.dumps(payload, separators=(",", ":")).encode(), headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urlopen(request, timeout=30) as response:
            value = json.load(response)
    except HTTPError as exc:
        if route == "/git/refs" and exc.code == 422:
            raise ScreenError("PERMANENT_REF_ALREADY_EXISTS_NO_RETRY") from None
        raise ScreenError(f"GITHUB_CREATE_HTTP_{exc.code}") from None
    if not isinstance(value, dict):
        raise ScreenError("GITHUB_OBJECT_REQUIRED")
    return value


def create_record(ref_name: str, filename: str, value: Mapping[str, Any], parent: str) -> str:
    if not _commit(parent):
        raise ScreenError("PERMANENT_PARENT_REQUIRED")
    raw = canonical_bytes(value)
    expected = _git_blob_sha(raw)
    blob = github_create("/git/blobs", {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
    if blob.get("sha") != expected:
        raise ScreenError("PERMANENT_BLOB_MISMATCH")
    tree = github_create("/git/trees", {"tree": [{"path": filename, "mode": "100644", "type": "blob", "sha": expected}]})
    commit = github_create("/git/commits", {"message": "Issue1388 " + filename, "tree": tree["sha"], "parents": [parent]})
    created = github_create("/git/refs", {"ref": ref_name, "sha": commit["sha"]})
    if created.get("ref") != ref_name or created.get("object", {}).get("sha") != commit["sha"]:
        raise ScreenError("PERMANENT_REF_READBACK")
    return str(commit["sha"])


def current_head() -> str:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True)
    if dirty or not _commit(head):
        raise ScreenError("EXECUTING_CHECKOUT_NOT_EXACT_CLEAN_COMMIT")
    return head


def validate_activation(path: Path, head: str) -> dict[str, Any]:
    value = read_json(path)
    required = {
        "schema": "zel.issue1388.alpha_screen_activation.v1",
        "issue": 1388,
        "candidate_id": CANDIDATE_ID,
        "token": ACTIVATION_TOKEN,
        "reviewed_source_sha": head,
        "source_commit": SOURCE_COMMIT,
        "source_blob": SOURCE_BLOB,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "cost_sha256": COST_SHA256,
        "period_ms": [START_MS, END_MS],
        "timeframe_min": 15,
        "global_heavy_group": GLOBAL_HEAVY_GROUP,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise ScreenError("ACTIVATION_BINDING:" + key)
    files = value.get("source_files_sha256")
    if not isinstance(files, dict):
        raise ScreenError("ACTIVATION_SOURCE_FILES")
    for relative, expected in files.items():
        if file_sha256(ROOT / relative) != expected:
            raise ScreenError("ACTIVATION_SOURCE_FILE_DRIFT:" + relative)
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1" or os.environ.get("GITHUB_EVENT_NAME") != "push":
        raise ScreenError("WORKFLOW_FIRST_ATTEMPT_PUSH_REQUIRED")
    if os.environ.get("ISSUE1388_GLOBAL_HEAVY_GROUP") != GLOBAL_HEAVY_GROUP:
        raise ScreenError("GLOBAL_HEAVY_BINDING")
    return value


def load_market(source_root: Path) -> dict[str, Any]:
    from backend.research.rebuild import scalp7_source_data_v2 as source

    if file_sha256(COST_PATH) != COST_SHA256:
        raise ScreenError("FROZEN_COST_FILE_DRIFT")
    frames = source.load_candles(source_root, 15, cache_dir=None)
    if set(frames) != set(SYMBOLS):
        raise ScreenError("SOURCE_SYMBOL_COHORT_DRIFT")
    selected: dict[str, pd.DataFrame] = {}
    for symbol, frame in frames.items():
        if frame.attrs.get("source_inventory_sha256") != SOURCE_INVENTORY_SHA256:
            raise ScreenError("SOURCE_INVENTORY_ATTRIBUTE_DRIFT")
        part = frame[(frame.open_ts_ms >= START_MS - WARMUP_MS) & (frame.open_ts_ms < END_MS)].copy().reset_index(drop=True)
        if part.empty or int(part.iloc[0].open_ts_ms) > START_MS - WARMUP_MS:
            raise ScreenError("SOURCE_WARMUP_NOT_COVERED")
        if int(part.iloc[-1].close_ts_ms) != END_MS:
            raise ScreenError("SOURCE_END_NOT_COVERED")
        part.attrs = dict(frame.attrs)
        selected[symbol] = part
    costs = read_json(COST_PATH)["costs_bps"]
    if set(costs) != set(SYMBOLS) or any(float(x) <= 0 for x in costs.values()):
        raise ScreenError("COST_PROFILE")
    return {"frames": selected, "costs": costs}


def source_receipt(market: Mapping[str, Any]) -> dict[str, Any]:
    rows = {}
    for symbol, frame in market["frames"].items():
        rows[symbol] = {
            "rows_15m": len(frame),
            "first_open_ts_ms": int(frame.iloc[0].open_ts_ms),
            "last_close_ts_ms": int(frame.iloc[-1].close_ts_ms),
            "minute_gap_count": len(frame.attrs.get("minute_gaps", [])),
            "incomplete_bucket_count": len(frame.attrs.get("incomplete_buckets", [])),
        }
    value = {
        "schema": "zel.issue1388.source_receipt.v1",
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "cost_sha256": COST_SHA256,
        "period_ms": [START_MS, END_MS],
        "timeframe_min": 15,
        "frames": rows,
        "costs_bps": {k: float(v) for k, v in market["costs"].items()},
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "order_adapter": "CONSERVATIVE_NEXT_OPEN_TAKER_STOP_FIRST",
        "donor_default_order_fill_claimed": False,
        "order_authority": "BLOCKED",
    }
    return {**value, "receipt_sha256": digest(value)}


def _rsi(close: pd.Series, period: int) -> pd.Series:
    values = close.to_numpy(dtype=float)
    output = np.full(len(values), np.nan, dtype=float)
    if len(values) <= period:
        return pd.Series(output, index=close.index)
    delta = np.diff(values)
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    average_gain = float(gain[:period].mean())
    average_loss = float(loss[:period].mean())

    def value() -> float:
        denominator = average_gain + average_loss
        return 100.0 * average_gain / denominator if denominator else 0.0

    output[period] = value()
    for i in range(period + 1, len(values)):
        average_gain = (average_gain * (period - 1) + gain[i - 1]) / period
        average_loss = (average_loss * (period - 1) + loss[i - 1]) / period
        output[i] = value()
    return pd.Series(output, index=close.index)


def _cci(frame: pd.DataFrame, period: int) -> pd.Series:
    typical = (frame.high + frame.low + frame.close) / 3
    mean = typical.rolling(period, min_periods=period).mean()
    deviation = typical.rolling(period, min_periods=period).apply(lambda x: float(np.mean(np.abs(x - np.mean(x)))), raw=True)
    return (typical - mean) / (0.015 * deviation.replace(0, np.nan))


def signals(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if "segment_id" not in frame:
        raise ScreenError("SEGMENT_ID_REQUIRED")
    entry = pd.Series(False, index=frame.index)
    exit_ = pd.Series(False, index=frame.index)
    interval = 15 * 60_000
    for _, part in frame.groupby("segment_id", sort=False, dropna=False):
        if part["segment_id"].isna().any():
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if len(part) > 1 and not part["open_ts_ms"].diff().iloc[1:].eq(interval).all():
            raise ScreenError("INTRA_SEGMENT_TIME_GAP")
        entry.loc[part.index] = ((_cci(part, 72) < -175) & (_rsi(part.close, 36) < 90)).fillna(False)
        exit_.loc[part.index] = ((_cci(part, 66) > -106) & (_rsi(part.close, 45) > 88)).fillna(False)
    return entry, exit_


def _roi(duration_minutes: int) -> float:
    if duration_minutes >= 244:
        return 0.0
    if duration_minutes >= 64:
        return 0.04093
    if duration_minutes >= 33:
        return 0.0853
    return 0.27058


def replay_symbol(symbol: str, frame: pd.DataFrame, cost_bps: float) -> tuple[list[dict[str, Any]], int, int, int, int]:
    entry_signal, exit_signal = signals(frame)
    rows = frame.to_dict("records")
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    pending_entry: dict[str, int] | None = None
    pending_exit = False
    prior_segment: Any = None
    gap_quarantined = 0
    signal_count = int(entry_signal[(frame.open_ts_ms >= START_MS) & (frame.open_ts_ms < END_MS)].sum())
    rejected_occupied = 0
    for i, bar in enumerate(rows):
        open_ms = int(bar["open_ts_ms"])
        if open_ms >= END_MS:
            break
        segment = bar.get("segment_id")
        if segment is None or (isinstance(segment, float) and math.isnan(segment)):
            raise ScreenError("SEGMENT_ID_REQUIRED")
        if prior_segment is not None and segment != prior_segment:
            gap_quarantined += int(position is not None or pending_entry is not None)
            position = None
            pending_entry = None
            pending_exit = False
        prior_segment = segment
        if pending_exit and position is not None:
            exit_price = float(bar["open"])
            gross = (exit_price / position["entry_price"] - 1) * 10_000
            trades.append({**position, "exit_ts_ms": open_ms, "exit_price": exit_price, "exit_reason": "NEXT_OPEN_EXIT_SIGNAL", "gross_bps": gross, "cost_bps": cost_bps, "net_bps": gross - cost_bps})
            position = None
            pending_exit = False
        if pending_entry is not None and position is None and START_MS <= open_ms < END_MS:
            position = {
                "identity": CANDIDATE_ID,
                "symbol": symbol,
                "signal_open_ts_ms": pending_entry["signal_open_ts_ms"],
                "signal_available_ts_ms": pending_entry["signal_available_ts_ms"],
                "entry_ts_ms": open_ms,
                "entry_price": float(bar["open"]),
                "side": "LONG",
            }
            pending_entry = None
        if position is not None:
            stop = position["entry_price"] * (1 - 0.34338)
            duration = max(0, (open_ms - position["entry_ts_ms"]) // 60_000)
            target = position["entry_price"] * (1 + _roi(int(duration)))
            exit_price = None
            reason = None
            if float(bar["low"]) <= stop:
                exit_price = min(float(bar["open"]), stop)
                reason = "STOP_FIRST"
            elif float(bar["high"]) >= target:
                exit_price = max(float(bar["open"]), target)
                reason = "ROI_TOUCH"
            if exit_price is not None:
                gross = (exit_price / position["entry_price"] - 1) * 10_000
                trades.append({**position, "exit_ts_ms": int(bar["close_ts_ms"]), "exit_price": exit_price, "exit_reason": reason, "gross_bps": gross, "cost_bps": cost_bps, "net_bps": gross - cost_bps})
                position = None
        if open_ms >= START_MS and bool(entry_signal.iloc[i]):
            if position is None and pending_entry is None and i + 1 < len(rows):
                pending_entry = {
                    "signal_open_ts_ms": open_ms,
                    "signal_available_ts_ms": int(bar["close_ts_ms"]),
                }
            else:
                rejected_occupied += 1
        if position is not None and bool(exit_signal.iloc[i]):
            pending_exit = True
    unresolved = int(position is not None or pending_entry is not None)
    return trades, signal_count, rejected_occupied, unresolved, gap_quarantined


def summarize(trades: list[dict[str, Any]], multiplier: int) -> dict[str, Any]:
    days = (END_MS - START_MS) / 86_400_000
    nets = [float(t["gross_bps"]) - multiplier * float(t["cost_bps"]) for t in trades]
    gross = sum(float(t["gross_bps"]) for t in trades)
    cost = multiplier * sum(float(t["cost_bps"]) for t in trades)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    equity = 0.0
    peak = 0.0
    dd = 0.0
    streak = max_streak = 0
    by_symbol: dict[str, float] = {}
    for trade, net in zip(trades, nets):
        equity += net
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        streak = streak + 1 if net <= 0 else 0
        max_streak = max(max_streak, streak)
        by_symbol[trade["symbol"]] = by_symbol.get(trade["symbol"], 0.0) + net
    total_abs = sum(abs(v) for v in by_symbol.values())
    return {
        "T": len(trades), "T_per_day": len(trades) / days,
        "WR_pct": 100 * len(wins) / len(trades) if trades else 0.0,
        "Gross_bps": gross, "Cost_bps": cost, "Net_bps": gross - cost,
        "GrossExp_bps_T": gross / len(trades) if trades else None,
        "CostExp_bps_T": cost / len(trades) if trades else None,
        "NetExp_bps_T": (gross - cost) / len(trades) if trades else None,
        "Net_bps_per_day": (gross - cost) / days,
        "payoff": (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None,
        "PF": sum(wins) / abs(sum(losses)) if losses else (None if not wins else "INF"),
        "DD_kind": "REALIZED_TRADE_CLOSE_EQUITY_BPS", "DD_bps": dd,
        "MaxLossStreak": max_streak,
        "concentration": {"largest_symbol_abs_net_share": max((abs(v) for v in by_symbol.values()), default=0.0) / total_abs if total_abs else None, "by_symbol_net_bps": by_symbol},
    }


def screen(market: Mapping[str, Any]) -> dict[str, Any]:
    all_trades: list[dict[str, Any]] = []
    signals_total = occupied = unresolved = gap_quarantined = 0
    for symbol in SYMBOLS:
        trades, signal_count, rejected, open_count, quarantined = replay_symbol(symbol, market["frames"][symbol], float(market["costs"][symbol]))
        all_trades.extend(trades)
        signals_total += signal_count
        occupied += rejected
        unresolved += open_count
        gap_quarantined += quarantined
    all_trades.sort(key=lambda row: (row["exit_ts_ms"], row["symbol"]))
    one, two = summarize(all_trades, 1), summarize(all_trades, 2)
    disposition = "SCREEN_SURVIVOR_PENDING_FULL" if one["T"] > 0 and one["Net_bps"] > 0 and two["Net_bps"] > 0 else "REJECT_ECONOMIC_EARLY"
    value = {
        "schema": "zel.issue1388.cheap_screen_result.v1", "issue": 1388,
        "candidate_id": CANDIDATE_ID, "source_commit": SOURCE_COMMIT, "source_blob": SOURCE_BLOB,
        "period_ms": [START_MS, END_MS], "timeframe_min": 15,
        "classification": "DEVELOPMENT_ONLY_NOT_FRESH_NOT_OOS",
        "signal_rules": "SOURCE_EXACT_SWING_HIGH_TO_SKY_DEFAULT_PARAMETERS",
        "order_adapter": "CONSERVATIVE_NEXT_OPEN_TAKER_STOP_FIRST",
        "donor_live_fill_equivalence": False,
        "census": {"signals_or_attempts": signals_total, "completed": len(all_trades), "occupied_rejections": occupied, "gap_quarantined": gap_quarantined, "unresolved_end": unresolved, "missing_fill_evidence": 0},
        "trades": all_trades, "cost_1x": one, "cost_2x": two,
        "disposition": disposition, "full_consumed": 0,
        "order_authority": "BLOCKED", "exchange_order_submitted": False, "promotion": False,
    }
    return {**value, "result_sha256": digest(value)}


def execute(source_root: Path, activation_path: Path, output_dir: Path) -> dict[str, Any]:
    head = current_head()
    activation = validate_activation(activation_path, head)
    if output_dir.exists():
        raise ScreenError("OUTPUT_DIRECTORY_ALREADY_EXISTS_NO_RETRY")
    market = load_market(source_root)
    receipt = source_receipt(market)
    start = {
        "schema": "zel.issue1388.alpha_screen_start.v1", "issue": 1388,
        "candidate_id": CANDIDATE_ID, "state": "STARTED_AFTER_INPUT_VALIDATION_BEFORE_SIGNAL_COMPUTE",
        "reviewed_source_sha": head, "source_receipt_sha256": receipt["receipt_sha256"],
        "activation_sha256": digest(activation), "period_ms": [START_MS, END_MS],
        "global_heavy_group": GLOBAL_HEAVY_GROUP, "order_authority": "BLOCKED",
    }
    start_commit = create_record(EXECUTION_REF, "STARTED.json", start, head)
    output_dir.mkdir(parents=True)
    write_once(output_dir / "SOURCE_RECEIPT.json", receipt)
    write_once(output_dir / "STARTED.json", {**start, "execution_commit_sha": start_commit})
    result = screen(market)
    write_once(output_dir / "RESULT.json", result)
    audited = read_json(output_dir / "RESULT.json")
    supplied = audited.pop("result_sha256")
    if supplied != digest(audited) or audited.get("cost_1x") != summarize(audited["trades"], 1) or audited.get("cost_2x") != summarize(audited["trades"], 2):
        raise ScreenError("SAVED_RESULT_AUDIT_FAIL")
    envelope = {"schema": "zel.issue1388.persisted_result.v1", "issue": 1388, "execution_commit_sha": start_commit, "result": result, "order_authority": "BLOCKED"}
    envelope = {**envelope, "envelope_sha256": digest(envelope)}
    result_commit = create_record(RESULT_REF, "RESULT.json", envelope, start_commit)
    write_once(output_dir / "PERSISTED.json", {**envelope, "result_commit_sha": result_commit})
    return {"state": "COMPLETE_PERSISTED_AND_AUDITED", "disposition": result["disposition"], "result_sha256": result["result_sha256"], "result_commit_sha": result_commit, "economic_table": {"1x": result["cost_1x"], "2x": result["cost_2x"]}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--activation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.source_root, args.activation, args.output_dir), sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
