# Measurement review — one Keltner entry repair

| Period | P closed net | D closed net | N closed net | N-D | N-P |
|---|---:|---:|---:|---:|---:|
| DEV2025 | -634.1339 | 3910.5089 | 4556.3060 | +645.7971 | +5190.4399 |
| Seen2026 | -1679.1979 | -1461.0166 | -397.8979 | +1063.1187 | +1281.3000 |

All totals are equal nominal trade-bps, not account returns. P is the fixed original parent; D is the unadopted PR1196 exit child; N keeps D exits and changes only original signal close >= (high+low)/2. DEV2025 remains TRADEOFF; seen2026 REJECT; combined research-reference decision REJECT. Partial gains are preserved without changing old verdicts or promoting N.

## What survived actual sequence replay

2025 D-common eligibility gives202 closed trades/net6022.2077, an apparent +2111.6988 increment. Full N has210 closed trades/net4556.3060. Relative to full D,200 closed origins and1open are unchanged;17 D closed origins disappear, saving3627.6402 losing amounts and forfeiting1018.6349 winning amounts (net+2609.0053). Ten new trades lose1963.2082. The difference is not hidden by a filtered subset. D net-improvement overP was4544.6428; N net-improvement is5190.4399, or114.2101% of that observed gain. This is an in-sample increment ratio, not a guarantee. D winning amount retention97.7904%; P96.8970%; top-decile winning amounts100% against both.

2026 common-D and full N both have75closed trades/net-397.8979. Four removed D losses total1063.1187;75common closed trades and4open have unchanged exit economics. There are no additional D-relative entries. All D winning amounts and both reference top-decile amounts survive. Relative to originalP, N still retains D's pre-existing new SOL origin worth+1305.0240; this was verified in full replay rather than added as a constant. The correct bridge is old fixed-D harm -1086.8426 + removed-D-origin effect1063.1187 + surviving new-to-P SOL1305.0240 = total N-P1281.3000. On originalP origins alone the remaining net change is -23.7240. This entry filter therefore does not repair the exit economics of common origins.

## Remaining risk and uncertainty

2025 cost2 closed net+123.9847 is only+0.5904bps per trade; including the unchanged open mark leaves hypothetical cost2 terminal+27.2536. AgainstD, grouped loss-run increases5219.6360→5548.5073 and marked DD12265.1987→12733.2112. Both are belowP but violate the frozen no-worse-D risk objective. Exposure falls399.3333→385.8333 symbol-days. The reused-data paired30-day-block confidence interval for N-D calendar-total marked change spans[-779.8116,+3225.4012].

2026 closed net-397.8979, cost2-1998.2077, and four open marks-616.9856 leave terminal net-1014.8835. DD6059.7626→5643.8641 improves againstD but remains aboveP5023.0786; loss-run3758.3091 is unchanged and aboveP3547.7544. Exposure147.1667→141.1667 symbol-days. The same-data interval[+254.4518,+2440.4602] is not selection-adjusted independent proof: the admission cohort was only four trades and approximately four30-day calendar blocks exist. Completed recovery duration and still-underwater duration refer to different recovered/censored episodes, not a single causal clock.

Same-calendar attribution confirms the risk mechanism, separately from differences between maximum values: N2025's worst-DD interval2025-09-19→2025-12-29T08Z has D -11875.4161 and N -12733.2112. Removed-entry contribution+766.8895 is outweighed by new-trade -1624.6846, with common contribution0, giving actual interval worsening -857.7951. In N2026's worst-DD interval2026-06-04→2026-07-09, D -5962.6492 becomes N -5643.8641 through removed-entry+318.7851; common/new contribution0. These are marked interval contributions, not total closed-trade PnL or causal differences between unrelated worst intervals.

## Validation and provenance

- One candidate ordinal29; prior28 and verdicts preserved. Two reused periods and four common/full views, no additional hypothesis slots. No result-dependent rule change.
- Diagnostic axis protocol local commit4a84db9 preceded current D cohort outcomes. Full code/rules/criteria were remotely frozen at6f6674ccbe477ffbc0fb981e95ae7cb918cf5c8c before any N replay. Its CI34044715078 passed check-only; legacy STAPC and N-economic replay steps were skipped.
- Synthetic unit/integration36, existing governance46 and controller16 checks passed; compile, Alpha Proof/common semantic self-tests and frontend validate passed. These are code checks, not economic PASS.
- Independent ledger arithmetic review:6798 assertions across P/D/N-common/N-full passed for fill/gross, cost components/floor, net/cost2, PF/win/payoff, open marks, exposure, grouped loss-run, daily DD, origin bridges and capped profit retention. Reviewer used stored ledgers only; no new price read or candidate replay.
- Local same-result verify-only reproduced result seal864843a20c40d76a10a536192f09e89ff081cc589aa0671579f1fd92d2de19b7 and durable file SHA9ba4d57f477c9b54b0fbcad54ac7bb5475f6be55c44a170a6d56060b7de8bf6b. All221 protected files match. Remote PR/master verification follows this evidence commit.
- Source reader retains original partition labels: already-seen validation/OOS-labelled prefix rows are reused under the existing seen-period authorization, not claimed unread or independent. No rows after2026-09-05T00Z, no observer data or unused validation are accessed.
- Q0 future observation and G5B/operating strategy unchanged. Formal credit0; execution=NONE,order=BLOCKED,live=BLOCKED; external paidAI0; Gemini actual video NOT_RUN. Reproduction creates no additional candidate allocation.
