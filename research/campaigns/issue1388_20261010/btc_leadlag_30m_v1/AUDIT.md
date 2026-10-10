# ISSUE1388: One fixed hypothesis, one actual costed DEVELOPMENT comparison

**Economics, not another PR/test tally.** Pinned rule before result at bcbd16268aada089cd4cb93a90c5ee9b41c00ddd, byte-for-byte original verified-source gzip `732ef1c9667b5aadb984e07466a9cd35bcfbcc781a3bc6df6bf0de0e07dfa555`; source owns no unused OOS credit.

This internal, *not source-exact donor*, BTC-leading ALT catch-up long-only 30m idea: BTC 30m bullish & above completed SMA24, ALT negative close-to-close but also above SMA24; enter ALT at next 30m open, stop at 1.5×14-bar completed ATR, exit by 8th completed 30m bar, no take profit. Five ALT instruments are evaluated independently; no account cash/exposure tracking.

## One-shot quantitative result

| Measure | cost1x | cost2x (same fills) |
|---|---:|---:|
| T (closed trades) | 138 | 138 |
| Gross/T | +0.129 bps | +0.129 bps |
| Cost/T | 15.180 bps | 30.360 bps |
| **Net/T** | **−15.051 bps** | **−30.231 bps** |
| Net trade-bps sum | −2,077.035 | −4,171.865 |
| PF | 0.707 | 0.502 |
| WR | 42.03% | 36.23% |
| Max loss streak | 10 | 10 |
| DD realized-close trade-bps | 4,467.022 | 5,696.711 |

All 5 tradable symbols have net1x negative; 115 trades in Sep (−11.798bps/T), 23 in Oct (−31.318bps/T). 214 completed-bar signals → 138 trades, 76 blocked by existing occupancy/closed-bar lifecycle.

**FAIL `REJECT_COST_KILLED`: the raw gross expectancy +0.129bps/T is far below 15.180bps/T modeled round trip. Do not re-tune the same source/axis/19d after looking at outcomes.** Given margin this is not a credible production edge. No W1/W2/W3 or fresh claim.

## Source/accuracy boundary

Source: GitHub Actions artifact #11305382754 (previously saved BingX public 1m), 6×27,415 real minutes, exactly 913 complete causal 30m bars each, excluded 25 trailing incomplete minutes, underlying compressed SHA256 `732ef1c9667b5aadb984e07466a9cd35bcfbcc781a3bc6df6bf0de0e07dfa555`, original reference scenario cost authority `cb9c337d95aa9eb65c32776ca68c63390350c501de4df8024b5416ed778dbe73`. Native source period Sep15–Oct4 2026; previously consumed DEV, **not** independent OOS, no verified historical funding, order-book queue, actual partial fill, account NAV, historical received-at-close witness; stop-first OHLC assumes ideal stop filling absent actual intrabar event order. Trade-level SHA in summary and full local 138-row receipt `5b09f227a6c17b3809bbbba240e9540e3a61fe0885fac42134297fda5401ee6f`. Original source and strategy rules preserved, no wallet order, no economy-heavy job or user account data.

Local Python source SHA `c5799719ab078fef4df9c878acfd932796a1722efc745a47407d3f8ee4242e93`, six audit unit tests PASS (source SHA/price continuity, cost1x/2x, next-open/stop ordering, no OOS credit, receipt integrity). Full script, tests and transaction-level JSON produced in current conversation working directory; GitHub carries this compact receipt and frozen prior first.

**Next:** this one new economic hypothesis has now been falsified using a real historical dataset. Reconcile latest owner evidence rather than old checkpoint, and route to a distinct licensed/native costed mechanism; do not confuse this non-authoritative dev calculation with a new #1388 common-runner cheap/FULL claim or Survivor.