# Frozen Q0 prospective research observer

Authorization: the user's PR1194 continuation and attached
`ZEL_AFTER_PR1194_Q0_PROSPECTIVE_OBSERVER_WORK(1).txt`, received before outcomes.
Research only. This is an observation connection, not candidate 27 or an
operating strategy replacement. Q0 is primary; B is an unadopted fixed auxiliary.

## Fixed calendar and preserved lineage

T0 = **2026-09-07 00:00 UTC**, T_end = **2027-01-05 00:00 UTC** (120 complete UTC
days). First prospective completed 4h bar closes **2026-09-07 04:00 UTC**.
These dates were selected before decoding any campaign prices. The final SPEC,
code and bootstrap must be permanently published before T0. A late freeze is a
hold, never a backdated activation or automatic calendar change. The runtime
checks the latest committed SPEC and its frozen file hashes, not just first-add
time. Git timestamps alone are not proof of remote publication; PR/CI receipts
and actual publication chronology remain part of the independent review.

PR1194 merge `2a7127de30d4b6ad1fcba4c2dca095d1fd8feba7` and result seal
`32d1abc111806e976702c1c0d5649465d5cf4f2bd3cfc57a42ac51e339dd6b39` remain intact.
The full prior preservation map, sealed PR1194 code and all its evidence files
are hash-bound here. Original states remain Q0 DEV_INCONCLUSIVE, Q1 DEV_REJECT,
Q2 NOT_RUN_NO_SUPPORTED_INTERVENTION and B DEV_INCONCLUSIVE_TRADEOFF. Seen result
SEEN_PERIOD_VULNERABILITY / SEEN_DATA_REPLICATION remains independent=false.
Candidates26, remaining0; seen1/1; original independent0/1 NOT_RUN. This new
campaign has its own namespace and consumes none of those candidate slots.

## Same source, permanent archive, no operating admission

Reuse owner G5_CLEAN_RUNNER_OWNER_V1 and its existing hourly UTC trigger
`50 * * * *`. A wrapper copies parsed original JSON rows from the existing
BingX USDT-M 4h request. It makes no additional request and returns the exact
original operational result. The sealed source/binding and active G5B strategy
set remain unchanged. Original full HTTP bytes are not retained: the archived
raw representation is the original parsed JSON row, explicitly distinguished
from its normalized OHLCV. Source/stream, run/attempt/commit, open/close,
observed-at, original payload hash and normalized value hash are retained.

The consumer runs after existing operational persistence. Its source delta,
contiguous cursor, channel/position/pending state, locked B observations and
accounting snapshot share one immutable hash-addressed transaction. CURRENT is
an atomic pointer. Git commits make this independent of90-day action artifacts.
STATUS is a repairable projection; CURRENT is authoritative after a crash.
The existing owner concurrency serializes runs. Push conflicts reload latest
master and consume the same packet; no additional API request or per-run PR.
Only this namespace is staged, preserving concurrent telemetry changes.

Same normalized key/value is a no-op preserving the first raw receipt. Different
value is quarantined, never overwritten. Missing members stop the aligned
seven-symbol cursor without deleting positions. Out-of-order records are kept;
gap repairs and all queued baskets are delayed evidence. Independently of an
already recorded gap, a first-seen close earlier than the source clock's latest
completed4h close is backfill. This also detects downtime followed by a fully
contiguous catchup packet. Ordinary receipt latency is recorded separately.
There is no imputation or skipped losing interval. Permanent conflicts latch a
hold; operator resolution would require preserving the original campaign facts.
Failed consumer runs append a failure receipt without changing operating state.

## Causal initialization and frozen execution

The existing canonical source prefix contains3751 bars per symbol, from
2024-12-19 08UTC through the **2026-09-05 12UTC close**. Its dataset and original
file hashes are verified before decoding. The seven symbols are frozen by SPEC.
The complete prefix is used once for channel and volatility initialization only;
no historical economic replay, PnL or positions enter the campaign. The partial
first UTC day is discarded by the original aggregator. A small immutable
bootstrap preserves channel attempts, the partial final day, source indices,
last closes and B's30 returns. Later calls restore it and advance new4h baskets.
The historical channel diagnostic trace is counted and hashed at initialization,
not copied into every checkpoint; its active attempt state and indices remain.
The archive may read historical source records to reconstruct its index/prices,
but never re-executes historical or old campaign signals each update.

Use the original Q0 aggregate_daily/channel/confirmation definitions and shared
execution geometry. Full UTC days require six contiguous completed4h bars.
Latched channel preparation, bullish confirmation, next-open long entry,
lower-channel protective stop, gap priority, bearish confirmation then next-open
exit, occupancy/cancellation/re-entry and no-short rules are unchanged.
Synthetic batch/incremental tests compare the complete signals, events, raw
trades and traces, including global indices, partial prefix and restarts.

Positions and pending orders start flat before T0. A confirmation exactly at
T0 is eligible, using only the just-completed warmup day; its next-open model
fill is only recorded when the following completed4h bar supplies its actual
open. No same-bar favorable retroactive fill is invented. Signal/model timestamp,
source received timestamp and actual consumer-recorded timestamp are distinct.
Model fills can be recorded hours after their notional execution time. They
are not live orders or evidence of achievable punctual fills.

The fixed Tend, not each latest watermark, governs signal inclusion. Pending
orders persist between updates. At Tend no new order or signal is admitted;
open positions remain open and are symmetrically marked at the final completed
close, never forcibly closed or deleted. Before Tend, UTC daily marks use the
original AFTER_OPEN_ORDERS convention and are published only once the following
completed4h bar provides that open. A/B accepted daily history stays immutable.

## A, fixed B and retrospective C accounting

A is unchanged unit-notional Q0. B keeps original38-reference-return lineage,
ddof1 and sigma_ref **0.03290943045427639**. At an eligible confirmation, compute
the fixed30 completed daily equal-weight seven-symbol basket returns ending at
that confirmation, then m=min(1,sigma_ref/sigma_entry). Lock m through exit.
No leverage aboveA, additions or holding rebalancing. Reference verification is
strictly before the original2025-01-29 evaluation start; the enlarged warmup
does not re-estimate it. C=k*A, where k=sum(Bweight*hold_ms)/sum(Ahold_ms), is
ex-post reporting only. Zero holding time leaves C undefined. C's historical
marks may be recalculated as k changes and are explicitly not an immutable
execution record or an input toB.

Reuse the bound research price-taker fee/spread/slippage/impact/funding model,
20bps roundtrip floor and whole-cost×2. Funding uses elapsed settlement times;
intrabar stops retain the original conservative close-time upper bound. Open
marks include the same hypothetical full-roundtrip cost, separately from closed
metrics. Entry-side costs, actual fills, signed funding, account capital and
nonlinear market impact remain unbound. Monetary values are fixed-reference
notional amounts in bps units, not account returns, account MDD or a sizing plan.

Reports separate A absolute outcomes, B−A attribution and B−C additional effect.
They retain signal/closed/open/pending counts, unit win rate, expectancy, PF,
payoff, total net/cost2, all costs, daily DD/recovery, all simultaneous exit
cohorts, actual entry clusters, symbol/month concentration, top3 winner amounts,
exposure and uncertainty. Differences between different worst loss runs are
descriptive maxima differences; matched cohorts provide contribution evidence.
Cost saving is already in the net bridge and is never added twice.

## Fixed interpretation and end rule

6T/12T are intermediate diagnostics only. No automatic early stop for profit,
parameter feedback, strategy replacement, extension or PASS promotion. The120-day
end is fixed even with too few trades. Integrity/user stops are retained with
their missing-data consequences. Economic interpretation remains descriptive
until a separate review at the fixed end.

Existing absolute research checks remain: at least6 closed trades, positive
closed net/expectancy, PF>1, realized payoff>=1, positive cost×2; open terminal
net/stress are shown separately. A's daily block interval versus no-trade is
distinct from B−C. B's original comparison requires positive terminal net and
cost2, nonworse marked DD/max grouped-loss versusC, net at leastC and one strict
improvement; the existing95% interval and sample/open limitations remain visible.
No universal requirement that all performance numbers beat prior DEV is created.
The same frozen block uncertainty implementation is descriptive with dependence
limits; clusters do not establish N_effective. Long holds are not independent
weekly trades. Intermediate intervals are not sequential acceptance tests.

Future time alone does not establish independence. This namespace starts
independent=false / NOT_ADJUDICATED. Compliance, delayed/backfilled data, source
access/changes, coverage, dependence and sample adequacy must be reviewed before
any independent evidence claim. The original independent0/1 NOT_RUN remains
unchanged. Formal credit0, operating adoptionfalse, executionNONE, order/live
BLOCKED. No G5B replacement, real sizing, paid AI or new scheduler.

## This implementation's completion boundary

Code wiring and synthetic lifecycle tests can finish now. A real master source
run must separately prove permanent new completed-bar storage, its original
identity and archive cursor/hash. Pre-T0 catchup is warmup, not future economic
evidence. The first actual eligible future bar cannot be verified before
September7 04UTC. If it has not arrived in this Work session, that observation
and all economic conclusions remain pending explicitly.
