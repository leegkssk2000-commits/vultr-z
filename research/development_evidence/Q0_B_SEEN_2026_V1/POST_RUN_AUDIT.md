# Post-measurement verification — fixed seen-period Q0/B

This note interprets the already sealed evaluation; no new hypothesis, rule,
calendar, reference or threshold was evaluated. Evidence remains
SEEN_DATA_REPLICATION / independent=false / formal_credit=0.

## Execution and fixed identities

- Remote pre-outcome commit: `662f3cafc6ce05f47d2a3329823a952b3bd0cd90`.
- Tested local pre-outcome commit: `7a7cbe7`; remote/local full tree identity
  `118b8610dfded79949b28cd11b977a9297c9a4c5`. GitHub connector published the
  same tree because shell push credentials were unavailable; no rule changed.
- SPEC seal: `fdcfab6ec713e13de2b1979ae4abf5fdc44689744769bb298f4865f7b4f370cc`.
- First measurement: 2026-09-06 11:59:29.478079–11:59:31.130544UTC; exit0.
- Result seal: `32d1abc111806e976702c1c0d5649465d5cf4f2bd3cfc57a42ac51e339dd6b39`.
- Separate candidate generation0, seen economic evaluation1/1, independent
  comparison0/1 with prior NOT_RUN unchanged, candidate cumulative26/remaining0.
- Source per symbol:3748 decoded4h rows =3028 warmup +720 evaluation;
  original labels2250DEV +724validation +52embargo +722purgedOOS. All latter
  reads are explicitly authorized seen-data use; no claim of OOS independence.
  The two first old-pool bars complete warmup; the final three after evaluation
  end remain undecoded. No raw_ohlcv archive or later canonical price decoded.

The prior independent eligibility failure and existing PR1193 verdicts remain
unchanged. No source audit was repeated to search for a fresh name or period.

## Actual economic finding

Q0's aggregate closed net is +7314.839288 amount-bps; cost2 +6448.378914.
B is +7261.471036 / +6397.473153; analytical C +7282.565788 / +6419.928287.
All stages share40signals,34closed,0open and11unit wins/23unit losses. These are
fixed-reference-notional amounts, not account returns or independent samples.

B minus C net is -21.094752, markedDD is worse by24.438313 and maximum grouped
loss is worse by12.264248. Thus the unchanged relative goal fails in this period:
SEEN_PERIOD_VULNERABILITY. Q0 and B absolute cost-adjusted positivity is separate
from the failure of B's additional allocation effect. Original Q0/B DEV verdicts
are not rewritten, and B is not promoted to a research/operating parent.

The same-calendar paired30day1000draw seed1178 interval for B−C net is
[-45.228451,+62.766166] amount-bps. It includes0: neither independent support
nor statistically established inferiority is claimed. There are24 distinct
entry timestamps, at most3 simultaneous entries,120calendar days/~4nominal
blocks; effective independent N remains unknown.

## Why B barely intervened

Only2/34 entry weights were below1; the other32 were exactly1.

- 1000PEPE, July4–July6: multiplier0.99601767, original loss saved0.353402.
- SOL, August25–August30: multiplier0.91599899, winner amount foregone53.721654.

Total B−A net is -53.368252. Modeled closed cost saving2.462492 is already
included in those net loss/winner contributions and must not be added again.
Same signals and unchanged unit win rate do not show better signal prediction.

## Same-cohort risk and timing

All three maximum grouped losing runs use the same9 trades/7exit groups,
May12 12UTC–June11 00UTC. A=B lose2779.711014, C loses2767.446765. B did not
reduce this actual worst run. All six original loss/win cohorts, each stage's
native loss cohorts, exact origin IDs and comparisons are preserved in the
accounting artifact.

The maximum markedDD calendar is May11 00UTC–August19 00UTC for all stages:
A5619.081051, B5618.727649, C5594.289336.31 nonzero per-position contributions
reconcile the same boundaries. The only B−A intervention there is the PEPE
+0.353402 saving. The SOL reduction occurs after the trough and reduces a
recovery-period winner; it cannot explain the prior DD. This is actual
same-window attribution, not subtraction of unrelated extrema.

Maximum completed recovery is102days for all three; terminal unrecovered
duration is8days. These durations are separate from closed-trade loss-run counts.

## Profit concentration

A marked net in May–July totals -4463.896984, offset by August +11778.736272.
B August net is +11725.014617. August is the only positive marked/exit month;
September's partial terminal interval has zero contribution. The positive
aggregate is concentrated in one period, not proof of stable cross-regime profits.

The current-period A top3 winners total9130.106163, retained100% by B. All-winner
money retention is99.594037%. This preservation coexists with no worst-run
improvement and a small loss of net versus C. Winner IDs are post-outcome
diagnostics, never executable selection features.

## Validation performed

- New synthetic regression34tests PASS; full relevant workflow unit suite227
  tests PASS; governance46 + controller16checks and two semantic/formal
  self-tests PASS; compile and canonical frontend validate PASS.
- Before new measurement, adapter reproduced original Q0 exactly:86closed,
  102signals, trades/events/daily bars/valuation/admission equal. Original B
  durable result reproduced with original result seal unchanged.
- New result with different PYTHONHASHSEED2718 reproduced immutable bytes.
- Independent saved-artifact arithmetic without evaluator imports/raw prices:
  18,616checks PASS, including38reference returns,34causal weights, full costs,
  3×120daily marks, C/exposure, all cohorts,7same-calendar windows, current
  winner groups, monthly/symbol concentration, recovery and fixed bootstrap.
-172preserved files and7durable output/spec/design/artifact file hashes match.
- Pre-outcome remote CI34031776921 PASS. PR/head/master verification uses the
  same existing Top5 No-Credit Exit workflow and immutable verify-only command.

Code/test/CI success is distinct from the measured economic goal failure.
No new candidate or second period was tested. No deploy is required.

## Future state

DESIGN.md's existing owner and source archive findings are preparation only.
Future Q0/B archive/observer connection remains NOT_IMPLEMENTED/NOT_ACTIVE;
no scheduler or future economics started. Existing collector/G5B/Top5 operation
and executionNONE/orderBLOCKED/liveBLOCKED remain unchanged. Paid externalAI0,
Gemini videoNOT_RUN. Research price-taker costs do not acquire actual-fill,
signed-funding or account-sizing authority from this result.
