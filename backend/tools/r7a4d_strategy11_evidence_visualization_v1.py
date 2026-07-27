from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "R7A4D_STRATEGY11_EVIDENCE_VISUALIZATION_V1"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return sha256(path)


def write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return sha256(path)


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def parse_time(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def svg_shell(width: int, height: int, title: str, body: str) -> str:
    safe = html.escape(title)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">' 
        '<rect width="100%" height="100%" fill="white"/>'
        f'<text x="20" y="28" font-family="sans-serif" font-size="18">{safe}</text>'
        f'{body}</svg>\n'
    )


def empty_svg(title: str, note: str) -> str:
    return svg_shell(900, 360, title, f'<text x="30" y="180" font-family="sans-serif" font-size="16">{html.escape(note)}</text>')


def line_svg(values: Sequence[float], title: str, zero_line: bool = True) -> str:
    if not values:
        return empty_svg(title, "NO_TRADES")
    width, height = 1000, 420
    left, right, top, bottom = 65, 25, 50, 45
    low = min(values + ([0.0] if zero_line else []))
    high = max(values + ([0.0] if zero_line else []))
    if abs(high - low) < 1e-12:
        high, low = high + 1.0, low - 1.0
    xscale = (width - left - right) / max(1, len(values) - 1)
    yscale = (height - top - bottom) / (high - low)
    points = []
    for index, value in enumerate(values):
        x = left + index * xscale
        y = top + (high - value) * yscale
        points.append(f"{x:.2f},{y:.2f}")
    body = [
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#222"/>',
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#222"/>',
        f'<text x="5" y="{top+5}" font-family="sans-serif" font-size="12">{high:.4f}</text>',
        f'<text x="5" y="{height-bottom}" font-family="sans-serif" font-size="12">{low:.4f}</text>',
    ]
    if zero_line and low <= 0 <= high:
        y0 = top + high * yscale
        body.append(f'<line x1="{left}" y1="{y0:.2f}" x2="{width-right}" y2="{y0:.2f}" stroke="#888" stroke-dasharray="5 5"/>')
    body.append(f'<polyline fill="none" stroke="#174ea6" stroke-width="2" points="{" ".join(points)}"/>')
    return svg_shell(width, height, title, "".join(body))


def bar_svg(values: Sequence[float], title: str) -> str:
    if not values:
        return empty_svg(title, "NO_TRADES")
    width, height = 1000, 420
    left, right, top, bottom = 65, 25, 50, 45
    low = min(min(values), 0.0)
    high = max(max(values), 0.0)
    if abs(high - low) < 1e-12:
        high, low = high + 1.0, low - 1.0
    yscale = (height - top - bottom) / (high - low)
    y0 = top + high * yscale
    step = (width - left - right) / max(1, len(values))
    bar_width = max(1.0, step * 0.72)
    body = [
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#222"/>',
        f'<line x1="{left}" y1="{y0:.2f}" x2="{width-right}" y2="{y0:.2f}" stroke="#444"/>',
    ]
    for index, value in enumerate(values):
        x = left + index * step + (step - bar_width) / 2
        y = top + (high - max(value, 0.0)) * yscale
        h = abs(value) * yscale
        if value < 0:
            y = y0
        fill = "#1b8a5a" if value >= 0 else "#b3261e"
        body.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{max(1.0,h):.2f}" fill="{fill}"/>')
    return svg_shell(width, height, title, "".join(body))


def scatter_svg(points: Sequence[tuple[float, float]], title: str) -> str:
    if not points:
        return empty_svg(title, "NO_MFE_MAE")
    width, height = 900, 480
    left, right, top, bottom = 65, 25, 55, 50
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    xmax = max(max(xs), 1e-6)
    ymax = max(max(ys), 1e-6)
    body = [
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#222"/>',
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#222"/>',
        f'<text x="{width/2-25}" y="{height-12}" font-family="sans-serif" font-size="12">MAE R</text>',
        f'<text x="8" y="{top}" font-family="sans-serif" font-size="12">MFE R</text>',
    ]
    for xvalue, yvalue in points:
        x = left + xvalue / xmax * (width - left - right)
        y = height - bottom - yvalue / ymax * (height - top - bottom)
        body.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#174ea6" fill-opacity="0.65"/>')
    return svg_shell(width, height, title, "".join(body))


def aggregate(trades: Sequence[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[str(trade.get(key) or "UNKNOWN")].append(trade)
    output = []
    for label, rows in sorted(groups.items()):
        net = [number(row.get("net_return_pct")) for row in rows]
        output.append({
            key: label,
            "trade_count": len(rows),
            "wins": sum(value > 0 for value in net),
            "win_rate_pct": 100.0 * sum(value > 0 for value in net) / len(rows),
            "net_return_pct_sum": sum(net),
            "avg_return_pct": sum(net) / len(rows),
        })
    return output


def market_index(fresh_root: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]], str]:
    manifest_path = fresh_root / "manifest.json"
    manifest = load_json(manifest_path)
    if manifest.get("state") != "PASS" or manifest.get("blockers"):
        raise RuntimeError("FRESH_MANIFEST_NOT_PASS")
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    frames: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in manifest.get("files", []):
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("window_id"))
        symbol = str(item.get("symbol"))
        relative = str(item.get("path") or "")
        candidates = [fresh_root / relative, fresh_root / relative.removeprefix("fresh/")]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            raise RuntimeError(f"MARKET_FILE_MISSING:{role}:{symbol}:{relative}")
        expected_sha = str(item.get("sha256") or "")
        actual_sha = sha256(path)
        if actual_sha != expected_sha:
            raise RuntimeError(f"MARKET_SHA_MISMATCH:{role}:{symbol}")
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
        lookup[(role, symbol)] = {**dict(item), "resolved_path": str(path), "actual_sha256": actual_sha}
        frames[(role, symbol)] = rows
    return lookup, frames, sha256(manifest_path)


def candle_slice(rows: Sequence[Mapping[str, Any]], entry_ts: str, exit_ts: str, padding: int = 12) -> list[dict[str, Any]]:
    entry = parse_time(entry_ts)
    exit_ = parse_time(exit_ts)
    parsed = [parse_time(row.get("timestamp") or datetime.fromtimestamp(int(row["timestamp_ms"]) / 1000).isoformat()) for row in rows]
    entry_index = min(range(len(parsed)), key=lambda index: abs((parsed[index] - entry).total_seconds()))
    exit_index = min(range(len(parsed)), key=lambda index: abs((parsed[index] - exit_).total_seconds()))
    start = max(0, min(entry_index, exit_index) - padding)
    end = min(len(rows), max(entry_index, exit_index) + padding + 1)
    return [
        {
            "timestamp_ms": int(float(row["timestamp_ms"])),
            "timestamp": str(row.get("timestamp") or ""),
            "open": number(row.get("open")),
            "high": number(row.get("high")),
            "low": number(row.get("low")),
            "close": number(row.get("close")),
            "volume": number(row.get("volume")),
        }
        for row in rows[start:end]
    ]


def candlestick_svg(candles: Sequence[Mapping[str, Any]], trade: Mapping[str, Any], title: str) -> str:
    if not candles:
        return empty_svg(title, "NO_CANDLES")
    width = max(1000, min(2400, 120 + len(candles) * 6))
    height = 560
    left, right, top, bottom = 75, 25, 55, 70
    levels = [number(candle.get("high")) for candle in candles] + [number(candle.get("low")) for candle in candles]
    for key in ("entry_price", "exit_price", "initial_sl", "initial_tp"):
        value = number(trade.get(key), math.nan)
        if math.isfinite(value):
            levels.append(value)
    low, high = min(levels), max(levels)
    pad = max((high - low) * 0.05, high * 0.0005)
    low, high = low - pad, high + pad
    yscale = (height - top - bottom) / max(high - low, 1e-12)
    step = (width - left - right) / max(1, len(candles))
    candle_width = max(1.0, min(5.0, step * 0.65))
    body = [
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#222"/>',
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#222"/>',
        f'<text x="5" y="{top+5}" font-family="sans-serif" font-size="12">{high:.5f}</text>',
        f'<text x="5" y="{height-bottom}" font-family="sans-serif" font-size="12">{low:.5f}</text>',
    ]
    for index, candle in enumerate(candles):
        x = left + (index + 0.5) * step
        open_ = number(candle.get("open")); close = number(candle.get("close")); candle_high = number(candle.get("high")); candle_low = number(candle.get("low"))
        yh = top + (high - candle_high) * yscale
        yl = top + (high - candle_low) * yscale
        yo = top + (high - open_) * yscale
        yc = top + (high - close) * yscale
        fill = "#1b8a5a" if close >= open_ else "#b3261e"
        body.append(f'<line x1="{x:.2f}" y1="{yh:.2f}" x2="{x:.2f}" y2="{yl:.2f}" stroke="#333" stroke-width="1"/>')
        body.append(f'<rect x="{x-candle_width/2:.2f}" y="{min(yo,yc):.2f}" width="{candle_width:.2f}" height="{max(1.0,abs(yc-yo)):.2f}" fill="{fill}"/>')
    overlays = (("entry_price", "ENTRY", "#174ea6"), ("exit_price", "EXIT", "#7b1fa2"), ("initial_sl", "SL", "#b3261e"), ("initial_tp", "TP", "#1b8a5a"))
    for key, label, color in overlays:
        value = number(trade.get(key), math.nan)
        if not math.isfinite(value):
            continue
        y = top + (high - value) * yscale
        body.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="{color}" stroke-dasharray="6 4"/>')
        body.append(f'<text x="{width-right-55}" y="{y-4:.2f}" font-family="sans-serif" font-size="11" fill="{color}">{label}</text>')
    body.append(f'<text x="{left}" y="{height-35}" font-family="sans-serif" font-size="12">{html.escape(str(trade.get("entry_ts")))}</text>')
    body.append(f'<text x="{width-right-220}" y="{height-35}" font-family="sans-serif" font-size="12">{html.escape(str(trade.get("exit_ts")))}</text>')
    return svg_shell(width, height, title, "".join(body))


def emit_pair(strategy_root: Path, name: str, payload: Any, svg: str, index: list[dict[str, Any]]) -> None:
    json_path = strategy_root / f"{name}.json"
    svg_path = strategy_root / f"{name}.svg"
    data_sha = write_json(json_path, payload)
    visual_sha = write_text(svg_path, svg)
    index.append({
        "kind": name,
        "data_path": str(json_path),
        "data_sha256": data_sha,
        "visual_path": str(svg_path),
        "visual_sha256": visual_sha,
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    evidence_root = Path(args.evidence_root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    out = Path(args.out).resolve()
    market_meta, market_frames, fresh_manifest_sha = market_index(fresh_root)
    summary_paths = sorted(evidence_root.glob("*/summary.json"))
    strategy_rows: list[dict[str, Any]] = []
    global_visuals: list[dict[str, Any]] = []
    candlestick_count = 0
    chart_count = 0

    for summary_path in summary_paths:
        strategy_id = summary_path.parent.name
        trades_path = summary_path.parent / "baseline_trades.json"
        if not trades_path.exists():
            continue
        summary = load_json(summary_path)
        trades_doc = load_json(trades_path)
        trades = [dict(row) for row in trades_doc.get("trades", []) if isinstance(row, Mapping)]
        trades.sort(key=lambda row: (str(row.get("entry_ts")), str(row.get("exit_ts")), str(row.get("symbol"))))
        strategy_root = out / "strategies" / strategy_id
        visual_index: list[dict[str, Any]] = []

        returns = [number(row.get("net_return_pct")) for row in trades]
        equity: list[float] = []
        running = 0.0
        for value in returns:
            running += value
            equity.append(running)
        drawdown: list[float] = []
        peak = 0.0
        for value in equity:
            peak = max(peak, value)
            drawdown.append(value - peak)
        r_values = [number(row.get("net_return_pct")) / max(number(row.get("risk_pct")), 1e-12) for row in trades]
        mfe_mae = [(max(0.0, number(row.get("mae_r"))), max(0.0, number(row.get("mfe_r")))) for row in trades if row.get("mae_r") is not None and row.get("mfe_r") is not None]

        emit_pair(strategy_root, "equity_curve", {"strategy_id": strategy_id, "points": equity, "source_trade_ledger_sha256": sha256(trades_path)}, line_svg(equity, f"{strategy_id} equity curve"), visual_index)
        emit_pair(strategy_root, "drawdown_curve", {"strategy_id": strategy_id, "points": drawdown, "source_trade_ledger_sha256": sha256(trades_path)}, line_svg(drawdown, f"{strategy_id} drawdown"), visual_index)
        emit_pair(strategy_root, "payoff_distribution", {"strategy_id": strategy_id, "net_r": r_values, "source_trade_ledger_sha256": sha256(trades_path)}, bar_svg(r_values, f"{strategy_id} net R by trade"), visual_index)
        emit_pair(strategy_root, "mfe_mae_scatter", {"strategy_id": strategy_id, "points": [{"mae_r": x, "mfe_r": y} for x, y in mfe_mae], "source_trade_ledger_sha256": sha256(trades_path)}, scatter_svg(mfe_mae, f"{strategy_id} MFE/MAE"), visual_index)
        chart_count += 4

        breakdown = {
            "strategy_id": strategy_id,
            "symbol": aggregate(trades, "symbol"),
            "window": aggregate(trades, "window_id"),
            "exit_reason": aggregate(trades, "exit_reason"),
            "source_trade_ledger_sha256": sha256(trades_path),
        }
        breakdown_sha = write_json(strategy_root / "breakdowns.json", breakdown)
        visual_index.append({"kind": "breakdowns", "data_path": str(strategy_root / "breakdowns.json"), "data_sha256": breakdown_sha})

        representatives: list[tuple[str, Mapping[str, Any]]] = []
        winners = [row for row in trades if number(row.get("net_return_pct")) > 0]
        losses = [row for row in trades if number(row.get("net_return_pct")) < 0]
        if winners:
            representatives.append(("representative_win", max(winners, key=lambda row: number(row.get("net_return_pct")))))
        if losses:
            representatives.append(("representative_loss", min(losses, key=lambda row: number(row.get("net_return_pct")))))

        for label, trade in representatives:
            key = (str(trade.get("window_id")), str(trade.get("symbol")))
            if key not in market_frames:
                raise RuntimeError(f"REPRESENTATIVE_MARKET_MISSING:{strategy_id}:{key}")
            candles = candle_slice(market_frames[key], str(trade.get("entry_ts")), str(trade.get("exit_ts")))
            meta = market_meta[key]
            evidence_payload = {
                "schema_version": "1.0",
                "strategy_id": strategy_id,
                "kind": label,
                "trade": trade,
                "candles": candles,
                "source_trade_ledger_sha256": sha256(trades_path),
                "source_market_sha256": meta["actual_sha256"],
                "source_market_manifest_sha256": fresh_manifest_sha,
                "source_market_path": meta.get("path"),
                "visualization_data_sha256": None,
            }
            evidence_payload["visualization_data_sha256"] = stable_sha({key: value for key, value in evidence_payload.items() if key != "visualization_data_sha256"})
            json_path = strategy_root / f"{label}_candles.json"
            svg_path = strategy_root / f"{label}_candles.svg"
            json_sha = write_json(json_path, evidence_payload)
            svg_sha = write_text(svg_path, candlestick_svg(candles, trade, f"{strategy_id} {label}"))
            visual_index.append({
                "kind": f"{label}_candles",
                "data_path": str(json_path),
                "data_sha256": json_sha,
                "visualization_data_sha256": evidence_payload["visualization_data_sha256"],
                "visual_path": str(svg_path),
                "visual_sha256": svg_sha,
                "source_market_sha256": meta["actual_sha256"],
            })
            candlestick_count += 1

        strategy_index = {
            "strategy_id": strategy_id,
            "trade_count": len(trades),
            "summary_sha256": sha256(summary_path),
            "trade_ledger_sha256": sha256(trades_path),
            "visuals": visual_index,
        }
        index_sha = write_json(strategy_root / "visual_index.json", strategy_index)
        strategy_rows.append({**strategy_index, "visual_index_sha256": index_sha})
        global_visuals.extend([{**row, "strategy_id": strategy_id} for row in visual_index])

    if len(strategy_rows) != 25:
        raise RuntimeError(f"VISUALIZED_STRATEGY_COUNT:{len(strategy_rows)}!=25")
    if chart_count != 100:
        raise RuntimeError(f"CHART_COUNT:{chart_count}!=100")
    if candlestick_count < 2:
        raise RuntimeError(f"CANDLESTICK_EVIDENCE_TOO_SMALL:{candlestick_count}")

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_VISUALIZATION_READY",
        "authority": "READ_ONLY_EXISTING_EVIDENCE_VISUALIZATION_NO_NEW_PERFORMANCE",
        "source_run_id": str(args.source_run_id),
        "source_head_sha": str(args.source_head_sha),
        "fresh_manifest_sha256": fresh_manifest_sha,
        "strategy_count": len(strategy_rows),
        "chart_json_svg_pair_count": chart_count,
        "candlestick_evidence_count": candlestick_count,
        "visual_file_count": len(global_visuals),
        "strategy_indexes": strategy_rows,
        "performance_claim_allowed": False,
        "fixture_or_historical_visualization_only": True,
        "next": "STATISTICAL_POWER_WINDOW_PLAN",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    write_json(out / "summary.json", final)
    write_json(out / "global_visual_index.json", {"rows": global_visuals})
    print(json.dumps({"state": final["state"], "strategies": len(strategy_rows), "charts": chart_count, "candles": candlestick_count, "next": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
