# KR3 주심사 승인묶음 — PENDING_AUTHORITY

원본 KR3 FULL의 SL=None과 기존 TRADEOFF를 보존한다. 아래 제안은 승인 전 비활성이며 코드작성자 승인으로 대체할 수 없다.

## R_and_no_protective_SL

Retain KR3 initial SL=None and TP=None. Approve statistical R only: d_i=10000*ATR20(signal_close_i)/actual_entry_price_i; R_i=net_bps_i/d_i; window NetR=sum R_i. Wilder ATR seed is mean of first20 true ranges, TR=max(H-L,abs(H-prevC),abs(L-prevC)); only completed native4h prefix. Missing/nonpositive denominator blocks. Explicitly permit a no-protective-SL research cohort or reject KR3 applicability; statistical R never represents account risk or protection.

단위: d_i trade-bps; R dimensionless statistical normalization

근거: Existing kr3_evidence_adapter_v1.approval_bundle proposal; original keltner_kr3_v1.py has original_protective_sl=None.

영향: Requires semantic authority for shared net_r field. No SL implementation or real-account sizing introduced.

## retention_baseline

Frozen KR1_FULL same native universe, calendar, source and costs. Parent positive CLOSED origin set B; D=sum(b_i>0). retention=100*sum(min(b_i,max(0,c_i)))/D over B. Child missing contributes zero retained profit, not a zero-return trade. Child open supplies bounds and prevents terminal. D=0 is unavailable. Preserve ordinary/top-decile diagnostics separately. Evaluate parent and candidate paths with their own actual occupancy; no FIXED splice.

단위: percent; D trade-bps

근거: Existing candidate-local retention proposal and existing shared >=60 gate.

영향: The denominator and baseline must be approved before new outcomes; this does not convert old TRADEOFF into PASS.

## windows_review

S=first native4h boundary strictly after approval, source readiness and candidate freeze for G5A sealed prospective validation; Wk=[S+(k-1)*30days,S+k*30days), k=1..3. Attribute by signal-close time; stop new cohort entries at each right edge and retain run-off of already admitted positions. One terminal look only after W3 and actual run-off complete; schedule deadline W3end+7days. T6/T12 are diagnostic/continuation only. After G5A PASS, a distinct fresh G5B boundary is required; no G5A validation row can become G5B fresh T.

단위: UTC ms; 30calendar days per window; one review

근거: Existing W1/W2/W3/frozen-selection authority; 30day/7day values PURE_DESIGN_PRIOR requiring approval, chosen before outcomes for finite calendar exposure.

영향: If unavailable or unresolved at scheduled review, classify insufficient evidence; do not extend in response to PnL.

## purge_embargo_runoff

Purge overlapping realized label/position intervals [entry_ts,observed_exit_ts], including actual/reference reservations where used. Unresolved interval end is +infinity and is purged. Embargo begins after the last actual training-label exit and spans96h; widen to any later observed native next-open. KR3 i+24 completed-bar cap is index-based, not a guaranteed96h wall-clock liquidation. Data gaps never create synthetic bars or force closes. At run-off deadline censored_open/unknown_exit remain blockers. Q0 unlimited hold is not assigned this horizon.

단위: UTC ms; native completed4h bars; observed intervals

근거: KR3 inherited HOLD12 and doubled cap24; same-label/position leakage prevention from STEP7; 96h separation proposal remains unapproved.

영향: May reduce effective sample, even to zero; protects independence without changing strategy exits.

## regime_shock

Diagnostic causal regime at each signal: sign(EMA50_t-EMA50_(t-1)) including flat, crossed with ATR20/close above or below frozen DEV median. Median and feature-code/source digests frozen before validation. Shock ID is UTC signal-day across all symbols; conservatively merge shock groups connected by any actual position-interval overlap. This is a calendar dependency proxy, not a claim of identified exogenous shocks. Missing timestamps/availability or unresolved overlaps blocks reviewed independence.

단위: regime labels; shock/component IDs; UTC day

근거: Existing same-signal or reviewed-shock connected-group counting; concrete calendar/overlap method is PENDING_AUTHORITY design prior.

영향: Conservative merging can make N_effective very small; labels never alter entries.

## effective_N_minimum_effect

Independent observation is mean net trade-bps within each approved shock/overlap component. Compute sigma_cluster on frozen approved DEV only, with method and exact input digest; missing/zero estimate blocks numeric sample assignment. For each window N_min=ceil(((z_(1-alpha_claim)+z_(1-beta))*sigma_cluster/delta)^2). Proposed delta=5 net trade-bps per component, beta=.20. Require N_effective>=N_min AND one-sided component-mean lower confidence bound >delta for every window, preserving all existing absolute gates. Use Student-t critical value with N-1 degrees of freedom for the final mean bound; approximation in power design is not a precision guarantee.

단위: components; net trade-bps/component; probability

근거: No existing authorized numerical N. Formula extends existing power proposal; delta5/beta.20 PURE_DESIGN_PRIOR, not fitted to unseen performance.

영향: No 6T/12T/sample-count substitution. Distribution/dependence assumptions must be reviewed; failure remains failure.

## multiple_testing

One candidate and one registered bundle. Familywise alpha=.05 allocated Bonferroni over seven preregistered one-sided claims: positive minimum mean in W1,W2,W3 and superiority by delta=5 net trade-bps/component to each of four required controls on pooled matched W1-W3 sealed-bundle evidence. alpha_claim=.05/7. Only control semantics and synthetic/DEV fixtures are prepared before sealed access. All four formal control economic results are produced once on the SAME candidate/data/cost identity as the nine-report bundle. Existing DEV p-values are not reused. All historical candidate exposures remain in the campaign ledger; no selection-unadjusted retrospective p-value is reported for old candidates. No unplanned early efficacy looks; T6/T12 only safety/continuation. If authority deems historical selection requires a larger family, adjust before any access and reapprove, never after outcomes.

단위: probability; seven claims; one sealed access

근거: Existing no-leakage/no-cherry-pick and four P4 controls. Proposed alpha/error allocation has no prior numeric authority.

영향: Retains old history and prevents reset by new filename; this is a proposed future single-candidate family, not retroactive significance.

## controls_neighbors

Retain all four P4 controls, defined and fixture-tested before sealed access; formal economic results computed once inside the SAME sealed candidate/data/cost bundle: direction_flip mirrors side and all directional comparisons with native event timing/occupancy; time_shift_placebo shifts the entire signal schedule by one UTC day and recomputes prefix-valid geometry; delayed_entry waits one extra native bar with native event invalidation and actual occupancy; regime_permutation uses seed1178 to permute timestamp opportunities within symbol/calendar window before outcomes, stratifying on frozen causal regime labels. Recompute each control own actual execution/cost/open positions; compare matched calendar effects, no missing-as-zero trades. Feature ablations cover every feature identified by the exact S2 causal map. Neighbor sensitivity exact inventory from parallel_exit_keltner_v1.PARENT_SPEC and inherited HOLD: tuple(fastEMA,slowEMA,HOLD) center=(20,50,12), variants=(19,50,12),(21,50,12),(20,49,12),(20,51,12),(20,50,11),(20,50,13). For each HOLD variant derive extension cap=2*HOLD and decision index=HOLD-1; no independent cap tuning. Lag1, EMA seed, ties, fixed source index and cost contract remain semantic constants. All six results are computed once in the same sealed bundle and cannot select a new candidate. Current native API enforces exact PARENT_SPEC; a separately isolated sensitivity producer is still required before these six executions, not a mutation of the native candidate. Unresolved directional control semantics or a missing sensitivity producer blocks execution instead of creating a PASS name.

단위: one sealed validation bundle; four controls and six sensitivity variants; fixture-only DEV preparation

근거: P4 requires direction_flip/time_shift_placebo/delayed_entry/regime_permutation plus feature ablations; STEP7 permits neighbor sensitivity but forbids optimization.

영향: These are proposed tests, not new selected trading candidates. Actual finite neighbor list remains dependent on exact inventory; bundle cannot activate without its hash.

## source_stale

Approve source-specific bounds only after source owner verifies cadence and clocks. Proposal: completed4h stream must equal latest expected completed bar, publication lag<=60s; trigger decision uses only available completed bar; current BBO event age<=2000ms and local receive age<=1000ms, request roundtrip<=2000ms, venue/local clock uncertainty<=500ms. Signed funding observation must identify settlement time/rate and be present before an affected terminal receipt is complete; missing funding is UNKNOWN, not zero. No historical quote repaired with current snapshot. Existing approved source-specific bounds, if available and stricter, take precedence. Actual delayed reception cannot be backdated to an already-past native open. If source availability occurs after the modeled open, classify execution mismatch and seek a separately approved timing contract; do not silently replace the fill or claim parity.

단위: UTC ms; source-specific event/receive clocks

근거: Native4h cadence is source-derived; 60s/2s/1s/500ms latency proposals PURE_DESIGN_PRIOR needing actual endpoint/host evidence and approval.

영향: These numbers are inactive. 4h stale threshold is never copied to tick/BBO; no source credit from a new file mtime.

## concentration_operating_risk

For research attribution require >=2 source symbols represented and no single symbol >50% of total positive net profit; remove largest positive trade and require remaining aggregate net>0. If total positive profit=0 the absolute economic gate already fails. Report peak simultaneous positions, reference reservations and per-symbol exposure without inventing account risk. Preserve existing native one-position-per-symbol occupancy and exact frozen universe; do not add position filters. No-SL cohort risk must be explicitly accepted for non-order observation; actual/live sizing remains blocked.

단위: symbol count; percent gross winning contribution; trade-bps; position count

근거: Native occupancy is existing authority. >=2/50%/largest-trade criterion are new PENDING_AUTHORITY conservative concentration checks, not historically approved gates.

영향: Can reject a profitable but concentrated result. No trade is dropped from reported economics and no live risk claim follows.

## existing_economic_integrity_gates

Bind shared contract digest byte-for-byte. G5A requires net expectancy>0, PF>1, cost2 net>0, nine complete bound reports, purged_oos_pass/negative_controls_superior/no_leakage/no_cherry_pick. G5B each W1/W2/W3 requires NetR>0,E>0,PF>=1,payoff>=1,retention>=60%; errors/duplicate/censored_open/unknown_exit all0; reviewed OOS/WF/stress/source/baseline/fee-slippage-funding/independence plus explicit terminal receipt. Existing numeric values unchanged.

단위: existing contract units

근거: backend/research/rebuild/g5_g14_shared_validation_contract_v1.json

영향: Adoption of new proposals cannot override an existing economic failure.
