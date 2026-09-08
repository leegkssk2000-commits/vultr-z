# Result-before-outcome causal review

Scope: `KR3_REQUAL_WINNER_REPAIR_AFTER_PR1213_V1`.
Owner: `winner_causality`; runtime/economic writer: root. This review uses source
code and synthetic observations only. It creates no market replay, paid request,
candidate, evaluation ordinal or shared-budget reservation.

Direct parent is `W6_RECHECK_ORIGINAL_REFERENCE` (B), with the original KR3
reference clock and `anchored_path` exit owner retained. D is not an execution
parent. The only candidate change is first-followup-close confirmation, otherwise
the original sixth-followup-close recheck. Confirmation requires the strict
origin-high breakout, `close > EMA20 > EMA50`, and the existing upper-half
predicate, all observed on the completed first followup bar. A failed first
confirmation cannot trigger at bars two through five. Original signal eligibility
is evaluated at the origin and cannot be repaired by a later candle.

## Required causal boundaries

- Advance the unchanged reference clock using the current completed bar before
  deciding confirmation. A released or EMA-exit-pending reference cannot enter.
- A successful early confirmation is terminal for this opportunity. If the actual
  same-symbol slot is occupied, cancel it immediately; do not retry at bar six.
  Later bar-six failure never retroactively removes an actual early entry.
- No use of stored B exit times or outcomes in admission. Actual exit paths must
  be valued by the inherited owner from the candidate's actual next-open fill.
- Preserve origin low, origin timeout, origin extension-decision index and
  unchanged priority. Do not transfer pre-entry low-breach state into the trade.
- Reference reservation is not actual position occupancy. Recheck failure and
  actual early exit do not release the reference early. Same-symbol decisions at
  or before a prior actual exit retain the original ownership exclusion.
- `feature_available_ts` for candidate confirmation/entry must be the confirming
  close. The inherited parent entry trace labels the origin feature timestamp;
  the new adapter must retain origin provenance separately and label confirmation
  availability correctly without editing the frozen parent owner.
- Held MFE/MAE begin at the actual entry bar, never the origin or waiting bars.
  Pending tail confirmation and actual terminal-mark position remain distinct;
  no fabricated liquidation or risk-R/SL/TP.
- Changing future observations may change subsequent exits and economics. It must
  not change decisions that were already determined by the common prefix.

The first-followup rule is an unproven DEV hypothesis, not an economic conclusion.
The parent owner is responsible for recording its observed pre-outcome separation
evidence and freezing both periods and all three permitted executions together.
No numerical threshold sweep, alternate delay evaluation, parent replay or
outcome-dependent amendment belongs to this review.

## Executed test evidence

Command (once locally):

```text
python -m unittest backend.research.rebuild.test_step7_kr3_winner_repair_v1 -v
Ran 17 tests in 0.017s
OK
```

The changed-boundary tests passed with actual process exit code 0. They cover
strict first-bar breakout/EMA/upper-half confirmation and sixth-bar fallback,
original ineligibility, confirmation availability, irreversible early entry,
reference EMA cancellation, actual runner cancellation without a sixth-bar retry,
original low/timeout/extension anchors, reference retention after actual low exit,
no waiting-period low-state inheritance, held excursions, prefix decision
invariance, separate tail waiting/marking, and durable claim/failure behavior.

The lifecycle failure test patches verification and the replay callable inside an
isolated temporary allocation. It demonstrates one consumed synthetic claim, no
false completion receipt/index and no retry. It is not formal authorization, a
market replay or an allocation in the shared campaign ledger. The inherited
parent test suite and completed economic validations were not rerun.

The new adapter correctly labels confirmation availability at the confirming
close and calls the unchanged inherited exit owner. No remaining causal/runtime
blocker was identified in this bounded source review and the listed tests. This
does not establish economic improvement, source eligibility or G5A qualification.
No deployment is needed for these research tests. Root owns the final integration
validation, candidate/input freeze, actual economic dispatch and remote CI.

## Pre-outcome counterexample limitation

The root's single-rule stored-ledger diagnostic reports first-bar confirmation in
21/56 harmed-original-winner opportunities and 29/85 A opportunities excluded by
B; the latter include 23 historical A losses and six wins. These labels are
diagnostic only and were not consumed by the replay. This is weak separation,
not an established winner discriminator. The same condition can revive losses.
The one bounded hypothesis must therefore report restored actual winner profits
and newly revived actual losses together, retain the B risk/cost comparisons and
make no post-outcome condition changes. The causal reviewer did not independently
rerun that ledger diagnostic or any candidate economics.
