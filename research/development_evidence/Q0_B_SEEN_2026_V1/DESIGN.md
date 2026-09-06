# Q0/B fixed 2026 seen-period replication — pre-outcome specification

Evidence type **SEEN_DATA_REPLICATION**, independent=false, formal_credit=0,
operating_adoption=false. This is one new economic evaluation of existing frozen
candidates, not an independent validation, new candidate, or new research parent.
Authorization: the user's `ZEL_Q0_B_AFTER_NOT_RUN_SEEN_PERIOD_WORK(2).txt` and
accompanying message. Its content hash is frozen in SPEC.json.

## Lineage and separate budgets

Original PR1193 merge `35be277a333a78164cb1dd4682958aa14a89705d`,
Q0_RISK_ENTRY_V1 result seal
`edab29b1ca3db8c75c8e29a439f6076e2dd9acd181b32665760c7915976ebb98`.
Q0 DEV_INCONCLUSIVE, Q1 DEV_REJECT, Q2 NOT_RUN_NO_SUPPORTED_INTERVENTION,
B DEV_INCONCLUSIVE_TRADEOFF remain unchanged. Candidate cumulative26, remaining0,
new candidates0. Prior independent comparison remains NOT_RUN, used0/1. This
separate evaluation ID Q0_B_SEEN_2026_V1 has one allocated measurement. Exact
immutable reproduction and analytical C consume no additional candidate/evaluation.
No alternative parameter, symbol, timeframe, calendar, B2 or post-result retry.

## Previously established use history — retained, not re-audited

At commit `c79943456e40538228879b46963a18b3c03f866e`:

| Committed source receipt | Exact fields | Prior use |
|---|---|---|
| backend/research/rebuild/a1_top5_g4_recent_historical_accelerator_latest.json | lanes.break_and_continue_main.source_summary.*; bars614; first_ts1778025600000; last_ts1786852800000 | All7 BingX4h histories, May6 00UTC–August16 04UTC bar opens; all input bars enter features. Economic windows June15–July15 and July15–August15. |
| backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json | lanes.break_and_continue_main.source_summary.*; closed_bars284; first_bar_ts1784592000000; last_bar_ts1788667200000 | All7 BingX4h histories, July21 00UTC–September6 04UTC opens; features and post-boundary prospective outcomes. |
| backend/research/rebuild/a1_top5_g4_primary_month_sharded_fasttrack_v2_latest.json | recent_6m.start_utc/end_utc; shards_complete=true; shard_count12 | BTC/ETH1h actual economic evaluations February15–August15, including early candidate-pool market outcomes. |

These source ranges jointly cover the full former candidate pool. Input bar
counts are not trades or independent samples; not every input bar had an outcome.
No raw-price byte equality between generations is claimed. Dataset-specific OOS0
receipts retain their original scope. The prior global-unused test failed with
UNUSED_POOL_NOT_ELIGIBLE_CROSS_GENERATION_SOURCE_USE; this result never rewrites it.
The present user separately authorizes these already-used prices as research data.

## Exact calendar, permitted reads and causal state

Original raw pool: [2026-05-07 16:00, 2026-09-05 12:00) UTC in bar-open/close
interval convention. Actual eligible signal/entry timestamps: [2026-05-08 00:00,
2026-09-05 00:00) UTC, exactly the inward full-day alignment, 120 calendar days.
Same fixed seven symbols, same frozen BingX4h OHLCV source and original cost
authority. No 1h strategy, resampled alternative, shortened period or symbol choice.

Read only the exact chronological4h prefix from original source start
2024-12-19 08:00UTC through bars closing at2026-09-05 00:00UTC inclusive.
The full file is checked as opaque bytes against its frozen SHA; no later price
objects are decoded. Record source rows by original split as well as warmup and
evaluation purpose. Old validation and original OOS-labelled rows in this
authorized prefix are truthfully reported, not relabelled as new unused DEV.

Full UTC days require six contiguous complete4h bars. The initial partial day
December19 is excluded from daily aggregation, never synthesized. Full original
daily history from December20 initializes the unchanged channel attempt state;
all before May8 is warmup only. No warmup trade/PnL is computed. The two raw-pool
bars on May7 after16UTC are warmup. Evaluation prices are precisely the7204h
bars with open>=May8 00 and close<=September5 00. No price from the three trailing
raw-pool bars after that end is decoded. Source-index offsets remain full-prefix.

Both candidates start with zero positions and no queued orders. Channel attempts
retain causal state from warmup, so confirmation at May8 00 can generate a
next-open entry at that timestamp. No prestart confirmed signal or position is
carried. This is flat-start replication, not continuous-operation carry-over.
Q0 functions aggregate_daily/generate_signals/replay are reused unchanged.
Latched-channel preparation, two-close confirmation, opposite confirmation,
fixed protective stop, gap/exit/entry/intrabar priority and occupancy are unchanged.
No native hold6/hold12, TP or common breakeven exit is substituted.

At end, a protective stop in the final complete4h bar may close a trade at the
original conservative close timestamp. No signal or new-open order at end is
allowed. Remaining positions stay open and are marked at the final completed
close; no forced fill or removed loss/win. Intermediate marks preserve the old
after-open-order convention; end mark is final-close with no future open.

## Frozen allocation and accounting

A is unchanged Q0. B uses same7-symbol equal-weight simple daily return basket,
last30 completed returns (ddof1) known at signal close, multiplier
min(1,0.03290943045427639/sigma_entry), positive and fixed until exit/mark.
Only symbol, lane, side, original signal_ts and entry_ts reach entry_weights.
No outcome, future price, C, exit timestamp or holding period enters B's decision.

The original reference is reconstructed with market_state's ORIGINAL Q0 evaluation
start January29 2025, not the new2026 start. Verify exactly38 returns, first
available December22 2024, last January28 2025, and sigma_ref above. Only the
ephemeral state's evaluation boundary is then moved to May8. New warmup prepares
rolling sigma and channel state, not a new reference. Full historical returns may
be in memory; entry_weights uses bisect and a strictly causal completed30 window.

C is k=sum(B entry_multiplier*hold_ms)/sum(A hold_ms), including open duration,
computed after execution. It is only a descriptive normalization; no C input to
candidate weights/reference. Zero total holding time yields INSUFFICIENT with
C undefined, not k1. Equal average nominal exposure is not equal account risk.

Reuse existing charge/charge_open/daily_valuation and q0_risk_entry_metrics.build.
All unit fees/spread/impact/slippage, elapsed8h funding and max20bps roundtrip
floor remain fixed. Weight only amounts under the original price-taker model;
cost2 doubles the full unit cost. Open marks use full hypothetical roundtrip cost
plus accrued model funding, not real forced fills. Actual signed funding, account
sizing, leverage, fixed minimum order cost and nonlinear impact remain unbound.

Unit signal counts, IDs, fill prices/times, exit/SL, signs, occupancy and unweighted
win rate are identical across A/B/C within this evaluation. They need not equal
the old2025 counts. Report amounts, not improved signal prediction or account MDD.

## Frozen goals and diagnostic methods

Preserve original numerical goals and absolute equality tolerance1e-7: B terminal
net>0 and cost2>0; B net>=C; B daily markedDD<=C; B grouped losing-run loss<=C;
at least one strict relative improvement. Reuse original study_decision for
technical application, then label new evidence as seen-period support,
INCONCLUSIVE/TRADEOFF or vulnerability. Never change original candidate verdicts
or call a technical goal match independent PASS. Minimum sample adequacy and
censoring/dependence limitations are reported separately, not silently promoted.

Derive all sign cohorts from the new period's A simultaneous-close groups using
the existing grouping semantics. Preserve exact originating IDs; compare A/B/C
money within each same cohort and compare daily marked changes on identical
calendar boundaries. These post-outcome labels never enter execution. Per-stage
worst losing-run groups and markedDD extrema may differ; differences of their
maxima are not causal same-trade attributions. Report individual versus
simultaneous sign changes and entry/loss clusters without claiming independence.

Preserve complete monthly/symbol amounts and concentration. Define new-period
top3 and original top-decile winners from A closed net only, for diagnostic
retention; do not search for 2025 IDs or use winner labels as a rule. Full winner
money, loss savings, excluded/new trades (expected0), gross/cost bridges and open
marks are shown. Cost saving is already included in net, never added twice.

Use the original noncircular paired30day moving-block1000draw bootstrap, seed1178,
on complete calendar marked B−C deltas including zeros and fixed realizedC. No
seed/block/end selection. The120day window has about4 nominal30day blocks, not4
proven independent samples. Holding periods/market clusters can exceed blocks;
data reuse and model-selection effects remain. Completed recovery durations and
terminal unrecovered duration are separate. Strong intervals do not confer credit.

## Tests, freeze and immutable execution

Before newly authorized2026 computation: synthetic timing/reference/boundary,
prefix-extension, stop/cost/open/C separation tests and oldDEV byte-parity checks.
Bind all new code/tests, old protected files, data map and costs, this design,
attachment hash, policy/goal, state and read boundaries in SPEC; commit and push
before outcomes. Then one new measurement. Reproductions verify immutable bytes
and cannot retune or replace the result. Existing workflow reused; no paidAI keys,
new workflow platform, scheduler or operating dispatch. New results separate.

## Future independent research — readiness only, not a prerequisite

Actual existing owner G5_CLEAN_RUNNER_OWNER_V1, workflow
.github/workflows/g5-clean-runner-shadow-v1.yml, schedule50 * * * *; BingX
/openApi/swap/v3/quote/klines4h, same seven instruments. Source payloads for NEW
latest-closed bars persist append-only in
backend/research/rebuild/g5_clean_runner_state_events_v1.jsonl; workflow artifacts
retain90days. The maximum4pages×1000 fetched warmup is not fully archived: only
latest completed-bar events persist, so interruptions can leave gaps.

At implementation source master3446602, the saved September6 09:40:56UTC receipt
reports source parity true and18 consecutive4h bars, most recent closes00/04/08UTC.
This is the observed committed state, not a claim of current real-time health.
Q0/B are absent from active_strategies. Existing Keltner/Supertrend/Break operation
is preserved. The historical stage-data freeze and native-epoch append path are
not a scheduled Q0 prospective OHLCV archive.

Future Q0/B connection is NOT_IMPLEMENTED / NOT_ACTIVE. Minimum future work:
separate deduped immutable research archive from existing closed-bar payloads,
coverage/hash checks; explicit fullprefix/channel/ref state, flat-start/end/cost,
read-access isolation and insufficient/stop decision frozen before outcomes;
separate approved research observer. Other fixed operations may use the market
without their outcomes feeding Q0/B candidate settings/calendar/selection; this
must be documented independently. No future scheduler/economic run is started
here. No G5B replacement or formal production claim follows.
