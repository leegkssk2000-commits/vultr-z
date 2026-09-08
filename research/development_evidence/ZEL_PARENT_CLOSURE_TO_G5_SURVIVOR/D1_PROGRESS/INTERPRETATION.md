# D1 actual result and finite-scope disposition

**D1 is not adopted: both periods deteriorate relative to the exact selected D. G5A HOLD remains.** Rule/implementation/SPEC/results are unchanged after measurement. This note derives quantities only from the saved complete ledger and ACCOUNTING.json. Both periods are already-used development data. Units are fixed equal-notional trade-bps, not account return/MDD. No initial protectiveSL/fixedTP and the original proxy fee/spread/impact/absolute-funding/floor costs remain explicit.

## Exact D inheritance succeeded; the added admission failed

|Evidence|DEV2025|SEEN2026|
|---|---:|---:|
|All original D completed positions preserved|108/108|34/34|
|All original D open positions preserved|0/0|2/2|
|Common original-D net change|0.00|0.00|
|D completed winner capped-profit retention|100.00%|100.00%|
|New completed entries|33|17|
|New wins / losses|8 / 25|4 / 13|
|New positive net amount|+4,260.35|+2,042.64|
|New negative net amount|-12,055.41|-4,253.53|
|New net amount = total D1-D delta|-7,795.06|-2,210.89|
|New gross amount before costs|-7,080.25|-1,818.32|
|All-cost2 D1-D delta|-8,509.87|-2,603.46|
|Marked DD increase|+4,655.74|+2,077.56|

Every original-D position's entry/exit timestamps and prices, net/gross/cost2/cost/fee/funding, MFE/MAE, exit anchor, extension/low-exit state and open marks were compared across17 fields and match. This is an observed same-input property, not a guarantee of future preservation. Original D source/result files were not changed. All four-way terminal deltas reconcile: common0 + removed0 + new delta + closed/open transitions0. Net already contains costs; no second addition of savings/losses.

## Why recovering old winners did not repair economics

Relative to KR3's winners that D had harmed, D1 restores7 to completed wins in2025 and4 in2026. The capped restored original profit is3570.04/2042.64 trade-bps; actual restored-child profits are4077.91/2042.64. These are subsets of the new-entry groups, not extra amounts to add. There are no newly harmed existing D completed winners in either period.

Old KR3 winner labels describe the old entry/exit path. The same origin, entered after six observed bars with D's shifted exit geometry, is a different economic opportunity. The precheck's positive original-KR3 sums were explicitly NOT a forecast of delayed D1 profit. The full replay now rejects that hypothesis: admission expands to more losing opportunities in both periods, and their gross sums are already negative before costs.

The two known missed HYPE winners do now enter and finish positive, but their actual D1 profits are only410.37 and1110.33 trade-bps, versus the prior KR3 profits3352.62 and3691.13. The old SOL winner remains blocked by the unchanged selected reference reservation. This is not permission to add the old profits, remove a symbol, or retroactively undo a prior entry.

D1's total2026 HYPE increment is+1274.99, while every other symbol's increment is negative. Excluding HYPE's saved contribution leaves-3485.89; that is sensitivity accounting, not an executable symbol-exclusion backtest. In2025 only BTC's added contribution is positive. The broad new-admission improvement hypothesis is therefore not supported.

Legacy shared accounting keys mentioning B (e.g. newly_harmed_B_completed_winners, change_vs_B) are reused helper field names. In this invocation the passed direct parent is EXACT D, never B. A85 is explicitly not applicable here. This note does not rename or alter saved owner output.

## Execution provenance and first transport failure

Initial run34226568725/job102062092876 passed source/hash preparation and16 synthetic tests, but rejected a git push containing a workflow file because the Actions token lacks workflows permission. The shell stopped before execute. Artifact10055961169 contains only original SPEC/DEV2025 ATTEMPT/BUDGET; full log confirms no execution command was reached. The initial local reservation is preserved, not deleted or called a completed economic experiment.

Transport recovery uses the same pending ordinal65, original SPEC seal8feaab7c162a0a23694db0e444072ddb99ed2b9a1e316c3a70687bea6113c4b1 and original candidate/code/input hashes. TRANSPORT_RECOVERY.json binds the old terminated job, immutable reservation bytes, explicit pre-execution failure, and actual new runtime identity. No old run ID is impersonated, no failed/unknown economic attempt is retried, and no extra allocation is created. The Actions job now pushes only evidence/budget, not workflows. Workflow edits are done separately by the authorized repository connector; no token scope elevation was attempted.

Actual two-period execution run34227310393/job102064547624 completed successfully. The recovered2025 reservation/start was pushed at74fad9c4ade1725f44d89ca33cc5555c4ae02d96 before the first actual replay. The2026 real attempt was pushed at79af50ac646fcf17e0611f537a8b5c67daa41f07 before its execution. Both exact remote ref values were checked before compute. Final accounting commitb142440d364eae06cab4488b46bbfd4cda742b19. New candidate46 / evaluations65,66; cumulative hypotheses45→46 and actual evaluations64→66. Transport failures are separate from economic trials and remain recorded.

## Closure

Final workflow removes both execution/recovery dispatches, writers, input downloads and retained credentials. It only verifies both mandatory completed receipts/results/attempts and consumed allocation2/2. Missing results fail; they never cause replay. Three closure tests supplement the16 pre-economic synthetic tests:19/19 localPASS. The narrow existing STEP7 route checks this scope's saved results without regenerating old strategies. The router change is not a candidate rule or gate relaxation.

Final CI, review and fixed-merge verification remain separate completion facts; consult the PR closure comment. No operating baseline changed. D remains the selected development comparator; D1 is a failed branch preserved for exclusion from repeated identical trials. No D2, new market collection, unused OOS, provider API call, live order or deployment was performed. A future change cannot claim improvement by preserving winners alone while adding larger new losses, or by inspecting the same periods and calling them independent.
