# Top5 external evidence: measured outcomes

Four new development children were measured once after preregistration. All four failed the unchanged development economics gate. The exact PR1180 Break child completed its one separately authorized validation comparison and failed. No candidate was promoted.

Gemini direct-video execution is **NOT_RUN**: this executor has no Gemini key and the connected GitHub toolset has no workflow_dispatch action. New paid requests = 0, billed API cost for this task = 0. Existing legacy Gemini cache is not counted as a fresh review. Public primary sources and one actual YouTube transcript informed the hypotheses; that does not fulfill the requested new Gemini video analysis.

## Source to implemented rule

| Lane | Actual parent / new child suffix | Evidence → change | Measured conclusion |
|---|---|---|---|
| TrendRider Primary | `trend_rider_primary_wr8125_native_policy` / `__dmi_direction_fade_veto_v1` | TV_ADX, TV_DMI, TA_LIB_ADX, DARWINEX_VIDEO: Veto only prior side-aligned DMI with non-rising ADX. Preserve opposite-DMI transition and rising-strength signals. | DEV_REJECT |
| TrendRider Broad | `trend_rider_broad_wr7000_native_policy` / `__dmi_direction_fade_veto_v1` | TV_ADX, TV_DMI, TA_LIB_ADX, DARWINEX_VIDEO: Same hypothesis on Broad native parent; correlated with Primary, not independent evidence. | DEV_REJECT |
| Break | Frozen V2 50-bar/volume long 4h hold6 / existing `__break_prior_direction_v1` | Prior green bar rule unchanged. AQR long-horizon momentum is only a broad rationale, not exact 4h proof. | VALIDATION_REJECT; original DEV_PROMISING receipt retained. |
| Keltner | `keltner_replacement_trend_pull_long_4h_h12_v2` / `__prior_atr_bull_context_v1` | TV_ST, TV_KC, DARWINEX_VIDEO: Admit EMA reclaim only in previous closed ATR10x3 bull state; reversal winners may be lost. | DEV_REJECT |
| Supertrend | `supertrend_replacement_highvol_mom_long_4h_h12_v2` / `__rising_strength_context_v1` | TV_ADX, TV_DMI, BOLLINGER_RULES: Require closed-signal ADX14 rising; preserve native high-volume momentum and hold12; early reversals can be lost. | DEV_REJECT |

[Wilder/ADX documentation](https://www.tradingview.com/support/solutions/43000589099-average-directional-index-adx/) separates strength from direction. [ATR-state recurrence](https://www.tradingview.com/support/solutions/43000634738-supertrend/) supplied the added Keltner context. The native V2 Keltner remains an EMA reclaim, and V2 Supertrend remains high-volume momentum; their names do not establish formula parity. [Darwinex](https://www.youtube.com/watch?v=5jG25OIHM5k), transcript 1:54–2:19, motivated separating persistent context from a trigger. Its generic higher-timeframe alignment idea was contradicted by the parent diagnosis and not implemented.

## Parent → child economics

E is net expectancy in bps per completed modelled trade. PF, win rate and payoff use net results. The first, second, fourth and fifth rows reuse the same 375-day development data. Break uses only the distinct 120.67-day validation window, with past data for indicator warmup. No purged OOS price was decoded.

| Lane | Trades / signals | E | PF | Win rate | Payoff | Avg win / loss bps | Cost×2 E |
|---|---|---|---|---|---|---|---|
| TrendRider Primary | 412→363 / 1555→1555 | -28.35 → -19.45 | 0.744 → 0.819 | 23.54 → 23.69% | 2.417 → 2.638 | 350.2/-144.9 → 371.9/-140.9 | -48.35 → -39.45 |
| TrendRider Broad | 457→413 / 3386→3386 | -31.67 → -18.66 | 0.720 → 0.829 | 22.32 → 23.24% | 2.506 → 2.738 | 364.6/-145.5 → 389.7/-142.3 | -51.67 → -38.66 |
| Break & Continue (validation) | 55→50 / 79→79 | -81.84 → -65.74 | 0.592 → 0.655 | 30.91 → 34.00% | 1.323 → 1.271 | 383.6/-290.1 → 366.5/-288.4 | -102.05 → -85.93 |
| Keltner | 217→160 / 379→379 | -2.92 → -12.85 | 0.987 → 0.940 | 47.47 → 46.88% | 1.092 → 1.066 | 451.7/-413.7 → 432.0/-405.4 | -24.22 → -34.11 |
| Supertrend | 243→188 / 493→493 | -22.85 → -12.49 | 0.906 → 0.950 | 43.62 → 44.15% | 1.171 → 1.201 | 507.1/-432.9 → 534.4/-444.8 | -44.19 → -33.81 |

## Exact trade attribution

Common trades retain identical native fill geometry and cost. Entry vetoes can free the original ownership/cooldown state and create new later trades; those are measured, not assumed to be a subset. Amounts below are sums of equal-notional trade bps, **not account returns or dollars**.

| Lane | Common | Avoided losses: T / bps | Missed winners: T / bps | New trades: T / net bps | Net difference | Winner count / amount retained |
|---|---|---|---|---|---|---|
| TrendRider Primary | 275 | 108 / 15645.2 | 29 / 7809.0 | 88 / -3219.4 | +4616.9 | 70.1% / 77.0% |
| TrendRider Broad | 307 | 119 / 17198.8 | 31 / 8695.9 | 106 / -1739.2 | +6763.8 | 69.6% / 76.6% |
| Break & Continue (validation) | 48 | 6 / 1690.0 | 1 / 293.2 | 2 / -182.4 | +1214.5 | 94.1% / 95.5% |
| Keltner | 157 | 32 / 14222.3 | 28 / 14122.2 | 3 / -1521.3 | -1421.1 | 72.8% / 69.6% |
| Supertrend | 157 | 49 / 21157.7 | 37 / 14770.2 | 31 / -3182.9 | +3204.5 | 65.1% / 72.5% |

## Streaks, exposure and uncertainty

Streaks group simultaneous closes; maximum streak loss is per symbol. Drawdown is cumulative closed-trade bps, not intratrade/account drawdown. Recovery reports completed recoveries and the still-open underwater interval separately. Weekly paired bootstrap uses 1,000 fixed-seed resamples; adaptive development reuse and correlated Primary/Broad populations prevent a formal significance claim.

| Lane | Max streak loss bps | Closed DD bps | Longest completed recovery days | Unrecovered days at end | Trades/day | Exposure symbol-days | Child−parent E 95% interval |
|---|---|---|---|---|---|---|---|
| TrendRider Primary | 2877.4 → 2593.7 | 11771.4 → 9969.3 | 0.0 → 0.0 | 375.0 → 375.0 | 1.099 → 0.968 | 387.0 → 340.9 | [-1.38, 21.29] |
| TrendRider Broad | 3870.8 → 3481.9 | 14471.8 → 10408.0 | 0.0 → 0.0 | 375.0 → 375.0 | 1.219 → 1.101 | 418.7 → 384.7 | [0.15, 27.15] |
| Break & Continue (validation) | 2988.5 → 2870.8 | 7091.7 → 6541.2 | 21.2 → 21.2 | 95.2 → 95.2 | 0.456 → 0.414 | 55.0 → 50.0 | [-10.24, 45.79] |
| Keltner | 4340.1 → 3685.3 | 16093.1 → 9534.2 | 50.7 → 95.2 | 101.3 → 100.5 | 0.579 → 0.427 | 434.0 → 320.0 | [-70.94, 54.30] |
| Supertrend | 4536.4 → 5503.3 | 12722.6 → 14155.2 | 126.3 → 90.2 | 232.0 → 219.2 | 0.648 → 0.501 | 486.0 → 376.0 | [-40.59, 64.99] |

## Baselines and controls

The frozen parent is the full feature ablation. A fixed-hash, completed-count-matched parent subset controls simple activity reduction; its exposure is reported separately and is not claimed to match exactly. Cash/no-trade net is zero. No outcome-selected control or threshold sweep was run.

| Lane | Parent E | Count-matched control E | Child E − control E | Child cost×2 net bps |
|---|---|---|---|---|
| TrendRider Primary | -28.35 | -31.70 | +12.25 | -14321.51 |
| TrendRider Broad | -31.67 | -32.37 | +13.71 | -15968.00 |
| Break & Continue (validation) | -81.84 | -64.89 | -0.84 | -4296.55 |
| Keltner | -2.92 | 58.19 | -71.03 | -5457.17 |
| Supertrend | -22.85 | -20.35 | +7.86 | -6356.62 |

## What was learned

- Primary/Broad: fading-direction veto avoided substantial old losses but removed 29/31 winners and admitted 88/106 new trades with negative aggregate PnL. Improvement did not create positive expectancy. Earlier failed children remain in the attribution ledger; neither is silently promoted.
- Keltner: avoided losses and lost winner profit almost cancelled; three new trades added about −1,521 bps. Lower closed drawdown did not rescue negative economics.
- Supertrend: ADX slope reduced aggregate losses but lost 37 winners and increased closed drawdown. The new-trade population lost about −3,183 bps.
- Break: the exact child retained 94.1% of validation parent winners, yet both parent and child lost money. Validation reject is preserved; OOS remains untouched.

The full loss map includes per-symbol streaks, UTC week clusters, top-decile winner concentration, and MFE-bound loss counts. Native exit bars can contain price movement after an intrabar stop: MFE is a diagnostic bound, never an entry or G6 exit rule. Fixed hash-selected charts show one loss-streak, win-streak and ordinary case per lane with the same 20-before/60-after window.

## Reproduction and authority

- Four-lane result: `54df1a3e7550f5626a880b0cb9867bde5dcafc118a6ec210ab445ea1bcc6fefd`.
- Break validation result: `4bdeedba53ea39153785e9e4e21330dfccff288db5502c39567d2d922f178294`.
- Development data: `cdefd32fa0f02fefb50a6f675f1d04c425c25fe23579ea97c443abe5d8e4484d`; bound cost: `4a031ed24544543ffae61ab080137ddbbb5e074e4e200ada9de3b48140ca2333`.
- Data owner ref and exact code/config manifests are frozen in the contracts. Costs retain the existing 20bps floor and symbol funding/spread/impact model; no cost reduction was used. Production trade-time lineage remains unproven, formal production credit = 0.
- Selection=false; promotion=false; execution=NONE; order/live=BLOCKED; exchange orders=false. G5B collector, open intents, boundaries, locked results and original MA001/STAPC001 rejects are unchanged.
- Requested next Gemini review requires the existing approved manual execution capability. The structured request and actual-request audit are ready; push cannot start these paid calls. New video results would require a new separately registered hypothesis, not relabel this completed batch.
- All five strategy lanes remain research scope. No current child qualifies for further OOS or prospective promotion.

See `external_evidence.json`, `comparison/receipt.json`, `charts/cases.json`, `research_registry.json`, and the isolated Break receipt for exact values and source limits.
