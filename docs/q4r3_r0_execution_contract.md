# Q4R3 R0 Canonical Truth Execution Contract

## Scope

R0 is a read-only ownership and runtime-lineage audit for:

- LBot, MBot, OBot, SBot
- AlphaTeam, BetaTeam, GammaTeam, DeltaTeam
- ZBot, Zico, Lico, Zlice

Canonical human-readable spelling is fixed to `Zico` and `Lico`. Legacy aliases are discovery inputs only.

## Evidence hierarchy

1. active systemd unit -> resolved ExecStart script -> resolved wrapper/package implementation
2. exact component filename/class/package identity
3. explicit contract/config binding
4. Git lineage, SHA-256, contract version, tests
5. role words only as supporting evidence, never as ownership evidence

## Mandatory distinctions

Every discovered surface must be classified by kind:

- runtime_core
- package_core
- adapter
- api_surface
- contract
- configuration
- service_wrapper
- ui_consumer
- test_support

A systemd `.wants` symlink is not an owner. A service file is not an implementation owner. A UI card is not a decision owner. A test is not a runtime owner.

## Candidate classification

R0 produces recommendations only; it does not move or delete files.

- KEEP: proposed canonical runtime/package owner
- ABSORB: useful module to merge under the canonical package
- RESERVE: inactive but potentially useful implementation
- QUARANTINE: conflicting, unsafe, or authority-bearing surface
- ARCHIVE: obsolete support, duplicate wrapper, or display-only legacy surface

## Contamination policy

Directories with explicit backup/archive/rollback/quarantine lineage are excluded. Functional filenames such as `lico_snapshot_bridge.py` are not excluded merely because they contain the word `snapshot`.

## Safety invariants

- no systemd mutation
- no file deletion, move, reset, clean, checkout, or stash in the active tree
- no Producer, Writer, Formal Ledger, Strategy, Method, or Skill Registry mutation
- Paper=false, Live=false, Order=false
- order_authority=blocked, execution_authority=none
- no historical backfill

## R0 PASS gate

- 12/12 canonical owner packages proven
- duplicate owner count = 0
- active execution path mapping = 100%
- unclassified runtime candidate count = 0
- unresolved symlink count = 0
- unresolved wrapper count = 0
- canonical output name violation count = 0

Any unresolved item yields HOLD with an explicit fix queue. No behavior patch begins from a partial R0 result.
