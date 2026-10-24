# HGL1 Work D ownership and duplicate-execution audit

Observed: 2026-10-24T09:44:46.358Z

**Verdict: HOLD_EXISTING_D_RUNTIME_CLAIM_DIRECTORY_UNVERIFIED.**

The existing shared durable D reservation directory, unused permanent HGL1 claim, new result directory and cross-host allocation are not verified. Do not start HGL1 DEV on the strength of this audit. This HOLD is scoped to HGL1; it does not acquire, change or block A's economic owner or other existing Work.

## Evidence

- D branch `work/zel-portfolio-coverage-20261021` remains at `ab71035013e226bdc9409a5f36f2f22c7cde3320`.
- A owner ref `research-coordinator-claims/issue1358-cloud-work-v1` remains at `910f998b1d60ddec30a76366ba49253a4afaa8dd`.
- Issue #1358 latest retrieved handoff comment is [6382321576](https://github.com/leegkssk2000-commits/vultr-z/issues/1358#issuecomment-6382321576), updated 2026-10-24T09:04:38Z. It records HGL1 actual-market DEV 0 / FULL 0 and leaves the existing D runtime claim/output paths unverified.
- The complete handoff at `6b91fd2ab8b8933c004712c1d8e49ce6a9fbe035`, path `research/campaigns/scalp7_20261024/holygrail_source_contract_v1/WORK_D_HANDOFF.md`, Git blob `0643f252d9b245f4a250adff3e44eb92a7b83b91`, requires an existing shared durable D reservation directory and cross-host allocation check. Neither it nor the inspected owner record supplies that directory.
- The frozen runner uses permanent exclusive claim filename `HGL1_RASCHKE_FIRST_PULLBACK_LONG_ZEL_V1.claim.json`. This audit neither creates nor consumes it.
- Owner JSON blob `7c6fd03e7a236710cefbcf192b7edf82ebf43db5` has no HGL1 entry. Its old invocation is `K117_UNCHANGED_PASSIVE_C_AND_D`, state `RELEASED`, phase `TERMINAL`, completed 2026-10-22T11:37:28Z. Its D output `/home/z/k117_be_observer_d_once_20261022_v1` is completed K117 evidence, not an HGL1 reservation.
- The VPS worktree inventory has 95 entries. Its only D-named worktree is `/home/z/worktrees/zel-work-d-k117-be-observer-v1`, detached at `af9451b4ad7efc2111bf88a1901df2d9a8a71a49`. No HGL1 worktree or matching HGL1 process was observed.
- Bounded immediate-child metadata in `/home/z`, `/home/z/z/runtime` and the old D K117 worktree did not establish an existing HGL1 shared reservation directory. Completed KAMA/Grimes filenames were observed only; their bodies were not opened.
- GitHub Actions read-only queries returned 3 in-progress and 15 queued runs. None has an HGL1/HolyGrail workflow name. Existing workflows were not started, cancelled or changed.

## Limits and continuation

No local process match and no matching workflow name are not cross-host proof that HGL1 was never consumed. Scoped metadata absence is not a global filesystem absence claim. No denied ledger, alternate rendition, global scanner, new collector or immutable snapshot export was read or created by this audit.

The root task separately audits the approved source and input eligibility. HGL1 DEV can proceed only after both that eligibility check and a factual existing D ownership/unused-claim check pass. Preserve the K117 control and completed KAMA/Grimes work. No DEV, FULL, guard, tests, orders, Actions mutation or owner/runtime mutation was performed here.

Machine-readable observations and all returned workflow metadata are in `OWNERSHIP_AUDIT.json`.

