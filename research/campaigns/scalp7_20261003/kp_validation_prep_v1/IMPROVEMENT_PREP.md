# Separate improvement preparation — NO_SUPPORTED_CHANGE

**NO_SUPPORTED_CHANGE** is the current conclusion for a new trading rule. The frozen parent remains unchanged. No new strategy, economic identity, profit estimate, stop/BE/partial/trailing/scratch modification or unseen-data tuning is proposed by this preparation. A later improvement would need separate identity, development history, control and authorization; it cannot inherit the parent's qualification.

## Existing seen evidence and the exact causal gap

Reuse `research/campaigns/scalp7_20261003/kp_saved_evidence_v1/REPORT.md` as archived attribution, not a new computation. Its119 amount reconciliation and32 modeled partial amounts are completed. It documents27 of109 rolling trades flipping from positive cost1x to nonpositive cost2x;24 terminal prices match existing fee-adjusted BE, including23 no-prior-partial approximately+2bps whole-trade Net1x. It also documents that31 post-outcome2R-partial trades finance the saved sample while78 other trades lose collectively. None of these outcome-defined cohorts is an entry feature.

These facts motivate recording what was known when BE armed and what actually happened afterward. They do not identify a usable causal filter or prove that wider initial stops, later BE, earlier scratch, different partial fractions or a different runner improves a chronological replay. Raw BE/partial trigger clocks, original chronological residual quantity and decision-time MFE/MAE/cost history were not recovered by the model-amount audit. No variation is justified without those fields and a separately authorized development control.

The old report's `NOT_DETERMINED` admission statement is historical; PR1350's actual approved limited baseline admission supersedes that uncertainty prospectively. This observation preparation neither repeats that admission nor expands it.

## Passive fields to preserve

| Observation event | Minimum fields | Causal use boundary |
|---|---|---|
| Signal/entry | Parent/runtime identity, rule/code/config/source hashes, symbol/side, UTC bar close/available and actual decision clock, new request/quote native/receipt/usable/process clocks, initial price/effective stop/R/original qty | Features known at that event only; modeled nextopen and observed quote remain distinct |
| BE armed/moved | Event ID/hash, trigger and processing clocks, pre-event stop and proposed new stop, quoted sideprice, **running-so-far** observed MFE/MAE, held completebars, original/residual qty, then-known fee/spread/slippage/funding values and their hashes | FinalMFE/MAE and later winner labels forbidden as inputs |
| Partial | Trigger/request/quote/receipt/process clocks, once-only2R/10% parent rule, original/residual qty before/after, notional/cost decomposition, causal event references | No inferred past partial timestamp or original exchange-fill claim |
| Exit/scratch/trail | Frozen trigger/reason code, clocks, pre-exit qty/stop/runningMFE/MAE, later new quote evidence, separate action clock | Do not equate observed paper with broker execution or late quote with prior OHLC fill |
| Funding/cost | Signed source settlement rate/time/mark and exposure-before-boundary; fee schedule/side spread/evidence slippage; separate reference reserve | Missing data null/block; no double funding reserve or second spread debit |
| Future observation | Later receipt/process clocks and causal prior-event link; label-only eventual outcome | Post-event diagnostics only; never entry or retroactive trigger feature |

Recording must be passive: observations are appended after a parent decision and cannot write candidate decision/stop/position parameters. Synthetic recording-enabled vs disabled decision parity is the integration acceptance check. Actual quote/source collection remains off in this task. Newly opened parent unseen outcomes would become seen for an improvement variant; access/use history must say so. Future diagnostic selection must use separate development data, not W2/W3 tuning.

The specific local adapter integration and its available event fields are reported in the preparation implementation receipt. Fields not emitted by the old shared paper event stream remain explicitly absent and block original-event claims; they are not fabricated from terminal MFE. Any missing BE callback trace producer requires future isolated source instrumentation approval before claiming the table complete. No global/common strategy engine or shared21identity/SR/HG1997 state is modified here.

## Boundary

This file prepares observation semantics and records the absence of a supported rule change. It runs0 economics,0 oldFULL,0 amount re-audit and0 newcollection. Formal SL/TP/partial/trailing/MFE-runner G6 research remains after same-lane reviewed G5B terminalPASS with separate scope. Parent OOS validation proceeds on the frozen parent independently of whether an improvement hypothesis is later supported.
