# Two distinct Top5 DEV experiments — actual results

Keltner removes only EMA20>EMA50. Supertrend retains origin signals and delays entry one 4h bar. No new indicator/exit sweep. Prior 18 applications preserved; two allocated applications consumed, cumulative 20; new allocation remaining=0.

All monetary figures are modeled equal-notional trade bps, not account returns. Fixed-origin timing comparisons may overlap and are not a portfolio. Shared chronological replay determines the economic decision.

| Lane | Variant | T | Net E bps | PF | Payoff | Cost2 E bps | Trades/day | Exposure symbol-days | Max grouped loss-run bps |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| keltner_trend_main | parent | 217 | -2.9223 | 0.9866 | 1.0919 | -24.2163 | 0.5787 | 434.0000 | 7709.3138 |
| keltner_trend_main | fixed_origin_child | 217 | -2.9223 | 0.9866 | 1.0919 | -24.2163 | 0.5787 | 434.0000 | 7709.3138 |
| keltner_trend_main | child | 517 | -10.5920 | 0.9557 | 1.0287 | -32.0587 | 1.3787 | 1034.0000 | 9507.1872 |

keltner_trend_main: **DEV_REJECT**. Failed checks: positive_expectancy, PF_above_one, positive_cost2x, positive_increment, no_exposure_increase

| supertrend_pullback_main | parent | 243 | -22.8509 | 0.9064 | 1.1714 | -44.1899 | 0.6480 | 486.0000 | 4456.3242 |
| supertrend_pullback_main | fixed_origin_child | 243 | -9.5651 | 0.9610 | 1.1240 | -30.9040 | 0.6480 | 486.0000 | 6121.4268 |
| supertrend_pullback_main | child | 241 | -11.4846 | 0.9535 | 1.0801 | -32.8025 | 0.6427 | 482.0000 | 6121.4268 |

supertrend_pullback_main: **DEV_REJECT**. Failed checks: positive_expectancy, PF_above_one, positive_cost2x


## Attribution, profit preservation and uncertainty

| Lane | Comparison | Shared / removed / new | Shared net delta | Removed parent net | New net | Net delta | Winner profit retained | Top-decile winner profit retained |
|---|---|---|---:|---:|---:|---:|---:|---:|
| keltner_trend_main | fixed_origin_child | 217 / 0 / 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| keltner_trend_main | child | 209 / 8 / 308 | 0.0000 | 1337.7665 | -3504.1557 | -4841.9222 | 0.9574 | 1.0000 |

keltner_trend_main child-minus-parent paired weekly 95% interval (bps/trade): [-97.76966053132031, 78.11947665768345]
Same-signal fixed-origin comparison is distinct from changed-price entry execution. Source keys match original signal time, not entry time.

| supertrend_pullback_main | fixed_origin_child | 243 / 0 / 0 | 3228.4615 | 0.0000 | 0.0000 | 3228.4615 | 0.8290 | 0.8999 |
| supertrend_pullback_main | child | 231 / 12 / 10 | 2300.9250 | 928.4719 | 1412.5415 | 2784.9946 | 0.7687 | 0.8374 |

supertrend_pullback_main child-minus-parent paired weekly 95% interval (bps/trade): [-34.67602324912182, 52.95752329571772]
Same-signal fixed-origin comparison is distinct from changed-price entry execution. Source keys match original signal time, not entry time.


Full gross/net, cost decomposition, common losses, winner-to-loss changes, origin identities, grouped DD/streaks, per-symbol results, tail exclusions and uncertainty are in receipt.json and sealed trade/event ledgers.

Repeated DEV is adaptive evidence, not independent validation. Validation/OOS rows decoded=0. Existing G5B, parents and prior failures preserved. No paid external AI, actual Gemini video input, deployment or trading authority.
