# Production Economic Guard V1

Scope: research-only upstream guard for no-idle sample-expansion and Top5 donor synthesis.

Hard-fail invariants:

- Child with zero completed trades cannot claim improvement.
- Child completed trades lower than its comparable parent cannot advance.
- Drawdown improvement from a zero-trade child is invalid.
- Child with both lower net PnL and lower net expectancy cannot advance.
- Donor/admission logic that reduces comparable completed-trade density is blocked.
- Rejecting a child preserves the incumbent and existing fresh25 state; no restart from zero.

This guard has no selection, promotion, execution, order, or live-trade authority. It changes only research candidate eligibility and routing.
