# M measured repair and review

All PnL and loss sums below are equal-nominal trade-bps, not account returns or account MDD. P is the original control; D is the PR1196 exit workcopy; N is the unadopted PR1197 entry workcopy; M adds only a causal D opportunity reservation. These are reused development observations, independent=false.

| Period / closed economics | P | D | N | M | M-N | M-D | M-P |
|---|---:|---:|---:|---:|---:|---:|---:|
| DEV2025 completed trades | 217 | 217 | 210 | 202 | -8 | -15 | -15 |
| DEV2025 net sum | -634.13 | 3,910.51 | 4,556.31 | 6,022.21 | +1,465.90 | +2,111.70 | +6,656.34 |
| DEV2025 expectancy / trade | -2.92 | 18.02 | 21.70 | 29.81 | +8.12 | +11.79 | +32.74 |
| DEV2025 PF | 0.9866 | 1.0927 | 1.1093 | 1.1542 | +0.0449 | +0.0615 | +0.1676 |
| DEV2025 cost2 net sum | -5,254.94 | -667.41 | 123.98 | 1,749.89 | +1,625.90 | +2,417.30 | +7,004.83 |
| SEEN2026 completed trades | 78 | 79 | 75 | 75 | 0 | -4 | -3 |
| SEEN2026 net sum | -1,679.20 | -1,461.02 | -397.90 | -397.90 | 0 | +1,063.12 | +1,281.30 |
| SEEN2026 expectancy / trade | -21.53 | -18.49 | -5.31 | -5.31 | 0 | +13.19 | +16.22 |
| SEEN2026 PF | 0.8869 | 0.9022 | 0.9713 | 0.9713 | 0 | +0.0692 | +0.0844 |
| SEEN2026 cost2 net sum | -3,362.78 | -3,152.72 | -1,998.21 | -1,998.21 | 0 | +1,154.52 | +1,364.58 |

The frozen focused goals pass: 2025 recovery and 2026 preservation. M is retained only as PARTIAL_DEVELOPMENT_WORKCOPY_RETAINED. Absolute economic decision remains REJECT across the two periods, with SEEN2026 negative; the older comparative study decisions remain TRADEOFF for 2025 and REJECT for 2026. No automatic research baseline replacement, formal PASS, operating adoption, or independent-validation claim is made.

## What the implemented clock changes

M reserves each D opportunity from information available at the current completed bar even when N rejects the actual entry. It releases by the frozen D timeout or observed EMA invalidation and next-open execution; the exit bar remains owned. It does not read stored D trade IDs, future exits, final outcomes, or a precomputed price path to admit signals. The shared old engine accounts for actual admitted trades after the causal pass. Virtual reservations have zero actual quantity, trade count, funding, transaction cost, PnL, and exposure.

2025: 379 original signals produce 218 reference reservations: 203 actual entries (202 completed, one open) and 15 vetoed virtual reservations. All 10 N-only replacements are blocked. Both displaced D trades are restored with unchanged economics, including their combined loss of 497.31. The chronological LINK chain is reference 2114 blocking 2120, then actual 2129 blocking 2138, then actual 2145. Historical indices identify reviewed output events only; they are not execution rules.

2026: 126 original signals produce 83 reference reservations: 79 actual entries (75 completed, four open) and four vetoed reservations. Every N/M completed trade, open position, fill, cost, and daily valuation is unchanged. The existing SOL trade contributes +1,305.02 once, with the same identity and economics as D/N.

## 2025 repair and costs of repair

The 10 excluded N replacements contain losses avoided of +3,128.70 and winning profits forfeited of -1,165.49, for +1,963.21 net. Restored D trades add -497.31. Unchanged common trades add zero. Thus +1,963.21 -497.31 = +1,465.90 actual completed-net improvement. Cost savings of 160.00 are already included, not added twice.

| Risk / preservation | 2025 N | 2025 M | 2026 N | 2026 M |
|---|---:|---:|---:|---:|
| Daily marked drawdown | 12,733.21 | 11,605.83 | 5,643.86 | 5,643.86 |
| Grouped maximum losing-run loss | 5,548.51 | 4,782.53 | 3,758.31 | 3,758.31 |
| Exposure, symbol-days | 385.83 | 372.67 | 141.17 | 141.17 |
| Win rate | 48.10% | 48.51% | 36.00% | 36.00% |
| Realized payoff | 1.1972 | 1.2248 | 1.7268 | 1.7268 |
| Open positions | 1 | 1 | 4 | 4 |
| Open net mark, hypothetical cost | -76.73 | -76.73 | -616.99 | -616.99 |

M preserves 97.48% of N's winning-profit amount in 2025 and 100% in 2026; large-winner amount is preserved 100% in both. Relative to P and D, 2025 winning-profit retention is 96.90% and 97.79%. All three references retain 100% of their large-winner amount.

Same-calendar attribution, not subtraction of unrelated maximum episodes:

- During the 2025 September 19–December 29 08:00 drawdown window, removed N trades contribute +1,624.68 and restored D trades -497.31, with common trades unchanged: marked PnL improves +1,127.38.
- During the October 8–November 4 losing-run-related daily window, removal of LINK1886 contributes +765.97, restored trades zero. Window marked PnL changes from -4,950.65 to -4,184.67. These are daily valuation sums, not the completed losing-run sum.

The 2025 M-N calendar-sum bootstrap 95% interval is [-163.66, +3,408.93]; it includes zero. Frozen 30-day blocks, 1,000 resamples, seed 1178 are unchanged. Results are not independent: the COMMON_D diagnostic and its expected effect were already seen before M. Actual M reproduces that diagnostic through causal admissions, without taking its trade subset as execution input. Open marks are never forced completed trades: M terminal net is 5,945.48 in 2025 and -1,014.88 in 2026, with cost2 terminal net 1,653.16 and -2,695.19 respectively.

## 2026 residual loss, with no additional candidate

The following disjoint closed-trade buckets subtract each trade's cost exactly once. Values derive from stored ledgers and exit traces. Labels describing eventual profit or loss are analysis labels only.

| M closed group | Trades | Gross | Cost | Net |
|---|---:|---:|---:|---:|
| Unchanged exit, nonloss | 26 | 12,717.42 | 551.22 | 12,166.20 |
| Unchanged exit, loss | 34 | -8,756.64 | 743.39 | -9,500.03 |
| Helpful early exit | 7 | -1,652.71 | 140.00 | -1,792.71 |
| Harmful early exit | 7 | -2,430.68 | 145.70 | -2,576.38 |
| D-shared new-to-P SOL | 1 | 1,325.02 | 20.00 | 1,305.02 |
| Total | 75 | 1,202.41 | 1,600.31 | -397.90 |

Four open positions are separate: gross mark -536.99, hypothetical cost 80.00, net mark -616.99. The 34 unchanged-exit losses run ENTRY_NEXT_OPEN to ORIGINAL_TIME_STOP_CLOSE without an EMA invalidation exit: 33 have negative gross and one becomes a -2.89 loss through costs. This identifies adverse paths surviving the fixed trend condition until max12 as a remaining issue; an observable separator has not been tested and is not inferred from hindsight. Helpful early exits improve their P comparisons by 856.39 while harmful early exits worsen them by 1,759.10. M does not fix either exit group.

2026 remains worse than P on marked drawdown (5,643.86 vs 5,023.08) and grouped losing-run loss (3,758.31 vs 3,547.75). Equality to N means preservation of prior gains, not recovery of these residual risks or proof of absolute profitability. No M2, indicator, parameter sweep, or exit change is executed.

## Freeze, verification, and boundaries

The rule/code freeze was pushed before actual M results: commit f9dd1e7481eddc046b9bc50f20ae8c5f9480c55b, tree 1b3f77d89423aa8068e163995efa95ff3a4e87e9. Preregistration CI run 34049700812 passed with economic reproduction skipped until a receipt existed. SPEC seal: bf93e2ed26350a7a7fad4b8348924e67763772ddbc09702de85e2626ab830db4. No sealed file changed after measurement.

- 53 M synthetic tests (24 adapter, 16 metrics, six diagnosis, seven runner), 46 existing governance tests and 16 existing controller tests passed: 115 total. Shared self-tests, compile and frontend validation passed.
- Local same-result verify-only passed with result seal b86757d2271190ffa85d78f01879b3fce57365b6ce03b46f78aff73e011199fe and durable receipt SHA256 677605ef91ca7f5b0930c207d4953d5f88cefcabb12ac8e828a233db02e347e8.
- Separate read-only ledger arithmetic review passed 16,489 assertions over 1,153 completed and 20 open P/D/N/M rows. Price-to-gross, cost components/floor, funding interval counts, net/cost2, exposure, PF/payoff, stored daily path arithmetic, periods/symbols, retention and bridges were recomputed. This review did not reread raw prices or run another economic candidate.
- Separate read-only event/lineage review passed 1,821 review units. Causal reservation, release timing, LINK sequence, restored economics, same-calendar contributions and unchanged 2026 SOL were checked.
- Prior 238 protected files retain byte parity. New candidate count is 30, prior 29 preserved, remaining M slots zero. Two fixed period applications and same-result reproductions are not extra candidates. Prior seen evaluation remains 1/1 and independent comparison 0/1 NOT_RUN.
- Input is the authorized reused DEV2025/SEEN2026 calendar only. The old bounded files include previously seen partition-labelled data; this is not a claim that zero historical validation-labelled rows were decoded. No unused validation/OOS or Q0 prospective evaluation prices are used for development.
- Frozen fee/spread/slippage/funding and the 20bps floor remain RESEARCH_COST_MODEL, not production execution evidence. Native P/D/N geometry and protective-stop definition are preserved; the V2 model has no newly supplied native protective SL.
- Q0 prospective observer, G5B collector/open intent/boundary, original verdicts, and operating code are unchanged. execution=NONE, order=BLOCKED, live=BLOCKED. New paid external AI calls are zero.

Full precision metrics, comparisons, funnels, concentration, uncertainty, window contributions, trace links and causal events are in RESULTS.md, receipt.json and the two compressed period ledgers. Remote result CI/merge/master verification is performed after this review; its actual status belongs to the PR/check records, not a preclaimed pass here.
