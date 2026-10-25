"""Bounded one-time READ-ONLY old-DEV bar snapshot. No collector, no account credential."""

import datetime
import gzip
import hashlib
import json
import subprocess
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def once(path):
    import sys

    repo = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo))
    from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as native

    f = Path(path)
    s = json.loads((f / "FREEZE.json").read_text())
    c = s["inputs"]["market_reader"]
    root = Path("/home/z/z")
    raw = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "show",
            s["inputs"]["liquid6"]["git_commit"] + ":" + c["code_path"],
        ]
    )
    if sha(raw) != c["code_sha256"]:
        raise RuntimeError("PINNED_NATIVE_SOURCE_CHANGED")
    if sha(Path(native.__file__).read_bytes()) != c["code_sha256"]:
        raise RuntimeError("NATIVE_IMPORT_NOT_SAME_SOURCE")
    symbols = sorted(
        set(
            ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT"]
            + [
                "1000PEPE-USDT",
                "1INCH-USDT",
                "APE-USDT",
                "BCH-USDT",
                "ETHFI-USDT",
                "HYPE-USDT",
            ]
        )
    )
    data = {}
    pins = {}
    for symbol in symbols:
        rows = native.fetch_bars(symbol, "1h", 1000)
        if len(rows) != 1000:
            raise RuntimeError(
                "PUBLIC_SOURCE_1000_1H_NOT_PRESENT:" + symbol + ":" + str(len(rows))
            )
        clock = [int(x["ts_ms"]) for x in rows]
        if any(b - a != 3_600_000 for a, b in zip(clock, clock[1:])):
            raise RuntimeError("PUBLIC_SOURCE_MISSING_HOUR:" + symbol)
        for bar in rows:
            if not all(
                isinstance(bar[k], (int, float))
                for k in ("ts_ms", "open", "high", "low", "close")
            ):
                raise RuntimeError("PRICE_TYPE_BAD")
            if bar["high"] < max(bar["open"], bar["low"], bar["close"]) or bar[
                "low"
            ] > min(bar["open"], bar["high"], bar["close"]):
                raise RuntimeError("OHLC_BOUNDS_BAD")
        saved = (
            json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode()
        pins[symbol] = {
            "n": len(rows),
            "first_ts_ms": clock[0],
            "last_ts_ms": clock[-1],
            "rows_sha256": sha(saved),
        }
        data[symbol] = rows
        print("SOURCE_1H_BOUND", symbol, len(rows), clock[0], clock[-1], flush=True)
    result = {
        "schema": "zel.trendrider.single_batch_bingx_1h.snapshot.v1",
        "utc_retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "read_code_sha256": c["code_sha256"],
        "source_type": "BINGX_PUBLIC_1H_RECENT_NO_HISTORICAL_HTTP_RECEIVE_TIMES",
        "no_account": True,
        "no_order": True,
        "symbols": data,
        "pins": pins,
    }
    payload = (
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    path = f / "MARKET_1H_SNAPSHOT.json.gz"
    with path.open("xb") as h:
        h.write(gzip.compress(payload, compresslevel=6))
    print(
        "MARKET_SNAPSHOT_SAVED",
        len(payload),
        sha(payload),
        sha(path.read_bytes()),
        flush=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--explicit-one-batch-public-read", action="store_true")
    args = parser.parse_args()
    if not args.explicit_one_batch_public_read:
        print("DEFAULT_OFF_NO_NETWORK_READ")
    else:
        once(args.root)
