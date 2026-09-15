from __future__ import annotations

# mypy: follow_imports=skip

import argparse
import contextlib
import gzip
import io
import importlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ev: Any = importlib.import_module(
    "backend.research.rebuild." + "a1_exact25_generic_evaluator_three_lane_v1"
)

REBUILD_DIR = Path(__file__).resolve().parent
if str(REBUILD_DIR) not in sys.path:
    sys.path.insert(0, str(REBUILD_DIR))
from benchmark25_transfer_overlay_v1 import (  # noqa: E402
    apply_transfer,
    self_test as overlay_self_test,
)

ROOT = Path(__file__).resolve().parents[3]
CACHE = Path("/home/z/z/runtime/three_lane_5m_180d_v2")
MICRO = Path("/home/z/z/runtime/benchmark6_micro_5m_v1.jsonl.gz")
CONTRACT = ROOT / "backend/research/rebuild/benchmark25_transfer_contract_v1.json"
MATRIX = (
    ROOT / "backend/research/rebuild/benchmark25_transfer_implementation_matrix_v1.json"
)
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
SYMS6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
TF15 = {"keltner_trend", "supertrend_pullback", "trend_ma_macd", "trend_rider"}
TF1H = {"turtle_trend"}
MICRO_REQUIRED = {"liquidity_sweep", "scalp_snap", "vol_spike_fade", "vwap_revert"}


def read_json(path: Path) -> dict[str, Any]:
    x = json.load(open(path))
    if not isinstance(x, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return x


def load_5m() -> dict[str, list[dict[str, Any]]]:
    m = read_json(CACHE / "MANIFEST.json")
    if m.get("state") != "PASS_SHARED_CACHE_COMPLETE":
        raise RuntimeError("CACHE_NOT_COMPLETE")
    out = {}
    for s in SYMS6:
        rows = []
        with gzip.open(CACHE / "data" / f"{s.replace('-','')}_5m.jsonl.gz", "rt") as f:
            for line in f:
                x = json.loads(line)
                rows.append(
                    {
                        "ts_ms": int(x["timestamp_ms"]),
                        "open": float(x["open"]),
                        "high": float(x["high"]),
                        "low": float(x["low"]),
                        "close": float(x["close"]),
                        "volume": float(x["volume"]),
                    }
                )
        out[s] = rows
    return out


def aggregate(rows: list[dict[str, Any]], interval_ms: int) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        k = int(r["ts_ms"]) // interval_ms * interval_ms
        buckets.setdefault(k, []).append(r)
    need = interval_ms // 300000
    out = []
    for k, xs in sorted(buckets.items()):
        xs = sorted(xs, key=lambda z: int(z["ts_ms"]))
        if len(xs) != need:
            continue
        out.append(
            {
                "ts_ms": k,
                "open": xs[0]["open"],
                "high": max(x["high"] for x in xs),
                "low": min(x["low"] for x in xs),
                "close": xs[-1]["close"],
                "volume": sum(x["volume"] for x in xs),
            }
        )
    return out


def load_micro() -> dict[tuple[str, int], dict[str, Any]]:
    out = {}
    with gzip.open(MICRO, "rt") as f:
        for line in f:
            x = json.loads(line)
            out[(str(x["symbol"]), int(x["ts_ms"]))] = x
    return out


def tf_ms(sid: str) -> int:
    return 3_600_000 if sid in TF1H else 900_000 if sid in TF15 else 300_000


def compact(d: dict[str, Any]) -> dict[str, Any]:
    m = d.get("metrics") or {}
    return {
        "T": int(d.get("completed_trades") or 0),
        "WR": m.get("win_rate"),
        "Net_bps": m.get("net_pnl_bps"),
        "Exp_bps_T": m.get("net_expectancy_bps"),
        "PF": m.get("net_profit_factor"),
        "DD_bps": m.get("max_drawdown_bps"),
        "integrity_defects": len(d.get("integrity_defects") or []),
    }


def split(d: dict[str, Any]) -> dict[str, Any]:
    tr = sorted(
        d.get("trades") or [], key=lambda x: (int(x["exit_ts"]), str(x["symbol"]))
    )
    cut = int(len(tr) * 0.60)

    def mm(xs):
        vals = [float(x["net_bps"]) for x in xs]
        wins = [x for x in vals if x > 0]
        losses = [-x for x in vals if x < 0]
        eq = pk = dd = 0.0
        for x in vals:
            eq += x
            pk = max(pk, eq)
            dd = max(dd, pk - eq)
        return {
            "T": len(vals),
            "WR": len(wins) / len(vals) if vals else None,
            "Net_bps": sum(vals),
            "PF": sum(wins) / sum(losses) if losses else None,
            "DD_bps": dd,
        }

    return {"train60": mm(tr[:cut]), "holdout40": mm(tr[cut:])}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    contract = read_json(CONTRACT)
    if args.self_test:
        overlay_self_test(contract)
        matrix = read_json(MATRIX)
        if (
            matrix.get("state") != "PASS_25_OF_25_1_TO_1"
            or matrix.get("unimplemented_count") != 0
        ):
            raise RuntimeError("BENCHMARK25_MATRIX_INCOMPLETE")
        for sid, spec in contract["strategies"].items():
            got = [
                x["transfer"]
                for x in matrix["strategies"][sid]["transfer_implementation"]
            ]
            if got != spec["transfer"]:
                raise RuntimeError(f"BENCHMARK25_TRANSFER_ORDER_MISMATCH:{sid}")
        print("PASS_BENCHMARK25_1_TO_1_MATRIX_86_TRANSFERS")
        return 0
    ids = list(contract["strategies"])
    selected = [
        sid for i, sid in enumerate(ids) if i % args.shard_count == args.shard_index
    ]
    base5 = load_5m()
    cache_by_tf = {
        300000: base5,
        900000: {s: aggregate(base5[s], 900000) for s in SYMS6},
        3600000: {s: aggregate(base5[s], 3600000) for s in SYMS6},
    }
    micro = load_micro()
    micro_first = min(t for s, t in micro)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    ledger0 = read_json(LEDGER)
    orig_pf, orig_b, orig_s, orig_l = (
        ev.policy_functions,
        ev.fetch_bars,
        ev.fetch_execution_snapshot,
        ev.LEDGER_PATH,
    )
    snap_cache = {}
    rows = []
    errors = []

    def cached_s(symbol, authority):
        if symbol not in snap_cache:
            snap_cache[symbol] = orig_s(symbol, authority)
        return snap_cache[symbol]

    for sid in selected:
        report_path = args.out_dir / f"{sid}.json"
        if report_path.exists():
            try:
                prior = read_json(report_path)
                if prior.get("state") == "PASS_BENCHMARK25_PARENT_CHILD":
                    rows.append(prior)
                    print("BENCH25_RESUME", sid, flush=True)
                    continue
            except Exception:
                pass
        try:
            tf = tf_ms(sid)
            bars_map = cache_by_tf[tf]
            symbols = ("BTC-USDT", "ETH-USDT") if sid in MICRO_REQUIRED else SYMS6
            boundary = (
                micro_first
                if sid in MICRO_REQUIRED
                else min(int(bars_map[s][0]["ts_ms"]) for s in symbols)
            )
            ledger = json.loads(json.dumps(ledger0))
            ledger["strategies"][sid]["status"] = "ACTIVE"
            ledger["strategies"][sid]["prospective_boundary_utc"] = (
                datetime.fromtimestamp(boundary / 1000, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
            last_bars = {}
            mode = {"name": "parent"}
            transfer_stats = {"admitted": 0, "rejected": 0, "fail_closed": 0}

            def local_b(symbol, interval, limit=1000):
                if symbol not in bars_map:
                    raise RuntimeError(f"CACHE_SYMBOL_MISSING:{symbol}")
                expected = {300000: "5m", 900000: "15m", 3600000: "1h"}[tf]
                if interval != expected:
                    raise RuntimeError(
                        f"BENCH25_INTERVAL_MISMATCH:{sid}:{interval}:{expected}"
                    )
                return bars_map[symbol]

            def wrapped_pf(module, strategy_id):
                compute, build = orig_pf(module, strategy_id)

                def cw(bs, *, symbol, now_ts_ms, config):
                    f = compute(bs, symbol=symbol, now_ts_ms=now_ts_ms, config=config)
                    last_bars[symbol] = bs
                    return f

                def bw(feature, **kw):
                    intent = build(feature, **kw)
                    if mode["name"] != "child" or bool(
                        getattr(intent, "no_trade", False)
                    ):
                        return intent
                    sym = str(getattr(feature, "symbol"))
                    sig = int(getattr(feature, "signal_ts"))
                    mx = micro.get((sym, sig)) if sid in MICRO_REQUIRED else None
                    child, meta = apply_transfer(sid, intent, last_bars[sym], mx)
                    st = meta.get("state")
                    if st == "PASS_TRANSFER_APPLIED":
                        transfer_stats["admitted"] += 1
                    elif st == "FAIL_CLOSED_NO_MICRO":
                        transfer_stats["fail_closed"] += 1
                    else:
                        transfer_stats["rejected"] += 1
                    return child

                return cw, bw

            ev.policy_functions = wrapped_pf
            ev.fetch_bars = local_b
            ev.fetch_execution_snapshot = cached_s
            with tempfile.TemporaryDirectory(prefix=f"bench25_{sid}_") as td:
                lp = Path(td) / "ledger.json"
                lp.write_text(json.dumps(ledger))
                ev.LEDGER_PATH = lp
                receipts = {}
                for name in ("parent", "child"):
                    mode["name"] = name
                    out = Path(td) / f"{name}.json"
                    prior_argv = list(sys.argv)
                    sys.argv = [
                        "bench25",
                        "--strategy-id",
                        sid,
                        "--symbols",
                        ",".join(symbols),
                        "--out",
                        str(out),
                        "--timeframe-ms",
                        str(tf),
                    ]
                    try:
                        with contextlib.redirect_stdout(io.StringIO()):
                            ev.main()
                    finally:
                        sys.argv = prior_argv
                    receipts[name] = read_json(out)
            parent, child = receipts["parent"], receipts["child"]
            spec = contract["strategies"][sid]
            report = {
                "schema": "zel.a1.benchmark25.transfer.replay.v1",
                "state": "PASS_BENCHMARK25_PARENT_CHILD",
                "strategy_id": sid,
                "timeframe_ms": tf,
                "symbols": list(symbols),
                "boundary_utc": ledger["strategies"][sid]["prospective_boundary_utc"],
                "benchmark_ids": spec["benchmark_ids"],
                "benchmark_strength": spec["benchmark_strength"],
                "lane_hint": spec["lane_hint"],
                "transfer": spec["transfer"],
                "do_not_copy": spec["do_not_copy"],
                "parent": compact(parent),
                "child": compact(child),
                "parent_split": split(parent),
                "child_split": split(child),
                "transfer_stats": dict(transfer_stats),
                "microstructure_observed_only": sid in MICRO_REQUIRED,
                "research_only": True,
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "live_trade_authority": "BLOCKED",
            }
            report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            rows.append(report)
            print(
                "BENCH25_ROW="
                + json.dumps(
                    {
                        "strategy_id": sid,
                        "tf": tf,
                        "parent": report["parent"],
                        "child": report["child"],
                        "transfer_stats": report["transfer_stats"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:
            err = {"strategy_id": sid, "error": f"{type(exc).__name__}:{exc}"}
            errors.append(err)
            print("BENCH25_ERROR=" + json.dumps(err, sort_keys=True), flush=True)
        finally:
            ev.policy_functions = orig_pf
            ev.fetch_bars = orig_b
            ev.fetch_execution_snapshot = orig_s
            ev.LEDGER_PATH = orig_l

    summary = {
        "schema": "zel.a1.benchmark25.transfer.shard.v1",
        "state": "PASS" if rows and not errors else "PARTIAL",
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "requested": selected,
        "success_count": len(rows),
        "error_count": len(errors),
        "errors": errors,
        "strategies": [
            {
                "strategy_id": r["strategy_id"],
                "parent": r["parent"],
                "child": r["child"],
            }
            for r in rows
        ],
        "authority": {
            "selection": False,
            "promotion": False,
            "execution": "NONE",
            "order": "BLOCKED",
            "live": "BLOCKED",
        },
    }
    (args.out_dir / "REPORT.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(
        "BENCH25_DONE="
        + json.dumps(
            {"success": len(rows), "errors": len(errors), "shard": args.shard_index},
            sort_keys=True,
        )
    )
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
