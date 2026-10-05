# Issue1358 V3: one frozen EMA21 limit entry hypothesis

Status: DESIGN_HYPOTHESIS_IMPLEMENTED; P1 shared-queue repair1/2;
final exact-source CI/review pending; shared producer queue policy OPEN.
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
this shared group; this job preserves pending owners with queue:max. The remaining default-single producers still prevent a repository-wide guarantee; activation is held by an explicit preclaim guard.
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
accounting, every later stop/gap/management terminal price/reason/clock,
completed and unresolved MFE/MAE from received raw-minute prefixes,
independently reconstructed native momentum, complete management census,
published summary candidate/signal/trade/unresolved counts and statuses, new-trade metrics and paired deltas. Old parent metric
summaries are reused without repeating its completed9-trade diagnosis.

Review4189754464 identified that three published paired-breakdown components
were not independently bound. The stdlib auditor now reconstructs every common
row and its identity/exit/net/delta fields, parent-loss and parent-winner change
sums, and exact field sets in both RESULT and SUMMARY. Separate corruption
controls cover each aggregate and the row collection. This is a new paired
economic-breakdown cause repair1/2; it does not reset or repeat the completed
saved-position or summary-census repair ledgers.

P1 review4187319851 identified GitHub's default single-pending shared group
replacing a previous pending evaluation despite cancel-in-progress:false.
Minimal repair1/2 sets queue:max and excludes nonactivation pushes from joining
the shared group. This campaign workflow received the initial fix; the later minimal Liquid6 cancel repair is disclosed below. Other owners/budgets and
the old PR1359 repair2/2 are preserved. No economic run preceded the repair.
See P1_REPAIR.json for the original setting failure and amended checks.

Review4187453910 found one of54 current shared-group producers (Liquid6 rescue)
used cancel-in-progress:true and could kill a permanently claimed execution.
Its minimal shared-lock repair moves the same group onto the unchanged economic
job, sets cancellation:false/queue:max, and separates source-only PR compilation
from the existing economic job. PRs never replay that other lane; its strategy,
inputs, budgets and existing branch/dispatch triggers remain unchanged.
No other producer is modified. This source policy repair must be merged into
default master before #1358 activation; no incoming producer may cancel the
claimed job. Historical-ref dispatch and deliberate manual cancellation remain
trusted-maintainer controls; do not dispatch old canceling versions during a
claimed execution. See CROSS_WORKFLOW_CANCEL_REPAIR.json. No service/collector
is started and no other lane's economic model is invoked by this repair.

Review4187506290 is addressed under user amendment6005135850 without editing
the other52 producers. The same activation may use workflow attempts2 or3 only
when every earlier economic job is durably recorded completed/cancelled with
no assigned runner and no steps, the current run/head/job/API attempt matches,
and an authenticated exact read proves the fixed claim ref absent. Attempt4+,
started or unknown jobs, permission/transport ambiguity, an existing claim,
claim-response loss and claim-after-failure all stop before the model. Atomic
creation of the unchanged fixed ref remains the only economic execution right.
Synthetic API/race fixtures cover both allowed recoveries and every fail-closed
case. SHARED_QUEUE_POLICY_HOLD.json retains the52-workflow inventory and the
remaining trust boundary; this is not a claim that GitHub natively guarantees
multi-pending FIFO.

Exact review4189972609 found that omitted runner/step keys could be mistaken
for empty evidence. V4 repair2/2 now requires all evidence keys to exist with
exact types: integer job id, runner id exactly0 or null, runner name exactly the
empty string, and steps exactly an empty list. Missing keys, wrong types and
steps:null fail before claim/model. The lifetime V4 repair cap is now consumed.

Running-job cancellation is separate. Liquid6 cancel:false/queue:max must reach
default master, and current reachable producers must have no cancel:true or
unknown setting before activation. Historical-ref manual dispatch and admin
cancellation remain trusted controls. No blanket foreign workflow edit, model
replay, schedule change, signal/census generation or economic claim occurred.

Next action: exact-source CI and independent review of the V4 admission repair;
normal merge without chasing unrelated result-JSON churn, default-master source
parity and Liquid6 verification, then publish separate approval and activation
only after fresh global owner/job/claim checks. Retrieve results and
independently audit full census/cost/paired outcomes before retain/reject.
No economic execution is represented as a preparation check.

Validation: focused synthetic integration/ownership tests and canonical
`npm run --prefix frontend/z-os-app-source validate`; detailed receipt saved
in TEST_RECEIPT.json. Deploy/service/collector/order action: DO_NOT_RUN.
Rollback before activation: revert only this new isolated campaign, its two
modules, tests and workflow; preserve every original source and evidence ref.
After claim, rollback never removes the permanent execution claim.
