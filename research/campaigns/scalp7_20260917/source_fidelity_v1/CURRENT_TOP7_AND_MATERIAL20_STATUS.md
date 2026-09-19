# Retained current7 and Material20 status

**The retained seven-lane system is not established as profitable.** These are unchanged cached baseline results, not the new source-fidelity candidate results. Equal7 remains Net -4,325.71 bps and adaptive remains Net -5,016.15 bps at1x cost. No new candidate is adopted in this report.

The September19 service witness is separately limited to **2026-09-19T14:18:01.327189Z**. It reports **0 completed fresh trades**. Common forward is HOLD/retry on source-snapshot changes; observed paper has32 open positions,1 pending and0 trades. Micro raw collection is failed; Micro forward is active but waiting for source clock admission. Its131 total signals are **not completed trades**.

Historical tables use rolling245 calendar days, 2026-01-13T00:00:00+00:00 to 2026-09-15T00:00:00+00:00, from genuine12-month source. Initial90-day context and30-day validation are separate. This already inspected history is development evidence, not untouched OOS or fresh. All bps are research trade-notional units, not account returns. Account return and MTM DD are N/A.

The retained primary identities are fixed. SHA256 prefixes below are expanded in [CURRENT_TOP7_AND_MATERIAL20_STATUS.json](CURRENT_TOP7_AND_MATERIAL20_STATUS.json), which also contains every cached window, month, symbol/pair and session metric at1x/2x. New candidate comparisons belong in [ECONOMIC_REPORT.md](ECONOMIC_REPORT.md); none are inferred here.

| Current lane | TF | Retained identity | Code SHA256 prefix | Status |
|---|---|---|---|---|
| Keltner / Holy Grail | 30m | scalp7_keltner_hg_parent_utc30m_v2 | b0919c9e3542 | PRESERVE_FROZEN_PARENT; historical1x/2x positive, fresh unconfirmed |
| Trend Rider | 15m | scalp7_rider_15m_impulse_pullback_reclaim_v2 | 9cdd3b802559 | MAINTAIN_FAIL_FOR_EXECUTED_15M_ADAPTATION; no Core |
| Break / Continue | 15m | scalp7_break_15m_anchored_retest_reclaim_v2 | df1831fb6ad1 | MAINTAIN_FAIL_FOR_LITERAL_15M_ADAPTATION; no Core |
| Supertrend | 30m | scalp7_supertrend_native_impulse_pullback_30m_v2 | aaf91c3e038f | MAINTAIN_FAIL_FOR_EXECUTED_30M_ADAPTATION; native risk component not isolated |
| Squeeze Break | 30m | scalp7_squeeze_panic_cost4_parent_utc30m_v2 | b0919c9e3542 | PRESERVE_FROZEN_PARENT; historical1x/2x positive, sparse and fresh unconfirmed |
| Cross-sectional MR V1 | 30m | mr_cross_sectional_v1_30m_causal_control_v2 | 1674f245d57e | PRESERVE_V1; small positive1x/negative2x, HOLD |
| Micro EDGE | 15m | MICRO_OBSERVED_TRADE_RECLAIM_15M_V2 | 5132e69d2739 | HOLD_SOURCE_EXECUTION; no historical OFI economics or fresh completed trades |

Current7 historical1x economics. Gross/T and cost/T are direct divisions of cached totals. Unresolved is rolling / validation; these are historical window outcomes, not current paper positions.

| Lane | T | T/day | WR% | Gross bps | Gross/T | Cost/T | Net bps | Net/T | PF | Realized DD | MaxLS | ES5 | Worst trade | Hold median/p95 min | Unresolved roll/val | Fresh completed T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|
| Keltner / Holy Grail | 109 | 0.445 | 59.63 | 7,586.95 | 69.61 | 15.04 | 5,947.63 | 54.57 | 2.003 | 1,609.47 | 5 | -289.17 | -366.83 | 180.00 / 750.00 | 0 / 0 | 0 |
| Trend Rider | 4358 | 17.788 | 22.28 | 7,685.01 | 1.76 | 14.97 | -57,549.68 | -13.21 | 0.682 | 58,693.85 | 39 | -142.22 | -305.52 | 135.00 / 540.00 | 21 / 3 | 0 |
| Break / Continue | 871 | 3.555 | 25.95 | -2,007.60 | -2.30 | 14.94 | -15,017.98 | -17.24 | 0.683 | 17,139.63 | 23 | -198.97 | -592.80 | 180.00 / 360.00 | 4 / 0 | 0 |
| Supertrend | 1886 | 7.698 | 36.80 | 10,651.50 | 5.65 | 14.91 | -17,466.56 | -9.26 | 0.850 | 26,233.22 | 21 | -266.18 | -726.25 | 480.00 / 480.00 | 14 / 0 | 0 |
| Squeeze Break | 25 | 0.102 | 48.00 | 1,892.29 | 75.69 | 14.87 | 1,520.49 | 60.82 | 1.912 | 576.67 | 3 | -288.34 | -322.96 | 300.00 / 330.00 | 0 / 0 | 0 |
| Cross-sectional MR V1 | 75 | 0.306 | 56.00 | 1,305.00 | 17.40 | 14.88 | 188.81 | 2.52 | 1.083 | 797.47 | 6 | -237.07 | -321.67 | 240.00 / 240.00 | 2 / 0 | 0 |
| Micro EDGE | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 0 |

Current7 cost2x stress uses the same frozen trades and allocation; it doubles cost debit and does not rerun entries or occupancy. Holding times and historical unresolved counts therefore remain unchanged.

| Lane | T | WR% | Gross/T | Cost/T | Net2x bps | Net2x/T | PF2x | DD2x | MaxLS2x | ES5 2x | Worst trade2x |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Keltner / Holy Grail | 109 | 34.86 | 69.61 | 30.08 | 4,308.32 | 39.53 | 1.624 | 2,019.03 | 11 | -303.87 | -380.85 |
| Trend Rider | 4358 | 18.86 | 1.76 | 29.94 | -122,784.37 | -28.17 | 0.472 | 123,691.43 | 57 | -157.45 | -319.54 |
| Break / Continue | 871 | 23.88 | -2.30 | 29.87 | -28,028.36 | -32.18 | 0.509 | 28,707.07 | 28 | -213.88 | -608.05 |
| Supertrend | 1886 | 33.40 | 5.65 | 29.82 | -45,584.61 | -24.17 | 0.662 | 48,356.11 | 27 | -281.35 | -740.25 |
| Squeeze Break | 25 | 48.00 | 75.69 | 29.74 | 1,148.69 | 45.95 | 1.617 | 609.11 | 3 | -304.55 | -338.67 |
| Cross-sectional MR V1 | 75 | 46.67 | 17.40 | 29.76 | -927.37 | -12.36 | 0.670 | 958.51 | 6 | -251.91 | -336.30 |
| Micro EDGE | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

Concentration shares use sum of positive net trade profits as the denominator. Empty windows are not negative windows. Squeeze has3 positive,2 negative nonempty and4 empty rolling windows.

| Lane | Positive / all windows | Nonempty windows | Largest month share | Largest symbol/pair share | Largest session share | Largest winner share | Losing-trade worst5% mean bps |
|---|---|---:|---:|---:|---:|---:|---:|
| Keltner / Holy Grail | 6 / 9 | 9 | 44.4% | 31.4% | 49.4% | 11.4% | -332.81 |
| Trend Rider | 1 / 9 | 9 | 16.2% | 23.3% | 39.3% | 1.0% | -151.75 |
| Break / Continue | 1 / 9 | 9 | 22.4% | 18.7% | 55.4% | 3.8% | -215.85 |
| Supertrend | 3 / 9 | 9 | 16.2% | 18.8% | 42.9% | 1.4% | -302.98 |
| Squeeze Break | 3 / 9 | 5 | 58.6% | 25.7% | 55.3% | 19.5% | -322.96 |
| Cross-sectional MR V1 | 6 / 9 | 8 | 46.7% | 11.2% | 46.5% | 9.7% | -318.94 |
| Micro EDGE | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

Window cells below are completed T / Net bps at1x; validation stays separate. Full WR/PF/DD/tail/cost2x per window is retained in JSON.

| Lane | Validation30d | Rolling1 | Rolling2 | Rolling3 | Rolling4 | Rolling5 | Rolling6 | Rolling7 | Rolling8 | Rolling9 5d |
|---|---|---|---|---|---|---|---|---|---|---|
| Keltner / Holy Grail | 10 / 752.81 | 27 / 416.36 | 9 / -768.30 | 6 / 174.29 | 3 / 24.23 | 27 / 1,877.23 | 5 / -437.34 | 2 / 5.93 | 27 / 4,810.72 | 3 / -155.50 |
| Trend Rider | 612 / -10,546.81 | 610 / -3,157.53 | 123 / 2,404.88 | 631 / -7,521.63 | 581 / -9,063.09 | 570 / -7,941.54 | 563 / -11,765.16 | 591 / -13,244.22 | 594 / -4,534.79 | 95 / -2,726.59 |
| Break / Continue | 106 / -754.15 | 119 / -379.68 | 95 / 597.55 | 91 / -1,304.10 | 108 / -1,861.92 | 131 / -4,052.18 | 97 / -3,654.81 | 108 / -3,347.30 | 104 / -227.16 | 18 / -788.38 |
| Supertrend | 241 / -5,845.89 | 248 / 1,800.97 | 87 / 1.26 | 236 / -2,030.60 | 257 / -4,281.13 | 260 / -4,197.18 | 261 / -5,755.15 | 236 / -4,807.36 | 259 / 3,234.52 | 42 / -1,431.90 |
| Squeeze Break | 1 / -12.62 | 0 / 0 | 2 / -114.97 | 4 / 16.75 | 0 / 0 | 0 / 0 | 4 / 38.34 | 0 / 0 | 14 / 1,834.07 | 1 / -253.71 |
| Cross-sectional MR V1 | 12 / -545.26 | 15 / -627.09 | 0 / 0 | 6 / 109.58 | 8 / 217.20 | 4 / 4.52 | 8 / 85.66 | 2 / 89.57 | 30 / 318.78 | 2 / -9.42 |
| Micro EDGE | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

Calendar-month cells are T / Net bps at1x within the rolling scope; January and September are partial calendar months.

| Lane | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep |
|---|---|---|---|---|---|---|---|---|---|
| Keltner / Holy Grail | 2 / -191.98 | 32 / 28.05 | 8 / -13.72 | 2 / 22.23 | 5 / -217.81 | 27 / 1,657.70 | 3 / 7.93 | 22 / 4,399.82 | 8 / 255.40 |
| Trend Rider | 401 / -3,716.03 | 287 / 2,498.92 | 450 / -5,226.71 | 602 / -7,918.37 | 557 / -6,995.00 | 571 / -14,128.73 | 593 / -10,129.10 | 618 / -4,901.25 | 279 / -7,033.41 |
| Break / Continue | 77 / 235.25 | 91 / 1,004.05 | 95 / -2,446.51 | 98 / -181.23 | 136 / -3,295.03 | 108 / -4,525.97 | 96 / -3,524.19 | 123 / -1,605.27 | 47 / -679.07 |
| Supertrend | 160 / 2,176.87 | 140 / -1,286.47 | 170 / 1,789.90 | 255 / -6,671.27 | 252 / -5,793.69 | 275 / -4,418.40 | 252 / -3,108.77 | 259 / 606.19 | 123 / -760.92 |
| Squeeze Break | N/A | N/A | 6 / -98.22 | N/A | N/A | 2 / 278.07 | 2 / -239.73 | 11 / 1,345.96 | 4 / 234.41 |
| Cross-sectional MR V1 | 4 / -53.02 | 11 / -574.07 | 4 / 119.71 | 7 / 90.07 | 5 / 68.11 | 8 / 55.04 | 4 / 173.61 | 22 / 559.40 | 10 / -250.03 |
| Micro EDGE | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

Symbol/pair cells preserve the stored grouping. Dynamic MR uses the saved pair strings; no arbitrary split of a pair trade into two independent trades is made.

| Lane | Stored symbol or pair | T | Net bps1x | Positive-profit share |
|---|---|---:|---:|---:|
| Keltner / Holy Grail | BTC-USDT | 10 | -427.66 | 1.4% |
| Keltner / Holy Grail | DOGE-USDT | 20 | 2,083.13 | 25.3% |
| Keltner / Holy Grail | ETH-USDT | 17 | 373.93 | 9.8% |
| Keltner / Holy Grail | LINK-USDT | 21 | 2,891.23 | 31.4% |
| Keltner / Holy Grail | SOL-USDT | 23 | 241.94 | 16.2% |
| Keltner / Holy Grail | XRP-USDT | 18 | 785.06 | 15.9% |
| Trend Rider | BTC-USDT | 732 | -10,477.32 | 11.2% |
| Trend Rider | DOGE-USDT | 766 | -6,121.45 | 23.3% |
| Trend Rider | ETH-USDT | 707 | -12,047.99 | 13.9% |
| Trend Rider | LINK-USDT | 726 | -10,766.41 | 18.2% |
| Trend Rider | SOL-USDT | 722 | -10,697.31 | 16.9% |
| Trend Rider | XRP-USDT | 705 | -7,439.19 | 16.5% |
| Break / Continue | BTC-USDT | 162 | -2,595.84 | 14.7% |
| Break / Continue | DOGE-USDT | 141 | -2,189.45 | 16.5% |
| Break / Continue | ETH-USDT | 131 | -1,078.06 | 18.4% |
| Break / Continue | LINK-USDT | 146 | -2,588.79 | 18.7% |
| Break / Continue | SOL-USDT | 147 | -2,634.20 | 18.6% |
| Break / Continue | XRP-USDT | 144 | -3,931.64 | 13.1% |
| Supertrend | BTC-USDT | 343 | -944.10 | 14.7% |
| Supertrend | DOGE-USDT | 290 | -5,346.55 | 15.4% |
| Supertrend | ETH-USDT | 312 | -1,560.13 | 18.0% |
| Supertrend | LINK-USDT | 285 | -1,638.64 | 17.2% |
| Supertrend | SOL-USDT | 311 | -5,013.47 | 15.9% |
| Supertrend | XRP-USDT | 345 | -2,963.68 | 18.8% |
| Squeeze Break | BTC-USDT | 3 | 17.93 | 2.9% |
| Squeeze Break | DOGE-USDT | 3 | 144.14 | 19.5% |
| Squeeze Break | ETH-USDT | 5 | 173.91 | 15.7% |
| Squeeze Break | LINK-USDT | 5 | 276.17 | 19.7% |
| Squeeze Break | SOL-USDT | 5 | 657.11 | 25.7% |
| Squeeze Break | XRP-USDT | 4 | 251.23 | 16.5% |
| Cross-sectional MR V1 | BTC-USDT / DOGE-USDT | 5 | 218.84 | 8.9% |
| Cross-sectional MR V1 | BTC-USDT / ETH-USDT | 4 | 98.56 | 4.0% |
| Cross-sectional MR V1 | BTC-USDT / LINK-USDT | 1 | -5.04 | 0.0% |
| Cross-sectional MR V1 | BTC-USDT / SOL-USDT | 5 | 33.60 | 6.0% |
| Cross-sectional MR V1 | BTC-USDT / XRP-USDT | 4 | -61.60 | 4.3% |
| Cross-sectional MR V1 | DOGE-USDT / BTC-USDT | 5 | 17.33 | 3.0% |
| Cross-sectional MR V1 | DOGE-USDT / ETH-USDT | 2 | -45.09 | 0.0% |
| Cross-sectional MR V1 | DOGE-USDT / LINK-USDT | 2 | -41.78 | 0.7% |
| Cross-sectional MR V1 | DOGE-USDT / SOL-USDT | 1 | -9.75 | 0.0% |
| Cross-sectional MR V1 | DOGE-USDT / XRP-USDT | 3 | 172.03 | 7.0% |
| Cross-sectional MR V1 | ETH-USDT / BTC-USDT | 1 | 29.20 | 1.2% |
| Cross-sectional MR V1 | ETH-USDT / DOGE-USDT | 1 | 25.12 | 1.0% |
| Cross-sectional MR V1 | ETH-USDT / LINK-USDT | 2 | 183.26 | 7.5% |
| Cross-sectional MR V1 | ETH-USDT / SOL-USDT | 4 | -131.73 | 0.2% |
| Cross-sectional MR V1 | ETH-USDT / XRP-USDT | 5 | -362.54 | 11.2% |
| Cross-sectional MR V1 | LINK-USDT / BTC-USDT | 1 | 95.28 | 3.9% |
| Cross-sectional MR V1 | LINK-USDT / DOGE-USDT | 3 | -196.80 | 1.0% |
| Cross-sectional MR V1 | LINK-USDT / ETH-USDT | 1 | 55.00 | 2.2% |
| Cross-sectional MR V1 | LINK-USDT / XRP-USDT | 2 | 79.29 | 3.5% |
| Cross-sectional MR V1 | SOL-USDT / BTC-USDT | 2 | -111.47 | 0.3% |
| Cross-sectional MR V1 | SOL-USDT / ETH-USDT | 3 | -102.38 | 0.0% |
| Cross-sectional MR V1 | SOL-USDT / LINK-USDT | 2 | -6.36 | 3.0% |
| Cross-sectional MR V1 | SOL-USDT / XRP-USDT | 5 | 23.35 | 8.0% |
| Cross-sectional MR V1 | XRP-USDT / BTC-USDT | 4 | 53.66 | 4.8% |
| Cross-sectional MR V1 | XRP-USDT / DOGE-USDT | 2 | 90.56 | 5.8% |
| Cross-sectional MR V1 | XRP-USDT / ETH-USDT | 1 | -34.76 | 0.0% |
| Cross-sectional MR V1 | XRP-USDT / LINK-USDT | 3 | 58.30 | 9.7% |
| Cross-sectional MR V1 | XRP-USDT / SOL-USDT | 1 | 64.74 | 2.6% |
| Micro EDGE | N/A | N/A | N/A | N/A |

The twenty material grades are unchanged starting records: C4, D8, HOLD8; B0/A0. The1m observer column is a historical projection in R units, not current fresh evidence. Native/state5m columns are separate old donor experiments; no old1m/5m/1h result becomes current15m/30m credit. D/HOLD current fresh counts are N/A because no current per-material observation was bound here.

| Material | Grade | Registry role | Old1m projection T / NetR | Separate5m native T / Net bps | Separate5m state T / Net bps | Cached current30m T / Net bps | Current fresh | Scoped failure / missing evidence |
|---|---|---|---|---|---|---|---|---|
| rbreaker_like | C | entry_quality_material | 4 / -3.37 | See source audit; not rebound here | See source audit; not rebound here | P: 5264 / -87,644.62; round1: 5374 / -90,542.45 | 0 completed; common HOLD | Negative30m rollingDEV controls and round1; oldshadowT4 sparsegrade. Neither establishes originalR-Breaker/systematicCrabel failure. Component marginal not measured; grade unchanged. |
| rsi_swing_fail | C | exit_or_risk_material | 9 / -1.43 | See source audit; not rebound here | See source audit; not rebound here | P: 2724 / -46,463.65; round1: 2767 / -48,073.74 | 0 completed; common HOLD | Negative30m price-sweep controls/exitround1. OldshadowT9 islow-sample C; not an oscillatorfailure-swing test nor ConnorsdailyETF reproduction. Component marginal not measured; grade unchanged. |
| trend_ma_macd | C | entry_quality_material | 5 / -0.91 | See source audit; not rebound here | See source audit; not rebound here | P: 685 / -1,292.60; round1: 1425 / -13,048.15 | 0 completed; common HOLD | Negative30m EMA/MACDcontrol andprice-reset-triggerround1; oldshadowT5 sparseC. DoesnotrefuteGMMA two-group contextual contribution. Component marginal not measured; grade unchanged. |
| turtle_trend | C | entry_quality_material | 52 / -2.53 | See source audit; not rebound here | See source audit; not rebound here | P: 2346 / -30,232.61; round1: 2287 / -41,557.46 | 0 completed; common HOLD | Negative30m Donchian20control andround1Donchian10closeexit. Prior1hnative andoldshadowT52 notcurrent15/30performancecredit. Component marginal not measured; grade unchanged. |
| alpha_combo | D | entry_quality_material | 1213 / -400.83 | 5m: 25816 / -377,133.73 | 5m: 25132 / -365,029.37 | N/A | N/A; not currentfresh-bound | Saved negative canonical1m observer outcomes and separately saved5m donor reconstructions retained; not original donor universal FAIL or current30m FAIL. Component marginal not measured; grade unchanged. |
| anchor_vwap_trend | D | entry_quality_material | 522 / -175.58 | 5m: 2581 / -37,278.72 | 5m: 2563 / -35,680.26 | N/A | N/A; not currentfresh-bound | Saved negative canonical1m observer outcomes and separately saved5m donor reconstructions retained; not original donor universal FAIL or current30m FAIL. Component marginal not measured; grade unchanged. |
| ema_ribbon_scalp | D | entry_quality_material | 1593 / -967.88 | 5m: 12769 / -193,385.38 | 5m: 14430 / -216,337.16 | N/A | N/A; not currentfresh-bound | Saved negative canonical1m observer outcomes and separately saved5m donor reconstructions retained; not original donor universal FAIL or current30m FAIL. Component marginal not measured; grade unchanged. |
| grid_rebalance | D | exit_or_risk_material | 1746 / -515.71 | 5m: 13600 / -190,194.36 | 5m: 6405 / -104,481.73 | N/A | N/A; not currentfresh-bound | Saved negative canonical1m observer outcomes and separately saved5m donor reconstructions retained; not original donor universal FAIL or current30m FAIL. Component marginal not measured; grade unchanged. |
| obv_trend | D | context_filter_or_veto_material | 202 / -92.92 | 5m: 6936 / -98,486.47 | 5m: 5579 / -82,193.72 | N/A | N/A; not currentfresh-bound | Saved negative canonical1m observer outcomes and separately saved5m donor reconstructions retained; not original donor universal FAIL or current30m FAIL. Component marginal not measured; grade unchanged. |
| pivot_reversal | D | context_filter_or_veto_material | 423 / -240.10 | 5m: 426 / -6,948.38 | 5m: 6346 / -90,412.19 | N/A | N/A; not currentfresh-bound | Saved negative canonical1m observer outcomes and separately saved5m donor reconstructions retained; not original donor universal FAIL or current30m FAIL. Component marginal not measured; grade unchanged. |
| vol_spike_fade | D | exit_or_risk_material | 138 / -118.77 | 5m: 324 / -4,868.23 | 5m: 677 / -9,767.18 | N/A | N/A; not currentfresh-bound | Saved negative canonical1m observer outcomes and separately saved5m donor reconstructions retained; not original donor universal FAIL or current30m FAIL. Component marginal not measured; grade unchanged. |
| vwap_revert | D | context_filter_or_veto_material | 707 / -180.41 | 5m: 1792 / -24,636.45 | 5m: 1520 / -20,926.04 | N/A | N/A; not currentfresh-bound | Saved negative canonical1m observer outcomes and separately saved5m donor reconstructions retained; not original donor universal FAIL or current30m FAIL. Component marginal not measured; grade unchanged. |
| bb_revert | HOLD | exit_or_risk_material | N/A (no snapshot) | 5m: 12989 / -191,034.40 | 5m: 10563 / -162,012.03 | N/A | N/A; not currentfresh-bound | Keep recovered standalone 5m native and state-machine negative economics separately. Canonical1m null or small observer snapshots are not30m economics, universal source rejection, or host-component comparison. Component marginal not measured; grade unchanged. |
| fvg_revert | HOLD | context_filter_or_veto_material | N/A (no snapshot) | 5m: 12757 / -175,944.96 | 5m: 13239 / -188,298.44 | N/A | N/A; not currentfresh-bound | Keep recovered standalone 5m native and state-machine negative economics separately. Canonical1m null or small observer snapshots are not30m economics, universal source rejection, or host-component comparison. Component marginal not measured; grade unchanged. |
| liquidity_sweep | HOLD | context_filter_or_veto_material | 24 / -14.59 | 5m: 451 / -5,885.05 | 5m: 437 / -6,574.44 | N/A | N/A; not currentfresh-bound | Keep recovered standalone 5m native and state-machine negative economics separately. Canonical1m null or small observer snapshots are not30m economics, universal source rejection, or host-component comparison. Component marginal not measured; grade unchanged. |
| mfi_rsi_div | HOLD | exit_or_risk_material | N/A (no snapshot) | 5m: 3085 / -40,035.95 | 5m: 12189 / -175,946.82 | N/A | N/A; not currentfresh-bound | Keep recovered standalone 5m native and state-machine negative economics separately. Canonical1m null or small observer snapshots are not30m economics, universal source rejection, or host-component comparison. Component marginal not measured; grade unchanged. |
| range_fade | HOLD | exit_or_risk_material | N/A (no snapshot) | 5m: 9904 / -142,806.45 | 5m: 7359 / -109,150.38 | N/A | N/A; not currentfresh-bound | Keep recovered standalone 5m native and state-machine negative economics separately. Canonical1m null or small observer snapshots are not30m economics, universal source rejection, or host-component comparison. Component marginal not measured; grade unchanged. |
| scalp_snap | HOLD | entry_quality_material | 392 / -168.50 | 5m: 366 / -5,386.74 | 5m: 922 / -14,016.86 | N/A | N/A; not currentfresh-bound | Keep recovered standalone 5m native and state-machine negative economics separately. Canonical1m null or small observer snapshots are not30m economics, universal source rejection, or host-component comparison. Component marginal not measured; grade unchanged. |
| session_bias | HOLD | exit_or_risk_material | N/A (no snapshot) | 5m: 12725 / -191,232.93 | 5m: 8794 / -132,178.85 | N/A | N/A; not currentfresh-bound | Keep recovered standalone 5m native and state-machine negative economics separately. Canonical1m null or small observer snapshots are not30m economics, universal source rejection, or host-component comparison. Component marginal not measured; grade unchanged. |
| sr_levels | HOLD | context_filter_or_veto_material | N/A (no snapshot) | 5m: 7016 / -104,954.21 | 5m: 7469 / -111,130.83 | N/A | N/A; not currentfresh-bound | Keep recovered standalone 5m native and state-machine negative economics separately. Canonical1m null or small observer snapshots are not30m economics, universal source rejection, or host-component comparison. Component marginal not measured; grade unchanged. |

The C4 controls and round1 variants above remain negative. Previously tested rounds are not reset. Canonical1m sample absence, Micro/flow execution gaps and exact-source differences are documented in the unchanged [27-target audit](audits/AUDIT_27.md). Source fidelity or logical repair does not by itself establish profitability or revive a material.

Cached portfolios below are the previous primary-set results, unchanged. They use independently flat research windows and saved standalone filled/unresolved opportunities; they are not a continuous account curve or a complete pool of all raw valid signals. The new HG/RSI/Break/SR candidates were not inserted.

| Prior portfolio | T | T/day | WR%1x/2x | Gross/T1x | Cost/T1x | Net1x/2x bps | Net/T1x/2x | PF1x/2x | Realized DD1x/2x | MaxLS1x/2x | ES5 1x/2x | Hold median/p95 min | Positive windows |
|---|---:|---:|---|---:|---:|---|---|---|---|---|---|---|---|
| equal7 | 4003 | 16.339 | 26.78 / 23.33 | 0.20 | 1.28 | -4,325.71 / -9,464.81 | -1.08 / -2.36 | 0.735 / 0.530 | 4,669.53 / 9,631.45 | 51 / 51 | -20.84 / -22.88 | 180.00 / 540.00 | 1 / 9 |
| adaptive | 602 | 2.457 | 29.07 / 24.42 | -0.64 | 7.70 | -5,016.15 / -9,649.15 | -8.33 / -16.03 | 0.729 / 0.558 | 5,620.18 / 10,180.07 | 20 / 24 | -159.64 / -172.25 | 225.00 / 480.00 | 0 / 9 |

September19 runtime status is an observation snapshot, not a forecast or a claim that an active process is progressing. The saved paper state last_poll is2026-09-16T17:13:36.493Z, and Micro last_received is2026-09-17T15:12:16.108Z. These older timestamps remain visible; an active September19 process does not establish current data progress or value its recorded open positions.

| Service / record | Observed state | What it establishes |
|---|---|---|
| Common source | active/running | Process presence only; no completed-trade or profitability claim |
| Frozen forward | active/running; HOLD_FRESH_SOURCE_OR_IDENTITY | SOURCE_SNAPSHOT_CHANGED_RETRY_WITHOUT_ADVANCING; fresh_closed_trades=0 |
| Micro raw | failed/failed; MainPID=0 | Raw collector was failed at witness time; no restart performed |
| Micro forward | active/running; WAIT_SOURCE_CLOCK_ADMISSION | economic_execution=false; processed_records=0; new_signals=0; total_signals=131; fresh_closed_trades=0 |
| Observed paper | active/running; RETRY_SOURCE_SNAPSHOT_CHANGED_NO_STATE_ADVANCE | Cursor not advanced; state has32positions,1pending,0trades; position values/MTM not inferred |

The existing gates remain in force: no host touch below B; formal fusion requires the existing independent B/fresh/behavior conditions. The historical registry T>=12 statement does not fill the current specification’s null minimum historical/fresh sample contract. No new threshold, grade, host replacement, Core/Survivor, order or live authority is created.

This report read cached files only. It ran no strategy tests, signals or economics and changed no service or Git state. Checks covered seven primary rows, twenty registry names, stored code/ledger/portfolio hashes and saved-metric arithmetic. The pre-economic AUDIT27 snapshot remains byte-for-byte unchanged.
