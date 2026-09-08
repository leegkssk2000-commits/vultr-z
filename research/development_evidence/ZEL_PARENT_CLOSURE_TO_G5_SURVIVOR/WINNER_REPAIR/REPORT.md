# PR1213 successor: KR3 winner repair E

**Economic decision: REJECT E as B replacement; retain the partial winner restoration and all failed results.** G5A remains HOLD. No automatic promotion or change to KR3/B, Q0, G5B, source collectors or operational strategies.

The full period tables, winner/loss cohorts, open positions, exposure, drawdown windows and concentration accounting are in [REPORT_ACCOUNTING.md](REPORT_ACCOUNTING.md). Units below are equal-notional trade-bps, not account returns. Both periods were already used DEV; neither is independent OOS.

|Period|View|Closed/open|Win rate %|Payoff|PF|Closed net|Terminal net|All-cost2 terminal|Marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|KR3 stored|202/1|41.09|1.82|1.27|10,341.73|10,265.00|5,744.23|11,727.79|
|DEV2025|B stored|102/0|38.24|3.28|2.03|12,403.90|12,403.90|10,235.27|2,619.35|
|DEV2025|E actual|132/0|36.36|2.15|1.23|5,365.37|5,365.37|2,485.64|7,083.31|
|SEEN2026|KR3 stored|75/4|33.33|2.85|1.43|5,363.56|4,746.58|3,002.13|4,093.69|
|SEEN2026|B actual|34/2|26.47|2.16|0.78|-1,351.99|-1,282.64|-2,027.47|3,011.56|
|SEEN2026|E actual|42/2|28.57|4.06|1.62|4,545.38|4,598.78|3,644.39|3,659.50|

## Preserved benefit and damage

- E restores 14 damaged KR3 winners in 2025, capped restored profit +4,608.44. General/large winner profit preservation improves from B's 43.36%/69.41% to 53.59%/81.42%.
- However, E revives 29 of B's A85 exclusions: 8 wins and 21 losses, actual E net -8,131.18. B-to-E total terminal change is -7,038.54, drawdown grows by 4,463.96, and five B winners become losses. The repair objective fails on the development period.
- In reused 2026, four damaged KR3 winners are restored; capped restored profit +6,886.44. B-to-E terminal change +5,881.42 includes HYPE +6,335.48. Excluding HYPE from the two stored ledgers leaves -454.06; drawdown increases 647.94 and one B winner becomes a loss. E terminal net remains 147.80 below KR3. One original KR3 winner stays open and is not counted as restored.
- Restored-winner and revived-loss cohorts overlap. Their sums are not added together as total improvement. Disjoint origin-state bridges reconcile the complete net difference, including costs and open marks.

Keep E solely as a failed/partial-improvement DEV research branch. B's 2025 improvement is also not stable across reused 2026. No D substitution, E2, sweep, exit optimization, new symbol exception or formal PASS is justified.

## Frozen change and actual execution

Scope `KR3_REQUAL_WINNER_REPAIR_AFTER_PR1213_V1`; task `task-e4437a8c8d9a7296`; parent PR1213 merge `2012c0213a783f70e654ecce0c1e4442a7e3a4b3`. Direct parent B is `W6_RECHECK_ORIGINAL_REFERENCE`; KR3 FULL remains inherited control.

E checks only the first subsequent completed bar: close strictly above the original signal high, close > EMA20 > EMA50, and close in the inclusive upper half of that completed bar. Failed early price conditions retain B's original bar-six recheck; no intermediate scan. Original reference expiration, pending EMA exit, missing next open or actual occupancy at a qualified decision cancels admission. Entry executes at the next observed open. Original reference reservation, original-low/timeout/extension anchors and native exit producer are reused unchanged. No initial protective SL or fixed TP was introduced.

The single rule was frozen before outcomes, with weaker-than-desired predecision separation explicitly disclosed in DIAGNOSTIC.md and CAUSAL_REVIEW.md. Local pre-outcome freeze commit `175bc517`; SPEC SHA256 `76b94ef6c7b33fd90ab351f80f716042c44192f23fcfe19756be5c62273d008e`. No outcome-dependent rule or period edits. The freeze is local, not claimed as a pre-outcome remote registration.

Actual command (one serial owner):

```sh
python -u -m backend.research.rebuild.step7_kr3_winner_repair_v1 --input out/WINNER_PREPARED.json.gz --execute > out/WINNER_EXECUTION.log 2>&1
```

Exactly E-DEV2025, B-SEEN2026, E-SEEN2026 ran, once each. RESULT_INDEX.json and per-run ATTEMPT/RECEIPT bind code, inputs, policy, costs, result hashes and evaluation ordinals 61/62/63. Candidate hypotheses increment only 44→45; evaluations 60→63. All earlier budget fields and trial records reconcile to the inherited budget hash. Completed allocation is 3/3, failed/running 0, and no retry is allowed.

Prepared raw inputs remain in the worktree's out/ directory and are reproducible from the recorded existing source git ref `6d6335d1c9ad7ecb1e9597da85c2eb87635561e1`; source/request budgets are unchanged. The already-used 2026 loader only reads the approved input boundary and does not execute Q0. INPUTS.json and PREPARED_RECEIPT.json bind the exact calendars and input/cost hashes. Existing proxy cost evidence remains proxy evidence, not a claim of actual historical fills.

## Verification and ownership

- Root owns candidate implementation, freeze, shared budget, all three serial economic runs and final integration.
- Causality agent delivered CAUSAL_REVIEW.md and 17 synthetic boundary tests: original admission/reference clock, first-bar and fallback behavior, actual occupancy, next-open timing, original exit anchors, prefix invariance and one-shot execution claims. All passed before economics; no economic replay by this agent.
- Accounting agent delivered the frozen pure accounting module, 3 passing synthetic tests, DIAGNOSTIC_RESULTS.json and REPORT_ACCOUNTING.md. Stored origin-state/cost/calendar reconciliation ran once after actual results, without market replay.
- Local frontend scope validation and stored artifact/code/input hash checks passed. Inherited candidate/evaluation history is unchanged under budget projection. Remote final-head CI, merge and fixed-merge verification are required next; they verify stored results and changed synthetic boundaries, never rerun economics.
- External API calls 0, new source requests 0, unused OOS access 0, live orders 0. Inherited shared USD5 budget and source allocations are unchanged. Both subagent outputs are incorporated and their work is stopped.

Session completion is separate from economic success. Final remote run IDs, exact merge SHA and REPORT_ONLY closure belong to the completion receipt/comment after successful CI; this pre-merge report does not claim they already happened.
