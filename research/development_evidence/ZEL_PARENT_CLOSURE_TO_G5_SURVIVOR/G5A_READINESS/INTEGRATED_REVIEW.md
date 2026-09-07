# PR1211 finite integrated review

Scope: `ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR`, `task-c28e09b57c612762`, existing PR1211. Reviewer: `integrated_review`. This is one bounded implementation/evidence review, not a second provider review, market replay, source collection, sealed-data inspection or economic qualification.

Decision: the fresh-process repair resolves the actual referenced-global P1. The evidence adapter includes the exact DEV2025 immutability correction below and may be integrated. KR3 remains `HOLD_ALPHA_PROOF`; this review supplies no formal approval, G5A/G5B PASS or promotion authority. CI and fixed-merge reproduction remain the root integrator's mandatory gates.

## Actual counterexamples and disposition

| Risk | Reproduced evidence | Repair and verification |
|---|---|---|
| Referenced-global substitution, comment5576068887 | Before repair, replacing the native module's `json`, `produce_reports`, or indirect `native_replay` left `producer_binding(execute_sealed_bytes)` unchanged. All three printed `BINDING_UNCHANGED True`; no sentinel, market replay or sealed read ran. This matches the actual [review comment](https://github.com/leegkssk2000-commits/vultr-z/pull/1211#issuecomment-5576068887). | Production no longer invokes the parent's callback. A signed source-closure/runtime/worker manifest selects copied source bytes, then a fresh `-I -S -B` process imports only that snapshot plus its independently administered standard library. Replacements in the parent's JSON object, report function and indirect helper cannot receive the input. |
| Mutable dependency or source after authorization | Prior code-object/globals-dictionary identity did not bind dependency values. | Source bytes are captured before authentication and bound to the signed manifest. The child verifies manifest, all source hashes and runtime identity before reading stdin. Original file mutation cannot change the staged bytes. Direct callback/code mismatch is still rejected by the canonical binding check. |
| Signature verifier selected through caller PATH | An actual synthetic temporary executable named `openssl`, containing only an exit-zero shell command, made the old `_signature_valid` accept an invalid public key and a 64-zero-byte signature. Sealed reads and reservations were both zero in this counterexample. | `/usr/bin/openssl` is fixed and checked with the existing protected-path owner; the child verifier receives only the fixed locale environment and its private temporary cwd. The new fake-PATH/invalid-signature regression rejects before reservation/read. |
| One-use right lost on error or cancellation | Reviewed durable reservation before read and failure receipt paths. | Fresh-child failure keeps the reservation; the next attempt rejects `QUERY_RIGHT_ALREADY_RESERVED_NO_RETRY`. Timeout/cancellation kills and reaps only the owned process group. No automatic retry or reservation reset was introduced. |
| Child environment/import/output | Reviewed actual subprocess arguments, copied import closure and output validation. | Caller environment, `PYTHONPATH`, site packages and checkout cwd are excluded. Child lifetime is bounded at120seconds; output is capped at64MiB, parsed as finite JSON and required to be a dictionary. Synthetic tests cover isolated paths, altered source, timeout/reaping, invalid JSON/non-dictionary and output limits. |

The S1 owner ran 12 new tests successfully in15.591seconds and 25 directly affected existing tests successfully in11.812seconds. The latter run preceded the final fixed-verifier hardening; the new invalid-signature and normal signed-dispatch tests cover that change. CI must execute the final integrated files. The native integration uses390 artificial constant bars per original symbol, zero trades and all nine payloads; it is implementation evidence, not a repeated historical experiment. Its final strengthening exercises signed fixture `_execute` → durable reservation → reader → fresh native child, with formal admission false.

The independently administered host, standard library and dispatch implementation remain trusted. A Python source snapshot is not a sandbox against a malicious host administrator. Prior file-only producer signatures do not authorize the new execution manifest; independent signing must bind the new identity.

## Economic evidence review

The unchanged `a1_alpha_proof_gate_v1` and `g5b_operational_terminal_v1` owners were inspected. No gate, candidate or numeric acceptance threshold was changed.

| Gate | Reviewed linkage and remaining limitation |
|---|---|
| P0 | The actual KR3 native comparison is one empirical support. Two periods or two files from the same campaign are not fabricated as independent primary evidence; P0 remains incomplete. |
| P1 | Three actual entry features map to frozen native code: EMA ordering, reclaim and directional half. Reference occupancy, actual slot, first-breach state and the KR3 holding-time veto are kept outside the entry-observable feature list. This supports the owner's P1 pass without claiming that future holding state exists at entry. |
| P2 | Explicit inherited values and seven-symbol modeled cost values are linked. `numeric_parameter_inventory_complete` is false; code hashes are not substituted for prior empirical justification. Transitive DSL and proxy-policy derivation gaps remain. |
| P3 | Existing stored FULL counts, gross expectation and modeled cost components are reused with candidate/data/cost parity. Means are not relabeled as required medians. Downstream numeric conditions are stated as necessary only; the KR3 launch decision remains unfulfilled. |
| P4 | Native replay receives no regime-entry feature. Regime labels are attached after native replay, so label permutation cannot change its economics. Only this control has a reasoned non-applicability row; three applicable controls and all entry-feature ablations remain incomplete. |
| P5 | There is no exact KR3 two-provider review receipt. Agent names are not counted as independent providers. API unavailable/not called is preserved. This controller review is not an external provider result. |
| P6 | General immutable-source and cost metadata exist, but their full-data SHA equals the saved SEEN2026 identity. Listing the separate DEV2025 hash does not itself prove an exact immutable full-to-DEV2025 slice relationship. The root integrator applied `exact_history_verified(authority, data_sha)`, which requires actual dataset-SHA parity. General evidence is retained separately; the mismatched DEV2025 `immutable_history_verified` and `historical_immutable` claims are false. KR3 split approval, proxy validation and integrity unknowns remain explicit; no new source audit is requested. |

The root's first actual projection command returned P-IDENTITY/P1 true, P0/P2–P6 false and `HOLD_ALPHA_PROOF`. The root corrected P6 and regenerated the affected projection once; this did not change the economic verdict or replay a market. Eight new evidence regression tests passed (seven adapter tests and one exact-history parity regression), including changed candidate, non-whitelisted input, hash drift, false causal availability, unjustified parameter priors and regime non-applicability that does not pass other controls.

Nine-report distinction is preserved: five report families have actual stored DEV components (`base_replay`, modeled `realistic_cost`, `cost2x`, descriptive `chronological_split`, `symbol_decomposition`); four have no actual candidate-bound measurement (`purged_oos`, `regime_decomposition`, `parameter_neighbor_stability`, `negative_controls`). All nine prior synthetic payloads remain explicitly synthetic. None is relabeled as a current actual sealed-producer receipt or independent OOS.

## Integration and stop boundary

The workflow's continuation classifier includes the new scoped files. The existing first-merge source trigger is not broadened; the integrator must use a distinct merge title, preserving the consumed source allocations. No old source run, Q0/G5B observer or other Work was touched by this review. No53,813 or30day×3 universal G5A threshold was introduced.

Root ownership: retain the applied exact P6 truth-label correction and final test/CI records, merge only after required checks, reproduce the fixed merge SHA once, save the completion record, then REPORT_ONLY and stop. No further reviewer or optional audit is requested.
