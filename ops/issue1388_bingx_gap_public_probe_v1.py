"""One-shot public gap probe; **not** an archive patch, strategy run or permission grant.

Six bounded GETs of exactly four originally missing 1-minute bars.
Keeps original campaign data/source SHA unchanged even when all rows exist.
The later response is only development backfill evidence, never historical
received-at-time / fresh execution / volume-unit / cost proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backend.research.rebuild.economic7_canonical_history_v1 import (
    BASE_URL, ENDPOINT, HistoryError, MINUTE_MS, response_rows,
)

GAP_START_MS = 1771014720000
GAP_END_MS = 1771014960000
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
MAX_REQUESTS = 6

def observed_utc():
    return datetime.now(timezone.utc).isoformat()

def main(out: Path):
    out.mkdir(parents=True,exist_ok=True)
    receipt = {
        "schema": "zel.issue1388.public_four_minute_gap_probe.v1",
        "original_frozen_source": "research/campaigns/scalp7_20260915/SOURCE_DATA_V2_30M.json",
        "operation": "READ_ONLY_NO_CANONICAL_MUTATION",
        "gap_start_ms": GAP_START_MS, "gap_end_exclusive_ms": GAP_END_MS,
        "expected_minutes_per_symbol": 4, "symbols": list(SYMBOLS),
        "budget_limit": MAX_REQUESTS, "request_count": 0,
        "started_utc": observed_utc(), "exchange_order_submitted":False,
        "research_only":True, "new_economic_claim":False, "fresh_ready":False,
        "historical_received_at_not_observed":True,"volume_unit":"UNKNOWN",
        "source_identity_requires_new_version_if_recovery_possible":True,
        "results": [],
    }
    for symbol in SYMBOLS:
        if receipt["request_count"] >= MAX_REQUESTS:
            raise RuntimeError("REQUEST_BUDGET_INVARIANT_BROKEN")
        query = {
            "symbol": symbol, "interval": "1m", "timeZone": 0,
            "startTime": GAP_START_MS, "endTime": GAP_END_MS-1, "limit": 1000,
            "timestamp": int(datetime.now(timezone.utc).timestamp()*1000),
        }
        url = BASE_URL + ENDPOINT + "?" + urllib.parse.urlencode(query)
        result={"symbol":symbol,"requested_utc":observed_utc(),"source":BASE_URL+ENDPOINT,
                "source_query":query, "source_http_status":None,
                "source_body_sha256":None,"rows_verified":0,
                "state":"SOURCE_HISTORY_UNAVAILABLE_OR_INVALID"}
        receipt["request_count"]+=1
        try:
            request=urllib.request.Request(url,headers={"User-Agent":"ZEL-Research-ReadOnly/1.0"})
            with urllib.request.urlopen(request,timeout=9) as response:
                raw=response.read(250_000)
                result["source_http_status"]=int(response.status)
                result["observed_body_received_utc"]=observed_utc()
            result["source_body_sha256"]=hashlib.sha256(raw).hexdigest()
            (out / f"{symbol}.http_body.json").write_bytes(raw)
            if result["source_http_status"]!=200:
                raise HistoryError("NON_200_PUBLIC_RESPONSE")
            rows=response_rows(raw,GAP_START_MS,GAP_END_MS)
            if len(rows)!=4 or [r["timestamp_ms"] for r in rows]!=list(range(GAP_START_MS,GAP_END_MS,MINUTE_MS)):
                raise HistoryError("UNEXPECTED_4_MINUTE_CENSUS")
            result["rows_verified"]=len(rows)
            result["state"]="FOUR_MINUTES_PUBLIC_BACKFILL_AVAILABLE_NEW_ARCHIVE_REQUIRED"
        except Exception as exc:
            result["error_class"]=type(exc).__name__
            result["error_message"]=str(exc)[:500]
        receipt["results"].append(result)
        print("GAP_SOURCE_PROBE",json.dumps({k:result[k] for k in ("symbol","state","rows_verified","source_http_status","source_body_sha256")},sort_keys=True),flush=True)
    receipt["finished_utc"]=observed_utc()
    receipt["source_confirmed_symbols"] = sum(x["rows_verified"]==4 for x in receipt["results"])
    receipt["all_six"]=receipt["source_confirmed_symbols"]==len(SYMBOLS)
    receipt["final_disposition"] = "POSSIBLE_VERSIONED_SOURCE_RECOVERY_NOT_INPLACE" if receipt["all_six"] else "HOLD_HISTORY_MISSING_OR_RESTRICTED"
    receipt["original_frozen_data_mutated"]=False
    path=out/"GAP_PROBE_RESULT.json"
    path.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print("GAP_PROBE_FINAL",json.dumps({"requests":receipt["request_count"],"complete":receipt["source_confirmed_symbols"],"verdict":receipt["final_disposition"],"no_economic_credit":True},sort_keys=True),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    main(args.output)
