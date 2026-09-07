# Native KR3 execution path

The root executes the frozen built-in synthetic integration once with:

```
python -m backend.research.rebuild.step7_kr3_execution_v1 --fixture --out-dir <new immutable output directory>
```

Production has one separate entry path:

```
python -m backend.research.rebuild.step7_kr3_execution_v1 --request <public signed request metadata.json> --out-dir <restricted result directory>
```

The latter calls `step7_authorized_io_v1.dispatch(request, execute_sealed_bytes)`. No unsigned raw-file CLI, caller-selected trust source, fixture approval or self-hash can activate that route. The callable receives bytes only after the authorization owner's durable access reservation. `execute_sealed_bytes` additionally rejects fixture/formal-unapproved specifications. The signature must pin the exact executable, design and cost contract; the booleans are not authentication.

The nine outputs are `base_replay`, `realistic_cost`, `cost2x`, `purged_oos`, `chronological_split`, `symbol_decomposition`, `regime_decomposition`, `parameter_neighbor_stability`, and `negative_controls`. Each contains actual payloads from raw synthetic/native evaluation, identity and specification hashes and a seal. `consume_reports` verifies all nine bytes/identities/required payloads and propagates economic readiness blockers. This byte consumer is not a G5A policy gate or G5B boundary writer. Existing gate thresholds and old STEP7 formal binding owner remain unchanged.

`d.build_bundle` uses the existing DSL, same bounded EMA seed and source index 239. `KR3.replay` invokes `KR1.replay` with the real KR3 path. Each actual symbol has one slot; its D reference reservations remain separate and carry no economics. KR1 retention uses its own FULL replay. Evaluating W1/W2/W3 never clears actual or reference occupancy: signal-close cohort attribution is applied after one complete start-to-runoff replay. The final permitted entry time and runoff deadline are explicit inputs. Unfinished positions remain separate hypothetical marks.

The six finite neighbor tuples rebuild features, original signals and D reference reservations. HOLD changes propagate through D, reservation, M2, KR1 and KR3 owners; decision index is HOLD-1 and extended cap is 2*HOLD. The original files are not changed. A serial lock and restoring context isolate these diagnostic executions; there is no optimization, best-neighbor selection or candidate registration.

Finite controls have explicit, currently unapproved semantics:

- Direction flip: short return and signed funding using the same long information clock and exit times. It is not a fully mirrored short strategy.
- Time shift: six native 4-hour bars forward; the shifted completed bar supplies the newly latched low and directional-half observation. Delayed entry uses one bar forward. Both rebuild their own reference and actual occupancy. Gaps are rejected before evaluation, so six accepted bars equal 24 elapsed hours on this source contract. No future return or parent's admitted trade list selects opportunities.
- Regime permutation: a deterministic causal rotation of the four computed labels. KR3 has no regime-based entry filter. Its economic effect must be zero; the report marks `comparison_valid=false`, and the consumer blocks formal readiness. Inventing a regime entry filter to make this control nondegenerate would change the candidate and is not authorized. Therefore nine computed reports must not be described as four valid economic negative controls.
- Explicit synthetic feature ablations remove trend, reclaim, directional-half and KR3-veto conditions one at a time. They are diagnostic producers, not adopted strategies. The KR3-veto ablation reuses the already computed KR1 FULL parent within the same bundle.

Costs reuse `signed_funding_cost_bps` and the existing `g5a_development_probe_v1.summarize` accounting report owner. Gross native modeled return is retained. An explicitly selected midpoint-return reconciliation separates quote-mid versus native entry/exit price differences from half-spread/depth impact. Fees, spread/impact, signed settlement funding and this basis reconciliation are summed exactly once. There is no separate slippage charge on top of depth impact. The supplied fixture cost2 contract doubles all signed components (including funding income and midpoint basis); this is an explicit proposed stress meaning, not an approved formal cost policy. Missing fee, BBO, timestamp, settlement, availability or cost meaning leaves the trade in the ledger with net=null and reasons. Parent unknown costs also block retention rather than disappearing from its winner denominator.

No signal known late can be claimed filled at an earlier native open. The raw native modeled trade remains for parity, but realistic-cost readiness fails. The producer never claims exchange fills or order execution. The isolated source probe computes native feature/reference metadata and serialized checkpoint parity without historical actual fills or PnL exposure. The latest completed raw signal is evaluated directly by the native DSL; its unobserved next open does not become a fill. A different source seed origin is not attested identical to historical DEV state.

Local verification: nine distinct synthetic tests passed initially. Root identified one concrete price-basis/timestamp/parent-unknown risk; the new regression and only its affected cost test passed after the minimal fix. Ten distinct tests total. The full nine-output integration is assigned to the root serial executor after final freezing, so these local tests are not a new economic experiment or independent validation.
