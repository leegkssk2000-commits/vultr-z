# Work C / D — finite parallel implementation, not competing economic owners

Recorded 2026-10-21. Latest user asks whether the 5–7-strategy / combined3–4-entry-per-day plan is feasible, how other strategies are selected, and requests separately executable Work instructions without wasting time.

Economic owner remains CLOUD_WORK_COORDINATOR_ISSUE1358_V1, owner ref research-coordinator-claims/issue1358-cloud-work-v1. Existing A economic execution and B orderless Shadow remain unchanged. The user-facing C/D instructions are prepared, NOT launched. Do not mark their proposed branches or sessions as already existing/active.

## New verified input: current saved-ledger coverage
Read this directory's K126_S25_COVERAGE.json at commit065dc0d9a45f529348815b3e26769c8625663afb. On the common usedDEV window [2026-01-13T00:00Z,2026-09-15T00:00Z), K126 and S25 form an unconstrained151-row union:54 entry days,191 zero-entry days,18 days with>=3 entries,10 days with>=4. S contributes only7 entry dates outside K. Same-symbol/same-side holding overlap is7 pairs. This is a NEW saved-ledger coverage calculation, not a new FULL or joint-account profit result. It establishes a coverage deficit, not which regime or new strategy will be profitable.

Source ref308bd2deb7acaaacf1adb582206e78262d72c9d1:
- research/campaigns/scalp7_20261017/parallel_benchmark_v1/winner_timeout_real_20261021T1142Z/CHRONO_ROWS.json.gz: use carry_scenario_trades,126rows,gzipSHAe8ed07c3e8616814163e8b6e23a854cbb98b724b9c6ed1ad83c5cb28936382dc.
- research/campaigns/scalp7_20260915/broad_rebuild_v2/results/scalp7_squeeze_panic_cost4_parent_utc30m_v2.trades.json.gz:26total including1validation; use partition=rolling25 only,gzipSHA5f1af277aefb4e0887d723ef7a59311385551abf500cd4308693f9cbf6000e52.

## Selection decision
A small number of complementary mechanisms is a plausible development direction; five or seven labels do not prove profitability or daily coverage. Five new tests do not guarantee five survivors. Preserve successful controls, test finite batches, and stop manufacturing variants to fill counts.

Prioritize candidates by: exact executable rules and existing input availability; a concrete difference from previously rejected mechanisms; potential to add opportunities outside the K/S clusters; standalone cost-adjusted economics; then marginal portfolio contribution and independent validation. Do not require third-party audited profits as a condition for any trial. Public popularity and author claims are not ZEL PASS.

First preparatory roles: bounded-range reversion, failed-downside-break recovery, and independently specified multi-timeframe continuation. These are proposed research roles, NOT selected or profitable identities. Exact old RangeFade/BBRevert/RSI/Rider/Break/Supertrend rules cannot be replayed unchanged. A fresh role must identify an actual causal rule difference and source, not merely indicator parameters. Inspect existing sources before adding up to4 new primary documents only to resolve executable-rule gaps. Preserve long/short policy and report each side separately; do not assume long-only if a control has short trades.

No magic score/threshold: require internally valid input, no future leakage, explicit stop/exit/next-open semantics and existing SSOT economic/risk conditions. Cost1x/2x, realistic occupancy, losing-streak amount, DD kind, winner retention, daily opportunity coverage and unused-period validation must be visible. Parameter sweeps and re-labelling usedDEV as OOS are forbidden. Repeated tests on the same245-day usedDEV remain development; subsequent forward history is independent only if it was not already consumed for selection or tuning.

## Work C — candidate adapter implementation
Scope ZEL_WORK_C_DISTINCT_CANDIDATE_IMPLEMENTATION_20261021_V1.
Proposed branch work/zel-candidate-adapters-20261021, output-only directory research/campaigns/scalp7_20261021/parallel_candidates_v1/work_c/.
Read the prior cee8812c direction/BATCH_BOUNDARY, current failure receipts, and actual engine interfaces. Prepare at most3 distinct executable adapters in this Work, within the existing total new-batch cap5; source-backed SPEC.json + adapter.py + causal/synthetic tests + SOURCE_MAP.md + HANDOFF.json. Preserve root modules. Do not end with a source list. Missing fields are identified instead of guessed; an unready candidate cannot block a ready one. Transfer the first ready candidate to the existing owner immediately without waiting for all3.
C may run synthetic and code/interface tests. C must NOT run actual-price signal-density/economic screens/FULLs or dispatch workflows. Those are consumed once by the existing economic owner. No API keys or live access are needed for the deliverable. Do not create a new evaluation framework.
Exact first output: identity/source/mechanism difference/module hash/tests/one executable command/input contract/remaining gaps. Economics not run stays unmeasured.

## Work D — opportunity and portfolio contribution implementation
Scope ZEL_WORK_D_PORTFOLIO_OPPORTUNITY_CONTRIBUTION_20261021_V1.
Proposed branch work/zel-portfolio-coverage-20261021, output-only directory research/campaigns/scalp7_20261021/portfolio_coverage_v1/work_d/.
Use pinned saved ledgers directly from GitHub; VPS/Actions/token access is not a prerequisite. Confirm the already supplied arithmetic once, then compute missing daily coverage, overlap, time occupancy, concurrent losses and date distribution. Implement or reuse a small contribution_report.py with synthetic-ledger tests. No new signal or price-path FULL.
Report mean/median/zero days/days>=3/days>=4/days<3/consecutive no-entry days on UTC and explicitly bounded Berlin calendars. Account for DST and partial edge dates. Separate completed-entry timestamps from all intended/admitted entries, independent opportunity clusters, partial executions and handoff turnover. Existing-ledger deletion or greedy merging is only a diagnostic, not a full shared-state portfolio replay.
Prepare a fixed input/output contract to consume future owner-generated candidate ledgers. Use current SSOT capital/risk/arbiter settings only; missing NAV/MTM inputs stay unbound without blocking non-NAV coverage analysis. Never pick a simultaneous winner by future PnL. Whole-price chronology/newly available missed entries go back to the single owner for a later exact portfolio comparison. The D output does not make a new pre-execution gate for C or standalone trials.
Outputs DAILY_COVERAGE.csv, CONTRIBUTION.json, contribution_report.py/tests, short HANDOFF.md. Real missing-date/collision analysis is required even before new candidate results arrive.

## Ownership and consumption
These Work briefs do not start new agents or reservations. Check current branch/scope output before implementation to avoid duplicated C/D work. C and D may run in separate user-started Work windows, in isolated paths. A remains the only economic consumer, B keeps observation. Neither C nor D edits OWNER/CHECKPOINT/economic claims or consumption ledgers. Each writes only its designated branch and directory, uses skip-ci messages, and reads back its exact commit. If write fails, retain output and report the exact failure without claiming GitHub success.
When a Work delivers, the existing owner records exact artifact/commit actually used and the subsequent run/receipt. A received handoff is not an economic result. A can consume C while D is still finishing and can continue S independent of both.

## Current handoff comparison: new failure, not still waiting
At2026-10-21T13:30:24.918Z, remote read found the rate-aware guard had reached capacity and started the existing one-shot candidate at13:27:52.368Z (childPID2151642). At13:27:59 it exited1 with CONTEXT_FIT_CHANGED in run_handoff.py line51. SUMMARY and STORAGE_completion do not exist. The failing step compares the recomputed rolling-context fit hash to the pinned control, before disabled-control or new-child strategy replay. Do not call this a measured losing candidate or successful profit comparison.
Preserve original STARTED/log/freeze evidence. Diagnose the first source/context representation mismatch before any retry, do not delete markers, change the expected hash, bypass the check or launch a duplicate. The conditional15:40 result target is no longer confirmed. This technical repair belongs to existing A, not to user token setup, C or D.

## Safety and packaging
No source-price downloads, paid AI/API, new credentials, installations, servers, services, order/Paper/Live/deploy, master direct writes, force/reset, security-check removal, global-heavy bypass or cancellation of unrelated owners. Do not touch /home/z/z dirty worktree or stop its remote agent. Keep existing B writer/state/three locks intact.
User package is ZEL_PARALLEL_WORK_CD_20261021.zip, containing README_START_HERE.txt, WORK_C_CANDIDATE_IMPLEMENTATION.txt, WORK_D_PORTFOLIO_COVERAGE.txt, SOURCE_POINTERS.json and PACKAGE_MANIFEST.json. It contains instructions and verified source pointers, not full market data or credentials. Files exist as conversation downloads; a separate Work must receive the relevant TXT or ZIP explicitly. Never pretend a missing attachment was read. No separate Work is claimed started here.
