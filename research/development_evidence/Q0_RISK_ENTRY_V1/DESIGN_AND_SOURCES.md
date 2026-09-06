# Q0 entry-risk study — fixed before new outcomes

One user-authorized entry-notional experiment, Q0_RISK_ENTRY_V1, reallocates the unused conditional slot from PR1192. Prior cumulative25 becomes26 only on successful new candidate measurement. Q2 stays NOT_RUN, Q0 DEV_INCONCLUSIVE and Q1 DEV_REJECT. The fixed-exposure analytical control is not another strategy, and rerunning the exact frozen result consumes no new hypothesis. No alternative sigma/window/ref/parameter result is permitted.

The scope is a DEV research amount-weighting adapter. It does not alter original signals, fills, stops, times, holding, occupancy, operating sizing or any G5/G6/G7/G11 authority. All original results remain sealed. Positive multipliers cannot alter individual trade signs or unit win rate. Differently weighted mixed-sign simultaneous close groups can change their aggregate sign; such grouping changes are reported separately from original pinned loss runs, never presented as signal improvement.

Calendar: 2025-01-29 00:00 UTC through 2025-12-29 00:00 UTC, end exclusive for entries and inclusive for terminal marks. Original seven symbols and immutable research price-taker unit cost authority. At an original UTC daily signal close, that just-completed daily return is available before the next-open fill at the same timestamp. The reference excludes all closes at or after evaluation start. Ref38 returns (39 completed closes), ddof1, sigma_ref=0.03290943045427639. Window exactly30, m=min(1,ref/current), no zero-vol repair. All choices and numerical check tolerance1e-7 amount-bps are frozen before new outcomes.

Counterfactual C uses a single ex-post k determined by B holding-time-weighted notional. This uses future holding durations strictly in accounting and is never supplied to the causal weight calculator. It is not a tradable risk target. The bootstrap conditions on this realized analytical normalization; it does not estimate the additional sampling uncertainty of selecting k.

Research decision: B terminal net and cost2 terminal net positive; terminal net no lower than C, daily marked DD and maximum simultaneous-close grouped loss-run amount no larger than C; at least one strict improvement. Meeting all checks yields only a research-promising consideration. If the paired30day1000draw seed1178 increment interval crosses zero, label DEV_INCONCLUSIVE. Mixed relative improvements with positive terminal/cost2 are DEV_INCONCLUSIVE_TRADEOFF; nonpositive absolute stress or no relative advantage is DEV_REJECT. These are user-fixed research comparisons, not changes to old SSOT/formal PASS. Large-win money/total profit concentration and signal invariance are always disclosed rather than inventing a post-result additional threshold.

All PR1192 original losing/winning envelopes and its separate marked-DD window are reused. Calendar windows may overlap. Their per-position weighted mark changes separate positions already held at window start from later entries. Entry-weight metadata show whether a reduction was fixed before a loss episode or arose only on later entries; no hypothetical intraholding rebalance is calculated. No causal forecasting claim follows from subsequent co-loss labels. Daily exposure and monthly/symbol mark contributions cover the entire calendar.

Cost amounts scale only under the same price-taker model: unit20bps floor and existing fees/spread/impact/slippage/elapsed funding remain unchanged. Fixed fees, minimum quantity, nonlinear impact and actual account-capital binding are not verified. Unfinished positions, if any, retain symmetric hypothetical full-roundtrip marks with no forced close.

Attachment SHA256: `be0faac53486334d2174ddba7704adf355b9f01b37fae78dbec758d54dff0332`.

# Q0_RISK_ENTRY_V1 — source scope and design separation

Read on 2026-09-06. This note records a bounded source check for the one user-authorized risk-allocation hypothesis. It contains no candidate returns, parameter selection, additional strategy, or paid external AI call. The sources concern other assets and implementations; their results are not Q0 or cryptocurrency performance evidence.

## Primary sources actually read

### Moreira and Muir (2017), *Volatility-Managed Portfolios*

- Identifier: [DOI 10.1111/jofi.12513](https://doi.org/10.1111/jofi.12513); requested [NBER working-paper page](https://www.nber.org/papers/w22208).
- Readable primary copy: [author-hosted published-paper PDF](https://amoreira2.github.io/alan-moreira.github.io/VolPortfolios_published.pdf).
- Read scope: abstract/introduction; §I.A–D, especially §I.B equations (1)–(2) and footnote 6, printed/PDF pp.6–7; §II transaction-cost and leverage discussion, Tables IV–V, printed/PDF pp.15–17. This copy has article-local page numbers 1–34, not final journal pagination.
- Verified distinction: the baseline scales monthly excess returns by inverse prior-month realized **variance**, with monthly position adjustment. Its scale constant matches unconditional volatility using the full sample. Table IV separately considers inverse volatility and capped leverage alternatives under stated turnover costs. The reported benefits concern market/factor/currency portfolios, not this Q0 allocation rule. The introduction also describes weakening volatility-timing benefits over longer holding horizons.
- Limit: NBER access returned 403. The author PDF supplies directly read primary text; no claim of reading its entire 34 pages, Internet Appendix, reproducing its data, or verifying all robustness exercises.

### Harvey et al. (2018), *The Impact of Volatility Targeting*

- Identifier: [DOI 10.3905/jpm.2018.45.1.014](https://doi.org/10.3905/jpm.2018.45.1.014).
- Readable primary material: [Man Group article](https://www.man.com/insights/the-impact-of-volatility-targeting), dated 30 May 2018: “Impact on Sharpe ratio,” “Impact on likelihood of tail events,” and the complete displayed “Introduction.”
- Verified finding: the authors report benefits differing by asset class: higher Sharpe ratios for equities/credit, negligible Sharpe effects for bonds/currencies/commodities, and reduced extreme-return incidence across their broader sample. Their described approach can increase exposure in quiet conditions and reduce it in volatile conditions; it is portfolio volatility targeting, not sizing frozen until a channel trade exits.
- Limit: the Man page is a summary and introduction, not a readable complete journal article. Its linked e-print returned an empty rendered body; publisher and SSRN full-text attempts did not expose a readable article. Consequently, exact estimator implementation, all tables, cost details, and the complete published empirical specification remain unverified here. No quoted economic result is transferred to Q0.

### Bongaerts, Kang and van Dijk (2020), *Conditional Volatility Targeting*

- Identifier: [DOI 10.1080/0015198X.2020.1790853](https://doi.org/10.1080/0015198X.2020.1790853).
- Readable primary copy: [Erasmus University repository PDF](https://repub.eur.nl/pub/130215/Bongaerts-Kang-van-Dijk-Conditional-volatility-targeting-2020-FAJ.pdf).
- Read scope: printed pp.1–5 (PDF pages 2–6; PDF page 1 is a publisher cover): introduction, “Data and Methods,” “Constructing Volatility-Targeting Portfolios,” equations (1)–(3), “Transaction Costs,” and Table 1.
- Verified limitation: full-sample rescaling is criticized as unavailable in real time for targeting realized volatility; implementable conventional targeting does not consistently improve international equity outcomes and can worsen drawdowns. Their proposed conditional strategy changes exposure in extreme volatility states. Their reference volatility uses much longer prior history than ZEL's approved warmup. Table 1 and the text support measuring absolute loss and tail outcomes alongside Sharpe ratios.
- Limit: publisher direct requests failed, but the university-hosted primary PDF was read. Later robustness sections, supplemental appendix, source data, and replication code were not audited. No extreme-state strategy or extra threshold is imported into this experiment.

## Source facts versus the authorized ZEL design

The following choices come from the user attachment, not an assertion that the papers prescribe them:

| Source connection | ZEL DESIGN_PRIOR fixed by the attachment | Consequence to measure, not assume |
|---|---|---|
| Time-varying volatility can inform exposure; reported economic effects depend on market and implementation. | Equal-weight simple daily returns of the same seven frozen Q0 symbols, using only complete UTC days assembled from six approved 4h bars. | Basket volatility may differ from the risk of currently held Q0 positions. No new universe or missing-symbol substitution. |
| Historical volatility is observable; the original studies use other horizons and adjustment schedules. | `sigma_ref` is the sample standard deviation (`ddof=1`) over all approved pre-evaluation warmup basket returns; `sigma_t` uses the latest 30 completed daily basket returns available at Q0's entry decision. | Short warmup and an entry-only estimate may be noisy or become stale. Record availability exactly; no zero/invalid-value repair. |
| Published examples include periodic rebalancing and may permit leverage. | `m = min(1, sigma_ref / sigma_t)`, strictly positive, fixed at entry through exit; no leverage above Q0, additional buying, trade omission, or intraholding rebalance. | Existing positions are not reduced when later volatility increases. Lower average exposure alone is insufficient evidence of better allocation. |
| Ex-post scaling can be informative as a comparison while being unavailable as a trading target. | Fixed control `k` equals candidate notional-weighted holding time divided by Q0 holding time over the whole evaluation period. | `k` is an explicitly retrospective analytical control, never a candidate input, executable policy, independent OOS, or predetermined target. |
| Cost and implementation differences matter to reported benefits. | Preserve Q0 unit-bps costs/funding/floor and convert their monetary contribution using the frozen trade multiplier under the existing research price-taker model. | No claim of verified minimum-order sizes, fixed fees, nonlinear impact, signed funding, or actual account sizing. |

The attachment alone fixes the pass/trade-off question: compare candidate B with equal-average-exposure analytical control C on terminal net, cost×2, marked drawdown, losing-run amounts, preserved large-win money, concentration, and uncertainty. The sources do not justify changing these conditions after results. Signal correctness and unweighted trade win rate must remain Q0's. New paid external AI calls: 0. Gemini video analysis: NOT_RUN; no run or timestamped video evidence exists for this source check.


# Q0 entry-risk metadata audit (read-only research note)

Checked checkout HEAD `910fb4f7368e05223712931c47e1257227c10bcb` against PR1192 master `d860b0819e7e10192a16dc546343e0248fc74081`. No validation/OOS price rows, signals, outcomes, or candidate weights/PnL were read or computed. Existing receipt usage metadata was read; the only new numerical calculation was the specifically requested pre-evaluation warmup basket standard deviation.

## Warmup-only freeze value

Source: `research/development_evidence/BREAK_CHANNEL_SOURCE_20260906_V1/daily_bars.jsonl.gz`, with universe/evaluation start from its `SPEC.json`.

- Fixed 7 symbols; every selected day has 6 constituents, UTC-midnight alignment, a 24h duration, and identical timestamps across all symbols.
- Strict reference boundary: `bar_close_ts < 1738108800000` (Q0 evaluation starts 2025-01-29 00:00 UTC).
- 39 daily closes per symbol; 38 consecutive equal-weight basket simple returns; no calendar gaps or missing symbols.
- First close available: `1734739200000` (2024-12-21 00:00 UTC).
- First return available: `1734825600000` (2024-12-22 00:00 UTC).
- Last return available: `1738022400000` (2025-01-28 00:00 UTC).
- `sigma_ref = statistics.stdev(basket_returns) = 0.03290943045427639`, ddof=1, no annualization.
- This supplies at least 30 observed daily returns before evaluation. Neither the evaluation-start close nor any candidate outcome entered this reference calculation.

## Existing unused-data metadata and boundaries

Read metadata only from `frozen data_ref:research/data/g5a_stage_v1/development_manifest.json`:

| Split | UTC start inclusive / end exclusive | 4h bars per symbol | Usage evidence |
|---|---|---:|---|
| Development | 2024-12-19 08:00 / 2025-12-29 08:00 | 2250 | Repeatedly used; 25 prior candidate applications remain recorded. |
| Validation | 2026-01-02 16:00 / 2026-05-03 08:00 | 724 | Already decoded for PR1181 Break validation; cannot be a fresh independent Q0 exam. |
| Purged OOS | 2026-05-07 16:00 / 2026-09-05 12:00 | 725 | Reviewed existing research receipts record zero access/zero budget consumed. Metadata identifies a possible unused pool, not present authorization or proof of full formal readiness. |

Manifest dataset SHA is `3a17c13bf38ba83d11a9246b99750fcd9bf4a29ef377023812b1cfc08febbd5a`; manifest seal is `1e2743466fdb1082bc9d39071e4169e75db374076f2cf22f846bf48af968514a`. Do not conflate this manifest dataset-map SHA with Q0's combined approved DEV identity `cdefd32fa0f02fefb50a6f675f1d04c425c25fe23579ea97c443abe5d8e4484d`.

Exact usage evidence: `research/development_evidence/BREAK_VALIDATION_20260905_V1/receipt.json` has `decision=VALIDATION_REJECT`, `comparison_budget_consumed=1`, `OOS_budget_consumed=0`; `source_access` records 724 validation rows and zero purged-OOS rows per symbol. Its prior `next_validation_plan.json` is a pre-run plan, so its old `validation_accessed=false` must not supersede this completed receipt. Q0/Q1/Q2 and subsequent Top5 result receipts preserve zero new validation/OOS access. No new raw-price verification was performed here.

## Exact gaps for a future one-shot independent test

1. **Permission and candidate freeze:** Current user authority explicitly excludes validation/OOS. Existing `backend/research/contracts/top5_break_validation_v1.json` and `top5_break_validation_v1.authorize()` authorize only the frozen PR1180 Break child, with `OOS_authorized=false` and `P0=UNCONFIRMED`. They do not authorize Q0 or transfer a spare OOS budget to it. A future separately authorized one-shot Q0 or risk-branch selection/config/code/data/cost/decision freeze is missing. No such policy was created during this audit.
2. **Q0-specific unused-calendar and boundary design:** Manifest split has a 26-bar embargo defined in `g5a_stage_source_cost_contract_v1.json` as `lookback_20_plus_max_hold_6`, created for the original STAPC001 experiment. It cannot by itself establish adequate purge for Q0's daily, potentially long-lived positions. Q0-specific initialization/warmup access, fresh-flat versus carried state, overlapping information/positions, and sample-end open marks need a pre-outcome specification. Required observed data for that future scope is not validated by this metadata-only audit; no missing prices were filled or assumed. Historical Break validation cannot be relabeled unused; any use only as authorized past warmup must be declared.
3. **Costs:** `g5a_stage_admission_latest_v1.json#/development` remains ready and binds the unchanged DEV cost seal `4a031ed24544543ffae61ab080137ddbbb5e074e4e200ada9de3b48140ca2333`, `development_cost_model=RESEARCH_ONLY_DEVELOPMENT_COST`, `formal_production_credit=0`. Its top-level `PRODUCTION_GRADE_READY=false`, `new_candidate_production_lineage_bound=false`, `production_cost_lineage=REQUIRES_TRADE_TIME_ENTRY_EXIT_DEPTH_SIGNED_FUNDING_EXECUTION_AND_DURABLE_LEDGER`; native epoch `funding_settlement_lineage_bound=false`. Thus current reusable research costs are bound; trade-time depth/actual fill/signed settlement lineage needed for formal production credit is absent. A separately authorized research-only independent comparison could explicitly retain proxy costs without claiming this closes formal gaps.
4. **Formal eligibility remains unchanged:** Q0 receipt's `formal_validation_readiness=BLOCKED_PENDING_SEPARATE_AUTHORITY_UNUSED_DATA_PRODUCTION_COST_AND_EXECUTION_LINEAGE`. `g5_g14_governance_contract_v1.json#/g5_terminal_gate` requires the existing terminal schema/state and OOS, walk-forward, stress, source-owner/economic-digest parity, frozen W1-through-W3 selection, complete fee/slippage/funding lineage, and integrity/economic fields. Q0 DEV_INCONCLUSIVE is not this terminal receipt. A single research test does not manufacture formal PASS or G5B rights. Actual sizing and G7/G11 authority remain excluded.

These are future independent-test/formal gaps, not prerequisites or new blockers for the currently authorized DEV risk-allocation measurement.

## Safe reuse and telemetry parity

- Existing DEV loader: `g5a_development_probe_v1.load_development()` verifies the frozen manifest, byte checksums, and cost binding, then calls `prefix_rows()` for exactly 2250 DEV rows. Full-file hashes are opaque. Do not call `g5a_development_data_v1.verify_dataset()` for this task: that acquisition verifier decodes complete files including holdouts.
- Existing `g5a_source_admission_v1.require_development()` checks the sealed DEV subreceipt independently of changing prospective telemetry. Current subreceipt seal matches the frozen Q0 binding.
- Changes between PR1192 master and the inspected HEAD: 23 telemetry files. Union of Q0 SPEC, Q1 SPEC, and Q2 analysis code/protected mappings: 153 files. Intersection with the 23 changed files is empty; every one of the 153 frozen file SHA256 values matches the checkout.
- Therefore current telemetry can be preserved while this DEV branch reuses frozen parental dependencies. Do not restore old telemetry from research snapshots.

No edits to repository files, new independent-test execution, paid calls, Gemini video run, collector, operating strategy, or execution/order/live changes were made by this audit.
