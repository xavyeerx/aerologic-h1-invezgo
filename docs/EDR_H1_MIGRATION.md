# EDR: Invezgo Closed-Candle H1 Migration

## Context and decision

Production price signals use Invezgo `analysis/chart/multi-time/{code}` with
`timeframe=60`. Daily chart data is no longer signal-eligible. Every indicator,
including Supertrend, is calculated from the same sequence of completed H1 bars.

## Bar contract

- Contract: `invezgo_h1_v1`, timeframe `60m`.
- Invezgo timestamps such as `09:00Z` are treated as IDX exchange wall-clock bucket
  labels and localized directly to `Asia/Jakarta`; they are not shifted from UTC.
- Incomplete current buckets are removed using the IDX regular-session, lunch-break,
  pre-open, pre-close, and auction bucket schedule.
- The scheduler runs one minute after each expected bucket close. A five-minute stale
  window avoids processing old slots after a long process pause.
- Realtime screener prices select candidates only. They never override the H1 close
  used by Supertrend or signal decisions.

## Indicator semantics

- Supertrend uses TradingView-compatible Wilder RMA ATR, period 10, multiplier 2.
- Initialization is at ATR bar `period - 1`, initially on the bearish upper band,
  matching `ta.supertrend`; project direction uses `+1` bullish and `-1` bearish.
- `return20_pct` means 20 H1 bars, and market momentum means five H1 bars.
- Daily aggregated turnover remains a liquidity/risk feature, not a signal timeframe.
- Existing daily alert history remains in place as an operational risk cap and to
  prevent duplicate alerts after deployment.

## Risks and validation boundary

Thresholds inherited from the Daily strategy are migration defaults, not evidence of
H1 strategy quality. Forward validation and historical H1 backtesting are required.
Exact chart parity also depends on TradingView using an equivalent IDX feed, session,
auction inclusion, corporate-action adjustment, and closed-bar comparison.
