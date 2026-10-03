# Offline input contract and exact resume interface

This is a preparation format implemented by `../input_binding.py`. It does not convert an old observation into a current source certificate and has no real-source strategy execution mode. The runnable synthetic fixture examples are in `tests/test_scalp7_kp_input_binding_v1.py`; all their prices/receipts are generated inputs.

## Actual-input metadata inspection

Use the existing authenticated operator path to supply metadata summaries. Deliver the export file's SHA256 independently through that path. `--pin-origin` describes that path; the code verifies hashes, not origin authentication. Do not use a self-declared hash as provider authentication.

```bash
python research/campaigns/scalp7_20261003/kp_validation_prep_v1/input_binding.py inspect \
  --export /authorized/operator-export/export.metadata.json \
  --expected-export-sha256 <OUT_OF_BAND_EXACT_SHA256> \
  --pin-origin <EXISTING_AUTHENTICATED_OPERATOR_PATH>
```

Without a supplied export, `inspect` returns `CURRENT_OPERATOR_METADATA_EXPORT_NOT_SUPPLIED` plus the separate DATA, IMPLEMENTATION and APPROVAL blockers. It does not create files, read the host or retry an offline connection. Its exit status indicates successful reporting, never execution permission.

Every document includes the exact candidate, `parent_identity` and `parent_module_sha256` pins. Every reference is `{path,sha256}`; paths must be relative `*.metadata.json` inside the supplied export directory. Symlinks, traversal, changed bytes, unsupported/duplicate JSON fields and mismatched schema/pins fail closed. Only these metadata documents are read; no referenced market-body, actual STATE, trade or result file is followed.

| Document | Schema | Additional exact fields |
|---|---|---|
| Export | `kp30.metadata_export.v1` | `census,usage,index` references |
| Census | `kp30.candidate_census_metadata.v1` | `collected_at_ms,ledger,reservations,locks,processes,state` references |
| Each census facet | `kp30.<facet>_metadata.v1` | `collected_at_ms,complete,records[{identity,status}]` |
| Usage | `kp30.usage_inventory_metadata.v1` | `complete,seen[{source_id,body_sha256,start_ms,end_exclusive_ms}]` |
| Source index | `kp30.source_index_metadata.v1` | `sources` list described below |
| Source-clock receipt | `kp30.source_clock_metadata.v1` | matching source fields plus `source_ts_ms,usable_at_ms,processed_at_ms` |

Facet statuses: ledger `NOT_RUN/STARTED/INTERRUPTED/FAILED/COMPLETE`; reservations `ACTIVE/RELEASED/NONE`; locks `LOCKED/UNLOCKED/NONE`; processes `RUNNING/STOPPED/NONE`; state `PRESENT/ABSENT/STARTED/INTERRUPTED/FAILED`. Unknown/missing fields are blocked, not inferred as NONE. Active, locked, running or STARTED records are conflicts. Each facet must be complete and bound to the census collection timestamp.

Each indexed source carries `source_id,body_sha256,received_at_ms,start_ms,end_exclusive_ms,usage_inventory_sha256,usage_inventory_complete,receipt`, with optional `source_identity_sha256`. Its clock receipt repeats source ID/body hash/receipt time/interval and carries nullable native `source_ts_ms`, `usable_at_ms` and `processed_at_ms`. Optional source identity must match on both. Index-use hash/complete and all receipt metadata must match. Native/receipt/usable/processing timestamps are checked against the census collection time. A nullable native clock remains disclosed; metadata binding cannot certify genuine execution clocks.

The immutable inherited ACCESS_INVENTORY SHA `fa8f9bc8a97f04c17ad67b275a7337f3a97128fed052a2879fbab0e30ea24746` is read only as metadata. Its original seen interval, recorded later observed extent and known source identities cannot be forgotten by an empty supplied seen list. Source identity hashes remain distinct from raw body hashes. The current runtime beyond those stored witnesses is not inferred. No source_ref body is opened.

All complete exports still report `execution_ready=false`, `currentness_certified=false`, `unused_status=METADATA_ONLY_NOT_CERTIFIED` and FULL credit0. Census age is a measured duration, with no invented SSOT cutoff. Actual body/use/provenance, costs/funding/intrabar evidence and later authority remain separate requirements.

## Supplied synthetic caller

```bash
python research/campaigns/scalp7_20261003/kp_validation_prep_v1/input_binding.py synthetic \
  --input /supplied/generated-input.json \
  --expected-input-sha256 <EXACT_SYNTHETIC_BUNDLE_SHA256> \
  --output-root /isolated/preparation/kp30_validation_prep_v1
```

A resumed existing attempt additionally requires `--recover`. Recovery must retain the original exact input bytes/SHA, configuration, output namespace and event IDs. Changed input/configuration is rejected; recovery never makes another FULL attempt.

The exact bundle keys are `schema,input_kind,candidate,config,events,cashflow_inputs`. Schema is `kp30.serialized_synthetic_input.v1`, input_kind is `SYNTHETIC_ONLY`. Config has `t0_ms,window_end_ms,runtime_identity,reference_costs_bps`; runtime identity starts `KP30_PREP_SYNTHETIC_`. Events have `event_id,now_ms,quotes,frames,wrapper`; frames serialize `{"30":{"BTC-USDT":[bar records]}}`. Wrapper is the unchanged adapter signal wrapper or null. Cashflow inputs are keyed by the signal opportunity_key and contain supplied `original_qty,quantity_lineage,pit_costs,funding,funding_coverage`; missing source components retain null/blockers.

The caller validates the input file/hash/format before creating a checkpoint. The original bundle SHA is bound into config_sha256 and durable `serialized_input_sha256`. The existing adapter's atomic state and processed-event bindings own recovery and deduplication. The caller outputs candidate-only `STATE.json` and `SUPPLIED_SYNTHETIC_REPORT.json`; pending/open positions are preserved. If final report writing fails after event commits, the attempt remains FAILED and explicit recovery reproduces the report from the same committed event state without duplicate fills.

This mode cannot receive REAL_SOURCE_RECEIPTS or authorize real-price replay. It supplies no collector, order client, production scheduler, FULL reservation or G5B release. Its cashflow definitions retain `PROPOSED_NOT_APPROVED_FOR_ECONOMIC_EXECUTION`.
