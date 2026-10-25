# Unified TrendRider — one signal-owner and loss-to-win causal bounded recovery (2026-10-25)

**Terminal outcome: HISTORICAL DEV SHOWS A GAIN, BUT ROBUSTNESS FAILS. HOLD, NO SHADOW/G5/PAPER/LIVE PROMOTION.** No new Work, no external feed/API download, no economic heavy FULL, no real orders.

## One strategy, no duplicated economic gain

The previously separate Liquid6 (1h first confirmation long / six liquid symbols) and Delayed Fill (1h one-bar delayed long / 12 symbols) share **97 of the original Liquid6 119 exact symbol+side+signal timestamp keys**. Unified owner: Liquid6 owns a shared signal, Delayed contributes only *unshared* candidates. 368 original trade rows -> 97 repeated signals removed -> 4 unsafe Delayed entries (sealed long SL >= actual entry) rejected -> **267 valid distinct source opportunities**.

All valid entries use the same fixed one-third instrument notional risk scaling, max six simultaneous 1/3 slots (two full units), single writer per symbol and two-hour cooldown. Signal tie break is chronological/alphabetical, never chosen by future PnL. Historical native data had already been used in prior development; all 12x1000 source 1h OHLC and the 368 original entry/exit prices are verified in upstream #1465 immutable evidence. There is no new unseen OOS data here.

## Causally frozen stages — no grid searching

S0 baseline original sealed SL or 48h TIMEOUT with unified ownership, no duplicates.

S1 winner extension: at original 48h *completed* TIMEOUT close require original profit >= +1 initial price stop-R, completed close above rising EMA20. Continue max 12 completed hourly bars, stop-first/gap-conservative, previous completed high water trailing stop (minus1.25R), entry+0.5R profit floor, native original cost plus 5bps instrument modeled carry per commenced8h.

S2 large-loss early abort: while original long remains open, after TWO prior completed bearish candles below falling EMA20 and price <= entry-0.5R, close at NEXT real hourly open. Native intrabar stop has strict priority; no seeing future bar high or filling at already observed close.

S3 loss reversal: only after long actually exits at a net cost2 loss and a fully completed bearish EMA20 confirmation, open ONE short at the NEXT hourly open after original long is closed. Initial short stop based on max(last2 completed highs +0.25 ATR14, entry+1.5 ATR14), 24h max with lagged trailing after +1R. Model realistic gap-open stop at worse actual open. No averaged-down long or martingale. Short costs use a conservative public-long proxy plus 5bps/8h modeled carry and original one-third risk scaling; no historical signed SHORT funding or actual execution fill verified.

S4 streak circuit: after three prior fully completed losing opportunities in 36h, pause NEW primary admissions for 6h after last known completion. Previously realized losses remain recorded; this cannot guarantee zero losses or zero consecutive losses.

## Actual modeled stress2x economics (trade-bps SUM, not account equity/NAV return)

| Causal stage | Admitted opportunities | Net2 bps | PF2 | Realized exit-leg DD2 bps | Max consecutive losing opportunities |
|---|---:|---:|---:|---:|---:|
| S0 unified original | 153 | -1,005.27 | 0.862 | 4,575.81 | 32 |
| S1 preserve existing big wins | 144 | -147.12 | 0.978 | 3,901.50 | 30 |
| S2 add early bearish stop | 157 | -1,671.84 | 0.766 | 4,884.42 | 31 |
| S3 add capped reversal short | 138 | -605.61 | 0.925 | 4,285.94 | 20 |
| S4 add 3-loss entry circuit | 121 | **+1,752.48** | **1.294** | **2,225.86** | **14** |

Compared with unified S0, stage4 modeled Net2 increases +2,757.75 trade-bps. This changes economic *ownership and allowed trade sample*: 267 available union opportunities lead to 121 accepted at S4, 146 rejected for concurrent risk, same-symbol ownership or circuit; exactly 24 blocked by loss circuit. Original losses have NOT all been recovered.

Under S4: 71 bounded SHORT legs, 32 model-positive shorts, short leg summed Net2 +668.90bps. **13 previously loss-making baseline opportunities finished net positive**; 8 of those were at least +1R relative to their original LONG price stop risk. Max single modeled SHORT +5.34R, but worst full original-risk-normalized opportunity **-107.27R** occurred because a legacy ETHFI initial stop distance corresponded to only 0.62 normalized bps. Extreme R ratios are unsafe and cannot be interpreted as real account risk controls without a native tick/ATR and cost floor.

## Negative controls: result is NOT economically robust

| Mandatory stress on frozen S4 | Net2 summed trade-bps |
|---|---:|
| S4 exact source modeled cost2 | +1,752.48 |
| +20 instrument bp extra roundtrip on every long/short leg | +472.48 |
| +40 instrument bp extra roundtrip on every long/short leg | **-807.52** |
| Short entry one further closed hour late | +236.84 |
| Exclude 1000PEPE and rerun full admission and circuit logic | **-752.27** |
| No reversal short (same other assumptions) | **-176.83** |
| No early-abort axis (same other assumptions) | **-695.93** |

Source close-month break: September +1,652.56bps; October **+99.92bps** only. Max losing opportunity streak still14. Current positive result depends on the full multi-axis pathway and on precise fill/cost/symbol composition. The same-pool common-trade improvement is NOT the complete overall improvement; new occupancy releases existing saved candidates, and other native signals omitted in the upstream parent receipts cannot be generated. Winner and loser membership cannot be filtered after seeing outcomes.

## Disposition / owner handoff

**C DEVELOPMENT = HOLD_ROBUSTNESS_FAIL**. Freeze and preserve existing two TrendRider baselines plus new single-owner result. Do not copy the source false-named 2 alphas to a live portfolio, expand leverage/size to recoup losses or set profit/promotion credit. The next legitimate step for existing C owner is a new untouched prospectively frozen regime/source with actual funding signed by side, next-open and intrabar stop evidence, +1h delay, realistic ≥40bp additional-cost robustness, stop-distance native minimum, H4 placebos and H5 symbol/regime concentration. If no new unburned data/time is available, HOLD without rerunning known historical data.

Authoritative files in this folder: FREEZE.json (saved before viewing S0-S4), fuse_and_recover.py, test_unified.py, RESULT.json, TRACES.json.gz (separate original+short legs and all rejects), robustness.py, ROBUSTNESS.json, SHA below. Source instrument OHLC and original raw model trade rows are already persisted in adjacent original PR #1465, and intentionally not duplicated in this submission.

## Cryptographic pins
- FREEZE.json = SHA256 30f8d356f8a71fde7deb323a31c4339ed64e729a3623b83c5ba94f945f40431c
- RESULT.json = SHA256 e99bbd783908628572a64875f7d019676fa5d686fdc7e7b29fd24cee2d4fab13
- TRACES.json.gz = SHA256 bc20d7e6b2f931cad8c5cd020fd3b396370dbf80e0bf746dd0fa1330f7e80239
- ROBUSTNESS.json = SHA256 d3f716800de6665df0ce0465776bdb938227cf9803d9f1c1fb279d5ddc494cb3
- fuse_and_recover.py = SHA256 c0c3a4899108508aad0db6c0b21f2d600363a4daf766d0ba7d8891978625e9ad
- robustness.py = SHA256 f8c21eadc02178d910dbad419041bd7e428e558688cf6fba5051859db84f417e
- test_unified.py = SHA256 e1a2cd863a205ed55dfbd296e77a55f1ae6851aafb903d08b18b78484f56944c
- Upstream source MARKET_1H_SNAPSHOT.json.gz = SHA256 16198ac2a3db7849237028a5f5a0100e2033162a9d93b05ad171273215c9a592
