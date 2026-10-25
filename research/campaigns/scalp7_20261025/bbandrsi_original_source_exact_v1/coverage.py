"""Read-only per-universe MTM review: no orders, no parameter fitting."""

from __future__ import annotations

import argparse
import hashlib
import gzip
import json
from pathlib import Path


def deterministic_gzip(raw: bytes) -> bytes:
    b = bytearray(gzip.compress(raw, compresslevel=7, mtime=0))
    b[9] = 255
    return bytes(b)


ROOT = Path(__file__).resolve().parent
CORES = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT")
SIX = (*CORES, "DOGE-USDT", "LINK-USDT")


def group(source: dict, names: tuple[str, ...]) -> dict:
    universe = source["per_symbol"]
    names = tuple(sorted(names))
    assert set(names).issubset(universe)
    m = len(next(iter(universe.values()))["equity_curve"])
    curves = [universe[k]["equity_curve"] for k in names]
    if not all(len(v) == m for v in curves):
        raise ValueError("ALIGNMENT_FAILED")
    equity = [sum(float(c[i]) for c in curves) for i in range(m)]
    high = float(len(names))
    dd = 0.0
    dd_fraction = 0.0
    for nav in equity:
        high = max(high, nav)
        dd = max(dd, high - nav)
        dd_fraction = max(dd_fraction, (high - nav) / high)
    v = [float(t["net_bps"]) for name in names for t in universe[name]["trades"]]
    grosspos = sum(max(0, x) for x in v)
    loss = -sum(min(0, x) for x in v)
    open_legs = [
        (n, universe[n]["open_at_end"]) for n in names if universe[n]["open_at_end"]
    ]
    return {
        "selected_symbols": list(names),
        "completed_T": len(v),
        "admitted_T": sum(universe[n]["entered_T"] for n in names),
        "open_T": len(open_legs),
        "closed_net_sum_trade_bps": sum(v),
        "closed_PF": grosspos / loss if loss else None,
        "closed_winrate": sum(x > 0 for x in v) / len(v) if v else None,
        "closed_net_ex_best2_bps": sum(v)
        - sum(sorted((x for x in v if x > 0), reverse=True)[:2]),
        "open_unrealized_gross_bps": sum(
            o["unrealized_gross_bps"] for _, o in open_legs
        ),
        "terminal_portfolio_mark_return_pct": 100 * (equity[-1] / len(names) - 1),
        "portfolio_mark_max_drawdown_pct": dd_fraction * 100,
        "terminal_portfolio_last_mark_forced_liquidation_pct": 100
        * (
            sum(universe[n]["terminal_equity_if_marked_liquidation"] for n in names)
            / len(names)
            - 1
        ),
        "worst_mark_to_market_open_bps": min(
            (o["unrealized_gross_bps"] for _, o in open_legs), default=None
        ),
        "unrealized_open_legs": [{"symbol": n, **o} for n, o in open_legs],
        "initial_equal_capital_units": len(names),
        "leverage": 1,
        "signed_funding_witness": "UNKNOWN",
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=ROOT / "COVERAGE.json.gz")
    args = p.parse_args()
    if args.out.exists():
        raise SystemExit("OVERWRITE_FORBIDDEN")
    raw = (ROOT / "RESULT.json.gz").read_bytes()
    allr = json.loads(gzip.decompress(raw))
    scenarios = {}
    for name, z in allr["simulations"].items():
        u = z["per_symbol"]
        scenarios[name] = {
            "six_target_symbols": group(z, SIX),
            "four_primary_symbols": group(z, CORES),
            "all_twelve_spot_equivalent": group(z, tuple(sorted(u))),
            "leave_one_six": {
                s: group(z, tuple(x for x in SIX if x != s)) for s in SIX
            },
        }
    output = {
        "schema": "zel.bbandrsi.source_exact.portfolio_concentration.v1",
        "source_result_sha256": hashlib.sha256(raw).hexdigest(),
        "frozen_asof": allr["source_asof"],
        "universe_risk": "price_stop25pct is NOT admissible for high leverage; no market authorization",
        "scenarios": scenarios,
        "orders": 0,
    }
    b = (json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    args.out.write_bytes(deterministic_gzip(b) if args.out.suffix == ".gz" else b)
    print("COVERAGE_SHA256", hashlib.sha256(b).hexdigest())
    for what in ("fee40_delay0h", "fee40_delay1h"):
        z = output["scenarios"][what]
        for names in (
            "four_primary_symbols",
            "six_target_symbols",
            "all_twelve_spot_equivalent",
        ):
            s = z[names]
            print(
                "UNIVERSE",
                what,
                names,
                "CLOSED",
                s["completed_T"],
                "OPEN",
                s["open_T"],
                "MARK_NET_PCT",
                round(s["terminal_portfolio_mark_return_pct"], 3),
                "DD_PCT",
                round(s["portfolio_mark_max_drawdown_pct"], 3),
                "PF",
                round(s["closed_PF"] or 0, 3),
            )
        negatives = sorted(
            (name, x["terminal_portfolio_mark_return_pct"])
            for name, x in z["leave_one_six"].items()
            if x["terminal_portfolio_mark_return_pct"] <= 0
        )
        print("LEAVE_ONE_SIX_NEGATIVE", what, negatives)


if __name__ == "__main__":
    main()
