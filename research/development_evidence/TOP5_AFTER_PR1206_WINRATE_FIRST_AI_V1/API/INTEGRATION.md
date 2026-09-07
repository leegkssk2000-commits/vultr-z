# Current API lane: BLOCKED, research use incomplete

Actual external AI calls: 0. Actual remote presence probes: 0. Remote secret
presence and run ID remain UNKNOWN/null. The low-win-rate question remains
unresolved; the completed old TPC1 code review does not make this call unnecessary.

The GitHub connector has no workflow_dispatch action. The local runtime has no gh
or GH_TOKEN/GITHUB_TOKEN binding. Browser is available, but the control-browser
skill forbids using it solely to recover a missing plugin-owned capability. No
GitHub website navigation, sign-in, provider request, or secret-value inspection
was performed. GET fetch and existing rerun tools were not used as dispatch.

The one free user action is Actions → **Top5 Cumulative V4 Manual API** → Run
workflow → branch **master**, **allow_network=false** (unchecked), retain
`research/development_evidence/TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1/API/API_APPROVAL.json`,
then Run workflow once. The pilot job is skipped. Save its run ID and the presence
artifact `top5-cumulative-api-probe-<run_id>`; do not post secret values.
[Official manual workflow instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow?tool=webui).

The new adapter binds the current scope to the existing canonical
`TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1/API/SHARED_TASK.json` on master.
It reuses the old fixed-host GitHub Contents SHA-CAS store, request implementation,
and lifecycle Registry. `bind_scope(existing_ledger, current_task)` returns a
proposal for the root writer; it performs no remote write. A prior existing
current task wins over a stale task supplied to this helper. Both older scopes,
their attempts, and old W2 stay frozen. The aggregate budget remains USD5 and at
most one Gemini plus one optional OpenAI request across all three scopes.

The frozen old Python module is loaded in a separate namespace. Only its scope
and DEV source directory are bound to V5; the imported old module and its file are
unchanged. The new adapter freezes its own bytes and the manual workflow in
addition to the original three runtime dependencies. Root must include
`prior_scope_digests` in approval, mapping each older scope to lifecycle
`digest(task)`, and inherit the exact `inherited_task_sha256`. The current task
must already exist in the canonical ledger before remote runtime opens it.

[Google's exact thinking guide](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
confirms that Gemini 2.5 Flash can disable thinking with `thinkingBudget=0`.
Together with `candidateCount=1` and the [GenerateContent maxOutputTokens field](https://ai.google.dev/api/generate-content),
the existing request caps its one response at 6000 tokens. The exact route is
`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent`.
The [model limit](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash)
is 1,048,576 input tokens; reserve this full accepted context as a conservative
bound, without claiming that the dossier uses that many tokens. The dossier is
separately limited to 16000 UTF-8 bytes. At [standard text rates](https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash)
of USD0.30/M input and USD2.50/M output, the token-price reservation is
USD0.3295728. Account tax/FX upper-bound authority is still UNKNOWN, not zero.
The corresponding gate remains closed until that evidence exists. Usage is not
an invoice; any sent request retains its reservation until actual reconciliation.

Root is the sole paid-request owner. The proposed workflow patch routes only the
exact new approval path to V5 while keeping the same manual workflow, no-network
probe, first-attempt gate, and concurrency group. It is not installed by S3.
No economic replay, holdout access, additional policy candidate, or API economic
benefit was measured by this role.
