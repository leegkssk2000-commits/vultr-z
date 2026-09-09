# C57: REJECT_KEEP_C54 — initial failure hypothesis measured

C54 remains the development reference. C57 does not deliver joint improvement. The two FULL runs are complete, not repeated; final code review/merge is recorded separately. All amounts are fixed-entry-notional trade-bps, not account returns or live15x results. Both periods are already-used DEV, formal_credit0/G5hold.

## Actual cause, not an engine failure claim
C57 preserves C54 entries, fixed original pullback floors, reference reservations, research costs and C51 profit-zone protection. It adds completed-close failure before C51 arms, with actual next-open exit and original exits taking priority. No resident exchange SL or initial margin/liquidation model was introduced.

Whole-pullback breaches occurred for21/8 positions, exactly the preflight21/8. This establishes applicability, NOT an advantageous decision. Existing recoverable winners were caught as well. Counts and prices were not changed after results.

|Net contribution vs C54|DEV2025|SEEN2026|
|---|---:|---:|
|Old-loss improvement|+2484.23|+562.34|
|Old-loss deterioration|-1160.77|-119.61|
|Original winner positive profit lost|-1930.68|-190.77|
|Additional loss on original winners|-1697.21|-168.63|
|Total terminal net increment|-2304.43|+83.32|

Original wins5/1 became losses; losses becoming wins0/0. Actual entry counts and open counts stay191/0 and69/2. New/removed or closed-open transitions0; cost savings already included in net.2025 net benefit on original losers+1323.46 was outweighed by winner damage3627.89.2026 benefit442.73 barely exceeded winner damage359.41. All29 changed origins and full contribution groups remain in the raw/accounting records; DETAILS.json summarizes contributions.

The average loss becomes smaller in both periods, but WR declines43.46→40.84% and37.68→36.23%.2025 PF declines1.420→1.345;2026 PF increases1.683→1.709. Better payoff is insufficient. Only3/8 strict goal checks improve:2025dailyDD and2026net/cost2. The original SUMMARY uses numerical equality tolerance; no roundoff-only success.

## Risk and concentration
Global daily markedDD2025 improves10452.80→10171.18. On the SAME parent peak/trough window, mark change is-10452.80→-10010.88, delta+441.92. These are not the same calculation: the candidate worst window can move.2026 retains the same parent window and worsens3997.48→4005.07, delta-7.59.

2026 terminal net increment+83.32 depends on a largest positive SOL contribution+217.99; subtracting it descriptively gives-134.67. Subtracting HYPE's aggregate+106.19 gives-22.86.2025 is negative overall and negative excluding HYPE(-2090.71). These are attribution diagnostics, NOT symbol-exclusion backtests or permission for year/symbol switches.

## Provenance and limitations
Original code/spec/results/attempts remain immutable. Pre-outcome SPEC674a2770f209445351da282d288391369236f05ab7467c1a2e0a7999e554e25e; source0f2016bdbded786dff5d95820b4f927b5d9bbd06. Runtime claims83931c674c515c2a2c49910f9c4d7215fca8a9f7 and a351a472c1ebdd1d6ef73fc5c833fd3cbb19b4a8 were pushed and read back before runs93/94. Actual workflow34299680952/job102303734312, artifact10084468581 preserves raw engine results and44 prereplay artificial tests from the full remote checkout.

Independent saved checks bind262 raw positions to charged geometry, research costs, metrics, streak/exposure and all common/new/removed/open contributions. Fixed floor data and trigger prices were checked against original hash-pinned packets:1491 floor-source references and1175 earlier held prearm observations. SOURCE_BINDING is anchored to those original packets. Saved CI verifies this projection and the same arithmetic, without importing an engine or obtaining market data. Same-calendar risk comes from stored daily marks, not independently observed historical fills. Research absolute-funding/floor costs are not contemporaneous signed settlement.

The previous profitable-pivot NOT_RUN remains separate. This new initial-failure candidate57 used2 FULLs, totals57/94; old56/92 preserved. No parameter tuning, reverse rule, automatic candidate58, new collection, unused OOS, paid projectmodelAPI, order, sizing or deployment. C54/C51/KR3 and other Work/collectors remain unchanged. Workflow is retired to read-only saved verification. Final review/CI/merge and exact-merge verification status belongs to the final PR receipt, not this preclosure note.
