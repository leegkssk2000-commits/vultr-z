# K.P evidence closeout — saved amounts, not a new strategy result

## What changed in the evidence

The current30m parent `scalp7_keltner_hg_parent_utc30m_v2` stays frozen. Its completed ledger has119 rows (validation10, rolling109). The previous missing-partial count is32 across all119 rows, not32 of rolling109.

A separate saved-only arithmetic implementation reconstructs each trade's model gross amount from entry price, effective original stop/fallback, the recorded after-stop MFE, the frozen once-only2R/10% partial rule, and terminal price. Reported gross/net are comparison targets, not back-solving inputs. It does not import the strategy, call a source loader, regenerate a signal, or replay price history.

All119 gross amounts reconcile; maximum absolute residual is2.2737367544323206e-13bps. The32 partial cases reconcile too (31rolling,1validation). This closes a **model-amount reconciliation gap**, not the missing raw event archive. Partial timestamps remain null; original events recovered=0. Final MFE cannot identify which bar first triggered a partial. Actual fills, chronological partial cashflows, account NAV/DD and historical funding settlements are not certified.

The original engine file last changed at `95af7914a01b24e9077ffcb28bd8f2233bca5541`,2026-09-15T19:15:15Z, before the parent run. Engine and parent hashes are pinned by the audit. Existing data/results are not overwritten or reclassified as unexecuted.

## Why cost2x win rate drops

Same109 rolling trades, same quantities/exits; only reference cost is doubled. No leverage change.

| Saved cohort | T | Net1x bps | Net2x bps |
|---|---:|---:|---:|
| All rolling |109|5947.631127|4308.317188|
| Positive1x to nonpositive2x |27|87.334275|-320.382629|
| Reached the frozen2R partial (post-outcome label) |31|10646.802442|10175.420658|
| Did not reach it (post-outcome label) |78|-4699.171314|-5867.103470|

Of27 cost flips,24 have STOP_FIRST,2 the frozen5bar scratch,1 max-hold exit. All24 STOP_FIRST cost-flip trades have terminal prices matching the already-existing fee-adjusted BE+2bps formula. Of these,23 have no prior partial and approximately+2bps whole-trade Net1x. One has an earlier2R partial, so a BE terminal price does not mean that its entire trade net is+2bps.

Review correction: initial code/report counted23 terminal matches by incorrectly excluding partial trades; reviewer4172857194 identified the omitted24th match. Whole-trade+2bps nonpartial matches remain23. The new regression separates these quantities. The correction changes attribution labels, not saved or reconstructed economics.

The31/78 split uses future outcomes and is **not an entry filter**. It says large-progress trades finance the rest of this saved sample, not that those winners can be selected in advance. Raising BE after seeing stress results, removing losing months/symbols, or suppressing all78 nonpartial trades would be a new strategy and is not performed or authorized here.

The existing5bar scratch cohort is21 trades, Net1x -1586.057111bps and Net2x -1900.154818bps. This is attribution, not evidence that earlier scratch, wider stops or removing scratch improves full replay.

## G4 / G5 decision boundary

- Development evidence: preserve positive frozen parent.
- Saved model amount reconciliation: PASS119 under pinned model/state semantics.
- Original partial event archive/account-level certification: NOT_COMPLETE.
- Official G4 PASS/current candidate G5 input eligibility: NOT_DETERMINED.
- G5 run/new FULL/new candidate/changed leverage/strategy mutation/LIVE: none.

`backend/research/prep/g5_validation_contract_v1.json` is a G5_PREP harness with execution NONE and selection/promotion false. It is not an admission receipt for this exact30m parent. `economic7_core_promotion_roadmap_v2.json` is a longer-term Core roadmap, not a substitute G4 gate. No legacy4h Keltner, Active5 1h or TrendRider Broad threshold is imported.

The remaining governance action is explicit candidate-to-contract binding (or an explicitly approved new version when the old one does not apply), not another broad search and not thresholds fitted to these results. Before any independent run, freeze data/window/cost/account definitions and execution allocation. Reusing inspected245d history is not fresh validation. Missing contract is not economic FAIL.

## Next actual scope

1. Reuse this amount audit; do not repeat completed parent replay for the same sum.
2. If genuine raw partial archives become available, join exact trades and append timestamp/quantity evidence; do not relabel inferred amounts as original events.
3. Resolve current candidate G4-to-G5 admission and separate independent-window authorization. Parent validation must not wait for unmeasured HG1997.
4. Keep improvement research separate. Findings support preserving big winners and measuring cost-sensitive small exits; they do not prove a new profitable rule. BE/partial/trailing already exist.
5. Squeeze frozen validation stays next; no Squeeze execution here. SR1347 and HG1997-1348 remain untouched.

## Reproduction and scope

Run `python3 -m unittest discover -s tests -p test_kp_saved_evidence_closeout_v1.py -v`, then `python3 scripts/kp_saved_evidence_closeout_v1.py --repo-root . --output-dir <new-output-dir>`.

The dedicated workflow reads saved files only, has contents:read, and no SSH/secrets/remote commands/deployment/schedule. Old guards, allowlists, immutable source, frontend and old results are unchanged. The user's explicit non-frontend research request and AGENTS exception are recorded in SCOPE_AUTHORIZATION.md; it grants no economic or promotion authority.

Local synthetic tests:19 passed, including partial-then-BE attribution. Exact final GitHub-head CI is recorded separately; predecessor checks are not inherited as new tests. Sources are pinned in the script; per-trade checks are produced in artifact audit/KP_AMOUNT_AND_COST_DIAGNOSIS.json. Original ledger remains permanent input. This is an evidence update, not profitability or execution promotion.
