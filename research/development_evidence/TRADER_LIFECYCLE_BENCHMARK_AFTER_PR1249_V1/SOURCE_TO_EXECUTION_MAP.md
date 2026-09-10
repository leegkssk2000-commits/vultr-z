# Source to execution map

|Source stage|Class|Code / observable / order|Accounting|
|---|---|---|---|
|Recent high, daily squeeze, cup/handle, price above21EMA|SOURCE with A01-A04 IMPLEMENTATION_CHOICE|daily_features/setup_at; completed daily prefix, radius2 confirmation; next4h activation|setup/pending/occupancy events retained|
|EMA8/EMA21/breakout entries|SOURCE with A05-A06 IMPLEMENTATION_CHOICE|open_point/segment; frozen levels;30/40/remainder; no lookback fill|actual lot quantities and fixed-reference allocation|
|2ATR disaster stop|SOURCE with A07 IMPLEMENTATION_CHOICE|add; first fill; monotonic average-entry stop|per-lot gap/touch gross and research costs|
|Three-day failed progress|SOURCE with A08 IMPLEMENTATION_CHOICE|manage_close at72h; one cost-aware<=0 decision; next actual open|realized+remaining decision cost through now|
|One-third high/1.272/1.618 ladder|SOURCE with A09 IMPLEMENTATION_CHOICE|target; frozen H/L and decimal unit; assembled quantity snapshot|partial legs aggregated into one campaign|
|Stop entry−ATR, entry, three-day trail|SOURCE with A10 IMPLEMENTATION_CHOICE|next_stop then next bar; last three completed daily lows|saved lot ledger and daily boundary values|
|OHLC order and evaluation censor|IMPLEMENTATION_CHOICE A11-A12|execute_bar conservative feasible paths; pending/open retained|ambiguity difference, terminal hypothetical exit costs|
|SqueezePro exact code, options greeks, actual trader fills/account returns|UNSUPPORTED|not substituted with claimed replication|no fidelity/independent/live credit|

C68 remains preserved; no C63/C68 signals are supplied to this candidate. All A01-A12 provenance resides in HANDOFF/contracts; first market outcomes cannot alter this map or the numerical choices.
