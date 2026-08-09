# ZEL Engine vNext — Alpha-First Architecture and Migration Roadmap

Status: DESIGN AUTHORITY / RESEARCH ONLY  
Order authority: BLOCKED  
Execution authority: NONE

## 1. Canonical engine

```text
Market/Data
  -> Integrity + Source Binding + Cost Contract
  -> Alpha Engine
       1) trend_momentum
       2) carry_flow
       3) relative_value_psa
  -> Regime Router
  -> Entry Qualifier
  -> Risk / Exit
  -> Execution
  -> Portfolio
  -> Bots / Skills / Advisor
  -> Shadow
  -> Paper
  -> Live
```

The production architecture is deliberately small. The 25 historical strategies are not allowed to remain as 25 parallel first-class engines.

## 2. Objective

PASS order is:

1. integrity is valid;
2. OOS net PnL > 0 after admitted costs;
3. OOS expectancy > 0;
4. drawdown is within Z_POLICY v3.0 / SSOT;
5. win rate is ranking information only.

A higher win rate is not required for PASS. TP/SL/exit optimization is forbidden until the underlying forward alpha edge is positive.

## 3. Alpha-family rules

- Exactly three canonical families are admitted initially: `trend_momentum`, `carry_flow`, `relative_value_psa`.
- One BASE per family.
- At most two admitted variants per family.
- At most three rescue generations per failed family/base hypothesis; then kill or redefine.
- Ensemble/cross-family allocation requires at least two independently validated survivors.
- AI may propose hypotheses, review, and red-team. AI may not promote a survivor or grant execution/order authority.

### trend_momentum

First BASE target: BTCUSDT/ETHUSDT, native 15m. Closed-bar signal -> next-bar-open fill. Causal features only. 1h/4h may be used only when native source binding is verified. Cost admission is mandatory.

### carry_flow

Funding/basis/flow inputs must be source-bound before signal evaluation. No synthetic or assumed funding/basis source may be used for an economic verdict.

### relative_value_psa

Pairs/relative-value data and adapter must be source-bound before economic evaluation. Pair construction, spread state, and fills must remain causal.

## 4. What happens to the historical 25 strategies

They are frozen as a **hypothesis and component library**, not deleted and not allowed to route directly to paper/live.

Each legacy implementation must be decomposed into exactly one primary migration role:

- `ALPHA_PRIMITIVE`: a feature or raw signal that can strengthen a canonical family.
- `REGIME_FILTER`: a market-state condition.
- `ENTRY_QUALIFIER`: entry timing/confirmation only.
- `RISK_EXIT_OVERLAY`: sizing, stop, trailing, partial, or exit behavior.
- `EXECUTION_OVERLAY`: order/slippage/turnover/execution behavior.
- `ARCHIVE_KILL`: duplicate, non-causal, non-source-bound, or economically dead logic.

Each item then receives one deterministic decision: `ABSORB`, `VARIANT`, `OVERLAY`, `QUARANTINE`, or `KILL`.

The historical implementation inventory is stored in `research/legacy_strategy25_inventory_v1.json`. It is an audit inventory, not current-master execution authority.

### Migration rule for genuinely orthogonal legacy edge

Do not force a valid legacy edge into the wrong family merely to preserve a three-family shape. If a legacy hypothesis survives causal/source/cost/OOS/DD checks and is demonstrably orthogonal to all three canonical families, record it as a **future-family candidate**. Do not admit a fourth production alpha family while the alpha-first lock is in zero-survivor state. A new family requires a separate deterministic architecture decision after core evidence exists.

## 5. Legacy-25 audit scorecard

Every legacy item must produce:

```text
legacy_name
source_path
source_hash
signal_lineage
migration_class
target_alpha_family
causal_ok
native_data_ok
raw_oos_edge
net_oos_edge
oos_expectancy
dd_within_ssot
correlation_to_family_base
unique_information
decision
```

No result without source path/hash and replay lineage may become a variant or overlay.

## 6. Canonical research pipeline

Collapse research into one chain:

```text
ingest
 -> integrity/source validation
 -> causal features
 -> alpha signal
 -> replay
 -> cost model
 -> OOS gate
 -> survivor registry
```

Release chain is separate:

```text
survivor registry
 -> regime/entry/risk/execution integration
 -> shadow
 -> paper
 -> live
```

There is no direct `strategy -> live` route.

## 7. Cleanup / de-sprawl pass

Cleanup is mandatory before broad strategy expansion, but deletion is evidence-driven.

### KEEP / REWIRE

- native data/source binding;
- cost model;
- replay/execution simulation;
- deterministic integrity and risk primitives;
- SSOT policy references;
- immutable research evidence/receipts.

### QUARANTINE / AUDIT

- historical Strategy11 workflow/fixture stack;
- legacy 25 implementations;
- superseded research candidates/configs;
- mixed-layer strategy modules where alpha, gate, sizing, and exit concerns are combined.

### DELETE only after reference proof

- tracked generated `tmp`/dummy artifacts;
- dead duplicate configs;
- inactive duplicate workflows;
- caches/transient outputs;
- files with zero inbound imports/references and no evidence/rollback value.

Current master visibly contains cleanup candidates such as tracked `dummy/` and `tmp/`, both `config/ensembles.yml` and typo-like `config/esnemble.json`, a mixed `strategies/` directory containing signal/gate/sizer/exit concerns, and a large set of Strategy11-specific workflows. These are **audit candidates**, not immediate deletion authority.

For every candidate, create a cleanup manifest row:

```text
path | inbound_refs | runtime_trigger | evidence_value | action | reason | rollback_ref
```

Required sequence: read-only inventory -> reference graph -> quarantine/disable if necessary -> regression verification -> delete only proven dead material.

## 8. Execution roadmap

### P0 — Alpha-first lock

- Canonical engine order.
- Three-family allowlist.
- Simplified objective.
- Zero-survivor change lock.
- CI regression that proves low WR can still PASS when net/expectancy/DD/integrity pass.
- CI regression that proves unrelated engine/portfolio/bot/shadow expansion is blocked.

### P1 — Cleanup inventory and pipeline collapse

- Enumerate workflows, timers/triggers, strategy modules, research scripts, configs, tmp/dummy outputs.
- Build inbound-reference graph.
- Classify KEEP / REWIRE / QUARANTINE / DELETE-CANDIDATE.
- Disable only verified obsolete active triggers first; do not erase evidence receipts.
- Produce one canonical research pipeline and one release pipeline.

### P2 — `trend_momentum` BASE

- BTC/ETH native 15m only.
- causal features and next-bar-open fills;
- raw edge first, then actual cost admission;
- OOS net/expectancy/DD gate;
- no exit optimization before positive forward alpha.

### P3 — `carry_flow` BASE

- bind native funding/basis/flow sources;
- verify timestamp alignment and holding-cost semantics;
- run same deterministic OOS economic gate.

### P4 — `relative_value_psa` BASE

- source-bind pair legs;
- validate pair adapter and spread causality;
- run cost-aware pair replay and OOS gate.

### P5 — Legacy 25 decomposition

- freeze current implementations/hashes;
- classify every item by layer;
- replay only unique alpha primitives;
- de-duplicate correlated/identical lineage;
- absorb useful components into canonical layers;
- kill or quarantine unsupported logic.

### P6 — Variant admission

- max two variants per alpha family;
- variants must add unique OOS information, not merely improve in-sample metrics;
- three failed rescue generations -> kill/redefine.

### P7 — Cross-family portfolio/ensemble

Only after >=2 independent survivors. Portfolio logic may allocate among survivors; it may not manufacture edge from failed alphas.

### P8 — Shadow integration

Validate lifecycle, state/ledger/display parity, execution assumptions, costs, DD/exposure, and no duplicate open/close.

### P9 — Paper canary

Paper authority opens only after the prior gates are deterministic and reproducible. Failure-learning/ML-light remains observer-only unless separately promoted by its own gate.

### P10 — Live readiness

Live remains last. No route is opened merely because UI, bots, skills, or ensemble layers are complete.

## 9. Stop conditions

Stop/hold rather than patch around any of the following:

- missing or stale source binding;
- non-causal feature/fill path;
- unavailable cost contract for an economic verdict;
- non-positive OOS net PnL or expectancy;
- DD outside SSOT;
- lineage/hash mismatch;
- duplicate/ambiguous authority path;
- attempt to expand downstream layers while zero-survivor lock is active.
