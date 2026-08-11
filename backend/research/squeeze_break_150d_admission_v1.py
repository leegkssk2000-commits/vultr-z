from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence

DATASET_SHA = "53676bb379635c6f81908be2c20e1598e00bffa4d0e08d8b492646416b8a46d8"
DATASET_STATE = "PASS_BINGX_1M_GAP_EXCLUDED_DATASET_STAGED"
POST_START_MS = 1771027200000
POST_END_MS = 1782549000000
STRATEGY_ID = "squeeze_break"
EXPECTED_OWNER_SHA256 = "c22b4016601ce37fc28999ca7690804c92d3f04997b4d01f06775aa49837ed38"
SYMBOLS = ("BTC-USDT", "ETH-USDT", "LINK-USDT", "SOL-USDT", "XRP-USDT")
PRODUCTION_SYMBOLS = ("BTC-USDT", "ETH-USDT")
WINDOWS = (
    ("W1", 1771027200000, 1774828800000),
    ("W2", 1774828800000, 1778630400000),
    ("W3", 1778630400000, 1782549000000),
)
EXPECTED_POST_ROWS = 192030
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000


def stable_sha(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("-", "").upper()


def _required_int(row: Mapping[str, Any], key: str, *, default: int = -1) -> int:
    value = row.get(key)
    return default if value is None else int(value)


def pick_post_rows(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if manifest.get("state") != DATASET_STATE:
        raise RuntimeError(f"DATASET_STATE:{manifest.get('state')}")
    if manifest.get("dataset_sha256") != DATASET_SHA:
        raise RuntimeError(f"DATASET_SHA:{manifest.get('dataset_sha256')}")
    if _required_int(manifest, "actual_total_rows", default=0) != 1_072_800:
        raise RuntimeError("DATASET_TOTAL_ROWS")
    if manifest.get("execution_authority") != "NONE" or manifest.get("order_authority") != "BLOCKED":
        raise RuntimeError("DATASET_AUTHORITY")
    out: dict[str, Mapping[str, Any]] = {}
    for row in manifest.get("results") or []:
        if not isinstance(row, Mapping) or row.get("segment_id") != "POST_GAP":
            continue
        symbol = str(row.get("symbol"))
        if symbol not in SYMBOLS:
            continue
        if _required_int(row, "start_ms") != POST_START_MS or _required_int(row, "end_exclusive_ms") != POST_END_MS:
            raise RuntimeError(f"POST_RANGE:{symbol}")
        if _required_int(row, "row_count") != EXPECTED_POST_ROWS:
            raise RuntimeError(f"POST_ROWS:{symbol}")
        if _required_int(row, "missing_interval_count") != 0 or _required_int(row, "duplicate_timestamp_count") != 0:
            raise RuntimeError(f"POST_INTEGRITY:{symbol}")
        out[symbol] = row
    if set(out) != set(SYMBOLS):
        raise RuntimeError(f"POST_SYMBOLS:{sorted(out)}")
    return out


def read_funding_json(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    candidates: list[Any] = []
    if isinstance(raw, list):
        candidates = raw
    elif isinstance(raw, dict):
        for key in ("rows", "data", "list", "fundingRates", "result"):
            if isinstance(raw.get(key), list):
                candidates = raw[key]
                break
    rows: list[dict[str, Any]] = []
    for row in candidates:
        if not isinstance(row, Mapping):
            continue
        ts = None
        for key in ("timestamp_ms", "fundingTime", "funding_time", "timestamp", "time", "ts"):
            if row.get(key) is not None:
                try:
                    ts = int(float(row[key]))
                    if ts < 10_000_000_000:
                        ts *= 1000
                except Exception:
                    ts = None
                break
        rate = None
        for key in ("funding_rate", "fundingRate", "rate"):
            if row.get(key) is not None:
                try:
                    rate = float(row[key])
                except Exception:
                    rate = None
                break
        if ts is not None and rate is not None and math.isfinite(rate):
            rows.append({"timestamp_ms": ts, "funding_rate": rate})
    dedup = {int(row["timestamp_ms"]): row for row in rows}
    return [dedup[k] for k in sorted(dedup)]


def funding_candidates(root: Path, symbol: str) -> list[Path]:
    compact = normalize_symbol(symbol)
    dashed = symbol.upper()
    names = {f"{compact}.json", f"{dashed}.json", f"{compact.lower()}.json", f"{dashed.lower()}.json"}
    direct = [root / "funding" / n for n in names] + [root / n for n in names]
    found = [p for p in direct if p.is_file()]
    if found:
        return found
    matches: list[Path] = []
    for p in root.rglob("*.json"):
        lname = p.name.lower().replace("-", "")
        if compact.lower() in lname and "fund" in str(p).lower():
            matches.append(p)
        if len(matches) >= 20:
            break
    return matches


def load_funding(root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    meta: dict[str, Any] = {}
    for symbol in SYMBOLS:
        best_rows: list[dict[str, Any]] = []
        best_path: Path | None = None
        for path in funding_candidates(root, symbol):
            rows = read_funding_json(path)
            if len(rows) > len(best_rows):
                best_rows, best_path = rows, path
        by_symbol[symbol] = best_rows
        first = int(best_rows[0]["timestamp_ms"]) if best_rows else None
        last = int(best_rows[-1]["timestamp_ms"]) if best_rows else None
        coverage = bool(best_rows and first is not None and first <= POST_START_MS and last is not None and last >= POST_END_MS - FUNDING_INTERVAL_MS)
        meta[symbol] = {
            "path": str(best_path) if best_path else None,
            "sha256": file_sha(best_path) if best_path else None,
            "rows": len(best_rows),
            "first_timestamp_ms": first,
            "last_timestamp_ms": last,
            "covers_post_gap": coverage,
        }
    return by_symbol, meta


def metric_field(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    values: list[float] = []
    for row in rows:
        try:
            v = float(row[field])
        except Exception:
            continue
        if math.isfinite(v):
            values.append(v)
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    avg_win = gp / len(wins) if wins else 0.0
    avg_loss = gl / len(losses) if losses else 0.0
    equity = peak = max_dd = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trade_count": len(values),
        "net_R": sum(values),
        "expectancy_R": sum(values) / len(values) if values else 0.0,
        "profit_factor": gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0,
        "payoff_ratio": avg_win / avg_loss if avg_loss > 0 else (999.0 if avg_win > 0 else 0.0),
        "max_drawdown_R": max_dd,
    }


def positive_window(metrics: Mapping[str, Any]) -> bool:
    return bool(
        int(metrics.get("trade_count") or 0) > 0
        and float(metrics.get("net_R") or 0.0) > 0.0
        and float(metrics.get("expectancy_R") or 0.0) > 0.0
        and float(metrics.get("profit_factor") or 0.0) >= 1.0
        and float(metrics.get("payoff_ratio") or 0.0) >= 1.0
    )


def sample_60_gate(metrics: Mapping[str, Any]) -> bool:
    return bool(int(metrics.get("trade_count") or 0) >= 60 and positive_window(metrics))


def replay_symbol_job(engine_path: str, source_root: str, market_root: str, symbol: str, mrow: Mapping[str, Any], funding_rows: list[dict[str, Any]]) -> dict[str, Any]:
    engine = load_module(Path(engine_path), f"zel_exact25_engine_squeeze150_{os.getpid()}")
    src = Path(source_root)
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    producer = engine.import_producer(src)
    _, registry = producer.load_registry(src)
    if len(registry) != 25 or STRATEGY_ID not in registry:
        raise RuntimeError(f"WORKER_REGISTRY:{symbol}:{len(registry)}")
    owner = registry[STRATEGY_ID]
    engine._WORKER_PRODUCER = producer
    path = Path(market_root) / "data" / str(mrow["file"])
    if not path.is_file() or file_sha(path) != str(mrow["file_sha256"]):
        raise RuntimeError(f"WORKER_MARKET_SHA:{symbol}")
    frame = engine.frame_from_csv(path)
    if len(frame) != EXPECTED_POST_ROWS:
        raise RuntimeError(f"WORKER_FRAME_ROWS:{symbol}:{len(frame)}")
    ts = frame["timestamp_ms"].astype("int64")
    if int(ts.iloc[0]) != POST_START_MS or int(ts.iloc[-1]) != POST_END_MS - 60_000:
        raise RuntimeError(f"WORKER_FRAME_RANGE:{symbol}")
    if not bool((ts.diff().dropna() == 60_000).all()):
        raise RuntimeError(f"WORKER_FRAME_GAP:{symbol}")
    result: dict[str, Any] = {"symbol": symbol, "windows": {}}
    for window_id, start_ms, end_ms in WINDOWS:
        wf = frame[(frame["timestamp_ms"] >= start_ms) & (frame["timestamp_ms"] < end_ms)].copy().reset_index(drop=True)
        expected = (end_ms - start_ms) // 60_000
        if len(wf) != expected:
            raise RuntimeError(f"WORKER_WINDOW_ROWS:{symbol}:{window_id}:{len(wf)}:{expected}")
        file_row = {"interval": "1m", "symbol": symbol, "window_id": f"SQUEEZE150_{window_id}", "path": str(mrow["file"]), "sha256": str(mrow["file_sha256"])}
        rr = engine.replay_lane(STRATEGY_ID, owner, file_row, wf, funding_rows)
        if int(rr.get("error_count") or 0) != 0:
            raise RuntimeError(f"WORKER_REPLAY_ERRORS:{symbol}:{window_id}:{rr.get('error_samples')}")
        rows = [dict(r) for r in rr.get("closed_rows") or []]
        result["windows"][window_id] = {
            "rows": rows,
            "integrity": {
                "bars": len(wf),
                "signals": int(rr.get("signal_count") or 0),
                "valid_entries": int(rr.get("valid_entry_count") or 0),
                "opens": int(rr.get("open_count") or 0),
                "closes": int(rr.get("close_count") or 0),
                "closed_rows": len(rows),
                "censored_open_at_window_end": int(rr.get("censored_open_at_window_end") or 0),
                "errors": int(rr.get("error_count") or 0),
            },
        }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--source-root", type=Path, required=True)
    ap.add_argument("--market-root", type=Path, required=True)
    ap.add_argument("--market-manifest", type=Path, required=True)
    ap.add_argument("--funding-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    manifest = json.loads(ns.market_manifest.read_text(encoding="utf-8"))
    post = pick_post_rows(manifest)
    engine = load_module(ns.engine.resolve(), "zel_exact25_engine_squeeze150_parent")
    if str(ns.source_root.resolve()) not in sys.path:
        sys.path.insert(0, str(ns.source_root.resolve()))
    producer = engine.import_producer(ns.source_root.resolve())
    _, registry = producer.load_registry(ns.source_root.resolve())
    if len(registry) != 25 or STRATEGY_ID not in registry:
        raise RuntimeError(f"REGISTRY:{len(registry)}:{STRATEGY_ID in registry}")
    owner = registry[STRATEGY_ID]
    owner_rel = str(getattr(owner, "owner_path", ""))
    owner_path = ns.source_root / owner_rel
    if not owner_rel or not owner_path.is_file():
        raise RuntimeError(f"OWNER_PATH:{owner_rel}")
    producer_path = ns.source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py"
    source_before = {"owner_sha256": file_sha(owner_path), "producer_sha256": file_sha(producer_path)}
    if source_before["owner_sha256"] != EXPECTED_OWNER_SHA256:
        raise RuntimeError(f"OWNER_SHA_DRIFT:{source_before['owner_sha256']}")

    funding_by_symbol, funding_meta = load_funding(ns.funding_root)
    funding_complete = all(bool(funding_meta[s]["covers_post_gap"]) for s in SYMBOLS)
    per_window_symbol: dict[str, dict[str, list[dict[str, Any]]]] = {w[0]: {s: [] for s in SYMBOLS} for w in WINDOWS}
    integrity: dict[str, Any] = {}
    futures = []
    with ProcessPoolExecutor(max_workers=5) as pool:
        for symbol in SYMBOLS:
            futures.append(pool.submit(replay_symbol_job, str(ns.engine.resolve()), str(ns.source_root.resolve()), str(ns.market_root.resolve()), symbol, dict(post[symbol]), funding_by_symbol[symbol]))
        for future in as_completed(futures):
            result = future.result()
            symbol = str(result["symbol"])
            for window_id in ("W1", "W2", "W3"):
                wrow = result["windows"][window_id]
                per_window_symbol[window_id][symbol].extend(wrow["rows"])
                integrity[f"{symbol}:{window_id}"] = wrow["integrity"]

    source_after = {"owner_sha256": file_sha(owner_path), "producer_sha256": file_sha(producer_path)}
    source_unchanged = source_before == source_after
    all_rows = [r for wid in ("W1", "W2", "W3") for s in SYMBOLS for r in per_window_symbol[wid][s]]
    identities = [str(r.get("event_id") or r.get("position_id") or "") for r in all_rows]
    nonempty_ids = [x for x in identities if x]
    duplicates = len(nonempty_ids) - len(set(nonempty_ids))
    integrity_ok = bool(
        source_unchanged and duplicates == 0 and len(integrity) == 15
        and all(v["errors"] == 0 and v["censored_open_at_window_end"] == 0 for v in integrity.values())
    )

    windows_out: dict[str, Any] = {}
    prod_window_pass: dict[str, bool] = {}
    all_window_pass: dict[str, bool] = {}
    for wid in ("W1", "W2", "W3"):
        all_w = [r for s in SYMBOLS for r in per_window_symbol[wid][s]]
        prod_w = [r for s in PRODUCTION_SYMBOLS for r in per_window_symbol[wid][s]]
        def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
            rows = sorted(rows, key=lambda r: engine.parse_epoch(r.get("exit_ts")) or 0.0)
            fee_slip = metric_field(rows, "realized_R")
            full_cost = metric_field(rows, "realized_R_including_funding_estimate")
            scoring = full_cost if funding_complete else fee_slip
            return {
                "fee_slippage_net": fee_slip,
                "including_funding_estimate": full_cost,
                "scoring_basis": "INCLUDING_FUNDING_ESTIMATE" if funding_complete else "FEE_SLIPPAGE_ONLY_FUNDING_HOLD",
                "positive_edge_gate": positive_window(scoring),
                "legacy_structural_60_trade_gate": sample_60_gate(scoring),
            }
        all_m = metrics(all_w)
        prod_m = metrics(prod_w)
        by_symbol = {normalize_symbol(s): metrics(list(per_window_symbol[wid][s])) for s in SYMBOLS}
        windows_out[wid] = {"all_symbols": all_m, "production_symbols": prod_m, "by_symbol": by_symbol}
        all_window_pass[wid] = bool(all_m["positive_edge_gate"])
        prod_window_pass[wid] = bool(prod_m["positive_edge_gate"])

    full_cost_key = "including_funding_estimate" if funding_complete else "fee_slippage_net"
    prod_rows = [r for wid in ("W1", "W2", "W3") for s in PRODUCTION_SYMBOLS for r in per_window_symbol[wid][s]]
    all_agg = metric_field(all_rows, "realized_R_including_funding_estimate" if funding_complete else "realized_R")
    prod_agg = metric_field(prod_rows, "realized_R_including_funding_estimate" if funding_complete else "realized_R")

    production_three_window_edge = bool(integrity_ok and funding_complete and all(prod_window_pass.values()))
    all_three_window_edge = bool(integrity_ok and funding_complete and all(all_window_pass.values()))
    if not funding_complete:
        state, action, next_step = "HOLD_SQUEEZE150_FUNDING_SOURCE_GAP", "hold", "BIND_COMPLETE_FUNDING_HISTORY"
    elif not integrity_ok:
        state, action, next_step = "HOLD_SQUEEZE150_INTEGRITY_FAILURE", "hold", "FIX_SOURCE_OR_REPLAY_INTEGRITY"
    elif not production_three_window_edge:
        state, action, next_step = "REJECT_SQUEEZE150_PRODUCTION_DURABILITY", "route_change", "ROUTE_CHANGE_TO_NEXT_SOURCE_READY_ECONOMIC_FAMILY"
    else:
        state, action, next_step = "HOLD_SQUEEZE150_ECONOMIC_PASS_AUTHORITY_GATES_PENDING", "hold", "BIND_RISK_DD_RETENTION_AUTHORITY_BEFORE_BOOTSTRAP_PASS"

    receipt: dict[str, Any] = {
        "schema_version": "zel.squeeze_break.150d_admission.v1",
        "state": state,
        "strategy_id": STRATEGY_ID,
        "route": "LOW_SAMPLE_EXTENSION_SAME_RULE_EXACT_SOURCE",
        "dataset": {
            "dataset_sha256": DATASET_SHA,
            "state": DATASET_STATE,
            "post_gap_start_ms": POST_START_MS,
            "post_gap_end_exclusive_ms": POST_END_MS,
            "rows_per_symbol": EXPECTED_POST_ROWS,
            "symbols": list(SYMBOLS),
            "production_symbols": list(PRODUCTION_SYMBOLS),
        },
        "windows": windows_out,
        "aggregate": {"all_symbols": all_agg, "production_symbols": prod_agg, "scoring_basis": full_cost_key},
        "funding": {"root": str(ns.funding_root), "complete_for_scoring": funding_complete, "by_symbol": funding_meta},
        "source_binding": {
            "owner_path": owner_rel,
            "expected_owner_sha256": EXPECTED_OWNER_SHA256,
            "owner_sha256_before": source_before["owner_sha256"],
            "owner_sha256_after": source_after["owner_sha256"],
            "producer_sha256_before": source_before["producer_sha256"],
            "producer_sha256_after": source_after["producer_sha256"],
            "source_unchanged": source_unchanged,
            "strategy_parameter_changes": 0,
            "feature_gate_changes": 0,
            "side_filter_changes": 0,
        },
        "integrity": {
            "lane_checks": integrity,
            "duplicate_trade_identity_count": duplicates,
            "integrity_ok": integrity_ok,
        },
        "all_symbols_three_window_positive_edge": all_three_window_edge,
        "production_three_window_positive_edge": production_three_window_edge,
        "production_window_gates": prod_window_pass,
        "sample_60_gate_by_production_window": {w: windows_out[w]["production_symbols"]["legacy_structural_60_trade_gate"] for w in ("W1", "W2", "W3")},
        "bootstrap_authority_gates": {
            "risk_request_bound": False,
            "dd_pct_bound": False,
            "retention_semantics_bound": False,
            "bootstrap_pass_evidence_emitted": False,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": action,
        "next": next_step,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": state,
        "production_three_window_positive_edge": production_three_window_edge,
        "production_window_gates": prod_window_pass,
        "production_aggregate": prod_agg,
        "all_aggregate": all_agg,
        "funding_complete": funding_complete,
        "integrity_ok": integrity_ok,
        "next": next_step,
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
