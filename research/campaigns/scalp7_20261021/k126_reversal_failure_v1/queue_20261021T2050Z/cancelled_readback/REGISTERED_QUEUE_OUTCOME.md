# K126 post-entry comparison: actual queue registration and pre-start cancellation

{
  "observed_at_utc": "2026-10-21T21:05:11.596139+00:00",
  "run_id": 39674182903,
  "attempt": 1,
  "registered_head": "cb5c45d716a7823c0b10201bbf1a15601698051a",
  "registered_position_snapshot": 2,
  "result": "CANCELLED_BEFORE_ANY_JOB",
  "run_updated_at_utc": "2026-10-21T20:54:20Z",
  "job_count": 0,
  "STARTED_exists": false,
  "SUMMARY_exists": false,
  "economic_consumed": 0,
  "direct_cancellation_actor_or_annotation": "NOT_OBTAINED",
  "mixed_queue_policy_confirmed": true,
  "shared_declarations": 58,
  "default_single": 50,
  "retention_patch_prepared_not_applied": true,
  "orders": 0
}

The existing one-shot comparison was actually registered in the common GitHub concurrency group, then cancelled before any job. Registration is not economic completion. The frozen trading rule, data and K126 baseline are unchanged.

The cancellation actor/annotation was not available. Do not claim a specific actor caused it. A repository-wide read of master af8e9c10490e0f7b414b61b29c898fda78311b50 found 58 exact common-group declarations, 50 still using default single-pending retention. GitHub documents that a new single-pending arrival replaces an existing pending request. This is a verified queue-policy defect and a plausible explanation, not a retrieved cancellation annotation.

A 50-line queue:max-only patch is provided, with parsed-YAML equivalence checks proving all triggers, jobs, commands and permissions unchanged. It has NOT been applied or merged. Some existing affected workflows execute economic steps on PR events: opening a broad PR without controlling those triggers could launch unauthorized comparisons, so no broad PR or mass reruns were created. Current active jobs and B were not stopped.

No extra profit or loss reduction has been measured in this turn. The exact prepared rule remains unconsumed, and new economic execution must retain shared serialization and the existing owner. Do not restart idle-polling guards or repeatedly submit the same cancelled request.
