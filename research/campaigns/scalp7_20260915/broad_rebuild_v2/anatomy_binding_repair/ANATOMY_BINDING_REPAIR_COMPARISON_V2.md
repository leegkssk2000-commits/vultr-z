# Rebuilt-lane candle anatomy from repaired saved ledgers

Only `results_binding_repair` was read. No economic replay, historical retune, promotion, or live/order action was performed. Validation and rolling remain separate. All three rebuilt children are still net-negative in the saved economic results.

Six identities produced 12 SVG panels and six JSON artifacts. Each identity and partition has two chronological examples for winner, loss, immediate fail, top-decile positive winner, and MFE giveback: 120 category placements covering 107 unique trades. Each displayed window contains eight bars before the signal, the signal bar, and twelve bars after it. Categories overlap; selected examples are illustrative, not a statistical sample.

| Partition | Lane | T control → child | Win % control → child | Immediate fail % control → child | MFE giveback % control → child |
|---|---|---:|---:|---:|---:|
| validation | Rider 15m | 952 → 612 | 25.00 → 22.22 | 31.72 → 18.95 | 16.18 → 23.69 |
| validation | Break 15m | 301 → 106 | 27.57 → 32.08 | 49.17 → 16.98 | 12.62 → 22.64 |
| validation | Supertrend 30m | 526 → 241 | 27.38 → 31.95 | 33.27 → 10.37 | 12.36 → 14.52 |
| rolling | Rider 15m | 6968 → 4358 | 27.10 → 22.28 | 27.84 → 16.98 | 15.54 → 23.84 |
| rolling | Break 15m | 2369 → 871 | 25.58 → 25.95 | 52.05 → 16.76 | 11.95 → 20.67 |
| rolling | Supertrend 30m | 3951 → 1886 | 30.19 → 36.80 | 29.06 → 5.83 | 14.73 → 9.38 |

Immediate fail means saved net < 0 and hold ≤ 2 bars; MFE giveback means saved conservative MFE ≥ 1R and net ≤ 0. Percentages use all included trades in the same identity and partition. Fat winners are the top ceil(10% of positive trades), selected independently within each identity and partition.

All three children reduce the proportion of saved losing trades held at most two bars in validation and rolling, while all three also reduce trade count. This is an outcome description, not a causal effect estimate or economic promotion.
Rider rolling immediate-fail share falls 27.84% to 16.98%, but giveback share rises 15.54% to 23.84% and win share falls 27.10% to 22.28%. Validation shows the same directions. The rebuilt sequence changes the failure timing without establishing positive edge.
Break rolling immediate-fail share falls 52.05% to 16.76%, while giveback share rises 11.95% to 20.67%; validation also shows fewer immediate failures and more givebacks. Rolling child winner/loss signal close-location medians are 0.7788/0.8000, so a universally stronger-close interpretation is unsupported.
Supertrend rolling immediate-fail share falls 29.06% to 5.83%, giveback falls 14.73% to 9.38%, and win share rises 30.19% to 36.80%, but T falls 3951 to 1886. Validation giveback moves the opposite way, 12.36% to 14.52%. The saved child remains economically negative; this evidence does not establish robust portfolio edge.
The three rolling child winner/loss body-fraction medians remain close: Rider 0.6737/0.6588, Break 0.6303/0.6087, Supertrend 0.6463/0.6392. Medians alone do not quantify distribution overlap; no new threshold or filter is selected from these labels.
Break child fat-winner signal range/ATR14 median is 1.7275 in rolling but 0.8607 in validation; the latter category has only four trades. This reversal is reported descriptively and is not used to choose a volatility threshold.

Actual candle examples (first chronological rolling example in its category):

- Break control, XRP long, signal close 2.0622: the next candle opens 2.0622, cannot print above that open, falls to 2.0570, and closes 2.0584. The saved trade stops on its first held bar.
- Break child, LINK long: the preceding two candles close at 14.083 and 14.087, followed by a signal close at 14.123, near the signal high of 14.131. The next bar falls to 14.026 and closes 14.047, stopping the trade; the following bars reclaim 14.113 then 14.185. The strong signal close itself does not prevent local shakeout.
- Break child, SOL long giveback: signal high 147.496 and close 146.572, followed by an initial close at 147.283, then 146.725 and 146.457. The saved trade later exits on anchored-breakout-level loss after 15 bars, with MFE 1.7517R and negative net. Its full exit occurs beyond the twelve-bar display and is explicitly flagged.
- Supertrend child, SOL long immediate failure: signal close 143.092 is almost its high 143.094. The next candle reaches 143.766 but closes 141.966; the second falls to 141.119 and the saved trade stops. A near-high signal close also appears in failure examples.
- Supertrend child, LINK short giveback: signal close 13.907 is followed by closes 13.772 and 13.753, then 13.830 and 13.844. The saved trade reaches 1.6607R before stopping with negative net after 14 bars.
- Rider child, ETH short immediate failure: signal close 3098.04 is followed by closes 3100.06 and 3107.94, then 3113.27. The saved structural stop occurs on the second held bar.

All exact OHLCV, segment/availability clocks, saved trade outcomes, category counts, and numerical feature medians are in the JSON artifacts; SVGs mark signal zero and shade future bars. Entry features never use those future bars. Missing source slots remain explicit gaps, with no synthetic OHLCV fill.

[Cohort manifest](ANATOMY_BINDING_REPAIR_COHORT_V2.json) · [Machine-readable comparison](ANATOMY_BINDING_REPAIR_COMPARISON_V2.json)

- `scalp7_trend_rider_opportunity_control_15m_v2`: [JSON](scalp7_trend_rider_opportunity_control_15m_v2.anatomy.json), [validation candles](scalp7_trend_rider_opportunity_control_15m_v2.validation.svg), [rolling candles](scalp7_trend_rider_opportunity_control_15m_v2.rolling.svg)

- `scalp7_break_and_continue_opportunity_control_15m_v2`: [JSON](scalp7_break_and_continue_opportunity_control_15m_v2.anatomy.json), [validation candles](scalp7_break_and_continue_opportunity_control_15m_v2.validation.svg), [rolling candles](scalp7_break_and_continue_opportunity_control_15m_v2.rolling.svg)

- `scalp7_supertrend_pullback_opportunity_control_30m_v2`: [JSON](scalp7_supertrend_pullback_opportunity_control_30m_v2.anatomy.json), [validation candles](scalp7_supertrend_pullback_opportunity_control_30m_v2.validation.svg), [rolling candles](scalp7_supertrend_pullback_opportunity_control_30m_v2.rolling.svg)

- `scalp7_rider_15m_impulse_pullback_reclaim_v2`: [JSON](scalp7_rider_15m_impulse_pullback_reclaim_v2.anatomy.json), [validation candles](scalp7_rider_15m_impulse_pullback_reclaim_v2.validation.svg), [rolling candles](scalp7_rider_15m_impulse_pullback_reclaim_v2.rolling.svg)

- `scalp7_break_15m_anchored_retest_reclaim_v2`: [JSON](scalp7_break_15m_anchored_retest_reclaim_v2.anatomy.json), [validation candles](scalp7_break_15m_anchored_retest_reclaim_v2.validation.svg), [rolling candles](scalp7_break_15m_anchored_retest_reclaim_v2.rolling.svg)

- `scalp7_supertrend_native_impulse_pullback_30m_v2`: [JSON](scalp7_supertrend_native_impulse_pullback_30m_v2.anatomy.json), [validation candles](scalp7_supertrend_native_impulse_pullback_30m_v2.validation.svg), [rolling candles](scalp7_supertrend_native_impulse_pullback_30m_v2.rolling.svg)
