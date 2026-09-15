"""Saved-result candle anatomy only; never generates signals or replays economics."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
import gzip
import hashlib
import html
import importlib
import json
import math
from pathlib import Path
import statistics
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

LANES = {"trend_rider", "break_and_continue", "supertrend_pullback"}
CATEGORIES = ("winner", "loss", "immediate_fail", "fat_winner", "mfe_giveback")
PRE_BARS = 8
POST_BARS = 12
EXAMPLES = 2
SCHEMA = "zel.scalp7.saved_result_candle_anatomy.v2"
ROOT = Path(__file__).resolve().parents[3]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("ANATOMY_NONFINITE_VALUE")
    return number


def _integer(value: Any) -> int:
    number = _finite(value)
    if number != int(number):
        raise ValueError("ANATOMY_NONINTEGER_TIME")
    return int(number)


def _prepare_frame(
    frame: pd.DataFrame, tf_ms: int
) -> tuple[dict[int, dict[str, Any]], str]:
    """Only the source OHLC prefix contributes to signal-time numerical features."""
    mapped: dict[int, dict[str, Any]] = {}
    previous: dict[str, Any] | None = None
    segment_rows: list[dict[str, Any]] = []
    true_ranges: list[float] = []
    atr: float | None = None
    availability = 0
    source_rows = []
    for raw in frame.to_dict("records"):
        required = (
            "open_ts_ms",
            "close_ts_ms",
            "available_ts_ms",
            "segment_id",
            "open",
            "high",
            "low",
            "close",
        )
        if any(k not in raw for k in required):
            raise ValueError("ANATOMY_CANDLE_SCHEMA_REQUIRED")
        row: dict[str, Any] = {k: _integer(raw[k]) for k in required[:3]}
        if raw["segment_id"] is None or pd.isna(raw["segment_id"]):
            raise ValueError("ANATOMY_SEGMENT_REQUIRED")
        row["segment_id"] = str(raw["segment_id"])
        row.update({k: _finite(raw[k]) for k in required[4:]})
        if row["open_ts_ms"] % tf_ms or row["close_ts_ms"] != row["open_ts_ms"] + tf_ms:
            raise ValueError("ANATOMY_UTC_TIMEFRAME_REQUIRED")
        if row["available_ts_ms"] < row["close_ts_ms"]:
            raise ValueError("ANATOMY_AVAILABLE_BEFORE_CLOSE")
        if previous is not None and row["open_ts_ms"] <= previous["open_ts_ms"]:
            raise ValueError("ANATOMY_DUPLICATE_OR_UNSORTED_SOURCE")
        o, h, low, c = (row[k] for k in ("open", "high", "low", "close"))
        if min(o, h, low, c) <= 0 or low > min(o, c) or h < max(o, c):
            raise ValueError("ANATOMY_INVALID_OHLC")
        if "volume" in raw and raw["volume"] is not None and not pd.isna(raw["volume"]):
            row["volume"] = _finite(raw["volume"])
            if row["volume"] < 0:
                raise ValueError("ANATOMY_NEGATIVE_VOLUME")
        else:
            row["volume"] = None
        source_rows.append(dict(row))
        contiguous = (
            previous is not None
            and previous["close_ts_ms"] == row["open_ts_ms"]
            and previous["segment_id"] == row["segment_id"]
        )
        if not contiguous:
            segment_rows, true_ranges, atr, availability = [], [], None, 0
        prior_close = segment_rows[-1]["close"] if segment_rows else c
        tr = max(h - low, abs(h - prior_close), abs(low - prior_close))
        true_ranges.append(tr)
        if atr is not None:
            atr = (13 * atr + tr) / 14
        elif len(true_ranges) == 14:
            atr = sum(true_ranges) / 14
        availability = max(availability, row["available_ts_ms"])
        rng = h - low
        row["numerical_base"] = {
            "body_fraction": abs(c - o) / rng if rng else None,
            "upper_wick_fraction": (h - max(o, c)) / rng if rng else None,
            "lower_wick_fraction": (min(o, c) - low) / rng if rng else None,
            "close_location_from_low": (c - low) / rng if rng else None,
            "signal_range_atr14": rng / atr if atr else None,
            "signal_true_range_atr14": tr / atr if atr else None,
            "prior_close_return_bps": (
                (c / prior_close - 1) * 10000 if segment_rows else None
            ),
            "four_bar_close_return_bps": (
                (c / segment_rows[-4]["close"] - 1) * 10000
                if len(segment_rows) >= 4
                else None
            ),
            "breaks_prior_high": (
                int(c > segment_rows[-1]["high"]) if segment_rows else None
            ),
            "breaks_prior_low": (
                int(c < segment_rows[-1]["low"]) if segment_rows else None
            ),
            "contiguous_prior_bar_count": len(segment_rows),
        }
        row["feature_available_ts_ms"] = availability
        segment_rows.append(row)
        mapped[row["open_ts_ms"]] = row
        previous = row
    return mapped, _sha(_json(source_rows))


def _features(source: Mapping[str, Any], trade: Mapping[str, Any]) -> dict[str, Any]:
    if int(source["feature_available_ts_ms"]) > int(trade["signal_ts_ms"]):
        raise ValueError("ANATOMY_SIGNAL_BEFORE_CAUSAL_FEATURE_AVAILABILITY")
    side = int(trade["side"])
    if side not in (-1, 1):
        raise ValueError("ANATOMY_SINGLE_DIRECTION_REQUIRED")
    base = dict(source["numerical_base"])
    location = base.pop("close_location_from_low")
    base["aligned_close_location"] = (
        location if side == 1 or location is None else 1 - location
    )
    for name in ("prior_close_return_bps", "four_bar_close_return_bps"):
        if base[name] is not None:
            base[name] *= side
    base["side_aligned_prior_extreme_break"] = base.pop(
        "breaks_prior_high" if side == 1 else "breaks_prior_low"
    )
    base.pop("breaks_prior_low" if side == 1 else "breaks_prior_high")
    return base


def _window(
    trade: Mapping[str, Any], mapped: Mapping[int, dict[str, Any]], tf_ms: int
) -> list[dict[str, Any]]:
    opened = int(trade["signal_open_ts_ms"])
    origin = mapped[opened]
    minimum, maximum = min(mapped), max(mapped)
    candles = []
    for offset in range(-PRE_BARS, POST_BARS + 1):
        stamp = opened + offset * tf_ms
        raw = mapped.get(stamp)
        if raw is None:
            candles.append(
                {
                    "relative_bar": offset,
                    "open_ts_ms": stamp,
                    "missing": True,
                    "missing_kind": (
                        "OUTSIDE_SOURCE_RANGE"
                        if stamp < minimum or stamp > maximum
                        else "SOURCE_GAP"
                    ),
                    "synthetic_fill": False,
                }
            )
            continue
        candle = {
            k: raw[k]
            for k in (
                "open_ts_ms",
                "close_ts_ms",
                "available_ts_ms",
                "segment_id",
                "open",
                "high",
                "low",
                "close",
                "volume",
            )
        }
        candle.update(
            {
                "relative_bar": offset,
                "missing": False,
                "same_segment_as_signal": raw["segment_id"] == origin["segment_id"],
                "feature_role": (
                    "CAUSAL_AT_SIGNAL"
                    if offset <= 0
                    and raw["available_ts_ms"] <= int(trade["signal_ts_ms"])
                    and raw["segment_id"] == origin["segment_id"]
                    else "OUTCOME_OR_OTHER_SEGMENT_DIAGNOSTIC_ONLY"
                ),
            }
        )
        candles.append(candle)
    return candles


def _partition_trades(
    ledger: Mapping[str, Any], identity: str, lane: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    windows = {
        r["window"]["label"]: r["window"] for r in ledger.get("window_receipts", [])
    }
    groups: dict[str, list[dict[str, Any]]] = {
        str(w["partition"]): [] for w in windows.values()
    }
    excluded: Counter[str] = Counter()
    seen: set[tuple[Any, ...]] = set()
    for raw in ledger["trades"]:
        trade = dict(raw)
        if trade["identity"] != identity or trade["lane"] != lane or trade.get("legs"):
            raise ValueError("ANATOMY_CURRENT_REBUILD_SINGLE_LANE_REQUIRED")
        signal, entry, exited, available = [
            _integer(trade[k])
            for k in (
                "signal_ts_ms",
                "entry_ts_ms",
                "exit_ts_ms",
                "outcome_available_ts_ms",
            )
        ]
        if not signal <= entry <= exited <= available:
            raise ValueError("ANATOMY_TRADE_CLOCK_INVALID")
        key = (identity, str(trade["symbol"]), signal, entry, exited)
        if key in seen:
            raise ValueError("ANATOMY_DUPLICATE_TRADE")
        seen.add(key)
        window = windows.get(trade["window_label"])
        if window is None or trade["partition"] != window["partition"]:
            raise ValueError("ANATOMY_PARTITION_RECEIPT_REQUIRED")
        if not int(window["start_ms"]) <= signal < int(
            window["end_ms"]
        ) or available >= int(window["end_ms"]):
            excluded["OUTSIDE_COMPLETE_WINDOW_EVIDENCE"] += 1
            continue
        groups.setdefault(str(trade["partition"]), []).append(trade)
    for rows in groups.values():
        rows.sort(
            key=lambda r: (
                r["signal_ts_ms"],
                r["entry_ts_ms"],
                str(r["symbol"]),
                r["exit_ts_ms"],
            )
        )
    return groups, dict(excluded)


def build_anatomy(
    evidence: Mapping[str, Any],
    ledger: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    candidate = evidence["candidate"]
    identity, lane, tf = (
        str(candidate["identity"]),
        str(candidate["lane"]),
        int(candidate["tf"]),
    )
    if lane not in LANES or tf not in (15, 30):
        raise ValueError("ANATOMY_CURRENT_15M30M_REBUILD_ONLY")
    if evidence.get("window_receipts") != ledger.get("window_receipts"):
        raise ValueError("ANATOMY_EVIDENCE_LEDGER_WINDOWS_MISMATCH")
    tf_ms = tf * 60000
    prepared = {
        symbol: _prepare_frame(frame, tf_ms) for symbol, frame in sorted(frames.items())
    }
    partitions, excluded = _partition_trades(ledger, identity, lane)
    output: dict[str, Any] = {
        "schema": SCHEMA,
        "identity": identity,
        "lane": lane,
        "timeframe_min": tf,
        "module_sha256": evidence["module_sha256"],
        "source_result_cohort": (
            "SOURCE_BINDING_REPAIR"
            if evidence.get("source_binding_repair_sha256")
            else "ORIGINAL_RESULT_COHORT"
        ),
        "source_binding_repair_sha256": evidence.get("source_binding_repair_sha256"),
        "ledger_sha256": evidence["ledger_sha256"],
        "economic_executions": 0,
        "selection_authority": False,
        "entry_feature_authority": False,
        "outcome_labels_are_diagnostic_only": True,
        "historical_retune": False,
        "candle_parameters": {
            "pre_bars": PRE_BARS,
            "post_bars": POST_BARS,
            "examples_per_category": EXAMPLES,
        },
        "category_definitions": {
            "winner": "saved net_bps > 0",
            "loss": "saved net_bps < 0",
            "immediate_fail": "saved net_bps < 0 and saved hold_bars <= 2",
            "fat_winner": "top ceil(10% * positive-trade count) by saved net within this identity and partition; descriptive outcome label only",
            "mfe_giveback": "saved conservative mfe_R >= 1 and saved net_bps <= 0",
        },
        "example_selection": "first two chronological members per category; overlapping categories explicitly retained",
        "source_frame_sha256": {s: value[1] for s, value in prepared.items()},
        "source_frame_hash_fields": "ordered open/close/available timestamps, segment, OHLC and nullable original volume; no synthetic volume",
        "excluded_counts": excluded,
        "partitions": {},
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
    }
    for partition, trades in sorted(partitions.items()):
        positives = sorted(
            [r for r in trades if _finite(r["net_bps"]) > 0],
            key=lambda r: (
                -_finite(r["net_bps"]),
                r["signal_ts_ms"],
                str(r["symbol"]),
                r["entry_ts_ms"],
            ),
        )
        fat_keys = {
            (r["symbol"], r["signal_ts_ms"], r["entry_ts_ms"])
            for r in positives[: math.ceil(len(positives) * 0.1)]
        }
        members: dict[str, list[dict[str, Any]]] = {c: [] for c in CATEGORIES}
        for trade in trades:
            symbol = str(trade["symbol"])
            if (
                symbol not in prepared
                or int(trade["signal_open_ts_ms"]) not in prepared[symbol][0]
            ):
                raise ValueError("ANATOMY_SIGNAL_CANDLE_MISSING")
            if int(trade["timeframe_min"]) != tf:
                raise ValueError("ANATOMY_LEDGER_TIMEFRAME_MISMATCH")
            net = _finite(trade["net_bps"])
            mfe = _finite(trade["mfe_R"])
            hold = _integer(trade["hold_bars"])
            if hold < 1 or mfe < 0:
                raise ValueError("ANATOMY_INVALID_HOLD_OR_MFE")
            labels = []
            if net > 0:
                labels.append("winner")
            elif net < 0:
                labels.append("loss")
            if net < 0 and hold <= 2:
                labels.append("immediate_fail")
            if (
                trade["symbol"],
                trade["signal_ts_ms"],
                trade["entry_ts_ms"],
            ) in fat_keys:
                labels.append("fat_winner")
            if mfe >= 1 and net <= 0:
                labels.append("mfe_giveback")
            feature = _features(
                prepared[symbol][0][int(trade["signal_open_ts_ms"])], trade
            )
            item = {
                **trade,
                "diagnostic_categories": labels,
                "causal_features_at_signal": feature,
            }
            for label in labels:
                members[label].append(item)
        summaries = {}
        for category, rows in members.items():
            features = rows[0]["causal_features_at_signal"] if rows else {}
            medians = {}
            for name in features:
                vals = [
                    r["causal_features_at_signal"][name]
                    for r in rows
                    if r["causal_features_at_signal"][name] is not None
                ]
                medians[name] = statistics.median(vals) if vals else None
            examples = []
            for row in rows[:EXAMPLES]:
                saved = {
                    k: row[k]
                    for k in (
                        "identity",
                        "symbol",
                        "side",
                        "signal_open_ts_ms",
                        "signal_ts_ms",
                        "entry_ts_ms",
                        "exit_ts_ms",
                        "outcome_available_ts_ms",
                        "net_bps",
                        "gross_bps",
                        "cost_bps",
                        "mfe_R",
                        "hold_bars",
                        "reason",
                        "partition",
                        "window_label",
                    )
                }
                examples.append(
                    {
                        "saved_trade": saved,
                        "diagnostic_categories": row["diagnostic_categories"],
                        "causal_features_at_signal": row["causal_features_at_signal"],
                        "candles": _window(row, prepared[str(row["symbol"])][0], tf_ms),
                        "exit_outside_display_window": int(row["exit_ts_ms"])
                        > int(row["signal_open_ts_ms"]) + (POST_BARS + 1) * tf_ms,
                    }
                )
            summaries[category] = {
                "category_count": len(rows),
                "examples_available": len(examples),
                "median_causal_features": medians,
                "examples": examples,
            }
        output["partitions"][partition] = {
            "eligible_saved_trade_count": len(trades),
            "neutral_net_trade_count": sum(float(r["net_bps"]) == 0 for r in trades),
            "categories": summaries,
        }
    return output


def render_svg(report: Mapping[str, Any], partition: str) -> str:
    """Exact OHLC vector candles. Future/outcome bars are shaded and never features."""
    body = report["partitions"][partition]
    examples = [
        (category, example)
        for category in CATEGORIES
        for example in body["categories"][category]["examples"]
    ]
    width, height = 1140, max(190, 130 + 240 * len(examples))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#101820"/>',
        '<g fill="#e8edf3" font-family="monospace">',
        f'<text x="25" y="28" font-size="16">{html.escape(str(report["identity"]))}</text>',
        f'<text x="25" y="52">{html.escape(partition)} | {report["timeframe_min"]}m | saved results only; no economic rerun</text>',
        '<text x="25" y="74" font-size="11">signal=0; bars +1 onward shaded: outcome anatomy only. Red dashed slots preserve missing source bars.</text>',
    ]
    if not examples:
        parts.append(
            '<text x="25" y="120">No examples in the saved evidence partition.</text>'
        )
    for n, (category, example) in enumerate(examples):
        trade = example["saved_trade"]
        top = 135 + 240 * n
        label = f'{category} | {trade["symbol"]} side={trade["side"]} | net={trade["net_bps"]:.2f}bps MFE={trade["mfe_R"]:.2f}R hold={trade["hold_bars"]}bars'
        parts.append(
            f'<text x="25" y="{top-25}" font-size="12">{html.escape(label)}</text>'
        )
        candles = example["candles"]
        visible = [c for c in candles if not c["missing"]]
        low, high = min(c["low"] for c in visible), max(c["high"] for c in visible)
        scale = 160 / max(high - low, 1e-12)
        for j, candle in enumerate(candles):
            x = 60 + j * 49
            offset = candle["relative_bar"]
            if offset > 0:
                parts.append(
                    f'<rect x="{x-23}" y="{top-9}" width="49" height="188" fill="#1d2c3b"/>'
                )
            if candle["missing"]:
                parts.append(
                    f'<rect x="{x-15}" y="{top+30}" width="30" height="90" fill="none" stroke="#ff8278" stroke-dasharray="4 3"/>'
                )
            else:
                yhigh = top + (high - candle["high"]) * scale
                ylow = top + (high - candle["low"]) * scale
                yo, yc = (
                    top + (high - candle["open"]) * scale,
                    top + (high - candle["close"]) * scale,
                )
                color = "#69daa4" if candle["close"] >= candle["open"] else "#ff8278"
                parts.append(
                    f'<line x1="{x}" x2="{x}" y1="{yhigh:.3f}" y2="{ylow:.3f}" stroke="{color}"/><rect x="{x-9}" y="{min(yo,yc):.3f}" width="18" height="{max(1,abs(yo-yc)):.3f}" fill="{color}"/>'
                )
            if offset == 0:
                parts.append(
                    f'<line x1="{x}" x2="{x}" y1="{top-12}" y2="{top+178}" stroke="#f8d56b" stroke-dasharray="2 4"/>'
                )
            parts.append(
                f'<text x="{x-7}" y="{top+195}" font-size="10">{offset}</text>'
            )
        parts.append(
            f'<text x="25" y="{top+216}" font-size="10">Source range {low:.7g}–{high:.7g}; no fabricated gap bars; outcome labels must not feed entry logic.</text>'
        )
    parts.append("</g></svg>\n")
    return "".join(parts)


def _immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError("ANATOMY_OUTPUT_EXISTS_WITH_DIFFERENT_CONTENT")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def extract_saved(
    evidence_path: Path,
    frames: Mapping[str, pd.DataFrame],
    out_dir: Path,
    *,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    """Read a completed individual campaign result; fail before output if ledger changed."""
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    ledger_path = (repo_root / evidence["ledger_path"]).resolve()
    if not ledger_path.is_relative_to(repo_root.resolve()):
        raise ValueError("ANATOMY_LEDGER_OUTSIDE_REPOSITORY")
    raw = ledger_path.read_bytes()
    if _sha(raw) != evidence["ledger_sha256"]:
        raise ValueError("ANATOMY_SAVED_LEDGER_HASH_MISMATCH")
    ledger = json.loads(gzip.decompress(raw))
    report = build_anatomy(evidence, ledger, frames)
    report["source_evidence_path"] = str(evidence_path)
    report["source_evidence_sha256"] = _sha(evidence_bytes)
    report["source_ledger_path"] = str(ledger_path)
    name = report["identity"]
    if not name or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for c in name
    ):
        raise ValueError("ANATOMY_UNSAFE_IDENTITY_FILENAME")
    if any(
        partition not in {"train", "training", "validation", "rolling", "fresh"}
        for partition in report["partitions"]
    ):
        raise ValueError("ANATOMY_UNKNOWN_EVIDENCE_PARTITION")
    _immutable(out_dir / (name + ".anatomy.json"), _json(report))
    for partition in report["partitions"]:
        if partition not in {"train", "training", "validation", "rolling", "fresh"}:
            raise ValueError("ANATOMY_UNKNOWN_EVIDENCE_PARTITION")
        _immutable(
            out_dir / (name + "." + partition + ".svg"),
            render_svg(report, partition).encode(),
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    if not args.result.is_file():
        raise FileNotFoundError("COMPLETED_ROOT_RESULT_REQUIRED_NO_EXECUTION")
    evidence = json.loads(args.result.read_text())
    source: Any = importlib.import_module(
        "backend.research.rebuild.scalp7_source_data_v2"
    )
    frames = source.load_candles(
        args.source_root, int(evidence["candidate"]["tf"]), cache_dir=args.cache_dir
    )
    report = extract_saved(args.result, frames, args.out_dir)
    print(
        json.dumps(
            {
                "identity": report["identity"],
                "partitions": list(report["partitions"]),
                "economic_executions": 0,
                "out_dir": str(args.out_dir),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
