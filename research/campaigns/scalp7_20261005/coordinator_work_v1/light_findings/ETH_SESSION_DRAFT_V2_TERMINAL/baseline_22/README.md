# ETH session isolated draft

Status: **NOT_COMMON_RUNNER_INTEGRATED**. This directory is outside the repository.

`eth_session_targets` exposes the signed quantity and causal clocks currently hidden by the common runner's boolean density helper. `replay_eth_sessions` uses supplied records only; it never loads market data, submits a claim, activates a campaign or calls a service.

Direction follows the stored05/17 rule. Execution, fixed unit continuous positions, and next-boundary expiry are explicit internal translations. They do not reproduce a source portfolio's session return or rebalancing. Existing normalized reference costs remain unchanged:14bps roundtrip means7bps per executed unit leg. Same-side boundaries produce no extra fees or closed trade. Funding is separately signed and remains unchanged under trading-cost stress.

The result preserves completed trades, the actual signed-unit turnover ledger, total paid fees, open entry fees, open/pending state and quarantined gaps. Closed-trade cost plus open entry cost must equal executed turnover times the one-way cost. No END force-close or after-END settlement is admitted.

The exact development END at00:00 structurally follows a17:00 long session. An open position is therefore expected for complete input. A terminal-accounting profile must be reviewed and frozen before any economic cheap-run consumption; a positive completed-trade subtotal cannot silently omit the final position and its costs.

The helper rejects missing START/END source coverage and occupied source gaps. Funding archive authenticity and complete465-row coverage remain caller prerequisites. The reported existing ETH raw hash is only parent-provided metadata; this task did not open that archive or any actual price rows.

Validation:22 artificial unittest methods and compile checks passed; independent review also passed22/22. Run only the isolated artificial suite:

```bash
cd /workspace/scratch/060cca3db8fa/eth_session_draft
"$CODEX_PRIMARY_RUNTIME_PYTHON" -m unittest -v test_eth_session_adapter_draft.py
```

Actual market replay, campaign edits, claims, activation and economic/model invocations:0.

