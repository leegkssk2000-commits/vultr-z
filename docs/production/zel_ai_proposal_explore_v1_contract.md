# ZEL AI Proposal Explore V1

This layer is proposal-only. It runs only after the deterministic economic-family router reports `HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED`.

Flow: deterministic Explore router -> AI proposal (max 2) -> deterministic source availability gate -> same-cycle Explore router.

The AI may propose a causal economic family/feature hypothesis plus required sources, falsification test, and natural horizon. It may not provide numeric thresholds, parameter sweeps, source code, leverage/sizing, profitability claims, selection/promotion/execution/order authority, or LIVE authority.

Identical Explore contexts reuse the durable proposal receipt. API failures are fail-closed with a one-hour retry cooldown and do not stop the PAPER daemon.

A source-ready proposal is not a survivor and is not executable. It only advances to `FREEZE_AI_PROPOSAL_AND_BUILD_DETERMINISTIC_ADMISSION`. A proposal requiring an unbound source advances only to `BIND_AI_PROPOSAL_REQUIRED_NATIVE_SOURCES` and remains HOLD.

All deterministic economic, durability, integrity, risk, PAPER and survivor gates remain downstream and authoritative.
