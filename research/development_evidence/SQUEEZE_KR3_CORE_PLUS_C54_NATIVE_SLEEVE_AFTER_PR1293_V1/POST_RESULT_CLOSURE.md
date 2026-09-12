# Post-result saved-only closure

Run `34690370575` completed both authorized U4 economic union evaluations exactly once and persisted their RESULT/SNAPSHOT/DECOMPOSITION/ARBITRATION/RECEIPT records:
- candidate89 / evaluation160 / DEV2025
- candidate89 / evaluation161 / SEEN2026

The shared budget is terminal clean: reserved=2, started=2, completed=2, failed=0, remaining=0; cumulative candidate/evaluation counters are 89/161.

After both results were persisted, the original all-in-one workflow terminated on the final diagnostic assertion `DONOR_NET_BRIDGE`. This did not consume or rerun economics. The saved snapshots themselves show exact bridge equality:
- DEV2025: child terminal net 18688.380986414617 - frozen parent 12642.057772682116 = 6046.323213732501, exactly the saved donor_net_contribution_bps.
- SEEN2026: child terminal net 13118.157906502269 - frozen parent 5924.430823152206 = 7193.727083350063, equal within floating representation to saved donor_net_contribution_bps 7193.727083350063.

Therefore closure is strictly saved-only. It must:
1. pin frozen SPEC parent/donor/input hashes;
2. pin both completed receipt hashes;
3. verify each child snapshot delta equals its saved donor contribution and sum of donor_net_by_symbol;
4. verify core_retention_fraction=1.0 and eligibility gates;
5. apply the already-frozen adoption contract;
6. write SUMMARY/INCUMBENT_SEAL/FINAL_STATUS/STATUS/REPORT only.

PR #1295 review finding `r3996063642` identified a post-result evidence-only defect: `sleeve_role` had been added to 167 naturally accepted donor rows after their original C54 row seal, so their top-level `trade_sha256` / `observation_sha256` no longer matched the canonical row bytes. The authorized repair is strictly saved-only: remove the stale top-level row seal, recompute it after `sleeve_role`, update the enclosing RESULT/RECEIPT hashes, verify all 167 persisted natural donor rows, and rerun this saved-only closure. Strategy semantics, metrics, SPEC, budget, and economic results must not change and economics must not rerun.

No strategy replay, parent/donor replay, candidate/evaluation allocation, market/OOS/fresh/G5 access, rule mutation, threshold rescue, paid AI, order or deployment is permitted in this closure.
