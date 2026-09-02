# Clean Minimal G5 Evidence Runner V1

## Scope

This runner replaces only the G5 evidence/control plane. It does not alter any strategy, entry, exit, cost, symbol universe, allocation, order, or live-trading rule. Primary remains retired. Broad remains on its existing W2 lineage and is not reset or reclassified.

## Seven logical modules

| Module | Single responsibility |
|---|---|
| source_adapter | Fetch and decode the canonical BingX USDT-M public 4h kline stream. |
| closed_bar_gate | Canonicalize `symbol|4h|bar_close_ts` and reject forming, duplicate, gapped, or invalid bars. |
| append_only_state_store | Enforce hash-chained monotonic state transitions under an exclusive file lock. |
| frozen_strategy_adapter | Evaluate only the three versioned frozen semantic assets. |
| trade_lifecycle_ledger | Track next-open/time-stop shadow trades and append one immutable economic row per `trade_id`. |
| fresh_acceptor | Fail closed unless every provenance, integrity, cost, and DATA_STALE gate passes. |
| telemetry_orchestrator | Record complete timing tuples and build shadow/cutover receipts. |

Runtime dependencies are Python standard library, the frozen clean-runner contract, and the frozen strategy manifest. No legacy collector or writer is imported. The old feature engine is used only by tests as an independent parity oracle for Supertrend and Break semantics.

## Authority sequence

1. Local schema/freeze/owner/state preflight.
2. Synthetic canary with formal credit zero.
3. `SHADOW_NO_CREDIT` on genuine closed 4h bars.
4. Three consecutive complete shadow bars.
5. Explicit cutover eligibility receipt; no automatic cutover.
6. After separately approved cutover, three further genuine bars establish production-ready parity.

DATA_STALE absence does not block evaluation or telemetry. It always blocks fresh acceptance. Legacy receipts remain intact and legacy evidence authority is treated as diagnostic only; it is never an automatic rollback target.

## Persistence and crash model

State and economic records are append-only JSONL. Each record contains a sequence number, previous-record SHA, payload SHA, and record SHA. Each append is protected by `flock`, flushed, and `fsync`'d. The GitHub workflow has one non-cancelling concurrency group and persists byte-prefix-monotonic ledgers to `master`. A partial or conflicting record causes a hard failure and formal credit remains zero.

## Rollback

Before cutover, stop the clean runner workflow and retain all receipts. After cutover, stop fresh acceptance and repair the clean runner. Do not reactivate the legacy evidence plane automatically.
