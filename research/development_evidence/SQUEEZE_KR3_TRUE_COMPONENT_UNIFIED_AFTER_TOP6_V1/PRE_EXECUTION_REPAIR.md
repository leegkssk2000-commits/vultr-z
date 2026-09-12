# PRE-EXECUTION repair — run 34688864954

The first branch workflow run `34688864954` completed canonical validation and all 106 frozen/synthetic regressions, then stopped in the pre-economic CAPREUSE saved verifier at `ALL_DAILY_CASH_MARKS`.

No `SPEC.json`, candidate reservation, `EXECUTION_STARTED`, child RAW/RESULT, candidate ordinal 85–87, or evaluation ordinal 153–158 was created or consumed. Child economic execution count = 0.

Root cause: this new workflow forced `actions/setup-python@v5` Python 3.11, while the original candidate82 saved-verification workflow `34538469208` ran on the Ubuntu-24.04 runner's default Python and passed the same byte-pinned verifier/source/input/result. The saved verifier uses exact equality for the daily marked metrics dictionary, so cross-runtime floating reduction differences are not a strategy/economic discrepancy.

Repair is transport/runtime-only before any economics:
- remove the newly introduced Python 3.11 override;
- execute under the same Ubuntu-24.04 default-Python class as the original verifier;
- preserve the failed run and all existing parent bytes;
- do not edit CAPREUSE raw/results/accounting/verifier or any U1/U2/U3 trading rule;
- keep retry=false for any actual economic evaluation.

The final selection/report step will read the already-verified saved CAPREUSE `SNAPSHOT.json` files directly instead of re-deriving parent daily marks under another runtime. Child snapshots are created once in their actual execution runtime and then verified as saved evidence.
