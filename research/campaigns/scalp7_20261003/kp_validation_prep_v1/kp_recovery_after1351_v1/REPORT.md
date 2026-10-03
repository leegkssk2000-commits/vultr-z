# K.P preparation recovery after PR1351

**P2 repaired; offline input binding and serialized synthetic caller added; actual execution remains BLOCKED.**

The source of this recovery is the repository, not the inaccessible prior Work conversation. `PR1351_RECOVERED.json` preserves the PR description, all five discussion/review records, reviewed master `5c9c90b26bc99b7cb69ea64b8f4ea584c292b096`, the ten later unrelated telemetry commits and open lane references. PR1351 merged as `4dafe69189a31642c998c6c8c9130c88ee1f5b96`. No K.P successor or P2 fix was found in that master. Immediately before storage, new master `b94dff1cb480725f8ee6ea9389905c7245e0a5e8` added only the two TrendRider Unified telemetry files; it was incorporated by normal fast-forward without changing this candidate or its tested code. SR #1347, HG1997 #1348 and older 1h Keltner #1016 are separate work and remain untouched.

## Review closure and concrete implementation

P1 is handled by the explicit user authorization exception in AGENTS.md. Both the inherited `../WORK_AUTHORIZATION.md` and this recovery's `WORK_AUTHORIZATION.md` request named research preparation and related tests. No frontend relocation or removal of the authorized research is required. AGENTS.md and all scope guards remain unchanged.

P2 was reproduced before modification. `P2_BEFORE_FIX.json` records that an injected checkpoint-write OSError masked the original RuntimeError, kept the retained object's writer descriptor open and caused same-process recovery to raise `KP_SINGLE_WRITER_LOCK_CONFLICT`. Durable STATE bytes remained unchanged.

`adapter.PrepCheckpoint.__exit__` now preserves the exact original exception object and traceback, attaches the secondary save/close error as a note, and closes the writer in a finally path. `close` closes the descriptor even if explicit unlock fails. Cleanup errors still propagate when there is no body error. Failed saves do not create a durable cursor/credit advance or erase STARTED state; explicit same-attempt recovery remains mandatory. The new fault suite covers RuntimeError, KeyboardInterrupt and SystemExit, simultaneous save/unlock faults, retained-reference reacquisition and committed-state recovery.

| Newly connected function | Actual behavior | Limit |
|---|---|---|
| `input_binding.inspect_metadata_export` | Binds caller-pinned metadata export bytes, candidate/parent pins, census facets, receipt hashes, use index and source clocks; preserves known inherited seen history | No source/STATE/trade body read; pin origin must come from an authenticated operator path; hash does not authenticate origin |
| Metadata receipt validation | Candidate-only summaries of ledger, reservations, locks, processes and STATE; exact schemas; path, hash, clock and conflict checks | No current host export has been supplied; census age is reported without an invented freshness cutoff |
| `input_binding.run_supplied_synthetic` | Serialized event/frame file → existing adapter/checkpoint → quantity/PIT-cost/signed-funding cashflow projection → isolated output report | SYNTHETIC_ONLY, no real-data strategy execution path |
| Durable caller input binding | Original input SHA is included in config/STATE; changed bundle rejected; recovery reuses the same event bindings and attempt | No retry credit or new economic identity |
| Inspection CLI | A concrete blocked report when export is absent; inspect and synthetic modes remain separate | CLI status/report never grants execution authority |

Synthetic caller event decisions reuse the frozen parent and ObservedPaper. The first PR CI exposed a direct-file import-path defect that local inherited PYTHONPATH had masked (1931 passed, one new CLI test failed). FIRST_CI_FAILURE.json preserves exact-head/check/job evidence. The CLI now supplies its resolved checkout root only in its direct-file entrypoint; the regression removes PYTHONPATH/PYTHONHOME and executes from checkout and unrelated directories. No environment/workflow/guard was changed. New file loading does not implement a collector, scheduler, venue trading client, production ledger, terminal scorer, PLUS_ONE_BAR or adjacent strategy paths.

## Current blockers: four distinct classes

| Class | Resolved locally | Still blocked, exact resume dependency |
|---|---|---|
| Connection | Repository/PR/current master and duplicate-work recovery; exported-census input interface implemented | Existing vultr device is Offline, last seen42h in this recovery's one inventory read. Current host ledger, lock, process and source state remain unobserved. Restore the existing normal read-only path or provide a current authenticated metadata export. No request was sent to the offline host |
| Data | Hash/schema/clock/use-history and inherited-seen binding implemented; synthetic quantity/cost/funding connected | No genuine current source inventory or complete use history, PIT fee/spread/slippage, signed-funding interval or intrabar provenance has been obtained. Missing values remain null/blocking. No current unused or fresh certificate |
| Implementation | P2 lock/exception repair, metadata binder and serialized synthetic caller are complete | Market-capable importer/scheduler/ledger, fixed-window controller and terminal/statistical/shift/adjacent paths remain unimplemented; those are outside this nonexecuting preparation |
| Approval | This repair/preparation scope and limited PR1350 baseline admission are grounded in actual user instructions | New protocol SHA `38457e2be737f0076c6f5740ea7698bbf40b4afd8bb7e5eff377d0960a5395f9`, five future paths, new policies, collection, FULL and G5B release remain unapproved |

`CURRENT_INPUT_BINDING.json` is the actual no-export inspection result of this Work. It is not a synthetic current-host witness. Offline does not prove the server is stopped or archives absent. The earlier rejected workflow metadata request was not retried by this recovery.

## Preservation and next resume point

PR1350's `ADMITTED_AS_G5A_FROZEN_RESEARCH_BASELINE_INPUT`, parent identity `389550fddc888266eaf336cdec83a63b05f0e5da198fe21d07a2cf171e4f5710` and module SHA `b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2` remain unchanged. All inherited preparation/protocol/validation receipts remain historical records; the changed adapter has a new source hash in this recovery's validation receipt. The original119 arithmetic, completed admission and oldFULL were not rerun as research.

Resume at the new metadata inspection boundary, not by rerunning the completed preparation or P2 repair. Supply a current candidate-only metadata export with an independently delivered exact SHA from the normal authenticated operator path; inspect its census/hash/use history without opening source bodies. A metadata binding pass still does not approve or start the market strategy. Record unresolved real-source/clock/quantity/cost/funding/intrabar and explicit protocol/execution authority before any later market wiring/release. See `INPUT_CONTRACT.md` for the concrete file interface and `../APPROVAL_BUNDLE.md` only as an unapproved inherited proposal.

No parent tuning, other-lane edits/budget transfer, newFULL, G5B activation, new collection, service change, paid spend or real order occurred. There is no deployment to run. Rollback is a normal reviewed revert of this preparation change; it has no operational service state to unwind. Preserve the recovery evidence and the original source/attempt history when reverting.

Local test counts/source hashes and the independent review are recorded in `VALIDATION_RECEIPT.json`. Remote CI/head/merge observations belong in the actual PR closeout after they are observed; this document grants no unobserved all-green or merge claim.
