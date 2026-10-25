"""BingX official PUBLIC funding+contract metadata. Exactly one call per
symbol/endpoint. No auth, no trading, no account, no retry on denial.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent
API = "https://open-api.bingx.com"
SYMBOLS = (
    "1000PEPE-USDT",
    "1INCH-USDT",
    "APE-USDT",
    "BCH-USDT",
    "BTC-USDT",
    "DOGE-USDT",
    "ETH-USDT",
    "ETHFI-USDT",
    "HYPE-USDT",
    "LINK-USDT",
    "SOL-USDT",
    "XRP-USDT",
)
LOW_MS = 1789318800000 - 24 * 3600000
HIGH_MS = 1792915200000


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def once(endpoint: str, params: dict):
    query = urllib.parse.urlencode(params)
    url = API + endpoint + "?" + query
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ZEL research-source-check/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=17) as res:
        raw = res.read()
        stamp = res.headers.get("Date")
        if res.status != 200:
            raise RuntimeError("BAD_HTTP:" + str(res.status))
    obj = json.loads(raw)
    if int(obj.get("code", -1)) != 0:
        raise RuntimeError("BAD_EXCHANGE_RESPONSE:" + str(obj.get("code")))
    return raw, obj, stamp


def main():
    if (OUT / "BINGX_PUBLIC_CONTRACT_FUNDING_RECEIPT_V1.json").exists():
        raise RuntimeError(
            "EXACT_SINGLE_PUBLISHED_PILOT_ALREADY_PRESENT_NO_NEW_NETWORK"
        )
    state = {
        "schema": "zel.bingx.funding_contract.public_r1",
        "endpoint_ref": "https://github.com/BingX-API/api-ai-skills/blob/main/skills/swap-market/api-reference.md",
        "purpose": "existing September-October 12-symbol source-only cost/tick/side funding attribution",
        "requested_symbols": list(SYMBOLS),
        "window_start_ms": LOW_MS,
        "window_end_ms": HIGH_MS,
        "no_auth": True,
        "no_orders": True,
        "no_paid_api": True,
        "no_usdt_account_reconciliation": True,
        "snapshots": {},
        "failures": {},
    }
    for idx, symbol in enumerate(SYMBOLS):
        entries = {}
        for kind, route, extra in (
            ("contract", "/openApi/swap/v2/quote/contracts", {}),
            (
                "funding",
                "/openApi/swap/v2/quote/fundingRate",
                {"startTime": LOW_MS, "endTime": HIGH_MS, "limit": 1000},
            ),
        ):
            fn = f"{symbol}_{kind}_RAW.json"
            params = {"symbol": symbol, **extra}
            try:
                raw, obj, serverdate = once(route, params)
                (OUT / fn).write_bytes(raw)
                records = obj.get("data")
                if not isinstance(records, list) or len(records) == 0:
                    raise RuntimeError("EMPTY_DATA")
                if kind == "contract":
                    if len(records) != 1 or records[0].get("symbol") != symbol:
                        raise RuntimeError("WRONG_CONTRACT")
                    sample = {
                        "fee_maker": records[0].get("makerFeeRate"),
                        "fee_taker": records[0].get("takerFeeRate"),
                        "quantityPrecision": records[0].get("quantityPrecision"),
                        "pricePrecision": records[0].get("pricePrecision"),
                        "size": records[0].get("size"),
                        "tradeMinUSDT": records[0].get("tradeMinUSDT"),
                        "status": records[0].get("status"),
                    }
                else:
                    times = [int(x["fundingTime"]) for x in records]
                    if len(times) != len(set(times)):
                        raise RuntimeError("DUPLICATE_FUNDING_TIME")
                    if not all(LOW_MS <= ts <= HIGH_MS for ts in times):
                        raise RuntimeError("FUNDING_OUTSIDE_REQUESTED_WINDOW")
                    sample = {
                        "first": min(times),
                        "last": max(times),
                        "minFunding_bps": min(
                            float(x["fundingRate"]) * 10000 for x in records
                        ),
                        "maxFunding_bps": max(
                            float(x["fundingRate"]) * 10000 for x in records
                        ),
                        "time_step_histogram_ms": dict(
                            __import__("collections").Counter(
                                abs(a - b)
                                for a, b in zip(sorted(times), sorted(times)[1:])
                            )
                        ),
                    }
                entries[kind] = {
                    "request": route,
                    "requested_parameters": params,
                    "raw_file": fn,
                    "raw_sha256": sha(raw),
                    "n": len(records),
                    "http_received_at_utc": dt.datetime.now(
                        dt.timezone.utc
                    ).isoformat(),
                    "response_date_header": serverdate,
                    "metadata": sample,
                }
                print(
                    "PASS_PUBLIC_SOURCE",
                    symbol,
                    kind,
                    len(records),
                    sha(raw)[:12],
                    flush=True,
                )
            except Exception as exc:
                state["failures"][symbol + ":" + kind] = (
                    type(exc).__name__ + ":" + str(exc)[:180]
                )
                print(
                    "SOURCE_HOLD",
                    symbol,
                    kind,
                    type(exc).__name__,
                    str(exc)[:110],
                    flush=True,
                )
                # No retry or provider circumvention.
                break
            time.sleep(1.05)
        state["snapshots"][symbol] = entries
    state["completed_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    state["requested_endpoint_calls_cap"] = 24
    state["failed"] = bool(state["failures"])
    raw = (json.dumps(state, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with (OUT / "BINGX_PUBLIC_CONTRACT_FUNDING_RECEIPT_V1.json").open("xb") as out:
        out.write(raw)
    print(
        "SOURCE_RECEIPT_COMPLETE",
        len(state["snapshots"]),
        "fully",
        sum(len(x) == 2 for x in state["snapshots"].values()),
        "failures",
        state["failures"],
        "SHA",
        sha(raw),
        flush=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Offline by default. Explicit bounded public-data read only."
    )
    parser.add_argument("--explicit-one-shot-public-source-read", action="store_true")
    args = parser.parse_args()
    if not args.explicit_one_shot_public_source_read:
        print("DEFAULT_OFF_NO_NETWORK")
    else:
        main()
