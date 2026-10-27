# Route A video-fidelity rebuild

## Root cause

The failed `ema_ribbon_beam` experiment was not a faithful implementation of the
Gemini/video Route A source set.

It combined:

- 8/21/55 EMA ribbon ordering,
- compression/expansion,
- reclaim/beam candles,
- ATR/structure stops,
- 2.2R/2.8R targets,
- a 15-minute primary replay.

That is a new hybrid of ribbon, squeeze and beam concepts. It is not the same as
the source strategies that were summarized from the videos.

The principal source Route A mechanics are instead:

1. **Rayner Teo histogram momentum**
   - EMA 60
   - MACD 1/60/9
   - pullback first, then a clearly expanding same-direction histogram bar
   - avoid EMA60 whipsaw
   - source timeframe: 1 hour
   - swing stop; histogram-peak exit or fixed 2R/3R

2. **Linda Raschke trend-filtered MACD cross**
   - EMA 200
   - MACD 12/26/9
   - bullish cross below zero only above EMA200
   - bearish cross above zero only below EMA200
   - swing stop and fixed 2R
   - proprietary PDM marker is unavailable and must be labeled as a proxy

3. **Bill Williams confirmed fractal pullback**
   - EMA 20/50/100 stack
   - pullback to EMA20/EMA50
   - classical five-bar fractal confirmed causally two bars later
   - swing/next-EMA stop and fixed 2R

4. **Bill Williams Alligator pullback**
   - causal SMMA 5/8/13 with historical 3/5/8 display shifts
   - reject tangled/narrow sleeping lines
   - enter the reclaim after a pullback in an established stack
   - swing stop and fixed 2R

## Files in this branch

- `backend/strategies/rayner_hist_momentum.py`
- `backend/strategies/raschke_macd_ema200.py`
- `backend/strategies/fractal_triple_ema_pullback.py`
- `backend/strategies/alligator_trend_pullback.py`
- `backend/strategies/_route_a_video_common.py`

## Fidelity policy

- Exact public indicator settings are preserved when the source summary contains
  them.
- Proprietary indicators are never silently fabricated.
- Any causal proxy is named in the result metadata.
- Entry cores are tested before skills, scale-in, partials, trailing or runners.
- Production registry, paper, live and order paths remain untouched.

## Selection policy

The tournament compares each source-faithful core under the same data,
execution and cost model. The first contracts are:

- native swing stop + 2R target,
- target +2R / loss cap -0.75R,
- target +2R / loss cap -0.50R.

A candidate is not promoted from a short discovery sample. It must retain its
edge in the existing non-overlapping 90-day dataset and under 0.10%, 0.15% and
0.20% round-trip cost assumptions.
