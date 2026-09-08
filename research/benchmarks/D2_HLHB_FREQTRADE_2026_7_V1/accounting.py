"""Pure ledger accounting for the pinned benchmark; never executes an engine or IO.

All common returns are per equal entry notional in trade-bps.  The inherited
roundtrip fee/spread/impact and absolute funding proxy are not actual execution
costs.  FT profit/fees remain a separate namespace, never deducted twice.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math

BAR_MS = 14_400_000
SETTLEMENT_MS = 28_800_000
FROZEN_COST_SHA256 = "e7b29de0b1810d14e02847917e951301f4d9a30da190ed7c6fc4cafbca581020"
COST_SEMANTICS = "ORIGINAL_DEV_PROXY_FEE_SPREAD_IMPACT_ABSOLUTE_FUNDING_DEBIT_20BPS_FLOOR; ALL_COST2_DOUBLES_ALL; OPEN_FULL_ROUNDTRIP_HYPOTHETICAL"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def verify_cost_binding(costs, expected_sha256=FROZEN_COST_SHA256):
    actual = digest(costs)
    if actual != expected_sha256:
        raise ValueError("COST_BINDING_MISMATCH")
    for binding in costs.values():
        cost_breakdown(0, 0, binding)
    return {"sha256": actual, "semantics": COST_SEMANTICS}


def timestamp_ms(value):
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("NONFINITE_TIMESTAMP")
        return int(value)  # Numeric ledger timestamps are explicitly milliseconds.
    if not hasattr(value, "timestamp"):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return int(round(value.timestamp() * 1000))


def cost_breakdown(entry, exit_, binding):
    entry, exit_ = int(entry), int(exit_)
    if exit_ < entry:
        raise ValueError("NEGATIVE_HOLD_DURATION")
    names = ("fee_bps", "spread_bps", "impact_bps", "funding_p95_per_settlement_bps")
    values = {k: float(binding[k]) for k in names}
    if any(not math.isfinite(v) or v < 0 for v in values.values()):
        raise ValueError("INVALID_COST_PROXY")
    settlements = max(0, exit_ // SETTLEMENT_MS - entry // SETTLEMENT_MS)
    funding = settlements * values["funding_p95_per_settlement_bps"]
    raw = sum(values[k] for k in names[:3]) + funding
    return {"fee_bps": values["fee_bps"], "spread_bps": values["spread_bps"],
            "impact_bps": values["impact_bps"], "funding_bps": funding,
            "funding_settlements": settlements, "floor_adjustment_bps": max(0., 20. - raw),
            "total_bps": max(20., raw)}


def cost(entry, exit_, binding):
    return cost_breakdown(entry, exit_, binding)["total_bps"]


def _symbol(pair):
    # Preserve the 1000 contract price unit; strip only a futures settlement suffix.
    return str(pair).split(":")[0].replace("/", "-")


def _near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-7)


def _validate_trade(t):
    if not (t["entry_ts"] <= t["exit_ts_lower"] <= t["exit_ts"]):
        raise ValueError("TRADE_TIME_ORDER")
    if t["entry_price"] <= 0 or t["exit_price"] <= 0:
        raise ValueError("INVALID_PRICE")
    for k in ("gross_bps", "net_bps", "cost2_bps", "cost_bps"):
        if not math.isfinite(t[k]):
            raise ValueError("NONFINITE_LEDGER")
    if not _near(t["gross_bps"], (t["exit_price"] / t["entry_price"] - 1) * 10000):
        raise ValueError("SAVED_PRICE_GROSS_MISMATCH")
    if not _near(t["net_bps"], t["gross_bps"] - t["cost_bps"]):
        raise ValueError("SAVED_NET_COST_MISMATCH")
    if not _near(t["cost2_bps"], t["gross_bps"] - 2 * t["cost_bps"]):
        raise ValueError("SAVED_COST2_MISMATCH")


def normalize_engine(raw, packet, end):
    """Normalize raw FT records; force_exit stays OPEN at known final close.

    Intrabar ROI/SL fill timestamp is unresolved in [bar open, bar close].
    Price is FT's own fill; only the funding settlement count has time bounds.
    """
    out = []
    for r in raw:
        if r.get("is_short", False) or float(r.get("leverage", 1) or 1) != 1:
            raise ValueError("LONG_ONE_X_ANALYTICAL_SCOPE")
        symbol = _symbol(r["pair"])
        entry = timestamp_ms(r["open_date"])
        ex = timestamp_ms(r["close_date"])
        reason = str(r["exit_reason"])
        opened = reason == "force_exit"
        intrabar = not opened and reason in ("roi", "stop_loss", "trailing_stop_loss", "stoploss_on_exchange")
        lower = int(end) if opened else ex
        upper = int(end) if opened else min(int(end), ex + BAR_MS) if intrabar else ex
        final_rows = [v for v in packet["rows_by"][symbol] if int(v["bar_close_ts"]) <= int(end)]
        if opened and (not final_rows or int(final_rows[-1]["bar_close_ts"]) != int(end)):
            raise ValueError("FINAL_MARK_MISSING")
        price = float(final_rows[-1]["close"]) if opened else float(r["close_rate"])
        entry_price = float(r["open_rate"])
        if entry_price <= 0:
            raise ValueError("INVALID_ENTRY_PRICE")
        gross = (price / entry_price - 1) * 10000
        lo = cost_breakdown(entry, lower, packet["costs"][symbol])
        hi = cost_breakdown(entry, upper, packet["costs"][symbol])
        t = {"symbol": symbol, "origin": f"{symbol}:{entry}", "entry_ts": entry,
             "entry_price": entry_price, "exit_ts": upper, "exit_ts_lower": lower,
             "exit_price": price, "closed": not opened, "reason": reason,
             "gross_bps": gross, "cost_bps": hi["total_bps"],
             "net_bps": gross-hi["total_bps"], "cost2_bps": gross-2*hi["total_bps"],
             "cost_lower_bps": lo["total_bps"], "net_upper_bps": gross-lo["total_bps"],
             "cost2_upper_bps": gross-2*lo["total_bps"],
             "cost_breakdown_lower": lo, "cost_breakdown_upper": hi,
             "intrabar_time_unobserved": intrabar,
             "engine": {k: r.get(k) for k in ("profit_ratio", "profit_abs", "fee_open", "fee_close",
                         "fee_open_cost", "fee_close_cost", "funding_fees", "stake_amount", "amount", "leverage", "exit_reason")},
             "engine_open_date": str(r["open_date"]), "engine_close_date": str(r["close_date"]),
             "engine_open_rate": entry_price, "engine_close_rate": float(r["close_rate"])}
        _validate_trade(t)
        out.append(t)
    return out


def normalize_saved(value, packet=None):
    """Read existing native economics only; do not invoke native replay.

    packet costs, when supplied, verify the independent inherited cost formula.
    Existing source values are retained instead of silently repaired.
    """
    out = []
    for opened, records in ((False, value.get("trades", [])), (True, value.get("open_observations", []))):
        for r in records:
            entry, ex = int(r["entry_ts"]), int(r["mark_ts"] if opened else r["exit_ts"])
            c = float(r["hypothetical_liquidation_cost_bps"] if opened else r["cost_bps"])
            t = {"symbol": r["symbol"], "origin": f'{r["symbol"]}:{entry}',
                 "entry_ts": entry, "entry_price": float(r["entry_price"]),
                 "exit_ts": ex, "exit_ts_lower": ex,
                 "exit_price": float(r["mark_price"] if opened else r["exit_price"]),
                 "closed": not opened, "reason": "ZEL_OPEN_MARK" if opened else r.get("exit_reason", r.get("reason", "ZEL_SAVED_EXIT")),
                 "gross_bps": float(r["gross_mark_bps"] if opened else r["gross_bps"]),
                 "net_bps": float(r["hypothetical_liquidation_net_mark_bps"] if opened else r["net_bps"]),
                 "cost2_bps": float(r["hypothetical_liquidation_cost2x_net_mark_bps"] if opened else r["cost2x_net_bps"]),
                 "cost_bps": c, "cost_lower_bps": c, "intrabar_time_unobserved": False}
            _validate_trade(t)
            if packet is not None and not _near(c, cost(entry, ex, packet["costs"][r["symbol"]])):
                raise ValueError("NATIVE_COST_FORMULA_MISMATCH")
            out.append(t)
    return out


def metrics(trades, packet, start, end):
    """Calculate equal-notional ledger metrics and same 4h-close marked DD.

    MTM is a hypothetical full-roundtrip liquidation valuation. Exposure totals
    sum position time and can exceed calendar time. Streak ties use symbol then
    origin, explicitly deterministic rather than an observed intrabar sequence.
    """
    if len({t["origin"] for t in trades}) != len(trades):
        raise ValueError("DUPLICATE_ENTRY_ORIGIN")
    for t in trades:
        _validate_trade(t)
        if not int(start) <= t["entry_ts"] <= t["exit_ts"] <= int(end):
            raise ValueError("TRADE_OUTSIDE_PERIOD")
    closed = sorted((t for t in trades if t["closed"]), key=lambda t: (t["exit_ts"], t["symbol"], t["origin"]))
    wins = [t["net_bps"] for t in closed if t["net_bps"] > 0]
    losses = [-t["net_bps"] for t in closed if t["net_bps"] < 0]
    avwin = sum(wins)/len(wins) if wins else None
    avloss = sum(losses)/len(losses) if losses else None
    marks = {}
    for symbol, rows in packet["rows_by"].items():
        marks[symbol] = {}
        for r in rows:
            ts = int(r["bar_close_ts"])
            if ts in marks[symbol]:
                raise ValueError("DUPLICATE_MARK_TIMESTAMP")
            marks[symbol][ts] = float(r["close"])
    curve, curve2, peak, peak2, dd, dd2 = [], [], 0., 0., 0., 0.
    clock = sorted({ts for m in marks.values() for ts in m if start < ts <= end})
    for ts in clock:
        eq = eq2 = 0.
        for t in trades:
            if t["entry_ts"] >= ts:
                continue
            if t["exit_ts"] <= ts:
                net, net2 = t["net_bps"], t["cost2_bps"]
            else:
                if ts not in marks[t["symbol"]]:
                    raise ValueError("MISSING_ACTIVE_POSITION_MARK")
                gross = (marks[t["symbol"]][ts]/t["entry_price"]-1)*10000
                c = cost(t["entry_ts"], ts, packet["costs"][t["symbol"]])
                net, net2 = gross-c, gross-2*c
            eq += net
            eq2 += net2
        peak, peak2 = max(peak, eq), max(peak2, eq2)
        dd, dd2 = max(dd, peak-eq), max(dd2, peak2-eq2)
        curve.append([ts, eq]); curve2.append([ts, eq2])
    terminal = sum(t["net_bps"] for t in trades)
    terminal2 = sum(t["cost2_bps"] for t in trades)
    if trades and (not curve or curve[-1][0] != end or not _near(curve[-1][1], terminal)):
        raise ValueError("FINAL_EQUITY_MISMATCH")
    bysymbol = {s: sum(t["net_bps"] for t in trades if t["symbol"] == s) for s in packet["rows_by"]}
    top = max(bysymbol, key=lambda s: (bysymbol[s], s)) if bysymbol else None
    positive = sum(max(v, 0.) for v in bysymbol.values())
    absolute = sum(abs(v) for v in bysymbol.values())
    streak = worst = 0
    for t in closed:
        streak = streak+1 if t["net_bps"] < 0 else 0
        worst = max(worst, streak)
    return {"unit": "equal_entry_notional_trade_bps", "closed": len(closed), "open": len(trades)-len(closed),
            "wins": len(wins), "losses": len(losses), "breakeven": len(closed)-len(wins)-len(losses),
            "win_rate": len(wins)/len(closed) if closed else None,
            "average_win_bps": avwin, "average_loss_bps": avloss,
            "payoff": avwin/avloss if avwin is not None and avloss else None,
            "PF": sum(wins)/sum(losses) if losses else None,
            "PF_undefined_reason": "NO_LOSSES" if not losses else None,
            "closed_net": sum(t["net_bps"] for t in closed),
            "open_mark": sum(t["net_bps"] for t in trades if not t["closed"]),
            "terminal_net": terminal, "terminal_cost2": terminal2,
            "gross_total_bps": sum(t["gross_bps"] for t in trades),
            "cost_total_bps": sum(t["cost_bps"] for t in trades),
            "mark4h_DD": dd, "mark4h_cost2_DD": dd2,
            "exposure_symbol_days": sum(t["exit_ts"]-t["entry_ts"] for t in trades)/86_400_000,
            "exposure_symbol_days_lower": sum(t["exit_ts_lower"]-t["entry_ts"] for t in trades)/86_400_000,
            "worst_loss_streak": worst, "streak_order": "exit_upper_ts,symbol,origin; not intrabar observed order",
            "by_symbol": bysymbol, "top_symbol": top,
            "top_symbol_contribution_bps": bysymbol[top] if top else None,
            "terminal_excluding_top_symbol_bps": terminal-bysymbol[top] if top else terminal,
            "top_positive_symbol_share": max(bysymbol[top], 0.)/positive if top and positive else None,
            "largest_absolute_symbol_share": max(map(abs, bysymbol.values()))/absolute if absolute else None,
            "intrabar_time_uncertain": sum(t.get("intrabar_time_unobserved", False) for t in trades),
            "net_upper_due_only_to_time_cost": sum(t.get("net_upper_bps", t["net_bps"]) for t in trades),
            "cost2_upper_due_only_to_time_cost": sum(t.get("cost2_upper_bps", t["cost2_bps"]) for t in trades),
            "equity4h": curve, "equity4h_cost2": curve2,
            "cost_status": "INHERITED_RESEARCH_PROXY_NOT_ACTUAL_COSTS", "formal_credit": 0}
