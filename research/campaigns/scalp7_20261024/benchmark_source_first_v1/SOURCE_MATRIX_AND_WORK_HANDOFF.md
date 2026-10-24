# ZEL source-first benchmark execution matrix — 2026-10-24

Repository: leegkssk2000-commits/vultr-z
Authority: A sole economic FULL owner=CLOUD_WORK_COORDINATOR_ISSUE1358_V1; global-heavy <=1.
No real orders, Paper/Live, G5 new credit, credential changes, copied long-running data writer or market API spend in this matrix.

## Selection protocol (not generic research)
1. Find **source-primary** method (original trader, author manual, original video timestamp, reference code), and record the exact rule versus our translation.
2. Before any outcome, check duplicate identities/rejected mechanism and whether an existing *verified* source price/time/cost stream is sufficient.
3. Freeze exactly one version at a commit with all calculation windows, entry, exit, end/censor, same-time tie, modeled fee1x and 2x.
4. Implement only this version; no parameter grid. At least 8 focused negative/as-of/cost tests; same opportunity/order chronology, source SHA and timestamp.
5. Run a cheap isolated MODELLED historical developer result (not OOS claim). Report T/day, Net1x, Net2x, PF, WR, trade-bps DD, loss streak, fat-tail winners preserved, child-only/skipped, forward partition and capital collision.
6. Retire negative cost2 or catastrophic winner destruction immediately. Only a source-ready, independently cost-positive candidate may be handed to A for regular authorized economic evaluation. Fresh G5/A/B remains independently gated.

## Actually completed — benchmark 01: Kaufman KAMA price-only 1h
Original formula: [StockCharts KAMA](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama), [QuantConnect KAMA reference](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/kaufman-adaptive-moving-average).
YouTube [Ali Casey | StatOasis — Kaufman Adaptive Moving Average Settings](https://www.youtube.com/watch?v=qpLZl_WU4cI): 05:48 strategy design, 07:03 KAMA/EMA comparison, 08:20 data mining warning (video lesson, NOT source of profit).
PRE-RESULT FREEZE commit `77eabc0a779bf9f6a6a1e55f5b76d8d7c573af38`.
6 symbols BTC ETH SOL XRP LINK DOGE, modelled 1h next-open long/cash. KAMA fast(10,2,30), slow(10,5,30) rising + completed price cross, exiting on fast KAMA break/slow downturn. Original prices from certified old public BingX source 2026-02-14..Aug30; first240h indicator-only. 20/40bps modeled roundtrip, actual fee/funding/unseen reception timestamp unavailable, 6 simultaneous candidates possible. This is NOT independent untouched OOS or account NAV.
Code [SCREEN.py](https://github.com/leegkssk2000-commits/vultr-z/blob/32e8b3996e43d2c71ae284e3d286232d5209179c/research/campaigns/scalp7_20261024/benchmark_kama_source_first_v1/SCREEN.py), 10 synthetic PASS.
[Result](https://github.com/leegkssk2000-commits/vultr-z/blob/86231ebb2bf68cf75e7e67fadb4b5381c5e690ea/research/campaigns/scalp7_20261024/benchmark_kama_source_first_v1/RESULT_SUMMARY.json) old ledger SHA256 `0f7c89c82ba0ff43aab4655129539c68b2ec17fa588be3d585a6953484cf34b3`.
TRAIN Mar05-Jun01: KAMA 427T Net2 -18803.63 trade-bps PF.433 maxloss25 T/day4.85.
VAL Jun01-Aug30: KAMA 431T Net1 +2737.28; **Net2 -5882.72** PF.821 maxloss36 T/day4.79.
**REJECT** (positive trading frequency does not mean after-cost profit). No symbols/parameters selected from observed validation.

## Actually completed — benchmark 02: Adam Grimes first pullback after channel thrust
Original [Adam Grimes Pullback article](https://www.adamhgrimes.com/pullback-trade-works/), [2014 video blog](https://adamhgrimes.com/trading-pullbacks/), [setup context](https://adamhgrimes.com/context-in-pullbacks-what-should-happen/).
Author discusses first thrust/channel → pullback to moving average → trend resumption, *not* exact numeric EMA20/50/20channel/8+8-bar code. Those are **ZEL authored quantifications**, documented ahead of metrics.
PRE-RESULT FREEZE commit `6b3a90406f5a8510c57df27f9f0776f15905ce57`. Same fixed 6 old-DEV symbols and 1h data, no unseen OOS, 20/40bps. Comparator identical trend+exit but immediate thrust entry; new child waits for first EMA20 pullback and confirmed recovery next-open.
Code [SCREEN.py](https://github.com/leegkssk2000-commits/vultr-z/blob/6d9b0c13c719802a061be0b621d80f69023f691e/research/campaigns/scalp7_20261024/benchmark_grimes_first_pullback_v1/SCREEN.py), 10 synthetic PASS.
[Result](https://github.com/leegkssk2000-commits/vultr-z/blob/01bd4717584c30409f5dabc4d76d3aa17b265341/research/campaigns/scalp7_20261024/benchmark_grimes_first_pullback_v1/RESULT_SUMMARY.json) local full SHA256 `0e44b205b6a15baefe0bb4087fd79d8eec39959175bece3a98867c20100a469a`.
TRAIN: comparator169T Net2 -13710.08, first-pullback53T Net2 -3598.96.
VAL: comparator157T Net2 +6436.13 PF1.472, first-pullback50T Net2 -2754.69 PF.366.
**REJECT** first-pullback quantification (also rejects blindly chasing comparator as train deeply negative). No after-the-fact symbol filters.

## Priority next candidate — Raschke original Holy Grail ADX/EMA, NOT yet newly executed
Original trader [Linda Raschke March 2004 interview, p.78 verified](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf), an author-derived [exact Holy Grail rule reference](https://algolang.io/docs/reference/indicators/trend-and-regime/), and [Daryl Guppy original GMMA](https://www.guppytraders.com/gmma-info).
Source principle ADX(14)>30 and rising -> first EMA20 retracement -> previous high buy trigger, swing low risk control and preceding swing high retest. Do not conflate with a bare EMA cross or Grimes quantification.
Existing legacy *mixed LONG/SHORT* `/home/z/z/runtime/benchmark_web_holygrail_rearm_v9.json`: historical 57T Net1+4993.48 trade-bps/PF2.658, train34/holdout23 both positive at the then-modeled cost. **NOT validated Net2/long-only/live/OOS**, and older data already consumed. Last direct reaggregation attempt had tool permission refusal. Do NOT use alternate invocation to bypass refusal, do NOT automatically promote. E source task must retrieve the actual exact original rule and first permitted source-ready independent clean data corpus; any new child rule freeze before results and D tests only if permitted under existing access.

## G5 portfolio source audit — Robert Carver (not a new positive standalone strategy)
YouTube [Robert Carver podcast (Zerodha) 2026](https://www.youtube.com/watch?v=p0znNV4oWe8): 22:10 breakout vs moving averages; 40:05 optimization; 49:29 live vs backtest; 52:37 DD; 1:13:34 diversification.
Original code [Rob Carver systematictradingexamples/tradingrules.py](https://github.com/robcarver17/systematictradingexamples/blob/master/tradingrules.py). Adopt VOL-ADJUSTED RISK/FORECAST discipline as a read-only account exposure lens, not another claimed independent alpha. Explicitly test co-open/overlap, normal and fat-tail win dependency, account-like capital allocation with *actual* notional only where source supports it; no invented account NAV/fee/funding.
Lookahead check [Freqtrade official lookahead-analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/). Never leak whole-frame future; store prefix invariance tests.

## Parallel Work contracts
**A (existing)**: authenticated official Squeeze signal-low single approved FULL only, check present claim/slot/consumption. Only A may undertake new official costed heavy.
**B (existing)**: exact K117 prospective default-OFF Shadow integration and source unit/PREAUTO read-only gates, do not share or restart B writer.
**C (existing)**: frozen Supertrend4h H12 control. Stage4 EMA extension and 2close child now REJECTED from two actually executed old-DEV 4/7 source experiments (issue1358 #6380197774, #6380288200). Keep 27 G5 prospective model outcome separate. Focus evidence on NEW untouched 7/7 source/true asof, and distinct original entry-quality mechanism if available; if not available, do not spin repeated H12 parameter tune.
**D (existing)**: this KAMA/Grimes sourced screen is ALREADY CONSUMED; do not repeat. Next one new mechanism only after E gives exact author, nonduplicated source, input SHA and no security refusal; do cost1x/2x original before economic A handoff.
**G5 (existing)**: certified lane-local economic accounting and K117/Supertrend cross-strategy shared capital exposure, no second economic owner and no new G5 PASS.
**E (optional 1 new light Work)**: ONLY primary video/code evidence and exact mapping, NOT another strategy research factory. Every author claim -> timecoded primary video/technical formula/source code -> native price/execution assumption -> first original source SHA and negative fixtures, propose MAX 2 executable candidates. Zero economic FULL, Orders, API spend, collector duplication, GitHub owner mutation. First source Raschke/Guppy exact ADX pullback; second one *different, not rejected or duplicate*. Deliver `SOURCE_TO_RULE.md` with executable native entry/exit/original-author vs ZEL assumptions and data coverage. If no original code or data trace, reject and find next source.
