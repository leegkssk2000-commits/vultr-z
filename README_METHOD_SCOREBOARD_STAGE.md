# Exact25 Method Scoreboard Stage

Read-only observer stage after Risk Scenario Grid.

- consumes the six-profile projection, future pair status and 12-scenario risk grid
- records raw method metrics: trigger, blocked, close joins, Net R, average R, positive rate, profit factor, drawdown, fee, slippage, MFE, MAE and hold time
- derives descriptive return/drawdown and MFE-capture ratios
- does not rank methods before a separate SSOT evidence gate exists
- no historical backfill
- no strategy, method, registry, producer, writer, ledger, Paper, Live or order mutation
- expected initial verdict: `METHOD_SCOREBOARD_HEALTHY_WAITING_FORWARD_TRIGGER`
