# Post-measurement interpretation audit — Q0_RISK_ENTRY_V1

This note derives accounting totals from the already measured, sealed unit/weighted ledgers, original pinned cohorts and saved entry observations. It does not rerun a strategy, change a weight, recompute a candidate, retune a parameter or consume another trial. The frozen specification, implementation, receipts and compressed outputs remain unchanged. All amounts below use the fixed reference notional expressed in bps units; none are account returns or account MDD.

## Original closed-run cohorts, distinct from calendar marks

The saved accounting already contains all 19 original cohort origin lists and every weighted closed-trade amount. Its main window tables report all-position calendar mark changes; they do not themselves tabulate the following closed-cohort sums. This post-run table completes that presentation. Original simultaneous-close group labels are retained, even if a positive group contains an individual losing trade or vice versa.

| Original Q0 cohort | Closed T | Q0 A closed net | Fixed C closed net | Risk B closed net |
|---|---:|---:|---:|---:|
| Q0_LOSS_RUN_0 | 16 | -5,224.687753 | -4,668.676603 | -3,994.649862 |
| Q0_WIN_RUN_1 | 5 | 2,838.303285 | 2,536.251115 | 2,016.208506 |
| Q0_LOSS_RUN_2 | 2 | -600.652160 | -536.730771 | -459.507197 |
| Q0_WIN_RUN_3 | 5 | 1,818.171017 | 1,624.681299 | 1,545.751347 |
| Q0_LOSS_RUN_4 | 6 | -1,595.413691 | -1,425.629803 | -1,359.300921 |
| Q0_WIN_RUN_5 | 1 | 657.824294 | 587.818648 | 558.473161 |
| Q0_LOSS_RUN_6 | 11 | -4,590.207551 | -4,101.717770 | -4,224.563725 |
| Q0_WIN_RUN_7 | 3 | 3,243.372832 | 2,898.213170 | 3,243.372832 |
| Q0_LOSS_RUN_8 | 1 | -263.183408 | -235.175435 | -263.183408 |
| Q0_WIN_RUN_9 | 5 | 9,078.649203 | 8,112.499565 | 9,078.649203 |
| Q0_LOSS_RUN_10 | 5 | -469.799639 | -419.803572 | -464.634315 |
| Q0_WIN_RUN_11 | 4 | 1,024.610158 | 915.571169 | 904.394492 |
| Q0_LOSS_RUN_12 | 5 | -929.033238 | -830.165542 | -917.668794 |
| Q0_WIN_RUN_13 | 2 | 1,445.085435 | 1,291.299477 | 1,445.085435 |
| Q0_LOSS_RUN_14 | 4 | -1,248.401072 | -1,115.546259 | -968.222136 |
| Q0_WIN_RUN_15 | 2 | 128.941162 | 115.219247 | 120.129766 |
| Q0_LOSS_RUN_16 | 1 | -35.570709 | -31.785275 | -32.965484 |
| Q0_WIN_RUN_17 | 2 | 300.760248 | 268.753350 | 278.732354 |
| Q0_LOSS_RUN_18 | 6 | -1,502.625459 | -1,342.716092 | -1,454.538090 |

Coverage is **86 distinct origins / 86 completed trades**, with no omissions or duplicate membership. These disjoint closed cohorts telescope to A **4,076.142956**, C **3,642.359917**, B **5,051.563164**. Their enclosing daily windows can overlap and must not be summed as if disjoint.

The maximum closed losing-run amount moves from original **run 0** in A/C to original **run 6** in B. The global maxima 5,224.687753 → 4,224.563725 are different cohorts; their difference is not a same-run causal contribution. On the original worst run 0, loss is instead 5,224.687753 → 3,994.649862, a reduction of **1,230.037891**. On original run 6, A/C/B losses are 4,590.207551 / 4,101.717770 / 4,224.563725: B improves on A but is **122.845955 worse than C** in that same closed cohort.

Original run 0's **calendar mark** change over 2025-02-01 00:00 → 2025-04-21 00:00 UTC is A **−5,178.338533**, C **−4,627.259866**, B **−3,957.776936**. These are all-position boundary-mark differences, not the run's closed-transaction totals above. The original marked drawdown window is separately 2025-05-11 → 2025-07-08 UTC.

## Entry timing inside the original marked-drawdown window

The following rows have nonzero mark contributions in the original 2025-05-11 → 2025-07-08 window. Entry time, allocation and volatility availability are saved observations; the window label is retrospective and never an execution feature.

| Contributing cohort | Positions | Q0 mark change | C mark change | B mark change | B minus C |
|---|---:|---:|---:|---:|---:|
| Entered before window | 4 | -1,193.681812 | -1,066.650222 | -1,022.874330 | 43.775892 |
| Entered at/after window start | 22 | -5,607.796949 | -5,011.015327 | -5,105.391485 | -94.376158 |

The net window difference is **B−C = −50.600266**. Four positions already entered before the window contribute +43.775892 relative to C; the 22 positions entered at/after its start contribute −94.376158. Four of those 22 entered exactly at the right boundary on July 8; their initial hypothetical full-roundtrip mark costs total −80 in A/B. This is the preregistered after-open valuation convention, not a price loss from time held before entry.

Concrete saved observations distinguish pre-loss allocation from later responses:

- At the first original losing-run entry, SOL on **February 1 00:00 UTC**, weight **0.923609763** was known at entry (30-day sigma 0.035631315 versus reference 0.032909430). Its later unit loss was −223.384200. The first loss was already partially reduced; the method did not wait for a completed losing-run label.
- Later entries on **March 25** used weight **0.600707445**, with observed sigma 0.054784456. Those allocations followed earlier losses in the February–April episode. This is consistent with the trailing measure responding during an existing episode, but does not prove the earlier strategy losses caused basket volatility or establish predictive power.
- Before the separate marked-DD window, BTC entered on **May 8** at weight **0.881271456**, and ETH/LINK/SOL on **May 10** at **0.851499379**. Their weights stayed fixed throughout holding. No later volatility observation could resize those positions.
- During that same DD window, BTC/HYPE/BCH entries on **June 11** used full weight **1.0**: sigma 0.032738800 was below the reference. Likewise, 1000PEPE and ETH entered on **June 30** with full weight **1.0** and sigma 0.030584130. Their window mark changes were −1,120.271643 and −377.974105, respectively. Being in an already worsening portfolio interval did not itself trigger a reduction; the rule only used trailing market volatility available at entry.

These facts do not show loss prediction or a universally timely response to changing volatility. They show a mix of reduced exposure before subsequent losses, later reductions within an ongoing loss episode, and full allocations before additional losses. No intraholding rebalancing counterfactual was calculated.

## Recovery and concentration trade-offs

- Maximum **completed** daily marked recovery duration is **85 days in A/C and 100 days in B**. All three finish unrecovered with **159 open underwater days**. These are existing global diagnostics; do not attach the longest recovery automatically to the separate maximum-DD window.
- July accounts for **83.0731% in A/C versus 85.5156% in B** of the sum of **positive exit-month aggregate closed net**. July closed net is 10,400.322684 in A/B and 9,293.520585 in C. This concentration definition is not the same as positive marked-month gains: under that latter definition July shares are **78.3882% in A/C and 80.9625% in B**.
- B preserves all **10,154.193075** of the original three largest winning-trade profits. Those three now represent **51.8547%** of B's total positive individual-trade profits, versus **48.3288%** in A/C. Preservation of the largest gains coexists with increased concentration because other winning amounts were reduced.
- Total winner amounts decrease by **1,428.637709** versus A while loss amounts decrease by **2,404.057917**. B retains **807.313332 more winner amount than C**, including **1,080.608992 more of the original top-three amount**. Cost savings are already included in these net amounts and must not be added again.

## Frozen research decision and reporting checks

The saved outcome **DEV_INCONCLUSIVE_TRADEOFF** is consistent with the frozen goal: B terminal net and cost2 net are positive; B beats C in terminal net and maximum grouped loss amount, but daily marked DD is **6,128.265815 versus C 6,077.665549**. Thus the nonworsening-DD goal fails by **50.600266**, and the B−C paired 95% calendar-sum interval **[−780.615128, +4,549.928984]** also includes zero. No threshold or equality tolerance was changed.

Signals, fills, unit net expectancy, **29/86 unit winners**, and all 86 original positions remain unchanged. In this dataset no mixed-sign simultaneous-close group changes aggregate sign, although the accounting correctly treats that as possible under unequal positive weights. Code/test PASS is separate from the economic decision. No new research reference or operating adoption follows.

Input identities for this read-only derivation:

- `SPEC.json` SHA256 `8ba094f1db049dbe9059c6b9a3600ab02615254ed5b891ff8429a1db295d69ea`.
- `receipt.json` SHA256 `b6bcb282adb7816f8ee77090ea205c61390b075f769d813f7968bbf5eb7f9fb5`.
- `weighted_accounting.json.gz` SHA256 `041fb971d7c7b2674118a63bce43cd950dbee82378d6f440881fa185f68928bf`.
- `market_and_entry_weights.json.gz` SHA256 `27dc65d281c43299bb85f5322e499511c26ebc4a93381e25604f3a4c8f56f719`.

## Independent arithmetic and reproducibility verification

A separate read-only calculation, using no evaluator imports, verified all saved basket returns and86 causal30-return weights, exact original Q0 unit rows, ex-post k=0.89358002312282, all3×334 daily marks from existing complete daily open/close prices with elapsed8h funding and the frozen floor, closed sums/PF/payoff/signs, all20 calendar windows and per-position contributions, originaltop3 profit and the existing paired bootstrap. All checks PASS; no economic/accounting defect found. All three maximum marked-DD intervals coincide with original May11→July8, so its B-C50.600266 deterioration also reconciles on identical boundaries. Original19 closed cohorts are separately preserved above.

Local synthetic regression:29 tests PASS; compile and frontend validate PASS. Different PYTHONHASHSEED immutable reproduction PASS with result seal `edab29b1ca3db8c75c8e29a439f6076e2dd9acd181b32665760c7915976ebb98`. Verified158 preserved files,6 frozen code files and6 durable result/spec/source/artifact hashes. Durable receipt file SHA256: `afc04a9ca279c605e7ef8b7037067e1cb594b006394f0463c13266b12b5332d7`.

Remote pre-outcome code/spec commit: `9b1736ceab48332c35e60c77e5e7ea41c7a3228e`; pre-registration CI [34027411294](https://github.com/leegkssk2000-commits/vultr-z/actions/runs/34027411294) PASS. The local pre-outcome metadata correction recorded in SPEC changes only unused-pool end time to2026-09-05 12UTC; no candidate results existed and no rule/reference/goal changed. Final SPEC seal `75b68c3f0a90653df90cd452f2dab4eda6559db739c869b358045ce0bd718bf7`.

This note is a post-measurement accounting presentation of already saved quantities, not a revised specification/result or a second hypothesis. Its own durable identity is the containing git commit; the frozen result receipt is unchanged. Cumulative26, remaining0. Code/CI PASS is not economic adoption. Q0/Q1/Q2 and G5B/operating/actual sizing/G7/G11/execution/order/live remain unchanged; no deploy required. No source data beyond the approved DEV prefix were decoded, no paid AI called.
