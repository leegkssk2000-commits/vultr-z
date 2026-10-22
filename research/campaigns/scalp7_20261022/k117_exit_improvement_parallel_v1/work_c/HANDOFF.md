# K117 Work C: loss timing and passive exit trace

**Disposition: NO_DISTINCT_CAUSAL_RULE.** One passive observer and an A-only run-once harness are implemented. No new trading policy or `RULE_FREEZE.json` is submitted. Real-price instrumentation and new-policy economics were not run by C. This is executable instrumentation plus a new saved-ledger decomposition, not a claim of improved returns.

## New findings from the exact117 ledger

All numbers below describe the frozen USED_DEV baseline; units are summed trade-bps. The raw decompressed ledger is SHA256 `7cba96a0627dbec42459f344a6e8e7dd70d97f87d71dfb573e10975153d7d0a7`, economic commit `8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8`. No old ALL126 path export was substituted.

| Existing progress range, retrospective only | Base losses | Loss Net1x | Base winners in same range | Winner Net1x |
|---|---:|---:|---:|---:|
| Credited MFE below existing0.40R scratch hurdle | 32 | -4337.9697454 | 4 | +139.93969435 |
| Credited MFE from0.40R to below existing1R BE | 14 | -1871.7557294 | 3 | +142.15062017 |

- All46 losses have credited MFE below1R. Because native MFE is monotone and stop checks precede its update, none is a loss after the existing1R BE/2R partial/3R runner activation. The stop-hit terminal bar's uncredited extremes remain unknown. This is a code-constrained exclusion, not a new entry/exit filter.
- Each progress range includes one nonnegative-gross, net-negative trade. Those two losses are not gross price failures.
- Two first-held-bar stops total **-220.33715589** Net1x. There was no completed post-entry callback before either stop. A close-confirmed exit preserving initial stop and priority cannot preempt these two.
- Seventy of71 winners contain a credited surviving-bar adverse range and a favorable final price. This is evidence of adverse movement before the final favorable exit, not a known first adverse close, MAE/MFE sequence, recovery timestamp or executable counterfactual fill. The seven winners in the table directly oppose using terminal progress ranges as a failure rule.
- Existing accepted post-rejection traces bind touch time for only11 entries (4 losses,7 winners);106 remain unknown from the saved ledger. The215 expired-setup events are not forcibly joined to accepted entries. The observer obtains touch provenance from the actual K117 objective object.
- The1x longest-count run is5 trades/-689.75494808, while the worst-amount run is3/-892.53216124. At2x the canonical longest11/-868.87050878 includes7 base losses and4 base winners; the worst-amount10/-1465.02985865 includes7 base losses and3 base winners. They are separate measures and sets.

`SAVED_LEDGER_REVIEW.json` contains all117 records, all71 winner counterexamples, exact source pins and run membership. `SOURCE_MAP.md` connects original source coverage to native fields/functions and falsification. Existing signal-bar/whole-pullback, prior-ADX, handoff, blanket-touch, ATR/cost and delay variants are not resubmitted. No new source-backed condition yet distinguishes earlier thesis failure from recovery; choosing a threshold now would manufacture that distinction.

## Executable identity and input contract

| Component | Identity / contract |
|---|---|
| Unchanged K117 policy | `scalp7_k126_veto_objective_completed_fresh_touch_v1` |
| Passive observer | `k117_passive_exit_observer_c_v1` |
| A harness scope | `K117_PASSIVE_EXIT_OBSERVER_C_V1` |
| Build | Exact `structural_failure.ExitComparison(True).build()` then exact `objective_lifetime.build(..., enabled=True)` |
| Execution input | Original BTC/ETH/SOL/XRP/LINK/DOGE order,17519 bars each,30m,full365-day context,round_trip,original windows/segments/gaps/availability/cost snapshot |
| Saved control | Exact K117 raw117 and carry-adjusted117, native traces130, objective-expiry events215, unresolved/boundary collections |
| Full specification | `ALL117_INPUT_CONTRACT.json`; `BASELINE_BINDING.json` records branch/consumption review and runtime hash readback |

The three `K117_*_SOURCE.txt` files are byte-identical baseline test fixtures, not new policy implementations. Their source hashes are checked before synthetic compilation. Runtime uses the pinned existing source chain. `enabled=False` returns the identical callable. Enabled observation invokes K117 once, temporarily traces pinned native functions, and restores the prior tracing hook; it does not replace callbacks, signals, stops or fills.

Observation separates initial admitted risk, signal/touch/entry clocks, bar-open state, completed-bar callback input/return, actual monotone stop/partial application, scheduled scratch/timeout, terminal result and availability. An already-pending next-open exit precedes the new bar's stop check. Otherwise stop/gap precedes target, excursion update and callback. No terminal stop-bar extreme is exposed as an earlier callback input.

The owner harness rejects changed source/input hashes or source order. It uses the existing paired lock and current capacity guard, writes only a new isolated output, and refuses an existing output directory. It compares full ordered raw117 dictionaries, unresolved/boundary lists, native traces and objective events with the saved baseline. It does not execute the former ALL126 observer, recompute carry by extra trade replays, or run a C/D policy comparison.

## A: first executable step

Only `CLOUD_WORK_COORDINATOR_ISSUE1358_V1` may run the native price instrumentation after reviewing its current claim, capacity, receipt and prior-start state. The acknowledgement flag grants no authority and does not create a claim. Do not run if a receipt/partial output already exists; inspect it instead. Do not start Actions, a waiting job, a new service or a competing economics owner.

Use an exact checkout of the Work C delivery commit reported with this handoff at `/home/z/worktrees/zel-work-c-k117-exit-observer-v1`. The checkout's containing commit is the executable source identity; verify it against the immutable remote commit/readback report. The existing baseline runtime supplies the pinned original files and cache. Run this construction-only check first (no prices loaded, no callable invocation, no output files):

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /home/z/z/venv/bin/python -B /home/z/worktrees/zel-work-c-k117-exit-observer-v1/research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/work_c/run_owner_exit_observer.py --bind-only --baseline-input-dir /home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1
```

Then, under the existing owner's normal authority, invoke the exact native observer once:

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /home/z/z/venv/bin/python -u -B /home/z/worktrees/zel-work-c-k117-exit-observer-v1/research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/work_c/run_owner_exit_observer.py --owner-ack CLOUD_WORK_COORDINATOR_ISSUE1358_V1 --run-once --baseline-input-dir /home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1 --output-dir /home/z/z/runtime/k117_passive_exit_observer_c_20261022_v1
```

The output directory must not exist and its parent must exist. Completion requires `PASSIVE_EXIT_OBSERVER_RECEIPT.json` with exact raw117, unresolved, boundary, native-trace and objective-event parity, plus the all-call trace and117-entry coverage. A `STARTED.json` or `HOLD.json` is not success and must not trigger a blind rerun. C has not invoked this command on prices. A should use the available observer without waiting for D; no new C economics candidate exists yet.

## Validation, preservation and limits

Run the synthetic suite from the delivery checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/work_c -p 'test_*.py' -v
```

`SYNTHETIC_TESTS.txt` records the actual command and result; `DELIVERY_MANIFEST.json` binds delivered file bytes. Synthetic tests establish observation and execution-contract behavior, not improved economic results. Native117 parity remains pending A's one run.

Baseline remains117T, Net1x+10159.281145923826/2x+8399.99437120003, PF2.63602742/2.16176107, WR60.68376%/36.75214%, frequency0.47755102/day, cohort-net realized DD1400.17183632/1577.87099992. These are quoted saved values, not account NAV, MTM drawdown, historical actual funding, OOS or live validation. Original K12634 large-winner preservation remains an additional axis for any future economic comparison; all117 raw-row parity is required here.

D's BE activation/height/partial fraction/runner and existing costs are untouched. No economic improvement is claimed; there is no C policy effect to combine with D. All changes are add-only in this directory on the approved Work C branch, `[skip ci]`, non-force publication. A/B/D, master, owner, workflows, root ops/tests and consumption ledgers are preserved. Actions/deploy should not run. Rollback is simply not invoking the new observer; no active policy was replaced.
