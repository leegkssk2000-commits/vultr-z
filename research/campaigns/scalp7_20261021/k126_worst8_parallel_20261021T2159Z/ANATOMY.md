# K126 worst8: execution-time anatomy, no new economics

Classification: SAVED_LEDGER_PLUS_CAUSAL_RAW_PATH_DIAGNOSIS_NOT_NEW_ECONOMIC_RESULT
Source: 81a12c422ee9329996d2f6b983267d2def490d4b
All126 included; outcomes are diagnostic labels only.

Worst8 total: -1128.22511669 trade-bps; STOP4 -592.82876551; SCRATCH4 -535.39635118.
Four scratch positions overlap 2026-02-23T04:30:00+00:00 to 2026-02-23T06:00:00+00:00. Loss share 47.45474%.
All four entries predate the first realized loss among them. This refutes a retrospective claim that a post-loss cooldown would prevent all four.
Whole-pullback close exit did not precede original exits for any of the eight.

|Entry UTC|Symbol/side|Reason|Net trade-bps|Initial risk/ATR|Raw matching extreme age min (not exact state age)|
|---|---|---|---:|---:|---:|
|2026-02-07T02:00:00+00:00|XRP-USDT/1|STOP_FIRST|-192.28643279|0.93701|0.0|
|2026-02-16T11:30:00+00:00|DOGE-USDT/-1|STOP_FIRST|-164.58304390|1.61503|60.0|
|2026-02-16T19:00:00+00:00|DOGE-USDT/-1|STOP_FIRST|-99.08215333|0.77306|30.0|
|2026-02-23T03:30:00+00:00|ETH-USDT/-1|HG_FROZEN_5BAR_MFE_SCRATCH|-51.52254313|7.20213|180.0|
|2026-02-23T03:30:00+00:00|SOL-USDT/-1|HG_FROZEN_5BAR_MFE_SCRATCH|-56.64683900|8.35011|300.0|
|2026-02-23T04:30:00+00:00|LINK-USDT/-1|HG_FROZEN_5BAR_MFE_SCRATCH|-197.54538881|6.98735|300.0|
|2026-02-23T04:30:00+00:00|XRP-USDT/-1|HG_FROZEN_5BAR_MFE_SCRATCH|-229.68158023|8.72225|1080.0|
|2026-02-23T08:30:00+00:00|SOL-USDT/-1|STOP_FIRST|-136.87713549|1.39944|30.0|

## What to implement next, separately
C: exact state/level provenance and pre-exit observability; a single justified adapter, no parameter sweep.
D: causal same-direction exposure and same-time outcome audit, with complete winning counterexamples and unit/SSOT binding.
A remains the only economic owner. C/D must not run competing FULL.

STOP_FIRST and SCRATCH are outcome labels, not proven causal filters.
The latest close-through-whole-structure rule had no actionable pre-exit event in any of the worst8.
Four scratch losses overlap. Waiting for their realized losses cannot retroactively prevent their earlier entries.
Large initial risk/ATR changes the scale of MFE_R and the existing scratch hurdle; provenance/stale-state is an open question, not a proven bug.
Never turn this observed risk_ATR range, outcome labels or dated cohort into a numerical filter.
Matching raw extreme age is not exact native touch/state origin. Native state tracing is still needed.
The 8-loss row run depends on native tie ordering; preserve it and report decision batches separately, never relabel it away.

No new profit increase, loss reduction, live performance or independentOOS is claimed by this diagnostic.
