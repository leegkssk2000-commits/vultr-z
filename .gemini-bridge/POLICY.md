# Gemini Assistant Bridge Policy

## Purpose

Use Gemini only as a read-only auxiliary researcher when the primary GitHub evidence, source files, logs, or public documentation are insufficient for a confident strategy or implementation decision.

## Allowed uses

- Summarize and compare public YouTube videos relevant to trading-system design, backtesting, execution, risk management, data integrity, or software engineering.
- Re-analyze sanitized public source material supplied in the request.
- Extract claims, assumptions, contradictions, methods, timestamps, and practical test ideas.
- Provide a second-opinion analysis that is independently verified before any repository change.

## Free-only constraints

- Model is fixed to `gemini-3.6-flash`.
- `free_only` must be `true`.
- Google Search grounding, Maps grounding, paid tools, Vertex AI, and billable extensions are forbidden.
- Maximum 5 public YouTube URLs per request; normally select 1-3.
- Public YouTube URLs only. Private, unlisted, paid, or authenticated sources are forbidden.
- Stop and return HOLD on quota, billing, permission, or model-access errors. Never enable billing automatically.

## Source selection

- ChatGPT selects candidate public videos using public web evidence before invoking Gemini.
- Prefer relevance, recency, creator credibility, method transparency, and view count together.
- High view count is a discovery signal, not proof of correctness.
- Record title, channel, publication date, URL, observed view count, and selection rationale when available.

## Safety boundaries

- Never transmit API keys, exchange credentials, private user data, private strategy code, order paths, production configuration, or confidential repository content.
- Gemini may not modify code, strategies, registry, router, services, Shadow, Paper, Live, or order authority.
- Gemini output is advisory only and cannot satisfy STRUCTURE_LOCK, performance, reproducibility, or promotion gates.
- Any actionable claim must be independently checked against primary documentation, repository evidence, or deterministic tests.

## Output requirements

- Separate verified claims, creator opinions, assumptions, contradictions, and unresolved questions.
- Include useful timestamps for video-derived claims when possible.
- State what evidence would falsify or validate each material claim.
- End with a minimal test plan rather than an unverified strategy change.
