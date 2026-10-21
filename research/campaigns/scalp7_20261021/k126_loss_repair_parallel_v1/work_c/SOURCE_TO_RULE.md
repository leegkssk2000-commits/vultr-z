# Work C: source, native contract, and the limit of a state repair

Scope: `K126_WORST8_STATE_AND_LOSS_REPAIR_C_V1`. Research checked on 2026-10-22 (Europe/Berlin). Sources below are free original interviews, author articles, publisher transcript, and code posted by its own author. None supplies a crypto30m execution ledger matching ZEL. External success claims are not measured K126 performance. No external ATR, ADX, clock, stop-distance, or holding-period number is imported into a new rule.

## Exact prior work retained

- Original K126: `308bd2deb7acaaacf1adb582206e78262d72c9d1`.
- Current whole-pullback close-failure completion: `81a12c422ee9329996d2f6b983267d2def490d4b`; prepared freeze at `b692aa8b4a6ab955afa11ee4a7a07e56a96a9c36`. The supplied result is a single-trade +16.44668480934 trade-bps change on used DEV, without improving the 8/13 loss streaks or drawdown. It is not production PASS.
- Diagnostic: `4a5985e362959f8460726fb56780fc10eab04a8b`; its completed anatomy is reused, not rerun.
- Rejected H02 at `50b0c6c4956f04b5b4d59f43a1c31e92f2a11aef` required a completed rising-ADX witness before touch. It removed recovery winners and worsened the base-cost streak. This document does not revive it as a renamed source-fidelity fix.
- Rejected signal-bar exit at `f7a697de16bec7ae64f36a0d5974f1cb28a201db` materially reduced Net and excluded/truncated winners. No second run with a different name or number is proposed.

## Sources read and their distinct contributions

### S1 — Raschke interview, AIQ Opening Bell, August 1997

[Author-hosted PDF](https://lindaraschke.net/wp-content/uploads/2026/01/august1997.pdf). Actual publication is August 1997; the upload directory is not the publication date. Read the printed p2 rule box, p4 winning/failing equity examples, and p6 stop discussion. Daily US equities are the pictured Holy Grail examples; other patterns discuss intraday/weekly data.

The sequence is initial rising ADX, EMA retracement, a stop-entry trigger, and protection at the newly formed swing. A declining ADX during the retracement is explicitly compatible with the setup. The Eaton example supplies a failed/stalled trade despite prior strength; the author compares its behavior with the broader market. It is qualitative failure evidence, not a coded threshold.

The interview makes favorable probability claims without a recoverable matched trade ledger; the publisher disclaims track records. No win-rate assumption is accepted. **Internal implication:** record the transition sequence and distinguish initial strength from later weakness. Do not turn all weak rows into resets, copy the example's elapsed days, or interpret an old equal-price timestamp as the native swing origin. This source does not define GMMA, regime vetoes, state expiry, or exchange admission.

### S2 — Raschke interview, Active Trader, March 2004

[Author-hosted PDF](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf). Read printed pp76–79, especially the Grail section on pp78–79. The example is December 2003 S&P500, 30-minute; the interview also discusses sequencing across shorter and longer intraday charts.

A prior momentum expansion is followed by a retracement and an attempt at new highs. Each timeframe has its own preceding strength evidence. The interview describes modeling tendencies and discretion rather than a fully specified automated system. The illustrated successful sequence is not an audited backtest. **Internal implication:** touch, turn, availability, and re-arming are separate events. The narrative neither proves that every retained weak-state extreme is erroneous nor prescribes expiry after a regime-ineligible native event. The already-rejected H02 interpretation stays rejected.

### S3 — Raschke interview, Active Trader, February 2004

[Author-hosted PDF](https://lindaraschke.net/wp-content/uploads/2026/01/raschke0204.pdf). Read printed pp66–71: short-timeframe noise, broad initial stops, loss-run risk, and momentum/volatility examples. Markets include index futures and equities; daily and intraday contexts differ.

The author explains that mechanical continuation trades may need broad stops while narrow stops get repeatedly hit. She also discusses adverse volatility environments where familiar flag patterns fail. These are author observations and hypothetical system statistics, not the six-symbol crypto126 sample. **Internal implication:** large risk alone is not a bug or exclusion criterion. Preserve broad-risk winners and normal pullbacks in tests; do not transplant leverage, win-rate, volatility or time numbers. D owns exposure work; C does not implement portfolio sizing.

### S4 — Adam H Grimes, When Good Setups Go Bad, 8 May 2018

[Author article](https://www.adamhgrimes.com/when-good-setups-go-bad/). Read the complete EURCHF example and its three lessons. The text describes a multi-month uptrend; no chart timeframe is asserted here beyond what the text supports.

A visually attractive flag fails via forceful adverse movement; the author also notes that many traders would not yet have entered. This is an important distinction between failed setup and actual losing position. No matched-cost result is supplied. **Internal implication:** an observer must distinguish generated event, entry admission, and later trade outcome. Pattern failure is not permission to label every setup as an executed loser or replay the rejected signal-bar exit.

### S5 — Adam H Grimes, Fundamental Trading Patterns

[Author reference](https://www.adamhgrimes.com/fundamental-trading-patterns/). Read Simple Pullback, Complex Pullback and Failure Test sections. The current reference page does not establish a reliable publication date, market or timeframe; schematic patterns are not a dated trading result.

An initial attempt to resume a trend can fail, form another countertrend leg, and then resume strongly. **Internal implication:** temporary weakness and a failed first attempt can occur in eventual winners. A forced reset may sacrifice those opportunities. Tests must include recovery paths, not just an attractive losing example. No bar count or numerical failure threshold is provided by this reference.

### S6 — BenTen, Holy Grail ADX Trading Setup for ThinkorSwim, 12 September 2019

[Author's public code, post 1](https://usethinkscript.com/threads/holy-grail-adx-trading-setup-for-thinkorswim.618/). Read the entire initial code block, not only the descriptive bullet list. The post is an indicator implementation; timeframe/market is user-selected, not a certified economic study.

The actual code colors bars by price relative to an SMA and an ADX level. It does not encode the prose's rising-ADX requirement, ordered touch/turn lifecycle, protective stop, fills, or reset. **Internal implication:** a familiar strategy title is insufficient evidence of code fidelity. This implementation is a useful counterexample, not code to transplant. No third-party code is copied into the adapter, and its noncommercial licensing is not treated as permission for commercial reuse. No verified performance is supplied.

### S7 — SMB Training, How to Use Tape Reading to Help you Keep Your Trading Profits, 23 December 2020

[Publisher video and transcript](https://www.smbtraining.com/blog/how-to-use-tape-reading-to-help-you-keep-your-trading-profits). Read the published transcript's setup, resistance/selling, reset, and final low-break review sections. The example is ABNB near its IPO, intraday, with a 15-minute context and tape observations. Full-video viewing, reliable transcript timecodes, and current view counts are not claimed.

The speakers distinguish a trade needing reassessment from the later point where the setup is plainly broken; they discuss removing risk and potentially re-entering. This is a retrospective desk review, not audited strategy performance. **Internal implication:** logging admission/reset decisions is useful, but tape selling, rebids and discretionary re-entry cannot be inferred from OHLC. The reference already motivated the rejected bar-exit branch; it cannot justify repeating that branch or importing partial-sizing rules.

### S8 — Better System Trader episode 124, Managing Trades with Linda Raschke, 1 October 2017

[Publisher episode page](https://bettersystemtrader.com/124-managing-trades-with-linda-raschke/). Read the currently published breakdown of exit modeling, concentration of gains, and market-state differences. The page is publisher text accompanying video, not a verified verbatim full transcript. Markets are broad futures/equity discussions; no single ZEL-equivalent TF or ledger.

It separates fixed-distance, time, and trailing exits and emphasizes that winners cannot be known in advance. **Internal implication:** keep one repair axis and preserve the current entry/stop/exit/cost baseline. Do not transplant its illustrative ATR/time parameters or use final MFE/PnL as a decision input. The material is not evidence that a new K126 adapter improves anything.

## Native contract and what is actually observable

Reviewed `backend/research/rebuild/scalp7_positive_lanes_v2.py::_hg_event`, the frozen `NATIVE_HANDOFF_ADAPTER.py::_fresh_touch_successor`, and the supplied `native_trace.py` **as text only**. C does not execute the supplied source replay harness.

| Native behavior | Source correspondence | Required observation / limitation |
|---|---|---|
| Strong row, stage0, EMA touch initializes both extrema | Broadly matches pullback sequence | Record actual touch row and its information-available time, independently from equal-price history |
| Strong stage1 rows update pull extrema before checking turn | Internal mechanical swing definition | Record each strictly changing extreme's origin; an equal price does not replace origin |
| A weak row can leave stage1 and extrema unchanged; a deeper native reset clears state | Falling strength during pullback is not automatically source-invalid | Distinguish held state from reset, and record skipped weak-row extrema; do not invent a continuous all-bar swing |
| A native event is generated before regime eligibility | ZEL-specific, no original-author equivalent | Record native after-state and caller after-state separately |
| In-window regime-ineligible event has `episode_traded` released without event reset | ZEL-specific lifetime choice, not an established stale-state bug | Observe whether its touch/extreme later feeds an accepted trade |
| Explicit verified admission rejection invokes the rejection reset policy | ZEL-specific execution contract | Preserve decision timestamp and later strictly new touch; UNKNOWN admission is not a rejection |
| Accepted event consumes episode; strong new high/low re-arms it | Mechanical re-arm rather than source-exact discretionary behavior | Record re-arm as its own row; do not claim same-bar new touch |

The saved126 trade/path files do not contain the full enriched pre-entry stream plus exact native and caller post-admission transitions. Therefore they cannot identify which retention route created each accepted reference. A latest matching raw high/low is neither a touch event nor proof of an unbroken state lineage. An observer can close this gap when A executes the pinned source-state pass once, under A's existing capacity and authority. It cannot close it by relabeling a saved price match.

## Single-axis hypothesis boundary

The sole prepared candidate, `scalp7_k126_known_regime_veto_fresh_touch_v1`, is an `INTERNAL_HYPOTHESIS`, not a verified source rule or bug fix. A **known regime-ineligible completed native turn** ends the current untraded setup; a subsequent EMA touch is required before another turn can be admitted. UNKNOWN/UNBOUND is missing evidence and does not trigger expiry. No cited author mandates this regime reset. The trigger is the native turn plus the contemporaneous known ineligible regime; it is not elapsed age, high risk/ATR, low final MFE, outcome, symbol, date, or a prior-ADX witness. It is also not an exit of an already-held trade.

This source review alone does not establish that such events occurred before the worst four scratches or that resetting them improves Net/streaks. The adapter is justified for a test by code/fixture evidence that this retention transition is reachable, with disabled parity; that is not evidence of its frequency in the actual126 or of economic benefit. A must compare complete chronology, removed/added opportunities, and lost recovery winners before an economic judgment. Until the missing transition fields are observed, causal attribution and economic promotion stay deferred, while the observer and single synthetic-tested adapter remain executable deliverables. A normal recovery winner can legitimately arise after the same veto, so the reset has a real false-positive risk.

Counterexamples required by the evidence are: broad-risk eventual winner; initial adverse move then recovery; normal pullback after strong motion; hard-reset versus retained state; next-open gap; stop-first; and simultaneous timestamp ordering. Event-time knowledge governs execution. Final PnL/MFE and the worst8 membership remain diagnostic labels only.
