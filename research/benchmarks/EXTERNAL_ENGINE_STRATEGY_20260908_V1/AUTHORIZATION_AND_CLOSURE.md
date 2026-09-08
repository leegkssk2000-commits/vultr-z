# PR1219 — authorization and original-outcome anchor disposition

## Existing owner request / review r3960192058

The owner explicitly requested: “그럼 엔진, 전략 대조 들어가.” and then “이어서 진행해”. The requested object is the ZEL engine and external strategy benchmark, not a frontend-only change. The pre-outcome SCOPE.md and the original PR body already recorded this exception under AGENTS.md: the finite research/benchmarks/EXTERNAL_ENGINE_STRATEGY_20260908_V1 directory, its own .github/workflows/zel-external-benchmark-v1.yml, the narrow completed-scope classifier in .github/workflows/step7-parent-survivor-v1.yml, and the append-only existing campaign BUDGET.json used for actual evaluations69–72.

This note records the existing task authorization; it is not a new blanket backend/workflow permission or a substitute for owner approval of a different task. AGENTS.md is unchanged. Native strategy, source/OOS/prospective collectors, live/order authority, SSH and deployment are outside this scope and remain untouched. Canonical frontend validation passed before the economic work and in final-head CI. The remaining review fix only changes saved-evidence verification and adds tests/documentation; it does not rerun the benchmarks or alter any original outcome.

## Original-outcome protection / review r3960192067 — accepted and fixed

The old verifier checked each result against its adjacent receipt, so coordinated replacement of both could evade that local integrity check. The new RESULT_ANCHOR.json contains21 exact SHA256s recovered from the original completed artifact10065819623, run34250475392/job102143325404, result commit863243f0382c0187807f7b1e4fd7b5e3cb3f2681. These pin all4 results,4 receipts,4 actual attempts, the original scientific SPEC/code, upstream source/license, environment, pre-economic tests and the executed budget snapshot. The original SPEC and result bytes are not amended.

verify_saved.py embeds the SHA256 of that exact manifest and verifies it BEFORE any arithmetic or receipt pairing. It then checks every pinned file. Thus replacing result+receipt fails, and updating their adjacent manifest hashes as well still fails the embedded manifest digest. This is a fixed post-execution outcome anchor, not an independent market observation, an external signature, or a claim that arbitrary replacement of the trusted verifier/host can be defeated. Authorized code changes to the trust anchor remain review-controlled; there is no automatic regeneration or reseal command.

Three new standard-library synthetic regressions cover coherent result+receipt substitution, paired substitution plus manifest rewriting, and mandatory anchor invocation at verifier entry. The first uses a coherent existing alternate payload that passes arithmetic to avoid confusing arithmetic validation with original-outcome identity. No market engine is imported or executed by these tests.

The consumed workflow remains read-only, with no economic dispatch, installer, input download, or git writer. Its existing benchmark-directory watch covers the new anchor and tests. Final CI and exact merged-commit verification must finish before PR closure is reported. D/D2/KR3/Break history, hypothesis48/evaluation72 state and all original economic verdicts remain unchanged.
