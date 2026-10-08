"""Artificial fixtures; no market files, claims or economic performance."""
from copy import deepcopy
import hashlib
import json

import pandas as pd
import pytest

from ops import issue1388_inverted_execution_v1 as lifecycle
from ops.issue1388_inverted_hammer_v1 import inverted_hammer_flags
from ops.issue1388_inverted_audit_v1 import AuditError, audit_inverted_hammer

HOUR = 3_600_000
SYMBOL = "BTC-USDT"


def fixture(n=230, signals=(160, 170, 190), *, gap=None, late=None):
    rows = []
    for i in range(n):
        price = 1000.0 - i
        rows.append({"open": price + 2, "high": price + 3, "low": price - 1, "close": price,
                     "open_ts_ms": i * HOUR, "close_ts_ms": (i + 1) * HOUR,
                     "available_ts_ms": (i + 1) * HOUR, "segment_id": "A"})
    for i in signals:
        bottom = rows[i - 1]["close"] - 1
        rows[i].update(open=bottom, close=bottom + .25, low=bottom, high=bottom + 1.25)
    if gap is not None:
        # A changed segment is a genuine source gap while source period remains fixed.
        for row in rows[gap:]:
            row["segment_id"] = "B"
    if late is not None:
        index, delay = late
        rows[index]["available_ts_ms"] += delay
    flags = inverted_hammer_flags(pd.DataFrame(rows)).tolist()
    decisions = lifecycle.bind_inverted_decisions(rows, flags)
    funding = [{"symbol": SYMBOL, "fundingTime": i * HOUR, "fundingRate": .0001 if i % 16 == 0 else -.00005,
                "markPrice": 1000.0 - i} for i in range(0, n, 8)]
    return rows, decisions, funding, {"start_ms": 150 * HOUR, "end_ms": n * HOUR, "roundtrip_cost_bps": 14.0}


def replay_and_audit(data, monkeypatch=None):
    rows, decisions, funding, kwargs = data
    saved = lifecycle.replay_inverted_hammer(SYMBOL, rows, decisions, funding, **kwargs)
    if monkeypatch:
        monkeypatch.setattr(lifecycle, "replay_inverted_hammer", lambda *a, **k: pytest.fail("AUDIT_CALLED_LIFECYCLE_REPLAY"))
    certificate = audit_inverted_hammer(SYMBOL, rows, decisions, funding, saved=saved, **kwargs)
    return saved, certificate


def test_complete_source_lifecycle_certificate_without_replay(monkeypatch):
    saved, certificate = replay_and_audit(fixture(), monkeypatch)
    assert len(saved["trades"]) == 2
    assert saved["signals"] == 3 and saved["occupied_rejections"] == 1
    assert certificate["closed_trades"] == 2 and certificate["source_flags_recomputed"]
    assert certificate["lifecycle_replay_called"] is False
    assert certificate["funding_archive_coverage_certified"] is False


@pytest.mark.parametrize("data", [
    fixture(n=185, signals=(160,)),  # Due at END: retained open, no liquidation.
    fixture(n=170, signals=(168,), late=(168, 2 * HOUR)),  # Unfilled pending.
    fixture(gap=170, signals=(160, 165)),  # Occupied source gap.
    fixture(gap=162, signals=(160,), late=(160, 2 * HOUR)),  # Pending source gap.
    fixture(signals=()),
    fixture(late=(160, HOUR // 2)),  # Next open after late receipt.
])
def test_pending_open_gap_empty_and_late_exact_states(data):
    saved, certificate = replay_and_audit(data)
    assert saved["unresolved_end"] == certificate["unresolved_end"]


def test_missing_funding_kept_unknown():
    rows, decisions, _, kwargs = fixture()
    saved, certificate = replay_and_audit((rows, decisions, None, kwargs))
    assert saved["disposition"] == "BLOCKED_MISSING_FUNDING"
    assert all(t["net_bps"] is None and t["funding_bps"] is None for t in saved["trades"])


def test_signed_funding_conservative_exact_boundaries():
    rows, decisions, _, kwargs = fixture(signals=(160,))
    entry, exit_ = 161 * HOUR, 185 * HOUR
    funding = [{"symbol": SYMBOL, "fundingTime": t, "fundingRate": r, "markPrice": 841.0}
               for t, r in ((entry, -.0001), (entry + HOUR, -.0001), (exit_, -.0001))]
    saved, _ = replay_and_audit((rows, decisions, funding, kwargs))
    assert saved["trades"][0]["funding_bps"] == -1.0
    assert saved["trades"][0]["funding_settlements"] == 1
    for row in funding:
        row["fundingRate"] = .0001
    saved, _ = replay_and_audit((rows, decisions, funding, kwargs))
    assert saved["trades"][0]["funding_bps"] == 3.0


def _rehash(saved):
    # An attacker can recompute an external digest; audit receives the body.
    return hashlib.sha256(json.dumps(saved, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.parametrize("tamper", ["later_entry", "drop_first_trade", "later_exit", "price", "cost", "funding",
                                   "candidate", "census", "occupied", "paid_cost", "quantity", "due", "source_false"])
def test_coordinated_outer_rehash_does_not_authorize_tampered_ledger(tamper):
    rows, decisions, funding, kwargs = fixture()
    saved = lifecycle.replay_inverted_hammer(SYMBOL, rows, decisions, funding, **kwargs)
    before = _rehash(saved)
    if tamper == "later_entry":
        trade = saved["trades"][0]
        stamp = trade["entry_ts_ms"] + HOUR
        price = rows[stamp // HOUR]["open"]
        identity = f"{SYMBOL}:{stamp}:{trade['signal_open_ts_ms']}"
        trade.update(entry_ts_ms=stamp, entry_price=price, entry_identity=identity, exit_due_ts_ms=stamp + 24 * HOUR)
        saved["orders"][0].update(execution_ts_ms=stamp, price=price, entry_identity=identity)
        saved["orders"][1].update(entry_identity=identity, exit_due_ts_ms=stamp + 24 * HOUR)
        trade["gross_bps"] = (trade["exit_price"] / price - 1) * 10000
        trade["net_bps"] = trade["gross_bps"] - trade["cost_bps"] - trade["funding_bps"]
    elif tamper == "drop_first_trade":
        saved["trades"].pop(0)
        saved["orders"] = saved["orders"][2:]
        saved["paid_trading_cost_bps"] -= 14
        saved["closed_trading_cost_bps"] -= 14
        saved["signals"] -= 2
        saved["occupied_rejections"] = 0
    elif tamper == "later_exit":
        trade = saved["trades"][0]
        stamp = trade["exit_ts_ms"] + HOUR
        price = rows[stamp // HOUR]["open"]
        trade.update(exit_ts_ms=stamp, exit_price=price, gross_bps=(price / trade["entry_price"] - 1) * 10000)
        trade["net_bps"] = trade["gross_bps"] - trade["cost_bps"] - trade["funding_bps"]
        saved["orders"][1].update(execution_ts_ms=stamp, price=price)
    elif tamper in ("price", "cost", "funding"):
        field = {"price": "exit_price", "cost": "cost_bps", "funding": "funding_bps"}[tamper]
        saved["trades"][0][field] += 1
        saved["trades"][0]["net_bps"] = saved["trades"][0]["gross_bps"] - saved["trades"][0]["cost_bps"] - saved["trades"][0]["funding_bps"]
    elif tamper == "candidate":
        saved["candidate_id"] = "E_FT_BBAND_RSI_1H_V1"
        for trade in saved["trades"]:
            trade["identity"] = saved["candidate_id"]
    elif tamper == "census":
        saved["signals"] += 1
    elif tamper == "occupied":
        saved["occupied_rejections"] -= 1
    elif tamper == "paid_cost":
        saved["paid_trading_cost_bps"] = saved["closed_trading_cost_bps"] = 0.0
    elif tamper == "quantity":
        saved["orders"][0]["quantity"] = 2
    elif tamper == "due":
        saved["trades"][0]["exit_due_ts_ms"] += HOUR
    else:
        decisions = deepcopy(decisions)
        decisions[160]["entry"] = False
    assert _rehash(saved) != before or tamper == "source_false"
    with pytest.raises(AuditError, match="IH_AUDIT"):
        audit_inverted_hammer(SYMBOL, rows, decisions, funding, saved=saved, **kwargs)


@pytest.mark.parametrize("state", ["open", "pending", "gap"])
def test_omitted_unresolved_state_and_recomputed_hash_rejected(state):
    data = (fixture(n=180, signals=(160,)) if state == "open" else
            fixture(n=170, signals=(168,), late=(168, 2 * HOUR)) if state == "pending" else fixture(gap=170, signals=(160,)))
    rows, decisions, funding, kwargs = data
    saved = lifecycle.replay_inverted_hammer(SYMBOL, rows, decisions, funding, **kwargs)
    if state == "open":
        saved["open_position"] = None
        saved["open_entry_cost_bps"] = 0.0
    elif state == "pending":
        saved["pending_entry"] = None
    else:
        saved["gap_quarantine"] = None
        saved["open_position"]["funding_bps_to_end_exclusive"] = 0.0
        saved["open_position"]["funding_settlements"] = 0
    saved["unresolved_end"] = 0
    saved["disposition"] = "DRAFT_ONLY_NO_VERDICT"
    assert _rehash(saved)
    with pytest.raises(AuditError, match="IH_AUDIT"):
        audit_inverted_hammer(SYMBOL, rows, decisions, funding, saved=saved, **kwargs)
