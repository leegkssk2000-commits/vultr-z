# Q4R3 Team/Advisor Upgrade Roadmap v1

## Canonical naming

Human-readable names are fixed as:

- `LBot`, `MBot`, `OBot`, `SBot`
- `AlphaTeam`, `BetaTeam`, `GammaTeam`, `DeltaTeam`
- `ZBot`, `Zico`, `Lico`, `Zlice`

Legacy spellings such as `ZICO`, `LiCo`, `LICO`, `zico`, and `lico` may be accepted only while discovering old files and units. Every new report, contract, status, UI label, and roadmap entry must emit `Zico` and `Lico`.

## Current position

The current Exact25 ledger remains a frozen Strategy/Method baseline only. It cannot support Skill, Team, ZBot, Zico, Lico, or Zlice performance claims.

Blocking facts:

- S0 readiness is 0/12
- canonical owners are ambiguous or missing
- Alpha/Beta/Gamma/Delta owners are missing
- Skill lineage proof remains incomplete
- ZBot dual-provider routing, cost, fallback, and evidence policy are not locked
- Zico control-plane ownership and contract are unproven
- Lico is fragmented and lacks a single source/freshness/execution contract

## Invariants

- Paper=false, Live=false, Order=false
- order_authority=blocked, execution_authority=none
- no Producer, Writer, Formal Ledger, Strategy, Method, or Skill Registry mutation during S0
- no historical backfill
- no Team/Advisor binding before S0 PASS
- no S-grade claim before S1/S2/S3 forward evidence

## R0 — Canonical Truth Lock

1. resolve active units to real executable files
2. resolve symlinks and wrapper chains
3. separate runtime owners, adapters, APIs, contracts, tests, and UI consumers
4. classify candidates as KEEP / ABSORB / RESERVE / QUARANTINE / ARCHIVE
5. pin one canonical owner package per component
6. pin SHA-256, version, Git lineage, and runtime owner
7. audit ZBot provider adapters, model aliases, prompt policy, budget, fallback, and evidence outputs
8. audit Zico lifecycle, permissions, idempotency, and fail-closed behavior
9. audit Lico sources, freshness rules, execution-cost model, and team-specific context
10. accept legacy Zico/Lico aliases for discovery but reject legacy spellings in outputs

R0 owner-resolution rules:

- a generic role word such as `trend`, `risk`, `advisor`, or `context` is never sufficient owner evidence
- a systemd `.wants` symlink is never the canonical owner
- interpreter paths must be resolved to their actual Python or shell scripts
- wrapper chains must be followed until the first-party implementation is found
- package ownership is permitted when one package intentionally contains several cohesive modules
- a filename containing `snapshot` is not contamination by itself
- contamination is excluded by directory lineage or explicit backup/archive naming, not by an isolated functional word
- exact component identity or runtime binding evidence is required

Exit gate:

- canonical owner proven for LBot, MBot, OBot, SBot, AlphaTeam, BetaTeam, GammaTeam, DeltaTeam, ZBot, Zico, Lico, Zlice
- duplicate owners = 0
- active execution paths mapped = 100%
- unclassified runtime candidates = 0
- unresolved symlinks = 0
- unresolved wrappers = 0
- canonical-name violations = 0

## R1 — Foundation Contracts: Zico Skeleton + Zlice Event Core

This foundation precedes Bot behavior upgrades so every later decision is controlled and recorded from its first forward event.

Zico minimum foundation:

- event-sourced lifecycle state machine
- idempotency and causal ordering
- one-position/one-owner lease
- permissions and capability checks
- fail-closed invariants
- deterministic replay skeleton

Zlice minimum foundation:

- append-only event contract
- event_id, decision_id, position_id, parent_event_id
- strategy_id, method_id, skill_id, team_id
- source_ids, contract_version, event_ts
- duplicate prevention and parent-chain validation

Baseline lifecycle:

`candidate_created -> team_resolved -> advisor_reviewed -> admitted -> open_requested -> open_confirmed -> managing -> close_requested -> closed_verified`

Exit gate:

- invalid parent event rejected
- duplicate event rejected
- replay produces the same state
- UI remains read-only consumer
- no execution authority introduced

## R2 — LBot/MBot/OBot/SBot Contract Upgrade

Shared envelope:

- position_id, symbol, side
- strategy_id, method_id, skill_id
- event_ts, source_ids, contract_version
- decision, confidence, abstain, reason_codes
- freshness_ms, latency_ms, evidence_ids

Role upgrades:

- LBot: trend regime, strength, continuation thesis, hold/reduce hysteresis
- MBot: method suitability, range state, conflict and timing quality
- OBot: breakout quality, fake-breakout, anomaly, momentum shift, MFE/MAE
- SBot: hard veto and soft penalty separation; stale, SL, DD, exposure, liquidation buffer, authority, duplicate state

Exit gate:

- typed input/output contracts
- deterministic reason codes
- confidence, abstain, freshness, latency
- failure isolation and tests
- no private execution authority

## R3 — Team Organization Upgrade

Each Team retains the original organizational design:

- one Main Bot
- one Support Bot
- two or three independent Watchers
- optional Helper activated by an explicit trigger

AlphaTeam/BetaTeam/GammaTeam/DeltaTeam assignments must be recovered from canonical evidence before modification. They must not be collapsed into identical weighting profiles.

Required Team output:

- team_id, main_thesis, main_action
- support_result, watcher_flags
- helper_used, helper_trigger_reason
- confidence, abstain, veto
- strategy_id, method_id, skill_id, evidence_ids

Exit gate:

- one canonical owner per Team
- Main/Support/Watcher/Helper assignment locked
- Watchers cover independent failure modes
- Helper activation is deterministic
- duplicate evidence is deduplicated

## R4 — Lico Execution Intelligence

Required capabilities:

- depth, spread, imbalance
- expected slippage and market impact by size preset
- funding, basis, open interest, liquidation stress
- BingX venue health and latency
- per-source freshness and source-consensus confidence
- macro/FX context with release-time leakage guard
- team-specific Alpha/Beta/Gamma/Delta context

Lico remains context-only and has no direction or order authority.

Exit gate:

- every source has owner, timestamp, stale threshold, and fallback
- stale/conflicting data produces abstain or hold context
- execution estimates are replayable

## R5 — ZBot Dual-Provider Meta-Advisor

ZBot compares complete Team proposals. It does not replace Team reasoning or Zico control.

Provider modes:

- BYPASS: no external model call
- SINGLE: one-provider review
- DUAL_BLIND: independent OpenAI and Gemini review
- OFFLINE_BATCH: post-close evaluation

Call policy:

- hard veto or missing/stale core data -> BYPASS and deterministic hold/block
- clear Team agreement without meaningful delta -> BYPASS
- minor uncertainty -> SINGLE
- high-risk disagreement or route conflict -> DUAL_BLIND
- provider conflict -> abstain; no third-model tie-breaker

Required controls:

- pinned model aliases
- identical structured input/output schema
- no execution capability
- per-decision and per-day budget guards
- provider circuit breaker
- bounded retries
- prompt version, hashes, tokens, latency, and cost recorded in Zlice
- No-ZBot/OpenAI-only/Gemini-only/Dual-Blind ablation

Exit gate:

- schema validity 100%
- unauthorized action 0
- duplicate provider call 0
- budget violation 0
- provider conflict handled deterministically

## R6 — Event-Driven Skill Lineage Repair

- Producer emits immutable decision/open envelopes
- Skill evidence is written at decision/open time
- Close joins deterministically by position_id and decision_id
- no historical reconstruction

Exit gate: 20 new closes, 100% lineage, duplicate/missing/stale = 0.

## R7 — Full Zico Integration

After Bot, Team, Lico, ZBot, and Skill contracts are complete, finish Zico orchestration:

- timeout, compensation, and state reconciliation
- SSOT policy compiler
- canary routing and rollback
- complete permission matrix
- complete invariant engine
- complete deterministic replay

Exit gate:

- no stale or reversed transition accepted
- no order without explicit authority
- no Shadow context leakage into Paper/Live
- rollback and replay verified

## R8 — S-grade Forward Gates

S1 20C: complete integrity.

S2 100C: per-Bot, per-Team, Lico, ZBot provider-mode ablation; avoided-loss, missed-profit, false-block, calibration, latency, and cost.

S3 300C: Strategy -> Method -> Skill -> Team -> Lico -> ZBot -> Zico -> Zlice, including fee/slippage/latency/DD/exposure penalties and no regression versus the frozen raw baseline.

## Immediate next action

Run R0 Canonical Truth Lock only. Do not patch behavior until the owner matrix and KEEP/ABSORB/RESERVE/QUARANTINE decisions are complete.
