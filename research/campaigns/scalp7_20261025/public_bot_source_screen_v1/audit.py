"""Cost/fat-tail/leave-one-symbol audit on the single untouched frozen 60-day screen."""

import collections
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

import screen

BASE = Path(__file__).resolve().parent


def digest(buf):
    return hashlib.sha256(buf).hexdigest()


def one_pass():
    raw = (BASE / "RESULT.json").read_bytes()
    res = json.loads(raw)
    assert res["source_census_sha256"] == digest(
        (BASE / "SOURCE_CENSUS.json").read_bytes()
    )
    origin = json.loads((BASE / "FREEZE.json").read_text())
    trades = json.loads(gzip.decompress((BASE / "TRADES.json.gz").read_bytes()))
    audit = {
        "schema": "zel.public_bot_source_screen.audit.v1",
        "source_result_sha256": digest(raw),
        "freeze_sha256": res["freeze_sha256"],
        "not_fresh_oos": True,
        "original_archive_manifest_HOLD": True,
        "no_real_quote_fill": True,
        "native_signal_source_copied_with_GPL": True,
        "split_and_fat_tail": {},
        "order_calls": 0,
    }
    for name, rows in trades.items():
        bysym = {}
        bymonth = {}
        loocv = {}
        for s in origin["symbols"]:
            own = [r for r in rows if r["symbol"] == s]
            bysym[s] = {"T": len(own), "cost40": screen.stats(own, 40)}
            complement = [r for r in rows if r["symbol"] != s]
            loocv[s] = {"T": len(complement), "cost40": screen.stats(complement, 40)}
        for month in ("2025-12", "2026-01", "2026-02"):
            own = [
                r
                for r in rows
                if dt.datetime.fromtimestamp(
                    r["entry_ts"] / 1000, dt.timezone.utc
                ).strftime("%Y-%m")
                == month
            ]
            bymonth[month] = {"T": len(own), "cost40": screen.stats(own, 40)}
        cuts = {}
        half = screen.to_ms("2026-01-14T00:00:00+00:00")
        for part, selection in (
            ("FIRST_30_CALENDAR_DAYS", [r for r in rows if r["entry_ts"] < half]),
            ("LAST_30_CALENDAR_DAYS", [r for r in rows if r["entry_ts"] >= half]),
        ):
            cuts[part] = screen.stats(selection, 40)
        stronger = {}
        for cost in (20, 40, 60, 80):
            stronger[f"cost{cost}"] = screen.stats(
                [{**r, f"net{cost}_bps": r["gross_bps"] - cost} for r in rows], cost
            )
        lossreason = collections.Counter(
            x["reason"] for x in rows if x["net40_bps"] < 0
        )
        # Whole strategy cannot masquerade as independent economic stream.
        evidence = {
            "native_timeframe": origin["strategies"][name]["timeframe"],
            "by_symbol": bysym,
            "leave_one_symbol_out": loocv,
            "by_month": bymonth,
            "time_halves": cuts,
            "cost_stress": stronger,
            "negative_trade_reasons": dict(lossreason),
            "cost40_T": len(rows),
            "cost40_win_T": sum(x["net40_bps"] > 0 for x in rows),
            "cost40_loss_T": sum(x["net40_bps"] < 0 for x in rows),
            "conservative_model_not_native_freqtrade_backtest": True,
        }
        audit["split_and_fat_tail"][name] = evidence

        def fmt(v):
            return round(v["Net_trade_bps_sum"], 2)

        print(
            "AUDITED",
            name,
            "trade_T",
            len(rows),
            "cost40",
            fmt(stronger["cost40"]),
            "cost60",
            fmt(stronger["cost60"]),
            "cost80",
            fmt(stronger["cost80"]),
            "halves",
            {k: fmt(v) for k, v in cuts.items()},
            "weakest_LOOCV",
            min((s, fmt(v["cost40"])) for s, v in loocv.items()),
            "net_no_top2",
            round(stronger["cost40"]["Net_without_best_2_trade_bps"], 2),
            "loss_reasons",
            dict(lossreason),
            flush=True,
        )
    data = (
        json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    (BASE / "AUDIT.json").write_bytes(data)
    print("AUDIT_SHA", digest(data), flush=True)


if __name__ == "__main__":
    one_pass()
