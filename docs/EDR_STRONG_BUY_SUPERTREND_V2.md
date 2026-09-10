# EDR: Strong Buy Supertrend Confirmation V2

## Status

Implemented on 2026-09-09 with build ID `20260909-strong-buy-st-v2`.

## Context

The previous Strong Buy rule combined `MOMENTUM_EXPANSION` and
`SUPERTREND_BOUNCE`. Momentum Expansion required EMA alignment, 20-bar return,
H1 volume ratio, and candle anatomy. These conditions tended to select extended
momentum, while the bounce path admitted a materially different setup under the
same alert label.

Candidate lanes also reserved scanner capacity for momentum, constructive, and
reversal groups even though the screener normally returns fewer than 50 stocks.

## Decision

Strong Buy now represents one setup family: `SUPERTREND_CONFIRMATION`.

The rule is:

```text
two latest H1 bars have Supertrend direction == bullish
AND 0% < session change <= STRONG_BUY_MAX_CHANGE_PCT (default 12%)
AND, when regime is SIDEWAYS or BEAR:
    Stoch RSI K < STRONG_BUY_STOCH_RSI_MAX (default 60)
    AND Stoch RSI K > Stoch RSI D
```

The latest of the two H1 bars may be the forming bar. Consequently, the second
confirmation can repaint before the bar closes. `BULL` and unclassified regimes
do not apply the Stoch RSI gate; the gate is explicitly scoped to `SIDEWAYS` and
`BEAR`.

Strong Buy no longer depends on:

- Momentum Expansion;
- Supertrend bounce or line-touch detection;
- EMA alignment;
- 20-bar return;
- H1 candle anatomy;
- minimum H1 volume ratio.

The five-day average turnover gate of Rp5 billion remains mandatory. Candidate
activity is still screened upstream using Invezgo volume pace and 20-day average
transaction value.

Candidate selection no longer assigns lanes. Results are deduplicated by ticker,
ranked by activity ratio and transaction value, and capped at 50.

The ticker-level frequency cap is reduced from three to two calls in a rolling
14-calendar-day window. Daily cross-category deduplication, consecutive-session
protection, and the post-alert ARB cooldown remain unchanged.

## Trade-offs and risks

- Removing H1 volume confirmation permits a signal after its intraday volume pace
  qualified upstream but the current H1 bar itself has weak relative volume.
- Two Supertrend bars reduce one-bar flips but add confirmation delay.
- Allowing the forming bar improves timeliness but retains repaint risk.
- Stoch RSI below 60 reduces extended entries in Sideways and Bear regimes, while
  `K > D` requires positive oscillator structure. Bull regimes deliberately accept
  overbought continuation.
- Removing lanes can allow high-activity names to dominate when the screener result
  exceeds 50, although this is expected to be uncommon.

## Validation requirements

Track results by build ID and record at least signal count, alert-time Stoch RSI,
session change, Supertrend confirmation state, repaint-at-close rate, and MFE/MAE
after 1H, 1D, and 3D. Threshold effectiveness must be evaluated on the new H1
cohort and must not be inferred from legacy Daily or H4 tracker records.

## 2026-09-10 target and deduplication amendment

Alert targets are no longer taken directly from the latest H1 indicator row. H1
bars are aggregated into Daily candles and the current Daily candle is anchored to
the realtime alert price. TP1 uses Daily ATR; TP2 uses a valid Daily resistance or
Daily ATR fallback. IDX tick rounding and output guards enforce `TP2 > TP1 > alert
price`.

Daily deduplication is now unconditional across Bullish Breakout, Strong Buy, Early
Entry, and Reversal Watch. The previous Bullish Breakout exception was removed, so
the first successfully claimed category owns the ticker for that date.

Identical alerts from different project directories remain an operational concern:
file locking only coordinates processes that share the same runtime database path.
Production must run a single service targeting a given Telegram chat and topic.
The optional signal backend is disabled by default because its former webhook URL
may have notification side effects. Telegram is the authoritative sender. When
backend sync is explicitly enabled, one payload is sent per alert batch rather than
once per Telegram chunk.

## Entry area and stop-loss amendment

The entry area spans from an eligible nearby support or a 0.5 Daily ATR pullback,
whichever is higher, up to the realtime alert price. Stop-loss selection uses the
nearest eligible Supertrend, pivot, or breakout support. A structural stop is used
when its risk from the alert price is between 4% and 7%. Shallower support is
normalized to 4% risk, deeper support is capped at 7%, and missing support falls
back to 5%. All prices are normalized to valid IDX price fractions and must satisfy
`SL < entry zone low <= entry zone high < TP1 < TP2`.
