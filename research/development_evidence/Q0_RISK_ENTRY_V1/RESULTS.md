# Q0 entry-notional risk study — measured DEV result

Same signals/fills/SL/holding/ownership; only entry notional changes. Unit trade returns remain Q0. Weighted amounts below use one fixed reference notional, expressed in bps units; these are not account returns or account MDD.

| Metric | Q0 A | Fixed same-exposure C | Entry-risk B |
|---|---:|---:|---:|
| Signals | 102 | 102 | 102 |
| Closed / open | 86 / 0 | 86 / 0 | 86 / 0 |
| Unweighted unit net expectancy | 47.3970 | 47.3970 | 47.3970 |
| Unweighted win rate % | 33.7209 | 33.7209 | 33.7209 |
| Weighted gross amount / closed T | 73.5522 | 65.7248 | 81.8043 |
| Weighted net amount / closed T | 47.3970 | 42.3530 | 58.7391 |
| Amount PF | 1.2407 | 1.2407 | 1.3477 |
| Mean winning / losing amount | 724.5046 / -297.0963 | 647.4028 / -265.4793 | 675.2412 / -254.9199 |
| Amount realized payoff | 2.4386 | 2.4386 | 2.6488 |
| Cost2 weighted net / closed T | 21.2418 | 18.9813 | 35.6739 |
| Closed net amount | 4,076.1430 | 3,642.3599 | 5,051.5632 |
| Open hypothetical net mark | 0.0000 | 0.0000 | 0.0000 |
| Terminal net amount | 4,076.1430 | 3,642.3599 | 5,051.5632 |
| Terminal cost2 net amount | 1,826.7957 | 1,632.3882 | 3,067.9538 |
| Daily marked DD amount | 6,801.4788 | 6,077.6655 | 6,128.2658 |
| Max grouped losing-run amount | 5,224.6878 | 4,668.6766 | 4,224.5637 |
| Nominal-weighted position-days | 276.6667 | 247.2238 | 247.2238 |
| Max simultaneous weighted slots | 6.0000 | 5.3615 | 5.5929 |
| Original winner money retained | 21,010.6326 | 18,774.6816 | 19,581.9949 |
| Original top-decile money retained / % | 10,154.1931 / 100.0000 | 9,073.5841 / 89.3580 | 10,154.1931 / 100.0000 |
| Fees / funding / all closed costs | 860.0000 / 934.6400 / 2,249.3472 | 768.4788 / 835.1756 / 2,009.9718 | 753.6522 / 832.3978 / 1,983.6094 |
| Net / weighted exposure-day | 14.7330 | 14.7330 | 20.4332 |
| Terminal net / marked DD | 0.5993 | 0.5993 | 0.8243 |
| Top-symbol / top-decile profit share | 0.2972 / 0.4833 | 0.2972 / 0.4833 | 0.3126 / 0.5185 |
| Mixed-sign close-group sign changes | 0 | 0 | 0 |

Reference daily sigma: 0.032909430454; pre-evaluation returns 38. Entry weights: {'T': 86, 'minimum': 0.6007074454640268, 'maximum': 1.0, 'mean_per_entry': 0.8763397109056821, 'reduced_entries': 60}. C k=0.893580023123, **ex-post analytical normalization only**, not a trading rule or an input to B. No weight above1, no zero/drop, no intraholding changes.

**Research decision: DEV_INCONCLUSIVE_TRADEOFF**; study goal met=False. Failed checks: DD_not_worse_than_C. Q0 remains the research reference. Code/CI PASS does not imply economic or formal adoption.

| Contribution | B minus Q0 | B minus C |
|---|---:|---:|
| Closed net change | 975.4202 | 1,409.2032 |
| Terminal net change | 975.4202 | 1,409.2032 |
| Original loss amount saved, signed | 2,404.0579 | 601.8899 |
| Original winner amount foregone, signed | 1,428.6377 | -807.3133 |
| Cost saving, already included in net | 265.7379 | 26.3624 |
| Gross change | 709.6823 | 1,382.8408 |

All 86 closed and 0 open positions are common. New/removed trades and their PnL are0. Loss/winner net contributions already include cost savings; do not add costs a second time.

## Original pinned calendar intervals

Original Q0 labels are analysis-only; windows can overlap. Mark all positions on identical boundaries. Different worst-window maxima are not causal attribution. Full per-position starting/ending marks are in weighted_accounting.json.gz.

| Original interval | UTC milliseconds | Q0 net mark change | C net mark change | B net mark change |
|---|---|---:|---:|---:|
| Q0_LOSS_RUN_0 | 1738368000000 to 1745193600000 | -5,178.3385 | -4,627.2599 | -3,957.7769 |
| Q0_WIN_RUN_1 | 1745452800000 to 1746057600000 | 164.1972 | 146.7234 | 114.1532 |
| Q0_LOSS_RUN_2 | 1746316800000 to 1746489600000 | -748.2147 | -668.5897 | -558.7691 |
| Q0_WIN_RUN_3 | 1746403200000 to 1747094400000 | 1,740.1495 | 1,554.9628 | 1,484.8155 |
| Q0_LOSS_RUN_4 | 1747267200000 to 1748390400000 | -963.8100 | -861.2413 | -819.8216 |
| Q0_WIN_RUN_5 | 1748304000000 to 1748390400000 | -642.6940 | -574.2985 | -537.7401 |
| Q0_LOSS_RUN_6 | 1748390400000 to 1751414400000 | -4,523.9870 | -4,042.5444 | -4,170.6468 |
| Q0_WIN_RUN_7 | 1752278400000 to 1752451200000 | -404.1749 | -361.1626 | -404.1749 |
| Q0_LOSS_RUN_8 | 1752537600000 to 1752624000000 | 492.2571 | 439.8711 | 492.2571 |
| Q0_WIN_RUN_9 | 1753142400000 to 1753401600000 | -2,217.4377 | -1,981.4581 | -2,217.4377 |
| Q0_LOSS_RUN_10 | 1753747200000 to 1757289600000 | -473.7174 | -423.3044 | -468.5521 |
| Q0_WIN_RUN_11 | 1757808000000 to 1757980800000 | -1,712.8510 | -1,530.5694 | -1,554.3601 |
| Q0_LOSS_RUN_12 | 1758240000000 to 1759708800000 | 128.4993 | 114.8244 | 172.9402 |
| Q0_WIN_RUN_13 | 1759881600000 to 1759968000000 | 350.6219 | 313.3087 | 350.6219 |
| Q0_LOSS_RUN_14 | 1761004800000 to 1764374400000 | -481.3030 | -430.0827 | -260.6672 |
| Q0_WIN_RUN_15 | 1764288000000 to 1764374400000 | -480.3744 | -429.2530 | -447.1680 |
| Q0_LOSS_RUN_16 | 1764374400000 to 1764460800000 | -302.4424 | -270.2565 | -280.2913 |
| Q0_WIN_RUN_17 | 1764460800000 to 1764547200000 | -50.5250 | -45.1481 | -46.8245 |
| Q0_LOSS_RUN_18 | 1765411200000 to 1766620800000 | -1,495.3393 | -1,336.2054 | -1,446.9452 |
| Q0_MAX_MARKED_DD | 1746921600000 to 1751932800000 | -6,801.4788 | -6,077.6655 | -6,128.2658 |

Entry-timing cohorts in receipt.json split positions entered before each window from later entries. Their recorded available_at and weight were fixed at each original entry; subsequent volatility cannot resize already held positions. These are retrospective calendar cohorts, not proof of pre-loss prediction. Positive individual multipliers preserve wins/losses; weighted simultaneous mixed-sign groups may nevertheless change aggregate run labels.

## Monthly marked net contributions

| Month | Q0 | C | B |
|---|---:|---:|---:|
| 2025-01 | -20.0000 | -17.8716 | -18.4722 |
| 2025-02 | -1,604.8775 | -1,434.0865 | -1,503.6380 |
| 2025-03 | -3,035.4950 | -2,712.4577 | -2,027.0106 |
| 2025-04 | 2,273.9880 | 2,031.9903 | 1,570.6795 |
| 2025-05 | -617.4792 | -551.7670 | -451.6656 |
| 2025-06 | -2,921.8887 | -2,610.9414 | -2,716.5715 |
| 2025-07 | 11,127.6582 | 9,943.4531 | 11,127.6582 |
| 2025-08 | -278.7862 | -249.1178 | -278.7862 |
| 2025-09 | -138.2777 | -123.5622 | -241.9636 |
| 2025-10 | 600.9261 | 536.9755 | 869.6305 |
| 2025-11 | 193.0004 | 172.4613 | 176.2408 |
| 2025-12 | -1,502.6255 | -1,342.7161 | -1,454.5381 |

## Symbol terminal net contributions

| Symbol | Q0 | C | B |
|---|---:|---:|---:|
| 1000PEPE-USDT | -59.9711 | -53.5889 | 245.4977 |
| BCH-USDT | -2,904.7463 | -2,595.6232 | -2,367.5725 |
| BTC-USDT | -482.7906 | -431.4120 | -366.8294 |
| ETH-USDT | 2,593.3894 | 2,317.4010 | 3,052.2508 |
| HYPE-USDT | 41.6767 | 37.2415 | -209.8842 |
| LINK-USDT | 4,687.2909 | 4,188.4695 | 4,256.1890 |
| SOL-USDT | 201.2938 | 179.8722 | 441.9118 |

## Uncertainty and boundaries

B-C mean daily marked increment: 4.2192;95% interval [-2.3371710421607363, 13.62254186796643]; calendar-sum interval [-780.615128081686, 4549.928983900787]. Existing paired noncircular30day1000draw seed1178 method. Fixed realized C k is conditioned on, not re-estimated as a tradable parameter. Dependence can exceed30days; repeated DEV and model selection are uncorrected. This is not independent OOS or account Sharpe.

Original unit prices/costs/metrics/daily risk parity PASS. All legacy files are verified by frozen SHA; original Q0/Q1/Q2 states and25-trial history remain unchanged. One measured new entry-risk candidate consumes the reallocated slot: cumulative26, remaining0. Exact reproductions are not new hypotheses. No automatic window/ref retuning.

Unused validation: the old Break validation was already consumed/rejected. Metadata identifies a purged-OOS pool, but Q0-specific authorization, candidate freeze, warmup/purge/ownership and open-end specification are absent. Original26bar embargo is a STAPC20+6 design, not automatic Q0 eligibility. Actual fill/depth/signed-funding and formal terminal lineage are unbound. These future gaps did not block this authorized DEV calculation.

See DESIGN_AND_SOURCES.md for directly read source locations and limitations. Moreira/Muir monthly inverse-variance and other rebalanced literature are not replications of this entry-only30day capped ZEL design. No paper performance is transferred to Q0.

validation/OOS decoded0; paid external AI0; Gemini actual videoNOT_RUN. G5B/operating/actual-account-sizing/G7/G11 unchanged; executionNONE/orderBLOCKED/liveBLOCKED. No deploy required.
