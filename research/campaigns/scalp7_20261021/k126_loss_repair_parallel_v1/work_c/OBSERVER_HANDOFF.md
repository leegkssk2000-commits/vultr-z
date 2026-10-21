# First executable delivery: exact-incumbent state observer

Scope `K126_WORST8_STATE_AND_LOSS_REPAIR_C_V1`. Economic owner remains `CLOUD_WORK_COORDINATOR_ISSUE1358_V1`. This first delivery is immediately usable without D or the candidate-policy tests. It does not authorize a new economic comparison.

Identity: `k126_native_state_origin_observer_c_v1`. Synthetic verification: **43 tests PASS**, including full return-object parity with the actual frozen `_fresh_touch_successor`, actual `_hg_event`, admission and stop-first engine on hand-authored prices. No real-price source-state replay ran in C. `OBSERVER_TESTS.txt` is the actual test output.

`observer.py` captures raw/feature availability, touch origin, strict pull-low/high assignment origins, weak-state retention/reset, regime ineligibility, explicit admission rejection, acceptance, and re-arm. Equal-price recurrences never replace an origin. Native after-state and wrapper after-policy state are distinct. Source inputs necessary to independently check touch/turn are included. Malformed or missing origins remain unknown and cannot produce a successful complete receipt.

`NATIVE_SUCCESSOR_FUNCTION.txt` is a test fixture copied exactly from commit `6f7a42171dab54ff1be544304f44ee06fdd8f056`, `ops/scalp7_keltner_fresh_touch_successor_v1.py::_fresh_touch_successor`. The full original module SHA256 is `e0afbe1d76c4a3c8b4470aae82b152bd3f59676339294653719c3f3a85e2f855`; excerpt SHA256 is `9cab68472492d27a0a990cdce73e51ecd8009866f2ba12fc3a29b02381094252`. Production/owner execution uses the existing pinned module, not a replacement engine.

## A-only next command (provided, NOT executed here)

Run from an isolated checkout of this delivery commit on the existing owner host. Its original runtime modules and cached six-symbol prices must already exist; this command downloads no prices. A first checks current owner, prior observer receipt/consumption, its existing allocation, and global/local capacity. The script also checks live capacity, takes the existing lock without creating it, verifies all source/code/context hashes, and refuses an existing output directory. An `--owner-ack` is an acknowledgement, not an allocation or lock replacement.

```bash
K126_INPUT_DIR=$(mktemp -d /tmp/k126-incumbent-81a12c42-XXXXXX)
git show 81a12c422ee9329996d2f6b983267d2def490d4b:research/campaigns/scalp7_20261021/k126_native_structure_failure_v1/completion/ROWS.json.gz > "$K126_INPUT_DIR/ROWS.json.gz"
git show 81a12c422ee9329996d2f6b983267d2def490d4b:research/campaigns/scalp7_20261021/k126_native_structure_failure_v1/completion/SUMMARY.json > "$K126_INPUT_DIR/SUMMARY.json"
python -B research/campaigns/scalp7_20261021/k126_loss_repair_parallel_v1/work_c/run_owner_observer.py \
  --owner-ack CLOUD_WORK_COORDINATOR_ISSUE1358_V1 \
  --run-once \
  --incumbent-input-dir "$K126_INPUT_DIR" \
  --output-dir /tmp/k126-origin-c-v1
```

If that Git object is absent, A may first fetch that exact commit; do not substitute a moving branch. Output is a new directory. Do not blindly retry after `STARTED.json` or a runtime error; inspect its receipt/HOLD first.

Required input SHA256:

| Input | SHA256 |
|---|---|
| `ROWS.json.gz` | `5f45180aa762dc091c16e8fa2d208dcf027c16f795d9533911d2c11d73a30c77` |
| decompressed rows | `98eaa46994eb8c4e9d89e7e17bbb9a9cce97b86f6a3a727c11e8136da75a85f3` |
| `SUMMARY.json` | `a69e1cce4b5dffe004d49820ced626962795952f2e7b06226eb71ad77b8f7812` |
| original context fit | `168044bf3bfd2bc4299c55fca84bc45c2e3ce56a79310e4583b02277c296b86c` |

The harness invokes the latest `structural_failure.ExitComparison(True).build()` once, verifies exact ordered raw126 rows plus unresolved/boundary parity, then writes `NATIVE_ORIGINS_ALL.json.gz`, `ENTRY_ORIGINS_ALL126.json`, and `OBSERVER_RECEIPT.json`. It does not run a candidate, cost comparison, density scan, or optimization. Existing source, runtime, owner, claims and ledgers are read-only.

The saved-data join already completed for all126 in `SAVED_INPUT_REVIEW.json`. It adds risk-unit/origin coverage, not the old anatomy aggregate. The single missing artifact is the pre-entry native/caller lifecycle trace linking each accepted reference to its real assignment. A raw price match cannot fill that gap. Initial risk is frozen from the actual admitted entry and stop; MFE_R uses that denominator even after later stop movement.

Local synthetic reproduction, no runtime/price access:

```bash
python -B -m unittest discover -s research/campaigns/scalp7_20261021/k126_loss_repair_parallel_v1/work_c -p 'test*observer.py' -v
```

No Actions, economic FULL, market API, Paper/Live, orders or deployment was started. This publication is implementation handoff, not owner consumption or an economic improvement receipt.
