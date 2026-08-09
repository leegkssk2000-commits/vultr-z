# ZEL Engine vNext — Unified G0 + Alpha-First Roadmap

Status: DESIGN/CONTROL AUTHORITY; execution=NONE; order=BLOCKED.

## Canonical engine

`Market/Data -> Integrity/Source/Cost -> Alpha Engine -> Regime Router -> Entry Qualifier -> Risk/Exit -> Execution -> Portfolio -> Bots/Skills/Advisor -> Shadow -> Paper -> Live`

Initial Alpha Engine families are exactly:
1. `trend_momentum`
2. `carry_flow`
3. `relative_value_psa`

## Objective

PASS order:
1. integrity valid;
2. OOS Net PnL > 0 after admitted costs;
3. OOS expectancy > 0;
4. DD within Z_POLICY v3.0 / SSOT;
5. WR is ranking-only.

No TP/SL/exit optimization before positive forward alpha edge.

## Absolute execution order

### G0-A — control-plane census
- workflow trigger/owner census;
- workflow dispatch/call graph;
- repository reference graph;
- master/runtime source census;
- unresolved active owner/reference => HOLD;
- destructive cleanup forbidden.

### G0-B — installation certification
Every strategy/module/bot/skill/method/data/replay/cost/workflow receives `L0_PRESENT -> L1_BOUND -> L2_CONTRACT -> L3_EVIDENCE -> L4_SHADOW_READY`.

Covered minimum inventory: historical strategy25, the three Alpha families, Skill registry, LBot/MBot/OBot/SBot route where applicable, ZBot, Zico, Zlice, Lico, Trade Methods, replay/data/cost/calibration, registry and workflow owners.

### Cleanup/quarantine
Only after G0 reference ownership is complete. Sequence: inventory -> reference proof -> quarantine/disable -> regression -> delete only proven-dead material. Evidence/rollback receipts are preserved.

### P2 — trend_momentum BASE
BTCUSDT/ETHUSDT native 15m; causal closed-bar signal -> next-bar-open fill; raw forward edge first; then actual cost admission; OOS objective gate.

### P3 — carry_flow BASE
Native funding/basis/flow source binding first; timestamp/holding-cost causality; same OOS objective gate.

### P4 — relative_value_psa BASE
Both pair legs and spread construction source-bound; causal pair adapter/fills; cost-aware OOS gate.

### P5 — strategy25 migration
The old 25 are a hypothesis/component library, not 25 parallel production engines.

Route each strategy through:
`25/25 current identity + baseline smoke -> zero-signal funnel OR trade-bearing exact-source parity -> one-axis component counterfactual -> disposition`.

Migration roles: `ALPHA_PRIMITIVE | REGIME_FILTER | ENTRY_QUALIFIER | RISK_EXIT_OVERLAY | EXECUTION_OVERLAY | ARCHIVE_KILL`.

Final decisions: `VARIANT | ABSORB | OVERLAY | QUARANTINE | KILL`.

- `VARIANT`: standalone OOS edge + unique information, max two per family.
- `ABSORB`: Base -> Base+component gives positive incremental OOS edge on identical data/cost/time geometry.
- `OVERLAY`: useful non-alpha transform for regime/entry/risk/exit/execution.
- `QUARANTINE`: lineage/provenance/path/sample/zero-signal cause unresolved.
- `KILL`: duplicate, non-causal, placebo-equivalent, cost-negative, or three rescue generations exhausted.

A genuinely orthogonal positive legacy edge may be recorded as a future-family candidate, but no fourth family is admitted while seed survivor count is zero.

### P6 — Alpha Variant Tournament
One BASE + at most two variants per family. Three failed rescue generations => kill/redefine.

### P7 — Portfolio/Ensemble
Requires >=2 independently validated survivors. Portfolio cannot manufacture edge from failed alphas.

### P8 — Shadow
Only certified active-route modules. Validate candidate->open->close lifecycle, ledger/state/display parity, costs, DD/exposure, duplicate open/close, and authority.

### P9 — Paper
Validated Shadow survivors only. Failure-learning/ML-Light initially observer-only.

### P10 — Live
Last stage. UI/Bot/Skill completeness alone never opens live/order authority.

## Canonical pipelines

Research: `ingest -> integrity/source validation -> causal feature -> alpha signal -> replay -> cost model -> OOS gate -> survivor registry`.

Release: `survivor registry -> regime/entry/risk/execution -> Shadow -> Paper -> Live`.

No direct strategy->live, AI->promotion, Bot->order or legacy-workflow bypass is permitted.
