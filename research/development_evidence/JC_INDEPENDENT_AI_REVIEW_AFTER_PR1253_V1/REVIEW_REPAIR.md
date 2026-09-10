# Pre-call repair of independent code-review findings

Automatic PR1255 review at 5f001c45 identified two P1 issues. No model has been called.
1. Prompt-only publication constraints are insufficient. public_result now hard-limits all serialized JSON keys/string values together to150 English alphanumeric words and5000 UTF8bytes, and rejects any matching six-word span from the transient publisher source. The model is asked for140 words including keys. A rejected response saves only hash/id/usage/status/estimated cost, never raw text/result. This total envelope also bounds source-derived paraphrase without pretending semantic attribution is computable. It is not a copyright clearance claim.
2. Source review now includes actual daily_features, confirmed_pivots, _average, validate, completed_utc_days as well as squeeze_features/setup_at and the BAR/DAY constants. Review scope is explicitly limited to supplied feature construction; no unsupported claim of auditing the separate boundary-merge/order replay. Input byte/outputtoken and dollar caps unchanged; oversize input fails before providers.

Tests add overlength/source-overlap rejection with metadata/cost retention, plus all requested code-dependency presence.19 artificial tests total. Syntax checked locally; actual full-checkout test execution remains remote.
No other rule, credential, economic budget, historical receipt or strategy changed.
