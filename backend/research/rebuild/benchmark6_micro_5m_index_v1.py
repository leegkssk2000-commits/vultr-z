from __future__ import annotations
import gzip
import json
from pathlib import Path

SRC = Path("/home/z/z/ledger/production_bingx_ws_microstructure_v2.jsonl")
OUT = Path("/home/z/z/runtime/benchmark6_micro_5m_v1.jsonl.gz")
SYMS = {"BTC-USDT", "ETH-USDT"}
BUCKET = 300_000


def main() -> int:
    agg = {}
    with SRC.open("rt", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            try:
                r = json.loads(line)
            except Exception:
                continue
            s = r.get("symbol")
            if s not in SYMS:
                continue
            ts = int(r.get("bucket_start_ms") or 0)
            b = (ts // BUCKET) * BUCKET
            k = (s, b)
            a = agg.get(k)
            if a is None:
                a = {
                    "symbol": s,
                    "ts_ms": b,
                    "rows": 0,
                    "buy": 0.0,
                    "sell": 0.0,
                    "trade_messages": 0,
                    "depth_messages": 0,
                    "bid_first": r.get("bid_qty_top20_first"),
                    "ask_first": r.get("ask_qty_top20_first"),
                    "imb_first": r.get("imbalance_top20_first"),
                    "bid_last": None,
                    "ask_last": None,
                    "imb_last": None,
                    "spread_sum": 0.0,
                    "spread_n": 0,
                }
                agg[k] = a
            a["rows"] += 1
            a["buy"] += float(r.get("aggressive_buy_qty") or 0)
            a["sell"] += float(r.get("aggressive_sell_qty") or 0)
            a["trade_messages"] += int(r.get("trade_messages") or 0)
            a["depth_messages"] += int(r.get("depth_messages") or 0)
            for kk, src in [
                ("bid_last", "bid_qty_top20_last"),
                ("ask_last", "ask_qty_top20_last"),
                ("imb_last", "imbalance_top20_last"),
            ]:
                if r.get(src) is not None:
                    a[kk] = r.get(src)
            if r.get("spread_bps_mean") is not None:
                a["spread_sum"] += float(r["spread_bps_mean"])
                a["spread_n"] += 1
    print("MICRO_ROWS_READ", n, "BUCKETS", len(agg), flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as g:
        for k in sorted(agg, key=lambda x: (x[1], x[0])):
            a = agg[k]
            den = a["buy"] + a["sell"]
            a["trade_imbalance"] = (a["buy"] - a["sell"]) / den if den > 0 else None
            for name, last, first in [
                ("bid_change", "bid_last", "bid_first"),
                ("ask_change", "ask_last", "ask_first"),
            ]:
                try:
                    a[name] = (float(a[last]) - float(a[first])) / max(
                        abs(float(a[first])), 1e-12
                    )
                except Exception:
                    a[name] = None
            try:
                a["imbalance_delta"] = float(a["imb_last"]) - float(a["imb_first"])
            except Exception:
                a["imbalance_delta"] = None
            a["spread_bps_mean"] = (
                a["spread_sum"] / a["spread_n"] if a["spread_n"] else None
            )
            for z in ["spread_sum", "spread_n"]:
                a.pop(z, None)
            g.write(json.dumps(a, sort_keys=True, separators=(",", ":")) + "\n")
    print("MICRO_INDEX", OUT, "bytes", OUT.stat().st_size, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
