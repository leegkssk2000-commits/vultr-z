# Issue1358 V3: one frozen EMA21 limit entry hypothesis

Status: DESIGN_HYPOTHESIS_IMPLEMENTED; P1 shared-queue repair1/2;
final exact-source CI/review pending.
Economic result: NOT_RUN. No profitability or G-stage claim.

The Work directly recovered artifact11305382754 using the dedicated GitHub
artifact download operation. The independently decompressed payload matched
`3da2f940e532be2c04ea25386782ef5732b12eb99d6f8203473ee3d57433d0b3`.
INPUT_RECEIPT.json records six assets, 164490 continuous minute rows, including
157290 rows in the already consumed fixed development window. Only structural
checks were made; no new real-price setup/census or economic replay preceded
an execution reservation. Freshness, unused OOS, exchange fills, volume units,
L2, funding/mark and account NAV remain uncertified.

The original SOURCE_RULE_AVAILABILITY and failed source-selection receipts on
the coordinator branch remain historical evidence. User amendment5999975905
supersedes their old requirement to await unpublished author rules or old real
orders for a new internal hypothesis. The original VPS v7 report is not a
dependency of this design. PR1359 remains completed at
f2c30586c3552d9e4fa32e253af365fc3a6d112e; its diagnostics and2/2 repair were
not replayed.

DESIGN_HYPOTHESIS.json freezes the single hypothesis before economics. Native
Squeeze first-release setup and positive-parent lifecycle are retained. After
receipt, a fixed BUY_LIMIT at native EMA21 becomes effective at the strict next
minute. It expires at the next30m boundary. The hypothesis exchanges lower
entry price for missed rallies, adverse selection and pending occupancy.
It is an INTERNAL_HYPOTHESIS, not an attributed author rule or established edge.

The failed Rider mechanism required a15m range impulse, pullback and closed-bar
reclaim, followed by market entry and pivot lifecycle. This candidate instead
uses the native30m squeeze episode, a fixed resting price, touch/expiry and
native Squeeze lifecycle. The old dist21_atr<=1.4 market veto and nonpositive
momentum exit child are also distinct. No9-trade threshold fitting was used.

Every eligible setup gets exactly one census disposition, including gate/stale
or occupied rejection, unfilled expiry, pending-end, filled unresolved and
completed outcomes. All derived events are MODELED_DEVELOPMENT_EVENTS. Order
snapshots retain terminal state and last processed minute for restart/dedup.
Economic execution itself remains permanently nonretryable after its claim;
synthetic restart support does not replenish that budget.

An OHLC touch models full-size entry at the limit and pays the unchanged full
reference taker costs at1x and2x. A lower opening gap keeps the adverse limit
entry-price bound rather than granting price improvement. A gap below SL exits
at the adverse opening price; same-minute entry/SL chooses entry then loss.
These are explicit pessimistic accounting assumptions, not executable-price
or maker-queue evidence. Management/excursions exclude the fill minute and its
incomplete30m bar. Actual impact, queue/nonfills, funding, liquidation and NAV
are not certified. Reference trade-bps sums are not account returns.

The source verification job uses synthetic data only. The economic job requires
an exact one-file activation child of the reviewed parent, a separately
published immutable approval ref, all source/input/window/fit/cost pins, and
global-heavy concurrency. The official shared-group endpoint must prove this
exact economic job is its sole active lease, matched to the actual job API.
Other active heavy owners or endpoint/permission/identity uncertainty cause a
preclaim HOLD without consuming the batch. Unrelated ordinary CI is outside
this shared group; pending heavy owners keep their queue positions.
Atomic permanent ref creation precedes all real-price feature generation,
including the opportunity ledger. Failed or
interrupted claimed executions preserve the claim and original exception.

Allocation: #1358 one candidate, total FULL<=2; candidate once. Saved exact
parent control is reused only with the bound unchanged conditions and matching
setup-stream SHA checked inside the candidate execution. A mismatch stops the
claimed run without silently replaying the parent. No extra period/variant is
authorized. All other lane owners, failures and budgets are preserved.

Independent saved-result audit code is also included. It imports no economic
model and checks raw-minute first-touch/expiry, occupancy, adverse fill/SL
accounting, full census, new-trade metrics and paired deltas. Old parent metric
summaries are reused without repeating its completed9-trade diagnosis.

P1 review4187319851 identified GitHub's default single-pending shared group
replacing a previous pending evaluation despite cancel-in-progress:false.
Minimal repair1/2 sets queue:max and excludes nonactivation pushes from joining
the shared group. Only this campaign workflow changes; other owners/queues and
the old PR1359 repair2/2 are preserved. No economic run preceded the repair.
See P1_REPAIR.json for the original setting failure and amended checks.

Next action: final exact-source CI and independent review; resolve findings within
the implementation repair allowance, then publish separate approval and
activation only after fresh global owner/job checks. Retrieve results and
independently audit full census/cost/paired outcomes before retain/reject.
No economic execution is represented as a preparation check.

Validation: focused synthetic integration/ownership tests and canonical
`npm run --prefix frontend/z-os-app-source validate`; detailed receipt saved
in TEST_RECEIPT.json. Deploy/service/collector/order action: DO_NOT_RUN.
Rollback before activation: revert only this new isolated campaign, its two
modules, tests and workflow; preserve every original source and evidence ref.
After claim, rollback never removes the permanent execution claim.
