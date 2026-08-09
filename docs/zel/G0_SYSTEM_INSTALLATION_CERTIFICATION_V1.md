# G0 SYSTEM INSTALLATION CERTIFICATION V1

## Objective
Establish one fail-closed installation and runtime-ownership certificate before destructive cleanup or Shadow integration.

This gate reconciles the two active roadmap needs:
1. control-plane cleanup safety (`workflow trigger/owner audit` + `runtime reference graph`), and
2. component installation proof (`strategy / skill / bot / method / replay / cost / workflow`).

## Mandatory order

### G0-A — CONTROL PLANE CENSUS
1. `P1.1 workflow trigger/owner audit`
   - enumerate workflows and triggers;
   - identify canonical owner, superseded/one-shot/duplicate triggers;
   - prove there is no competing runtime owner before any cleanup.
2. `P1.2 runtime reference graph`
   - enumerate references from workflows/config/registry/systemd/runtime entrypoints to strategy/config/module files;
   - unresolved references fail closed.
3. `master + runtime source census`
   - bind canonical path, runtime path, source SHA, registry/import owner and active owner.

### G0-B — COMPONENT CERTIFICATION
Each component receives a level, never a binary "installed" label.

- `L0_PRESENT`: canonical/runtime file exists and SHA is recorded.
- `L1_BOUND`: registry/import/systemd/runtime owner resolves to that SHA; duplicate owner count is zero.
- `L2_CONTRACT`: input/output schema, authority boundary, fail-close, idempotency and rollback contract pass.
- `L3_EVIDENCE`: role-appropriate real-data evidence exists; exact replay is required only for economic transforms.
- `L4_SHADOW_READY`: end-to-end active route preserves state/ledger/cost/authority/display invariants.

Shadow-impacting modules must be `L4` before integration into Shadow. Alpha BASE research does not wait for unrelated advisory modules to reach L4; Data/Replay/Cost/Core at L3 is sufficient to continue BASE research.

## Covered inventory
The certificate must cover, at minimum:
- 25 historical strategies;
- canonical Alpha families: `trend_momentum`, `carry_flow`, `relative_value_psa`;
- skill registry;
- ZBot, Zico, Zlice, Lico;
- Trade Methods;
- replay/data/cost/calibration owners;
- workflow/control-plane owners;
- registry/runtime bindings used by the active route.

## Strategy-25 disposition protocol
All 25 are identity-checked and baseline-smoked first. They are not all given identical heavy replay.

1. `25/25 identity + baseline smoke`
2. zero-signal strategies -> funnel diagnosis:
   `raw_condition -> setup -> qualified -> order_intent -> closed_trade`
3. trade-bearing strategies -> exact-source baseline parity
4. component counterfactuals on one axis at a time
5. disposition:
   - `VARIANT`: standalone OOS edge plus independent information relative to canonical Alpha family;
   - `ABSORB`: component adds positive incremental OOS edge to a canonical BASE;
   - `OVERLAY`: useful regime/entry/risk/exit/execution transform, not standalone Alpha;
   - `QUARANTINE`: lineage, provenance, path, sample or zero-signal cause unresolved;
   - `KILL`: causal/economic failure, duplicate information, placebo-equivalent, cost-negative or rescue exhausted.

For `ABSORB`, the relevant test is `Base -> Base+component` on the same data/cost/time geometry. Win rate is ranking-only, not a PASS gate.

## Cleanup authority
No destructive cleanup is allowed during G0-A or before the reference graph and certification manifest are complete.

Allowed before certification:
- read-only inventory;
- hash/reference graph generation;
- classification as candidate residue;
- quarantine plan;
- rollback proof.

Actual deletion requires all of:
- canonical owner identified;
- zero active references;
- zero runtime ownership;
- rollback path recorded;
- replacement source certified where applicable.

## Release sequence after G0
`G0-A control-plane census -> G0-B installation certification -> proven-safe cleanup/quarantine -> P2 trend_momentum BASE -> P3 carry_flow BASE -> P4 relative_value_psa BASE -> P5 strategy25 absorption/variant migration -> P6 Alpha Variant Tournament -> P7 Portfolio/Ensemble (only after >=2 independent survivors) -> P8 Shadow -> P9 Paper -> P10 Live`.

## Hard locks
- Do not use file existence as proof of installation.
- Do not use source-SHA parity as proof of functional readiness.
- Do not reuse historical 25-strategy results as current canonical authority without current-source parity.
- Do not combine weak strategies to manufacture apparent portfolio edge.
- Do not destructively clean while reference ownership is unresolved.
- Do not open Shadow/Paper/Live/order authority from this gate.

`execution_authority=NONE`
`order_authority=BLOCKED`
`action=hold`
