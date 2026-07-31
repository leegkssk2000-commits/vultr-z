# ZEL Component Pipeline V2

Research-only replacement for the superseded V1 component loop.

- Independent LBot/MBot/OBot/SBot profiles.
- Alpha/Beta/Gamma/Delta evaluate every watcher; SBot keeps hard-veto precedence.
- ShortBeam and loss-direction adds remain observer-only.
- TEAM → SKILL → ZBOT → ZICO → LICO is applied sequentially only when the current-stage delta is material and non-negative.
- ZLICE validates lineage and never mutates economics.
- Exact attribution residual must be zero.
- Fewer than 20 trades forces LOW_SAMPLE_HOLD.
- Groq and Workers AI receive material axes only.
- Gemini direct-video runs only for a new exact fingerprint or convergence, generates hypotheses only, and is fingerprint-deduplicated.
- Shadow, Paper, Live and order authority remain blocked.
