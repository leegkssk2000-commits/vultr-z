# K.P evidence closeout — saved amounts, not a new strategy result

## What changed in the evidence

The current 30m parent `scalp7_keltner_hg_parent_utc30m_v2` stays frozen. Its completed ledger has 119 rows (validation 10, rolling 109). The previous missing-partial count is 32 across all 119 rows, not 32 of rolling109.

A separate saved-only arithmetic implementation reconstructs each trade's model gross amount from entry price, effective original stop/fallback, the recorded after-stop MFE, the frozen once-only 2R/10% partial rule, and terminal price. Reported gross/net are comparison targets, not back-solving inputs. It does not import the strategy, call a source loader, regenerate a signal, or replay price history.

All119 gross amounts reconcile; maximum absolute residual is 2.2737367544323206e-13 bps. The32 partial cases reconcile too (31 rolling, 1 validation). This closes a **model-amount reconciliation gap**, not the missing raw event archive. Partial timestamps remain null; original events recovered=0. The final MFE cannot tell us which bar first triggered a partial. Actual fills, chronological partial cashflows, account NAV/DD and historical funding settlements are not certified.

The original engine file last changed at `95af7914a01b24e9077ffcb28bd8f2233bca5541`, 2026-09-15T19:15:15Z, before the parent run. Engine and parent hashes are pinned by the audit. Existing data/results are not overwritten or reclassified as unexecuted.

## Why the cost2x win rate drops

Same109 rolling trades, same quantities/exits; only reference cost is doubled. No leverage change.

| Saved cohort | T | Net1x bps | Net2x bps |
|---|---:|---:|---:|
| All rolling |109|5947.631127|4308.317188|
| Positive1x to nonpositive2x |27|87.334275|-320.382629|
| Reached the frozen2R partial (post-outcome label) |31|10646.802442|10175.420658|
| Did not reach it (post-outcome label) |78|-4699.171314|-5867.103470|

Of27 cost flips,24 have STOP_FIRST,2 the frozen5bar scratch,1 max-hold exit. Of those27,23 have terminal prices matching the already-existing fee-adjusted BE+2bps formula (within arithmetic tolerance). Thus much of the65-to38 positive-trade count change is small-profit classification sensitivity, not a different signal or higher leverage.

The31/78 split uses future outcomes and is **not an entry filter**. It says that large-progress trades finance the rest of this saved sample, not that those winners can be selected in advance. Raising the BE price after seeing the stress result, removing losing months/symbols, or suppressing all78 nonpartial trades would be a new strategy and is not performed or authorized here.

The existing5bar scratch cohort is21 trades, Net1x -1586.057111bps and Net2x -1900.154818bps. This is an attribution, not evidence that earlier scratch, wider stops or removing scratch improves the full replay.

## G4 / G5 decision boundary

- Development evidence: preserve the positive frozen parent.
- Saved model amount reconciliation: PASS for119 rows under pinned model/state semantics.
- Original partial event archive / account-level economic certification: NOT_COMPLETE.
- Official G4 PASS / current candidate G5 input eligibility: NOT_DETERMINED.
- G5 run, new FULL allowance, new candidate, changed leverage, strategy mutation, LIVE: none.

`backend/research/prep/g5_validation_contract_v1.json` is a G5_PREP harness with execution NONE and selection/promotion false. It is not an admission receipt for this exact30m parent. `economic7_core_promotion_roadmap_v2.json` is a longer-term Core roadmap, not a substitute exact G4 gate. No legacy4h Keltner, Active5 1h or TrendRider Broad threshold is imported.

The remaining governance action is explicit candidate-to-contract binding (or an explicitly approved new version when the old one does not apply), not another broad search and not inventing thresholds to fit this result. Before any independent run, freeze its data/window/cost/account definitions and execution allocation. Reusing the inspected245d history is not fresh validation. The absence of a contract is not economic FAIL.

## Next actual scope

1. Reuse this amount audit; do not repeat the completed parent replay to obtain the same sum.
2. If a genuine raw partial archive becomes available, join by exact trade identity and append timestamp/quantity evidence; do not relabel these inferred amounts as original events.
3. Resolve the exact candidate's G4-to-G5 admission contract and separate independent-window authorization. Parent validation must not wait for the separate unmeasured HG1997 model.
4. Keep improvement research separate. The present findings support preserving big winners and measuring cost-sensitive small exits; they do not prove a new profitable rule. No new BE/partial/trailing addition is claimed; those already exist.
5. Squeeze frozen validation remains next in the strategy queue; no new Squeeze run is launched here. SR #1347 and HG1997 #1348 remain untouched.

## Reproduction and limits

Run `python3 -m unittest discover -s tests -p test_kp_saved_evidence_closeout_v1.py -v`, then `python3 scripts/kp_saved_evidence_closeout_v1.py --repo-root . --output-dir <new-output-dir>`.

The dedicated workflow checks saved files only, has contents:read permission, and has no SSH, secrets, remote commands, deployment or schedule. Existing guard, allowlist, immutable source, frontend and old result files are unchanged. Local synthetic tests:18 passed. Exact GitHub-head CI status must be checked separately.

Sources are pinned in the script; per-trade inferred checks are produced in the CI artifact `audit/KP_AMOUNT_AND_COST_DIAGNOSIS.json`. The original ledger remains the permanent input. This report is a research evidence update, not a profitability or execution promotion.
