# C1 native economic result

Classification: actual usedDEV, not OOS or account return.
Disposition: REJECT_C1_GROSS_NEGATIVE_KEEP_EXISTING_CONTROLS
Code ref: d20d140968f3d10934258357601c06e2aaeb0d43

|Metric|Rolling245d cost1x|Rolling245d cost2x|
|---|---:|---:|
|T|133|133|
|T_per_day|0.5428571428571428|0.5428571428571428|
|Gross_bps|-203.84619283836957|-203.84619283836957|
|Cost_bps|1986.2595371726627|3972.5190743453254|
|Net_bps|-2190.105730011031|-4176.365267183693|
|PF|0.4883538662909652|0.2434955099393465|
|WR_pct|44.3609022556391|27.819548872180448|
|DD_bps|2215.392094424083|4176.365267183693|
|MaxLossStreak|9|18|

Validation30d separately: {"closed_T": 23, "unresolved": 0, "levels": {"cost1x": {"T": 23, "T_per_day": 0.7666666666666667, "Gross_bps": -181.74209467063716, "Cost_bps": 346.4733969349619, "Net_bps": -528.215491605599, "NetExp_bps_T": -22.96589093937387, "PF": 0.2164780831282106, "WR_pct": 30.434782608695656, "DD_bps": 615.9531649157348, "DD_kind": "realized_equal_notional_trade_bps; simultaneous outcome cohorts netted together", "MaxLossStreak": 6}, "cost2x": {"T": 23, "T_per_day": 0.7666666666666667, "Gross_bps": -181.74209467063716, "Cost_bps": 692.9467938699238, "Net_bps": -874.6888885405609, "NetExp_bps_T": -38.029951675676564, "PF": 0.057574446572876053, "WR_pct": 17.391304347826086, "DD_bps": 875.9150121064965, "DD_kind": "realized_equal_notional_trade_bps; simultaneous outcome cohorts netted together", "MaxLossStreak": 6}}}

Full native adapter exit0 confirmed, duration712.70seconds including source verification. Source/strategy/cost not changed. All saved metrics independently sum-checked. No synthetic exits. Historical original controls kept. No same-rule parameter sweep.
